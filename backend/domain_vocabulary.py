"""Domain vocabulary and abbreviation data for query correction."""

from __future__ import annotations

import json
import re
from pathlib import Path

KNOWLEDGE_ROOT = Path(__file__).parent / "knowledge"
VOCAB_PATH = KNOWLEDGE_ROOT / "domain_vocabulary.json"
ABBREV_PATH = KNOWLEDGE_ROOT / "query_abbreviations.json"
TYPO_PHRASES_PATH = KNOWLEDGE_ROOT / "query_typo_phrases.json"

_typo_phrase_cache: dict | None = None
_vocab_cache: dict | None = None
_abbrev_cache: dict[str, str] | None = None


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_domain_vocabulary(*, force: bool = False) -> dict:
    global _vocab_cache
    if _vocab_cache is not None and not force:
        return _vocab_cache

    data = _load_json(VOCAB_PATH)
    _vocab_cache = {
        "version": data.get("version", 0),
        "terms": sorted(set(data.get("terms", []))),
        "phrases": sorted(set(data.get("phrases", []))),
        "source_counts": data.get("source_counts", {}),
    }
    return _vocab_cache


def load_abbreviations(*, force: bool = False) -> dict[str, str]:
    global _abbrev_cache
    if _abbrev_cache is not None and not force:
        return _abbrev_cache

    data = _load_json(ABBREV_PATH)
    abbrev = data.get("abbreviations", data)
    _abbrev_cache = {
        str(key).lower().strip(): str(value).strip()
        for key, value in abbrev.items()
        if str(key).strip() and str(value).strip()
    }
    return _abbrev_cache


def vocabulary_lookup() -> set[str]:
    vocab = load_domain_vocabulary()
    return {item.lower() for item in vocab.get("terms", [])}


def phrase_lookup() -> set[str]:
    vocab = load_domain_vocabulary()
    return {item.lower() for item in vocab.get("phrases", [])}


def tokenize_domain_text(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if token]


def load_typo_phrases(*, force: bool = False) -> dict:
    global _typo_phrase_cache
    if _typo_phrase_cache is not None and not force:
        return _typo_phrase_cache
    data = _load_json(TYPO_PHRASES_PATH)
    _typo_phrase_cache = {
        "phrases": {k.lower().strip(): v.lower().strip() for k, v in data.get("phrases", {}).items()},
        "protected_phrases": [p.lower().strip() for p in data.get("protected_phrases", [])],
    }
    return _typo_phrase_cache


def get_vocabulary_status() -> dict:
    vocab = load_domain_vocabulary()
    abbrev = load_abbreviations()
    return {
        "loaded": bool(vocab.get("terms") or vocab.get("phrases")),
        "path": f"knowledge/{VOCAB_PATH.name}",
        "version": vocab.get("version"),
        "term_count": len(vocab.get("terms", [])),
        "phrase_count": len(vocab.get("phrases", [])),
        "abbreviation_count": len(abbrev),
        "abbreviation_path": f"knowledge/{ABBREV_PATH.name}",
    }
