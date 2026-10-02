"""Draft supervisor resolutions using similar KB branches."""

from __future__ import annotations

import logging
from typing import Any
from json_store import find_similar_active_issues
from draft_enrichment import draft_needs_enrichment, enrich_draft_entry, kb_examples_from_matches
from ingest import build_keywords
from kb_search import find_possible_kb_matches
from kb_manager import get_registry
from lms_faq_import import faq_entry_to_draft_entry, search_lms_faq
from llm import check_llm_available
from llm_drafter import (
    _build_prompt,
    _enrich_from_examples,
    _example_ids,
    _llm_failure_response,
    parse_llm_entry,
    validate_unified_entry,
)

logger = logging.getLogger(__name__)

try:
    from llm_drafter import _call_llm
except ImportError:
    _call_llm = None  # type: ignore[misc, assignment]


def _active_issue_to_example(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "issue_name": row.get("issue_name", ""),
        "category": row.get("category_id", ""),
        "topic_category": row.get("category_id", ""),
        "problem_statement": row.get("problem_statement", ""),
        "policy": row.get("policy_text", ""),
        "resolution_steps": row.get("resolution_steps", []),
        "required_documents": row.get("required_documents", []),
        "l1_team": row.get("l1_team", "Support Desk"),
        "l1_person": row.get("l1_person", "TBD"),
        "issue_id": str(row.get("id", "")),
    }


def _fallback_from_example(query: str, example: dict[str, Any]) -> dict[str, Any]:
    entry = _active_issue_to_example(example)
    entry["issue_name"] = entry["issue_name"] or query[:80]
    entry["problem_statement"] = entry["problem_statement"] or query
    if not entry.get("resolution_steps"):
        entry["resolution_steps"] = ["Follow the approved resolution guidance."]
    entry["sources"] = ["db_template_fallback"]
    return entry


def _template_issue_name(
    draft_source: str | None,
    similar_db: list[dict[str, Any]],
    draft_entry: dict[str, Any],
) -> str | None:
    if draft_source not in ("db_template_fallback", "fallback", "empty_fallback"):
        return None
    if similar_db:
        name = str(similar_db[0].get("issue_name", "")).strip()
        if name:
            return name
    name = str(draft_entry.get("issue_name", "")).strip()
    return name or None


def _kb_template_draft(
    normalized_query: str,
    caller_type: str,
    *,
    similar_db: list[dict[str, Any]],
    faiss_matches: list[dict[str, Any]],
    examples: list[dict[str, Any]],
    example_ids: list[str],
    draft_source: str = "kb_template",
    error: str | None = None,
) -> dict[str, Any]:
    """Fast draft from KB / similar branches — no LLM call."""
    if similar_db:
        draft_entry = _fallback_from_example(normalized_query, similar_db[0])
    else:
        draft_entry = {
            "issue_name": normalized_query[:80],
            "problem_statement": normalized_query,
            "policy": "",
            "resolution_steps": [],
            "required_documents": [],
            "l1_team": "",
            "l1_person": "",
            "sources": ["kb_template"],
        }
    draft_entry = enrich_draft_entry(
        draft_entry,
        normalized_query,
        caller_type,
        faiss_matches=faiss_matches,
        db_examples=examples,
    )
    result: dict[str, Any] = {
        "draft": draft_entry,
        "draft_source": draft_source,
        "examples_used": example_ids,
        "possible_matches": faiss_matches,
        "db_similar": similar_db,
        "template_issue_name": _template_issue_name(draft_source, similar_db, draft_entry),
    }
    if error:
        result["error"] = error
    return result


def _lms_faq_draft(
    normalized_query: str,
    caller_type: str,
    *,
    lms_matches: list[dict[str, Any]],
    faiss_matches: list[dict[str, Any]],
    similar_db: list[dict[str, Any]] | None = None,
    examples: list[dict[str, Any]] | None = None,
    example_ids: list[str] | None = None,
    draft_source: str = "lms_faq_draft",
    error: str | None = None,
) -> dict[str, Any]:
    """Build supervisor draft primarily from FAQ match."""
    top = lms_matches[0]
    draft_entry = faq_entry_to_draft_entry(top["entry"], caller_type)
    draft_entry = enrich_draft_entry(
        draft_entry,
        normalized_query,
        caller_type,
        faiss_matches=faiss_matches,
        db_examples=examples or [],
    )
    ids = list(example_ids or [])
    faq_id = top.get("lms_faq_id")
    if faq_id and str(faq_id) not in ids:
        ids.insert(0, str(faq_id))
    result: dict[str, Any] = {
        "draft": draft_entry,
        "draft_source": draft_source,
        "examples_used": ids,
        "possible_matches": faiss_matches,
        "lms_matches": lms_matches,
        "db_similar": similar_db or [],
        "template_issue_name": draft_entry.get("issue_name"),
    }
    if error:
        result["error"] = error
    return result


def _supervisor_lms_matches(normalized_query: str, caller_type: str) -> list[dict[str, Any]]:
    try:
        embed_model = get_registry().embed_model
        return search_lms_faq(
            normalized_query,
            caller_type,
            embed_model=embed_model,
            top_k=5,
            min_score=0.28,
        )
    except Exception as exc:
        logger.warning("FAQ search skipped: %s", exc)
        return []


def _load_llm_examples(
    normalized_query: str,
    caller_type: str,
    *,
    similar_db: list[dict[str, Any]],
    faiss_matches: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect few-shot examples from FAQ, DB, FAISS branches, or unified KB."""
    examples: list[dict[str, Any]] = []
    example_ids: list[str] = []

    for match in _supervisor_lms_matches(normalized_query, caller_type)[:3]:
        examples.append(faq_entry_to_draft_entry(match["entry"], caller_type))
        if match.get("lms_faq_id"):
            example_ids.append(str(match["lms_faq_id"]))

    for row in similar_db:
        examples.append(_active_issue_to_example(row))
        if row.get("id"):
            example_ids.append(str(row["id"]))

    if not examples and faiss_matches:
        examples = kb_examples_from_matches(faiss_matches, caller_type)
        example_ids = [
            str(match.get("branch_id", ""))
            for match in faiss_matches
            if match.get("branch_id")
        ]

    if not examples:
        from llm_drafter import _find_similar_entries, _rank_unified_examples

        unified = _rank_unified_examples(
            normalized_query,
            _find_similar_entries(normalized_query, top_k=5),
        )[:3]
        examples = [dict(entry) for entry in unified]
        example_ids = [
            str(entry.get("issue_id") or entry.get("issue_name", ""))
            for entry in unified
            if entry.get("issue_id") or entry.get("issue_name")
        ]

    return examples, example_ids


def draft_resolution_for_queue(
    query: str,
    caller_type: str,
    *,
    fast: bool = False,
    possible_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Find similar KB issues, draft via the LLM (slow) or KB template (fast)."""
    normalized_query = query.strip()
    if possible_matches:
        faiss_matches = possible_matches
    else:
        faiss_matches = find_possible_kb_matches(normalized_query, caller_type, top_k=3)

    lms_matches = _supervisor_lms_matches(normalized_query, caller_type)

    # Fast path: FAQ first, then KB template — no LLM call on submit.
    if fast:
        if lms_matches:
            return _lms_faq_draft(
                normalized_query,
                caller_type,
                lms_matches=lms_matches,
                faiss_matches=faiss_matches,
                draft_source="lms_faq_fast_draft",
            )
        return _kb_template_draft(
            normalized_query,
            caller_type,
            similar_db=[],
            faiss_matches=faiss_matches,
            examples=[],
            example_ids=[],
            draft_source="kb_fast_draft",
        )

    similar_db = find_similar_active_issues(normalized_query, caller_type, top_k=3)
    examples, example_ids = _load_llm_examples(
        normalized_query,
        caller_type,
        similar_db=similar_db,
        faiss_matches=faiss_matches,
    )

    if lms_matches and not check_llm_available():
        return _lms_faq_draft(
            normalized_query,
            caller_type,
            lms_matches=lms_matches,
            faiss_matches=faiss_matches,
            similar_db=similar_db,
            examples=examples,
            example_ids=example_ids,
            draft_source="lms_faq_template",
            error="AI drafting unavailable",
        )

    if not check_llm_available() or _call_llm is None:
        return _kb_template_draft(
            normalized_query,
            caller_type,
            similar_db=similar_db,
            faiss_matches=faiss_matches,
            examples=examples,
            example_ids=example_ids,
            draft_source="db_template_fallback",
            error="AI drafting unavailable",
        )

    prompt = _build_prompt(normalized_query, examples if examples else [])

    try:
        raw_response = _call_llm(prompt)
        parsed_entry = parse_llm_entry(raw_response, normalized_query)
        if examples:
            parsed_entry = _enrich_from_examples(parsed_entry, examples, normalized_query)
        if draft_needs_enrichment(parsed_entry, caller_type) or faiss_matches:
            parsed_entry = enrich_draft_entry(
                parsed_entry,
                normalized_query,
                caller_type,
                faiss_matches=faiss_matches,
                db_examples=examples,
            )
        draft_source = "llm_db_fewshot"
        draft_error = None
    except Exception as exc:
        logger.warning("LLM draft failed: %s", exc)
        failure = _llm_failure_response(
            normalized_query,
            examples,
            example_ids,
            f"AI drafting unavailable: {exc}",
        )
        draft_entry = failure.get("draft") or _fallback_from_example(
            normalized_query, similar_db[0] if similar_db else {}
        )
        try:
            draft_entry = enrich_draft_entry(
                draft_entry,
                normalized_query,
                caller_type,
                faiss_matches=faiss_matches,
                db_examples=examples,
            )
        except Exception as enrich_exc:
            logger.warning("Draft enrichment failed after LLM error: %s", enrich_exc)
        draft_source = str(failure.get("draft_source", "db_template_fallback"))
        return {
            "draft": draft_entry,
            "draft_source": draft_source,
            "examples_used": example_ids,
            "possible_matches": faiss_matches,
            "lms_matches": lms_matches,
            "db_similar": similar_db,
            "template_issue_name": _template_issue_name(
                draft_source, similar_db, draft_entry
            ),
            "error": str(exc),
        }

    keywords = build_keywords(
        str(parsed_entry.get("issue_name", "")),
        f"{parsed_entry.get('problem_statement', '')} {normalized_query}",
    )
    parsed_entry["trigger_keywords"] = keywords[:12]
    if similar_db and not parsed_entry.get("topic_category"):
        parsed_entry["topic_category"] = similar_db[0].get("category_id")
        parsed_entry["category"] = similar_db[0].get("category_id")

    validation_errors = validate_unified_entry(parsed_entry)
    if validation_errors:
        if similar_db:
            parsed_entry = _fallback_from_example(normalized_query, similar_db[0])
            draft_source = "db_template_fallback"
        elif faiss_matches:
            kb_examples = kb_examples_from_matches(faiss_matches, caller_type)
            if kb_examples:
                parsed_entry = enrich_draft_entry(
                    parsed_entry,
                    normalized_query,
                    caller_type,
                    faiss_matches=faiss_matches,
                    db_examples=kb_examples,
                )
                draft_source = "kb_template_fallback"
        if draft_needs_enrichment(parsed_entry, caller_type):
            parsed_entry = enrich_draft_entry(
                parsed_entry,
                normalized_query,
                caller_type,
                faiss_matches=faiss_matches,
                db_examples=examples,
            )

    template_name = _template_issue_name(draft_source, similar_db, parsed_entry)

    return {
        "draft": parsed_entry,
        "draft_source": draft_source,
        "examples_used": example_ids,
        "possible_matches": faiss_matches,
        "lms_matches": lms_matches,
        "db_similar": similar_db,
        "template_issue_name": template_name,
    }
