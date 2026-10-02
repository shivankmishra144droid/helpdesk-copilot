"""Fill incomplete supervisor drafts from KB branches and DB examples."""

from __future__ import annotations

import re
from typing import Any

from category_utils import resolve_stored_category_id, topic_category_ids
from ingest import build_keywords
from kb_manager import get_kb
from kb_search import get_agent_script
from llm_drafter import _enrich_from_examples

_POLICY_SPLIT = re.compile(r"\n\nPolicy:\s*", re.IGNORECASE)

GENERIC_RESOLUTION_STEPS = frozenset(
    {
        "follow supervisor-approved guidance.",
        "follow the approved resolution guidance.",
        "follow the guidance in the uploaded document.",
    }
)

FAST_DRAFT_SOURCES = frozenset(
    {"kb_fast_draft", "kb_template", "kb_template_fallback", "db_template_fallback"}
)
LLM_DRAFT_SOURCES = frozenset(
    {"llm_db_fewshot", "llm", "llm_format", "llm_polish"}
)


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split("|") if part.strip()]
    return []


def _split_policy_from_script(script: str) -> tuple[str, str]:
    text = str(script or "").strip()
    if not text:
        return "", ""
    match = _POLICY_SPLIT.search(text)
    if match:
        return text[: match.start()].strip(), text[match.end() :].strip()
    return text, ""


def _normalize_l1_team(value: str) -> str:
    team = str(value or "").strip()
    if team.lower().startswith("assign to "):
        return team[10:].strip()
    return team


def _apply_topic_category(
    entry: dict[str, Any],
    caller_type: str,
    *,
    query: str = "",
) -> dict[str, Any]:
    topic_id = resolve_stored_category_id(
        entry.get("topic_category") or entry.get("category"),
        caller_type,
        issue_name=str(entry.get("issue_name", "")),
        problem_statement=f"{entry.get('problem_statement', '')} {query}".strip(),
    )
    if topic_id:
        entry["category"] = topic_id
        entry["topic_category"] = topic_id
    return entry


def branch_to_draft_entry(branch: dict[str, Any], caller_type: str = "seller") -> dict[str, Any]:
    """Map a KB branch (steps/documents/escalation) to unified draft fields."""
    script = get_agent_script(branch)
    problem, policy_from_script = _split_policy_from_script(script)
    policy = str(branch.get("policy") or policy_from_script or "").strip()

    keywords = branch.get("trigger_keywords")
    if not keywords:
        keywords = build_keywords(branch.get("branch_name", ""), script)

    entry = {
        "issue_name": str(branch.get("branch_name", "")).strip(),
        "category": "",
        "topic_category": "",
        "problem_statement": problem or script,
        "policy": policy,
        "resolution_steps": list(branch.get("steps") or branch.get("resolution_steps") or []),
        "required_documents": list(branch.get("documents") or branch.get("required_documents") or []),
        "l1_team": _normalize_l1_team(str(branch.get("escalation") or branch.get("l1_team") or "")) or "TBD",
        "l1_person": str(branch.get("escalation_person") or branch.get("l1_person") or "").strip() or "TBD",
        "trigger_keywords": list(keywords) if isinstance(keywords, list) else [],
        "_branch_id": branch.get("branch_id"),
    }
    if branch.get("manual_enrichment"):
        entry["manual_enrichment"] = branch["manual_enrichment"]
    return _apply_topic_category(
        entry,
        caller_type,
        query=problem or script,
    )


def kb_examples_from_matches(
    matches: list[dict[str, Any]],
    caller_type: str,
) -> list[dict[str, Any]]:
    if not matches:
        return []
    store = get_kb(caller_type)
    branch_by_id = {branch["branch_id"]: branch for branch in store.branches}
    examples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in matches:
        branch_id = str(match.get("branch_id", "")).strip()
        if not branch_id or branch_id in seen:
            continue
        branch = branch_by_id.get(branch_id)
        if not branch:
            continue
        seen.add(branch_id)
        examples.append(branch_to_draft_entry(branch, caller_type))
    return examples


def draft_needs_enrichment(entry: dict[str, Any], caller_type: str = "seller") -> bool:
    steps = _coerce_string_list(entry.get("resolution_steps"))
    policy = str(entry.get("policy", "")).strip()
    l1_team = str(entry.get("l1_team", "")).strip()
    l1_person = str(entry.get("l1_person", "")).strip()
    docs = _coerce_string_list(entry.get("required_documents"))
    keywords = _coerce_string_list(entry.get("trigger_keywords"))
    topic_id = resolve_stored_category_id(
        entry.get("category") or entry.get("topic_category"),
        caller_type,
        issue_name=str(entry.get("issue_name", "")),
        problem_statement=str(entry.get("problem_statement", "")),
    )

    if len(steps) < 2:
        return True
    if len(policy) < 20:
        return True
    if not topic_id:
        return True
    if not l1_team or l1_team.upper() == "TBD":
        return True
    if not l1_person or l1_person.upper() == "TBD":
        return True
    if not docs:
        return True
    if not keywords:
        return True
    if topic_id not in topic_category_ids(caller_type):
        return True
    return False


def is_weak_kb_draft(
    entry: dict[str, Any],
    possible_matches: list[dict[str, Any]] | None = None,
) -> bool:
    """True when the draft is a generic placeholder, not a real resolution."""
    steps = _coerce_string_list(entry.get("resolution_steps"))
    normalized_steps = {step.lower().strip() for step in steps}

    if not steps:
        return True
    if normalized_steps <= GENERIC_RESOLUTION_STEPS:
        return True

    problem = str(entry.get("problem_statement", "")).strip()
    issue_name = str(entry.get("issue_name", "")).strip()
    if (
        problem
        and issue_name
        and problem.lower() == issue_name.lower()
        and len(steps) < 3
    ):
        return True

    if possible_matches and len(steps) >= 3:
        return False

    return len(steps) < 2


def should_llm_redraft(issue: dict[str, Any]) -> bool:
    """Whether supervisor issue should get a full LLM draft (no keyword match required)."""
    extras = issue.get("extras") or {}
    draft_source = str(extras.get("draft_source") or issue.get("draft_source") or "")
    if draft_source in LLM_DRAFT_SOURCES:
        return False
    if draft_source and draft_source not in FAST_DRAFT_SOURCES:
        return False

    draft = dict(issue.get("draft") or {})
    if draft.get("manual_enrichment") == "llm":
        return False

    possible_matches = (
        issue.get("possible_matches")
        or extras.get("possible_matches")
        or []
    )
    return is_weak_kb_draft(draft, possible_matches)


def enrich_draft_entry(
    entry: dict[str, Any],
    query: str,
    caller_type: str,
    *,
    faiss_matches: list[dict[str, Any]] | None = None,
    db_examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge KB + DB examples into an incomplete draft."""
    enriched = dict(entry)
    examples: list[dict[str, Any]] = []
    manual_enriched = enriched.get("manual_enrichment") == "llm"
    saved_problem = str(enriched.get("problem_statement", "")).strip() if manual_enriched else ""
    saved_docs = (
        _coerce_string_list(enriched.get("required_documents"))
        if manual_enriched
        else None
    )
    saved_steps = (
        _coerce_string_list(enriched.get("resolution_steps"))
        if manual_enriched
        else None
    )

    for example in kb_examples_from_matches(faiss_matches or [], caller_type):
        examples.append(example)
    for example in db_examples or []:
        examples.append(example)

    if examples:
        enriched = _enrich_from_examples(enriched, examples, query)

    if manual_enriched:
        if saved_problem:
            enriched["problem_statement"] = saved_problem
        if saved_docs is not None:
            enriched["required_documents"] = saved_docs
        if saved_steps:
            enriched["resolution_steps"] = saved_steps

    steps = _coerce_string_list(enriched.get("resolution_steps"))
    if not manual_enriched and len(steps) < 2 and examples:
        source_steps = _coerce_string_list(examples[0].get("resolution_steps"))
        if source_steps:
            enriched["resolution_steps"] = source_steps

    if not _coerce_string_list(enriched.get("resolution_steps")):
        enriched["resolution_steps"] = ["Follow supervisor-approved guidance."]

    if not manual_enriched and not _coerce_string_list(enriched.get("required_documents")):
        enriched["required_documents"] = ["Screenshot of the error and the account ID"]

    team = str(enriched.get("l1_team", "")).strip()
    if not team:
        enriched["l1_team"] = "TBD"

    person = str(enriched.get("l1_person", "")).strip()
    if not person:
        enriched["l1_person"] = "TBD"

    if not str(enriched.get("policy", "")).strip() and examples:
        policy = str(examples[0].get("policy", "")).strip()
        if policy:
            enriched["policy"] = policy

    if not str(enriched.get("policy", "")).strip():
        enriched["policy"] = "Follow the published help-centre guidance; ask a supervisor if unsure."

    if not _coerce_string_list(enriched.get("trigger_keywords")):
        enriched["trigger_keywords"] = build_keywords(
            str(enriched.get("issue_name", "")),
            f"{enriched.get('problem_statement', '')} {query}",
        )[:12]

    return _apply_topic_category(enriched, caller_type, query=query)
