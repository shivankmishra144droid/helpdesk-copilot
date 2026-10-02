"""Build domain vocabulary JSON from seller/buyer knowledge bases."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from category_utils import load_topic_categories, normalize_caller_type  # noqa: E402
from ingest import load_kb  # noqa: E402
from kb_manager import VALID_CALLER_TYPES, kb_path  # noqa: E402

OUTPUT_PATH = BACKEND_DIR / "knowledge" / "domain_vocabulary.json"
STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "to",
    "for",
    "in",
    "on",
    "at",
    "is",
    "are",
    "was",
    "be",
    "can",
    "not",
    "no",
    "of",
    "with",
    "from",
    "by",
    "as",
    "it",
    "this",
    "that",
    "please",
    "sir",
    "maam",
    "help",
    "issue",
    "problem",
    "error",
    "unable",
    "cannot",
    "working",
    "failed",
    "fail",
    "show",
    "showing",
    "option",
    "options",
    "step",
    "steps",
    "contact",
    "team",
    "support",
    "after",
    "each",
    "one",
    "all",
    "any",
    "if",
    "then",
    "when",
    "where",
    "what",
    "how",
    "do",
    "does",
    "did",
    "will",
    "would",
    "should",
    "have",
    "has",
    "had",
    "been",
    "being",
    "into",
    "through",
    "during",
    "before",
    "after",
    "above",
    "below",
    "between",
    "under",
    "again",
    "further",
    "once",
    "here",
    "there",
    "why",
    "who",
    "which",
    "their",
    "them",
    "they",
    "you",
    "your",
    "our",
    "we",
    "us",
    "me",
    "my",
    "i",
}


def _tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if token]


def _collect_from_kb(caller_type: str) -> tuple[Counter[str], Counter[str]]:
    path = kb_path(caller_type)
    data = load_kb(path)
    term_counts: Counter[str] = Counter()
    phrase_counts: Counter[str] = Counter()

    def add_text(text: str) -> None:
        cleaned = " ".join(str(text or "").lower().split())
        if not cleaned:
            return
        if len(cleaned.split()) >= 2:
            phrase_counts[cleaned] += 1
        for token in _tokenize(cleaned):
            if len(token) >= 2 and token not in STOPWORDS:
                term_counts[token] += 1

    for branch in data.get("branches", []):
        add_text(branch.get("branch_name", ""))
        for keyword in branch.get("trigger_keywords", []):
            add_text(str(keyword))
        for field in (
            "agent_script",
            "auto_script",
            "manual_script",
            "problem_statement",
            "policy",
        ):
            value = branch.get(field)
            if value:
                add_text(str(value)[:300])
        steps = branch.get("steps") or []
        if isinstance(steps, list):
            for step in steps[:8]:
                add_text(str(step))

    for item in load_topic_categories(caller_type):
        add_text(item.get("name", ""))
        add_text(item.get("id", "").replace("_", " "))

    return term_counts, phrase_counts


def build_vocabulary() -> dict:
    total_terms: Counter[str] = Counter()
    total_phrases: Counter[str] = Counter()
    source_counts: dict[str, dict[str, int]] = {}

    for caller_type in VALID_CALLER_TYPES:
        terms, phrases = _collect_from_kb(caller_type)
        total_terms.update(terms)
        total_phrases.update(phrases)
        source_counts[caller_type] = {
            "terms": len(terms),
            "phrases": len(phrases),
        }

    terms = sorted(
        token
        for token, count in total_terms.items()
        if count >= 1 and len(token) >= 2
    )
    phrases = sorted(
        phrase
        for phrase, count in total_phrases.items()
        if count >= 1 and 2 <= len(phrase.split()) <= 6
    )

    return {
        "version": 1,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "terms": terms,
        "phrases": phrases,
        "source_counts": source_counts,
    }


def main() -> None:
    payload = build_vocabulary()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(
        f"Wrote {OUTPUT_PATH} "
        f"({len(payload['terms'])} terms, {len(payload['phrases'])} phrases)"
    )


if __name__ == "__main__":
    main()
