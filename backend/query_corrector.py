"""Safe query normalization and domain spell correction for Helpdesk Copilot search."""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from typing import Any

from domain_vocabulary import (
    get_vocabulary_status,
    load_abbreviations,
    load_domain_vocabulary,
    load_typo_phrases,
    vocabulary_lookup,
)

logger = logging.getLogger(__name__)

PROTECTED_PATTERN = re.compile(
    r"("
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
    r"https?://\S+|"
    r"\b(?:nw|po|order|bid|ra)[-_/]?\d{4,}\b|"
    r"\b\d{6,}\b|"
    r"(?:₹|rs\.?|inr)\s*[\d,]+(?:\.\d+)?"
    r")",
    re.IGNORECASE,
)
WORD_PATTERN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.IGNORECASE)

# Ordinary English words are never "corrected" into domain terms. The domain
# vocabulary deliberately excludes them, so without this guard fuzzy matching
# turned "unable" into "able" and "with" into "switch".
COMMON_WORDS = frozenset(
    """
    a about above after again against all also am an and any are as at be because been
    before being below between both but by can cannot could did do does doing done down
    during each even ever every few for from further get gets getting got had has have
    having he her here him his how i if in into is it its itself just me more most my
    myself need needs no nor not now of off on once only or other our out over own please
    same she should since so some still such than that the their them then there these
    they this those through to too under until up upon us very via was we were what when
    where which while who whom why will with within without would yet you your
    able unable again already always anything because before cant didnt doesnt dont
    either else enough everything isnt keeps kept know last later many much never next
    nothing often once since something sometimes soon tell thanks today tried try trying
    wasnt went whats wont yesterday
    issue issues problem problems error errors help working work works show showing shown
    failed fail fails failing coming come comes came going goes went says said saying
    seems seem still yet want wants wanted take taking taken make making made give giving
    """.split()
)

_vocab_terms: set[str] | None = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def is_correction_enabled() -> bool:
    return _env_bool("QUERY_CORRECTION_ENABLED", True)


def correction_mode() -> str:
    mode = os.environ.get("QUERY_CORRECTION_MODE", "symspell").strip().lower()
    if mode in {"dictionary", "symspell", "experimental_contextual", "disabled"}:
        return mode
    return "symspell"


def min_confidence() -> float:
    return _env_float("QUERY_CORRECTION_MIN_CONFIDENCE", 0.80)


def max_edit_distance() -> int:
    return _env_int("QUERY_CORRECTION_MAX_EDIT_DISTANCE", 2)


def _unicode_normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def normalize_query_text(text: str) -> str:
    return _collapse_whitespace(_unicode_normalize(text).lower())


def _split_protected(text: str) -> list[tuple[str, bool]]:
    parts: list[tuple[str, bool]] = []
    cursor = 0
    for match in PROTECTED_PATTERN.finditer(text):
        if match.start() > cursor:
            parts.append((text[cursor : match.start()], False))
        parts.append((match.group(0), True))
        cursor = match.end()
    if cursor < len(text):
        parts.append((text[cursor:], False))
    return parts or [("", False)]


def _get_vocab_terms() -> set[str]:
    global _vocab_terms
    if _vocab_terms is None:
        _vocab_terms = vocabulary_lookup()
    return _vocab_terms


_sorted_vocab: tuple[set[str], tuple[str, ...]] | None = None


def _get_sorted_vocab() -> tuple[str, ...]:
    global _sorted_vocab
    vocab = _get_vocab_terms()
    if _sorted_vocab is None or _sorted_vocab[0] is not vocab:
        _sorted_vocab = (vocab, tuple(sorted(vocab)))
    return _sorted_vocab[1]


def _expand_abbreviations(text: str) -> tuple[str, list[dict[str, str]]]:
    abbrev = load_abbreviations()
    changes: list[dict[str, str]] = []
    tokens = text.split()
    expanded: list[str] = []

    for token in tokens:
        bare = re.sub(r"[^a-z0-9]", "", token.lower())
        replacement = abbrev.get(bare)
        if replacement and bare != replacement.replace(" ", ""):
            expanded.append(replacement)
            changes.append({"type": "abbreviation", "from": token, "to": replacement})
        else:
            expanded.append(token)

    return " ".join(expanded), changes


def _spell_correct_word(word: str) -> tuple[str, float]:
    bare = word.lower()
    vocab = _get_vocab_terms()
    if not vocab or bare in vocab or bare in COMMON_WORDS or len(bare) <= 2:
        return word, 1.0

    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return word, 1.0

    # Sorted, not the raw set: extractOne keeps the first of equally scored
    # candidates, and set order changes with PYTHONHASHSEED on every restart.
    match = process.extractOne(
        bare,
        _get_sorted_vocab(),
        scorer=fuzz.ratio,
        score_cutoff=70,
    )
    if not match:
        return word, 1.0

    candidate, score, _index = match
    distance = _levenshtein(bare, candidate)
    if distance > max_edit_distance():
        return word, 1.0

    confidence = round(score / 100.0, 4)
    if confidence < min_confidence():
        return word, confidence

    if word.isupper():
        return candidate.upper(), confidence
    if word[:1].isupper():
        return candidate.capitalize(), confidence
    return candidate, confidence


def _levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    prev = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            current.append(
                min(
                    prev[j] + 1,
                    current[j - 1] + 1,
                    prev[j - 1] + cost,
                )
            )
        prev = current
    return prev[-1]


def _apply_spell_correction(text: str) -> tuple[str, list[dict[str, str]], float]:
    changes: list[dict[str, str]] = []
    confidences: list[float] = []
    corrected_parts: list[str] = []

    for chunk, protected in _split_protected(text):
        if protected:
            corrected_parts.append(chunk)
            continue

        words = WORD_PATTERN.findall(chunk)
        if not words:
            corrected_parts.append(chunk)
            continue

        rebuilt = chunk
        for word in words:
            fixed, confidence = _spell_correct_word(word)
            confidences.append(confidence)
            if fixed != word:
                changes.append({"type": "spelling", "from": word, "to": fixed})
                rebuilt = rebuilt.replace(word, fixed, 1)
        corrected_parts.append(rebuilt)

    overall = round(min(confidences), 4) if confidences else 1.0
    return "".join(corrected_parts), changes, overall


def _is_protected_phrase(text: str) -> bool:
    lowered = text.lower().strip()
    for phrase in load_typo_phrases().get("protected_phrases", []):
        if phrase and phrase in lowered:
            return True
    return False


def _apply_phrase_corrections(text: str) -> tuple[str, list[dict[str, str]]]:
    phrases = load_typo_phrases().get("phrases", {})
    if not phrases:
        return text, []
    lowered = text.lower().strip()
    if _is_protected_phrase(lowered):
        return text, []
    changes: list[dict[str, str]] = []
    # longest phrase first to avoid partial replacements
    for src in sorted(phrases, key=len, reverse=True):
        if src in lowered:
            dst = phrases[src]
            lowered = lowered.replace(src, dst)
            changes.append({"type": "phrase", "from": src, "to": dst})
    return lowered, changes


def _retrieval_gate_enabled() -> bool:
    return _env_bool("QUERY_CORRECTION_RETRIEVAL_GATE", True)


def _top_semantic_score(query: str, caller_type: str) -> float:
    try:
        from kb_manager import get_kb, get_registry
        from kb_search import faiss_semantic_search

        store = get_kb(caller_type)
        embed = get_registry().embed_model
        hits = faiss_semantic_search(query, store, embed, top_k=1)
        if not hits:
            return 0.0
        return float(hits[0].get("semantic_score", 0.0))
    except Exception:
        return 0.0


def correct_query(query: str, *, caller_type: str | None = None) -> dict[str, Any]:
    original = query or ""
    normalized = normalize_query_text(original)

    base = {
        "original_query": original,
        "normalized_query": normalized,
        "corrected_query": normalized,
        "correction_applied": False,
        "correction_confidence": 1.0,
        "correction_changes": [],
        "correction_mode": correction_mode(),
    }

    if not normalized:
        return base

    if _is_protected_phrase(normalized):
        return base

    if not is_correction_enabled() or correction_mode() == "disabled":
        return base

    working = normalized
    changes: list[dict[str, str]] = []

    phrase_fixed, phrase_changes = _apply_phrase_corrections(working)
    working = phrase_fixed
    changes.extend(phrase_changes)

    expanded, abbrev_changes = _expand_abbreviations(working)
    working = expanded
    changes.extend(abbrev_changes)

    confidence = 1.0
    if correction_mode() in {"symspell", "experimental_contextual"}:
        if correction_mode() == "experimental_contextual":
            # Note: contextual mode is a stub — same as symspell until a real model exists
            pass
        if load_domain_vocabulary().get("terms"):
            working, spell_changes, confidence = _apply_spell_correction(working)
            changes.extend(spell_changes)

    corrected = _collapse_whitespace(working)
    applied = corrected != normalized and bool(changes)
    if applied and confidence < min_confidence():
        applied = False
        corrected = normalized

    if applied and caller_type and _retrieval_gate_enabled():
        before = _top_semantic_score(normalized, caller_type)
        after = _top_semantic_score(corrected, caller_type)
        if after + 0.01 < before:
            applied = False
            corrected = normalized
            changes = []

    result = {
        **base,
        "corrected_query": corrected,
        "correction_applied": applied,
        "correction_confidence": confidence if applied else 1.0,
        "correction_changes": changes if applied else [],
    }
    if applied:
        logger.info(
            "Query correction applied: %r -> %r (confidence=%.2f)",
            normalized,
            corrected,
            confidence,
        )
    return result


def get_query_corrector_status() -> dict[str, Any]:
    vocab = get_vocabulary_status()
    mode = correction_mode()
    enabled = is_correction_enabled() and mode != "disabled"
    return {
        "enabled": enabled,
        "mode": mode,
        "min_confidence": min_confidence(),
        "max_edit_distance": max_edit_distance(),
        "vocabulary": vocab,
        "status": "active" if enabled and vocab.get("loaded") else "disabled",
    }
