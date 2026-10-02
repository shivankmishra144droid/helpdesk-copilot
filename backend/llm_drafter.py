"""LLM resolution drafter — drafts supervisor resolutions from resolution examples."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

import llm_provider
from category_utils import CATEGORY_LISTS
from kb_manager import get_registry, normalize_caller_type
from kb_search import normalize_query

logger = logging.getLogger(__name__)

UNIFIED_KB_PATH = Path(__file__).parent / "knowledge" / "resolution_examples.json"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"

# Category ids an LLM draft may use (seller + buyer topic categories).
VALID_CATEGORIES = frozenset(
    category["id"] for categories in CATEGORY_LISTS.values() for category in categories
)

REQUIRED_ENTRY_FIELDS = (
    "issue_name",
    "category",
    "problem_statement",
    "policy",
    "resolution_steps",
    "required_documents",
    "l1_team",
    "l1_person",
)

STRICT_RULES = """
CRITICAL FORMAT RULES:
1. resolution_steps MUST be a flat list of 4-8 simple strings
2. NO nested numbering (no 1. 2. 3. inside a step)
3. NO invented UI details (no "click Edit", no "navigate to", no button names)
4. Each step must be ONE action, not a paragraph
5. Copy steps VERBATIM from examples, only adapt topic — do not expand or add fake details
6. l1_person MUST be exact names from examples, no punctuation after
"""

_embed_model: SentenceTransformer | None = None
_unified_entries: list[dict[str, Any]] | None = None
_entry_embeddings: np.ndarray | None = None


def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        # Reuse the app's shared, lock-guarded model rather than loading a second copy.
        from kb_manager import get_registry

        try:
            _embed_model = get_registry().embed_model
        except RuntimeError:
            _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    return _embed_model


def _entry_embed_text(entry: dict[str, Any]) -> str:
    steps = " ".join(str(step) for step in entry.get("resolution_steps", []))
    docs = " ".join(str(doc) for doc in entry.get("required_documents", []))
    return (
        f"{entry.get('issue_name', '')} | {entry.get('category', '')} | "
        f"{entry.get('problem_statement', '')} | {entry.get('policy', '')} | "
        f"{steps} | {docs}"
    )


def load_unified_kb() -> list[dict[str, Any]]:
    """Load unified KB into isolated in-memory structure (not kb_manager / FAISS)."""
    global _unified_entries, _entry_embeddings

    if _unified_entries is not None:
        return _unified_entries

    if not UNIFIED_KB_PATH.exists():
        raise FileNotFoundError(f"Unified KB not found: {UNIFIED_KB_PATH}")

    with UNIFIED_KB_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("Unified KB 'entries' must be a list")

    _unified_entries = [dict(entry) for entry in entries if isinstance(entry, dict)]

    if _unified_entries:
        texts = [_entry_embed_text(entry) for entry in _unified_entries]
        _entry_embeddings = _get_embed_model().encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).astype(np.float32)
    else:
        _entry_embeddings = np.zeros((0, 384), dtype=np.float32)

    return _unified_entries


def _find_similar_entries(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    entries = load_unified_kb()
    if not entries or _entry_embeddings is None or not query.strip():
        return []

    query_vector = _get_embed_model().encode(
        [query.strip()],
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype(np.float32)

    scores = (_entry_embeddings @ query_vector.T).flatten()
    k = min(top_k, len(entries))
    top_indices = np.argsort(scores)[::-1][:k]

    results: list[dict[str, Any]] = []
    for index in top_indices:
        entry = dict(entries[int(index)])
        entry["_score"] = round(float(scores[int(index)]), 4)
        results.append(entry)
    return results


def _candidate_text(candidate: dict[str, Any]) -> str:
    return " ".join(
        str(candidate.get(key, ""))
        for key in (
            "issue_name",
            "problem_statement",
            "policy",
            "branch_name",
        )
    ).lower()


def _format_example(entry: dict[str, Any], index: int) -> str:
    steps = "\n".join(
        f"  {i}. {step}" for i, step in enumerate(entry.get("resolution_steps", []), start=1)
    )
    docs = ", ".join(str(doc) for doc in entry.get("required_documents", []))
    return (
        f"EXAMPLE {index}: {entry.get('issue_name', '')}\n"
        f"Category: {entry.get('category', '')}\n"
        f"Problem: {entry.get('problem_statement', '')}\n"
        f"Policy: {entry.get('policy', '')}\n"
        f"Resolution Steps:\n{steps}\n"
        f"Required Documents: {docs}\n"
        f"L1 Team: {entry.get('l1_team', '')} | {entry.get('l1_person', '')}"
    )


def _build_prompt(query: str, examples: list[dict[str, Any]]) -> str:
    example_blocks = [
        _format_example(example, index) for index, example in enumerate(examples, start=1)
    ]
    examples_text = "\n\n".join(example_blocks) if example_blocks else "No examples available."

    categories = ", ".join(sorted(VALID_CATEGORIES))
    return f"""You are a senior Helpdesk Copilot support agent. Write resolutions in this exact format.

STYLE EXAMPLES (copy structure and completeness — adapt policy/steps to the new query):
{examples_text}

NEW QUERY: "{query}"

Write a complete resolution entry. Adapt content from the most relevant example above.

CRITICAL: Match the QUERY INTENT exactly. If the query is about a refund not received,
do NOT use guidance about a payment that failed. If the query is about a failed payment,
do NOT use refund-delay guidance. Pick the example whose problem_statement
matches the query, not just the topic name.

MANDATORY RULES:
1. policy MUST contain the full adapted policy text from examples — NEVER leave empty or use placeholders
2. resolution_steps MUST have at least 3-4 steps — include verification, guidance, and escalation
3. required_documents MUST list ALL documents from relevant examples — do not skip any
4. l1_person MUST be the role from the most relevant example — NEVER use "TBD" or placeholders
5. l1_team MUST match the example team (e.g. Seller Finance Desk)
6. Output the COMPLETE entry. Do not stop early. Do not truncate.

{STRICT_RULES}

BAD EXAMPLE (do NOT do this):
"If eligible, enable the option in settings using these steps: 1. Log in... 2. Click..."

GOOD EXAMPLE (do this):
"If eligible, enable the option in settings"
"For payment issues: assign to Seller Finance Desk"

Return ONLY valid JSON (no markdown fences):
{{
  "issue_name": "concise title for the issue",
  "category": "one of: {categories}",
  "problem_statement": "describe the caller issue",
  "policy": "FULL policy paragraph adapted from examples — multiple sentences required",
  "resolution_steps": ["step 1", "step 2", "step 3", "step 4"],
  "required_documents": ["doc 1", "doc 2", "doc 3"],
  "l1_team": "team from example",
  "l1_person": "role from example",
  "sources": ["supervisor_approved_llm"]
}}"""


def _pick_best_example(examples: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    if not examples:
        return None
    if examples[0].get("_rank_score") is not None:
        return examples[0]

    query_lower = query.lower()
    for example in examples:
        blob = _candidate_text(example)
        if any(token in blob for token in query_lower.split() if len(token) >= 4):
            return example
    return examples[0]


def _sanitize_steps(steps: list[str], example_steps: list[str]) -> list[str]:
    """Remove hallucinated sub-steps and duplicates."""
    cleaned: list[str] = []
    seen: set[str] = set()

    for step in steps:
        step = step.strip()
        if not step:
            continue

        if re.search(r"\d+\.\s", step) and len(step) > 100:
            continue

        step_lower = step.lower()
        if step_lower in seen:
            continue
        seen.add(step_lower)
        cleaned.append(step)

    if len(cleaned) < 3:
        return example_steps

    return cleaned[:8]


def _sanitize_l1_person(person: str, example_person: str) -> str:
    value = (person or example_person or "").strip().rstrip("?.! ")
    if not value or value.upper() == "TBD":
        return example_person.strip().rstrip("?.! ")
    if "|" in value and example_person:
        return example_person.strip().rstrip("?.! ")
    if example_person and len(value) < len(example_person) - 3:
        return example_person.strip().rstrip("?.! ")
    return value


def _enrich_from_examples(
    entry: dict[str, Any],
    examples: list[dict[str, Any]],
    query: str,
) -> dict[str, Any]:
    """Fill incomplete LLM output from the closest unified KB example."""
    source = _pick_best_example(examples, query)
    if not source:
        return entry

    policy = str(entry.get("policy", "")).strip()
    source_policy = str(source.get("policy", "")).strip()
    if len(policy) < 80 and source_policy:
        entry["policy"] = source_policy

    steps = _coerce_string_list(entry.get("resolution_steps"))
    source_steps = _coerce_string_list(source.get("resolution_steps"))
    if len(steps) < 3 and source_steps:
        entry["resolution_steps"] = _sanitize_steps(source_steps, source_steps)
    elif source_steps:
        merged = list(dict.fromkeys([*steps, *source_steps]))[:15]
        entry["resolution_steps"] = _sanitize_steps(merged, source_steps)
    else:
        entry["resolution_steps"] = _sanitize_steps(steps, source_steps)

    docs = _coerce_string_list(entry.get("required_documents"))
    source_docs = _coerce_string_list(source.get("required_documents"))
    if source_docs:
        entry["required_documents"] = list(dict.fromkeys([*docs, *source_docs]))[:20]

    person = str(entry.get("l1_person", "")).strip()
    source_person = str(source.get("l1_person", "")).strip()
    entry["l1_person"] = _sanitize_l1_person(person, source_person)

    team = str(entry.get("l1_team", "")).strip()
    source_team = str(source.get("l1_team", "")).strip()
    if (not team or team.upper() == "TBD") and source_team:
        entry["l1_team"] = source_team

    if not str(entry.get("issue_name", "")).strip() and source.get("issue_name"):
        entry["issue_name"] = str(source["issue_name"]).strip()

    if not str(entry.get("problem_statement", "")).strip():
        entry["problem_statement"] = query

    category = str(entry.get("category", "")).strip()
    source_category = str(source.get("category", "")).strip()
    if category not in VALID_CATEGORIES and source_category in VALID_CATEGORIES:
        entry["category"] = source_category

    return entry


def _build_fallback_draft(query: str, examples: list[dict[str, Any]]) -> dict[str, Any]:
    """Template draft from the closest resolution example when no LLM is available."""
    if examples:
        top = _pick_best_example(examples, query) or examples[0]
        category = str(top.get("category", "General_Policy")).strip()
        if category not in VALID_CATEGORIES:
            category = "General_Policy"
        steps = list(top.get("resolution_steps", []))[:15]
        docs = list(top.get("required_documents", []))[:15]
        return {
            "issue_name": query[:80],
            "category": category,
            "problem_statement": query,
            "policy": str(
                top.get("policy", "Refer to portal policy and adapt from the closest resolution example.")
            ).strip(),
            "resolution_steps": steps
            or [
                "Confirm the issue details with the caller.",
                "Apply steps from the closest unified KB example.",
                "Escalate to L1 if unresolved.",
            ],
            "required_documents": docs or ["Screenshot of the error and the account ID"],
            "l1_team": str(top.get("l1_team", "Registration")).strip(),
            "l1_person": str(top.get("l1_person", "Support Desk")).strip(),
            "sources": ["supervisor_approved_llm", "fallback_unified_kb"],
        }
    return parse_llm_entry("", query)


def _llm_failure_response(
    query: str,
    examples: list[dict[str, Any]],
    example_ids: list[str],
    detail: str,
) -> dict[str, Any]:
    return {
        "error": detail,
        "setup_instructions": llm_provider.setup_instructions(),
        "draft": _build_fallback_draft(query, examples),
        "draft_source": "fallback",
        "examples_used": example_ids,
        "query": query,
    }


DRAFT_SYSTEM_PROMPT = (
    "You write complete Helpdesk Copilot resolutions as strict JSON only. "
    "Never leave policy empty. Never use TBD. "
    "Steps must be short flat strings — no nested numbering or invented UI clicks."
)


def _call_llm(prompt: str) -> str:
    return llm_provider.complete(prompt, system=DRAFT_SYSTEM_PROMPT, max_tokens=1500)


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        cleaned: list[str] = []
        for line in lines:
            match = re.match(r"^(?:\d+[\).]|[-•])\s*(.+)$", line)
            cleaned.append(match.group(1).strip() if match else line)
        return cleaned
    return []


def parse_llm_entry(raw: str, query: str) -> dict[str, Any]:
    text = _strip_json_fence(raw)
    data: dict[str, Any] | None = None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            data = parsed
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    data = parsed
            except json.JSONDecodeError:
                data = None

    if data is None:
        data = {
            "issue_name": query[:80] or "New Support Issue",
            "category": "General_Policy",
            "problem_statement": text[:500] or query,
            "policy": "Follow the published help-centre guidance; ask a supervisor if unsure.",
            "resolution_steps": _coerce_string_list(text) or ["Follow supervisor-approved guidance."],
            "required_documents": ["Screenshot of the error and the account ID"],
            "l1_team": "Registration",
            "l1_person": "TBD",
            "sources": ["supervisor_approved_llm"],
        }

    entry = {
        "issue_name": str(data.get("issue_name", query[:80] or "New Support Issue")).strip(),
        "category": str(data.get("category", "General_Policy")).strip(),
        "problem_statement": str(data.get("problem_statement", query)).strip(),
        "policy": str(data.get("policy", "")).strip(),
        "resolution_steps": _coerce_string_list(data.get("resolution_steps")),
        "required_documents": _coerce_string_list(data.get("required_documents")),
        "l1_team": str(data.get("l1_team", "Registration")).strip(),
        "l1_person": str(data.get("l1_person", "TBD")).strip(),
        "sources": _coerce_string_list(data.get("sources")) or ["supervisor_approved_llm"],
    }

    if not entry["resolution_steps"]:
        entry["resolution_steps"] = ["Follow the approved resolution guidance."]
    if not entry["required_documents"]:
        entry["required_documents"] = ["No specific documents required"]

    if entry["category"] not in VALID_CATEGORIES:
        entry["category"] = "General_Policy"

    return entry


def _supervisor_resolution_text(steps: list[str]) -> str:
    cleaned = [s.strip() for s in steps if s.strip()]
    if not cleaned:
        return "(supervisor has not written resolution steps yet)"
    if len(cleaned) == 1:
        return cleaned[0]
    return "\n".join(f"{index + 1}. {step}" for index, step in enumerate(cleaned))


def _build_supervisor_format_prompt(
    *,
    query: str,
    caller_type: str,
    entry: dict[str, Any],
) -> str:
    steps = _coerce_string_list(entry.get("resolution_steps"))
    docs = _coerce_string_list(entry.get("required_documents"))
    issue_name = str(entry.get("issue_name") or "").strip() or query[:80]
    category = str(entry.get("category") or entry.get("topic_category") or "").strip()
    problem = str(entry.get("problem_statement") or query).strip()
    policy = str(entry.get("policy") or "").strip()
    l1_team = str(entry.get("l1_team") or "").strip()
    l1_person = str(entry.get("l1_person") or "").strip()

    return f"""Format supervisor-written Helpdesk Copilot resolution content.

Agent query: {query}
Caller type: {normalize_caller_type(caller_type)}

Supervisor draft (paragraph, rough notes, or existing steps — do not invent facts):
Issue name: {issue_name}
Category: {category or "(not set)"}
Problem statement: {problem}
Policy: {policy or "(none)"}
Resolution content:
{_supervisor_resolution_text(steps)}
Required documents: {" | ".join(docs) if docs else "(none)"}
L1 team: {l1_team or "(not set)"}
L1 person: {l1_person or "(not set)"}

Task:
- If resolution content is a paragraph or unstructured notes, split it into clear, actionable steps for a support agent.
- If it is already structured steps, polish wording for clarity and consistency without changing meaning.
- Lightly improve problem_statement and policy only when text is provided; do not invent policy.
- Keep issue_name and category unless they are empty.
- required_documents: keep listed items; add only if clearly implied by the resolution text.

Return ONLY valid JSON:
{{
  "issue_name": "...",
  "category": "...",
  "problem_statement": "...",
  "policy": "...",
  "resolution_steps": ["step 1", "step 2"],
  "required_documents": ["..."],
  "l1_team": "...",
  "l1_person": "...",
  "sources": ["supervisor_approved_llm"]
}}"""


def format_supervisor_entry_with_llm(
    *,
    entry: dict[str, Any],
    query: str,
    caller_type: str,
) -> dict[str, Any]:
    """Format paragraph notes or polish existing supervisor draft fields via the LLM."""
    normalized_query = (query or "").strip()
    normalized_caller = normalize_caller_type(caller_type)
    if not normalized_query:
        return {
            "error": "Query is required",
            "draft": None,
            "draft_source": None,
            "examples_used": [],
            "query": query,
        }

    steps_in = _coerce_string_list(entry.get("resolution_steps"))
    problem_in = str(entry.get("problem_statement") or "").strip()
    if not steps_in and not problem_in:
        return {
            "error": "Write resolution steps or a problem statement before using Generate with AI.",
            "draft": None,
            "draft_source": None,
            "examples_used": [],
            "query": normalized_query,
        }

    prompt = _build_supervisor_format_prompt(
        query=normalized_query,
        caller_type=normalized_caller,
        entry=entry,
    )

    try:
        raw_response = _call_llm(prompt)
        parsed = parse_llm_entry(raw_response, normalized_query)
    except Exception as exc:
        logger.warning("Supervisor format/polish failed: %s", exc)
        return {
            "error": f"AI drafting unavailable: {exc}",
            "draft": None,
            "draft_source": None,
            "examples_used": [],
            "query": normalized_query,
        }

    merged = dict(parsed)
    for field in ("issue_name", "category"):
        original = str(entry.get(field) or entry.get("topic_category") or "").strip()
        if original:
            merged[field] = original
    if str(entry.get("l1_team") or "").strip():
        merged["l1_team"] = str(entry["l1_team"]).strip()
    if str(entry.get("l1_person") or "").strip():
        merged["l1_person"] = str(entry["l1_person"]).strip()
    saved_docs = _coerce_string_list(entry.get("required_documents"))
    if saved_docs and not _coerce_string_list(merged.get("required_documents")):
        merged["required_documents"] = saved_docs

    # Note: one source label — paragraph vs polish is prompt-only, not a separate code path
    is_paragraph = len(steps_in) <= 1 and len(" ".join(steps_in)) > 60
    draft_source = "llm_format" if is_paragraph else "llm_polish"

    return {
        "draft": merged,
        "draft_source": draft_source,
        "examples_used": [],
        "query": normalized_query,
        "caller_type": normalized_caller,
    }


def validate_unified_entry(entry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_ENTRY_FIELDS:
        value = entry.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"Missing required field: {field}")
    if entry.get("resolution_steps") and not isinstance(entry["resolution_steps"], list):
        errors.append("resolution_steps must be a list")
    if entry.get("required_documents") and not isinstance(entry["required_documents"], list):
        errors.append("required_documents must be a list")
    return errors


def _example_ids(examples: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for example in examples:
        value = example.get("_branch_id") or example.get("issue_id")
        if value:
            ids.append(str(value))
    return ids


def _rank_unified_examples(
    query: str, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Re-rank unified KB examples by query intent (e.g. refund vs unable to pay)."""
    query_norm = normalize_query(query)
    query_words = {word for word in query_norm.split() if len(word) > 2}
    refund_query = any(
        token in query_norm
        for token in ("refund", "refunded", "not received", "business days")
    )
    pay_query = any(
        token in query_norm
        for token in ("unable to pay", "cannot pay", "not pay", "removed", "new user")
    )

    scored: list[tuple[float, dict[str, Any]]] = []
    for entry in entries:
        blob = (
            f"{entry.get('issue_name', '')} {entry.get('problem_statement', '')}"
        ).lower()
        overlap = sum(1 for word in query_words if word in blob)
        score = overlap + float(entry.get("_score", 0.0))

        if refund_query:
            if "refund" in blob:
                score += 2.0
            if "unable to pay" in blob or "removed" in blob:
                score -= 1.5
        if pay_query and not refund_query:
            if "unable to pay" in blob or "removed" in blob:
                score += 1.5
            if "refund" in blob and "not received" in blob:
                score -= 1.0

        scored.append((score, entry))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored]


def draft_resolution(query: str, caller_type: str = "seller") -> dict[str, Any]:
    """Draft from unified KB only. Seller/buyer matches are shown separately on submit."""
    normalized_query = (query or "").strip()
    normalized_caller = normalize_caller_type(caller_type)
    if not normalized_query:
        return {
            "error": "Query is required",
            "draft": None,
            "examples_used": [],
            "query": query,
        }

    try:
        unified_hits = _find_similar_entries(normalized_query, top_k=5)
        examples = _rank_unified_examples(normalized_query, unified_hits)[:3]
    except FileNotFoundError as exc:
        return {
            "error": str(exc),
            "setup_instructions": f"Place resolution_examples.json at {UNIFIED_KB_PATH}",
            "draft": None,
            "examples_used": [],
            "query": normalized_query,
        }

    example_ids = _example_ids(examples)

    prompt = _build_prompt(normalized_query, examples)

    try:
        raw_response = _call_llm(prompt)
        parsed_entry = parse_llm_entry(raw_response, normalized_query)
        parsed_entry = _enrich_from_examples(parsed_entry, examples, normalized_query)
    except Exception as exc:
        logger.warning("LLM draft failed: %s", exc)
        response = _llm_failure_response(
            normalized_query,
            examples,
            example_ids,
            f"AI drafting unavailable: {exc}",
        )
        response["caller_type"] = normalized_caller
        return response

    return {
        "draft": parsed_entry,
        "draft_source": "llm",
        "examples_used": example_ids,
        "query": normalized_query,
        "caller_type": normalized_caller,
    }


def _parse_manual_enrichment(raw: str) -> dict[str, Any]:
    text = _strip_json_fence(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    if not isinstance(parsed, dict):
        return {}

    return {
        "problem_statement": str(parsed.get("problem_statement", "")).strip(),
        "required_documents": _coerce_string_list(parsed.get("required_documents")),
        "policy": str(parsed.get("policy", "")).strip(),
    }


def enrich_manual_section(
    *,
    issue_name: str,
    section_text: str,
    resolution_steps: list[str],
    caller_type: str = "seller",
) -> dict[str, Any]:
    """Use LLM to extract problem_statement and required_documents from a manual section.

    Issue name and resolution steps are taken from the rule-based parser — not overwritten here.
    """
    from llm import check_llm_available

    issue_name = str(issue_name or "").strip()
    if not issue_name or not str(section_text or "").strip():
        return {}

    if not check_llm_available():
        logger.info("Skipping manual LLM enrichment — no LLM provider available")
        return {}

    steps = [str(step).strip() for step in resolution_steps if str(step).strip()]
    steps_preview = "\n".join(f"- {step}" for step in steps[:10]) or "- (none parsed yet)"
    section_excerpt = str(section_text).strip()[:2500]
    normalized_caller = normalize_caller_type(caller_type)

    prompt = f"""Parse this Helpdesk Copilot manual section.

Issue name (already fixed — do not change): {issue_name}
Caller type: {normalized_caller}

Resolution steps (already extracted from manual — do not change or repeat):
{steps_preview}

Manual section:
{section_excerpt}

Return ONLY valid JSON:
{{
  "problem_statement": "1-3 sentences describing what the caller faces (agent-facing, polite)",
  "required_documents": ["list of documents or screenshots to collect"],
  "policy": "short policy note only if explicitly stated, else empty string"
}}

Rules:
- Do NOT include issue_name, resolution_steps, l1_team, or l1_person.
- required_documents may be an empty list if the manual does not mention any.
- Base problem_statement on the manual text, not generic filler.
"""

    try:
        content = llm_provider.complete(
            prompt,
            system=(
                "You extract Helpdesk Copilot fields as strict JSON only. "
                "Return problem_statement and required_documents from the manual text."
            ),
            max_tokens=500,
            timeout=90,
        )
    except Exception as exc:
        logger.warning("Manual section LLM enrichment failed: %s", exc)
        return {}
    return _parse_manual_enrichment(content)


def apply_manual_llm_enrichment(
    branch: dict[str, Any],
    section_text: str,
    caller_type: str = "seller",
) -> dict[str, Any]:
    """Merge LLM-extracted problem_statement and documents into a parsed branch."""
    enriched = enrich_manual_section(
        issue_name=str(branch.get("branch_name", "")),
        section_text=section_text,
        resolution_steps=list(branch.get("steps") or []),
        caller_type=caller_type,
    )
    if not enriched:
        return branch

    problem = enriched.get("problem_statement", "").strip()
    if problem:
        branch["agent_script"] = problem
        branch["problem_statement"] = problem

    documents = enriched.get("required_documents")
    if documents is not None:
        branch["documents"] = documents

    policy = enriched.get("policy", "").strip()
    if policy:
        branch["policy"] = policy

    branch["manual_enrichment"] = "llm"
    return branch
