"""Topic categories for buyer/seller Helpdesk Copilot navigation."""

from __future__ import annotations

import json
import re
from pathlib import Path

KNOWLEDGE_ROOT = Path(__file__).parent / "knowledge"

TAXONOMY_PATH = KNOWLEDGE_ROOT / "taxonomy.json"


def _load_taxonomy() -> dict:
    """Domain taxonomy (categories, keyword rules, aliases) lives in data, not code."""
    if not TAXONOMY_PATH.exists():
        return {}
    with open(TAXONOMY_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


_TAXONOMY = _load_taxonomy()

# Default category lists, used until categories.json exists for a caller type.
CATEGORY_LISTS: dict[str, list[dict[str, str]]] = {
    caller: list(_TAXONOMY.get("categories", {}).get(caller, []))
    for caller in ("buyer", "seller")
}

# (category_id, phrases to match in tagging + branch name), first match wins.
INFERENCE_RULES: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    caller: [
        (category_id, tuple(phrases))
        for category_id, phrases in _TAXONOMY.get("inference_rules", {}).get(caller, [])
    ]
    for caller in ("buyer", "seller")
}

# Display names / LLM labels -> category ids.
CATEGORY_ALIASES: dict[str, str] = dict(_TAXONOMY.get("category_aliases", {}))

FALLBACK_CATEGORY: dict[str, str] = dict(_TAXONOMY.get("fallback_category", {}))


def normalize_caller_type(caller_type: str) -> str:
    value = (caller_type or "seller").lower().strip()
    return "buyer" if value == "buyer" else "seller"


def categories_path(caller_type: str) -> Path:
    return KNOWLEDGE_ROOT / normalize_caller_type(caller_type) / "categories.json"


def load_topic_categories(caller_type: str) -> list[dict[str, str]]:
    normalized = normalize_caller_type(caller_type)
    path = categories_path(normalized)
    if path.exists():
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data.get("categories", CATEGORY_LISTS[normalized])
    return CATEGORY_LISTS[normalized]


def topic_category_ids(caller_type: str) -> set[str]:
    return {item["id"] for item in load_topic_categories(caller_type)}


def resolve_stored_category_id(
    category: str | None,
    caller_type: str,
    *,
    issue_name: str = "",
    problem_statement: str = "",
) -> str | None:
    """Map draft/LLM category labels to a valid categories-table id, or None."""
    normalized = normalize_caller_type(caller_type)
    valid_ids = topic_category_ids(normalized)
    raw = str(category or "").strip()

    if raw and raw in valid_ids:
        return raw

    candidates: list[str] = []
    if raw:
        candidates.append(raw.lower().replace(" ", "_"))
        mapped = CATEGORY_ALIASES.get(raw.lower())
        if mapped:
            candidates.append(mapped)

    for candidate in candidates:
        if candidate in valid_ids:
            return candidate

    inferred = infer_topic_category(
        {"branch_name": issue_name, "tagging": problem_statement},
        normalized,
    )
    if inferred in valid_ids:
        return inferred
    return None


def save_topic_categories(caller_type: str, categories: list[dict[str, str]]) -> None:
    """Persist category list to knowledge/{caller_type}/categories.json."""
    normalized = normalize_caller_type(caller_type)
    path = categories_path(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump({"categories": categories}, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temp.replace(path)


def category_name_by_id(caller_type: str, category_id: str) -> str | None:
    for item in load_topic_categories(caller_type):
        if item["id"] == category_id:
            return item["name"]
    return None


def infer_topic_category(branch: dict, caller_type: str) -> str:
    normalized = normalize_caller_type(caller_type)
    tagging = (branch.get("tagging") or "").lower()
    name = (branch.get("branch_name") or "").lower()
    haystack = f"{tagging} {name}"

    for category_id, phrases in INFERENCE_RULES[normalized]:
        if any(phrase in haystack for phrase in phrases):
            return category_id

    fallback = FALLBACK_CATEGORY.get(normalized)
    if fallback:
        return fallback
    categories = CATEGORY_LISTS.get(normalized) or [{"id": "uncategorized"}]
    return categories[0]["id"]


def assign_topic_category(branch: dict, caller_type: str) -> str:
    existing = branch.get("topic_category")
    if existing:
        return existing
    category_id = infer_topic_category(branch, caller_type)
    branch["topic_category"] = category_id
    return category_id


def enrich_branches(branches: list[dict], caller_type: str) -> list[dict]:
    for branch in branches:
        assign_topic_category(branch, caller_type)
    return branches


def count_branches_by_category(
    branches: list[dict], categories: list[dict[str, str]]
) -> list[dict]:
    counts: dict[str, int] = {}
    for branch in branches:
        category_id = branch.get("topic_category") or "uncategorized"
        counts[category_id] = counts.get(category_id, 0) + 1

    return [
        {
            "id": item["id"],
            "name": item["name"],
            "branch_count": counts.get(item["id"], 0),
        }
        for item in categories
    ]
