"""Cross-encoder re-ranker for Helpdesk Copilot hybrid search."""

from __future__ import annotations

import logging
import math
import os
import time
from typing import Any

from concurrency import guard_model_method
from kb_manager import get_branch_description
from kb_search import (
    _hybrid_final_score,
    get_agent_script,
    normalize_query,
)

logger = logging.getLogger(__name__)

VALID_MODES = frozenset({"cross_encoder", "xgboost", "hybrid", "disabled"})

_cross_encoder = None
_load_failed = False

CROSS_ENCODER_ENABLED = os.getenv("CROSS_ENCODER_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)
CROSS_ENCODER_MODEL = os.getenv(
    "CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
)
CROSS_ENCODER_TOP_K = max(1, int(os.getenv("CROSS_ENCODER_TOP_K", "15")))
CROSS_ENCODER_WEIGHT = float(os.getenv("CROSS_ENCODER_WEIGHT", "0.7"))
CROSS_ENCODER_BATCH_SIZE = max(1, int(os.getenv("CROSS_ENCODER_BATCH_SIZE", "16")))
_CONFIGURED_MODE = os.getenv("RERANKING_MODE", "").strip().lower()


def _default_ranking_mode() -> str:
    # Rerankers are opt-in (see benchmarks/results.md): XGBoost is about level with
    # the plain hybrid formula on top-1 but weaker on top-3 and slower, and the
    # cross-encoder is more accurate but ~7x slower. A model file merely existing
    # on disk shouldn't silently change ranking.
    return _CONFIGURED_MODE or "hybrid"


RERANKING_MODE = _default_ranking_mode()
if RERANKING_MODE not in VALID_MODES:
    logger.warning("Invalid RERANKING_MODE=%r — using hybrid", RERANKING_MODE)
    RERANKING_MODE = "hybrid"

# Hybrid combine: 0.7 * normalized_ce + 0.3 * normalized_existing (after batch norm).
HYBRID_CE_WEIGHT = CROSS_ENCODER_WEIGHT
HYBRID_EXISTING_WEIGHT = 1.0 - CROSS_ENCODER_WEIGHT


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _minmax_normalize(scores: list[float]) -> list[float]:
    if not scores:
        return []
    if len(scores) == 1:
        return [1.0]
    low = min(scores)
    high = max(scores)
    if high <= low:
        return [1.0 for _ in scores]
    span = high - low
    return [round((score - low) / span, 4) for score in scores]


def _steps_summary(branch: dict, *, max_steps: int = 5) -> str:
    steps = branch.get("steps")
    collected: list[str] = []
    if isinstance(steps, list):
        collected = [str(step) for step in steps[:max_steps]]
    elif isinstance(steps, dict):
        for value in steps.values():
            if isinstance(value, list):
                collected.extend(str(step) for step in value[:max_steps])
            if len(collected) >= max_steps:
                break
        collected = collected[:max_steps]
    else:
        for key, value in branch.items():
            if key.startswith("steps_") and isinstance(value, list):
                collected.extend(str(step) for step in value[:max_steps])
            if len(collected) >= max_steps:
                break
        collected = collected[:max_steps]
    return " ".join(collected)


def build_rerank_document_text(branch: dict, store=None) -> str:
    """Document side of query–document pair for cross-encoder scoring."""
    if not isinstance(branch, dict):
        return ""

    parts = [branch.get("branch_name", "")]
    if store is not None:
        problem = store.data.get("problem_name") or store.category.get("name")
        if problem:
            parts.append(str(problem))

    keywords = branch.get("trigger_keywords") or []
    if isinstance(keywords, list):
        parts.append(", ".join(str(k) for k in keywords if k))

    description = get_branch_description(branch)
    if description:
        parts.append(description)

    script = get_agent_script(branch)
    if script:
        parts.append(script)

    steps_text = _steps_summary(branch)
    if steps_text:
        parts.append(steps_text)

    return " | ".join(part.strip() for part in parts if part and str(part).strip())


def load_cross_encoder(*, force: bool = False):
    """Lazy-load CrossEncoder once; returns None when disabled or unavailable."""
    global _cross_encoder, _load_failed

    if not CROSS_ENCODER_ENABLED:
        return None
    if _cross_encoder is not None and not force:
        return _cross_encoder
    if _load_failed and not force:
        return None

    try:
        from sentence_transformers import CrossEncoder

        start = time.perf_counter()
        _cross_encoder = guard_model_method(
            CrossEncoder(CROSS_ENCODER_MODEL, device="cpu"), "predict"
        )
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.info(
            "Loaded cross-encoder %s in %sms (cpu)",
            CROSS_ENCODER_MODEL,
            elapsed_ms,
        )
        _load_failed = False
        return _cross_encoder
    except Exception as exc:
        logger.warning(
            "Cross-encoder unavailable (%s) — fallback chain continues",
            exc,
        )
        _cross_encoder = None
        _load_failed = True
        return None


def is_cross_encoder_available() -> bool:
    return load_cross_encoder() is not None


def _xgboost_available(caller_type: str) -> bool:
    try:
        from xgboost_ranker import is_ranker_available

        return is_ranker_available(caller_type)
    except ImportError:
        return False


def get_effective_ranking_mode(caller_type: str = "seller") -> str:
    """Resolve configured mode after availability checks."""
    mode = RERANKING_MODE
    if mode == "disabled":
        return "disabled"
    if mode == "hybrid":
        return "hybrid"
    if mode == "xgboost":
        return "xgboost" if _xgboost_available(caller_type) else "hybrid_fallback"
    if mode == "cross_encoder":
        if is_cross_encoder_available():
            return "cross_encoder"
        if _xgboost_available(caller_type):
            return "xgboost_fallback"
        return "hybrid_fallback"
    return "hybrid_fallback"


def get_fallback_state(caller_type: str = "seller") -> str | None:
    """Which fallback tier is active when configured mode is unavailable."""
    if RERANKING_MODE == "cross_encoder" and not is_cross_encoder_available():
        if _xgboost_available(caller_type):
            return "xgboost"
        return "hybrid"
    if RERANKING_MODE == "xgboost" and not _xgboost_available(caller_type):
        return "hybrid"
    return None


def faiss_candidate_k(top_k: int, caller_type: str) -> int:
    """FAISS pool size before re-ranking (~15–20 for cross-encoder)."""
    mode = get_effective_ranking_mode(caller_type)
    if _CONFIGURED_MODE == "cross_encoder" or mode == "cross_encoder":
        # Note: cap at 20 — enough CE candidates without scanning full KB
        return min(20, max(top_k, CROSS_ENCODER_TOP_K, 15))
    return max(top_k, 10)


def _existing_score(item: dict) -> float:
    if item.get("final_score") is not None:
        return float(item["final_score"])
    if item.get("xgboost_score") is not None:
        return float(item["xgboost_score"])
    branch = item.get("branch") or {}
    return _hybrid_final_score(
        item.get("normalized_query", ""),
        item.get("expanded_query", ""),
        branch,
        float(item.get("semantic_score", 0.0)),
        float(item.get("keyword_score", 0.0)),
    )


def _valid_candidates(faiss_results: list[dict]) -> list[dict]:
    valid: list[dict] = []
    for item in faiss_results:
        branch = item.get("branch")
        if not isinstance(branch, dict):
            continue
        if not branch.get("branch_id") or not branch.get("branch_name"):
            continue
        valid.append(item)
    return valid


def rank_with_cross_encoder(
    query: str,
    faiss_results: list[dict],
    caller_type: str,
    store,
    embed_model,
    *,
    combine_with_xgboost: bool = False,
) -> list[dict] | None:
    """
    Re-rank FAISS hits with a cross-encoder.

    Returns None when the model is unavailable (caller should fall back).
    Hybrid combine: HYBRID_CE_WEIGHT * norm_ce + HYBRID_EXISTING_WEIGHT * norm_existing.
    """
    _ = embed_model
    model = load_cross_encoder()
    if model is None:
        return None

    candidates = _valid_candidates(faiss_results)
    if not candidates:
        return []

    normalized_query = normalize_query(query)
    if not normalized_query:
        return candidates

    if combine_with_xgboost:
        try:
            from xgboost_ranker import is_ranker_available, rank_with_xgboost

            if is_ranker_available(caller_type):
                candidates = rank_with_xgboost(
                    query, candidates, caller_type, store, embed_model
                )
        except ImportError:
            pass

    pairs = [
        (normalized_query, build_rerank_document_text(item["branch"], store))
        for item in candidates
    ]

    start = time.perf_counter()
    raw_scores = model.predict(pairs, batch_size=CROSS_ENCODER_BATCH_SIZE)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "Cross-encoder scored %s pairs in %sms (batch=%s)",
        len(pairs),
        elapsed_ms,
        CROSS_ENCODER_BATCH_SIZE,
    )

    ce_norm = [_sigmoid(float(score)) for score in raw_scores]
    existing_raw = [_existing_score(item) for item in candidates]
    existing_norm = _minmax_normalize(existing_raw)

    reranked: list[dict] = []
    for item, ce_score, ce_n, existing_n in zip(
        candidates, raw_scores, ce_norm, existing_norm
    ):
        combined = round(
            HYBRID_CE_WEIGHT * ce_n + HYBRID_EXISTING_WEIGHT * existing_n, 4
        )
        enriched = dict(item)
        enriched["cross_encoder_score"] = round(float(ce_score), 4)
        enriched["cross_encoder_norm"] = round(ce_n, 4)
        enriched["existing_norm"] = round(existing_n, 4)
        enriched["final_score"] = combined
        reranked.append(enriched)

    reranked.sort(
        key=lambda row: (row["final_score"], row.get("cross_encoder_norm", 0.0)),
        reverse=True,
    )
    return reranked


def get_cross_encoder_health(caller_type: str = "seller") -> dict[str, Any]:
    loaded = _cross_encoder is not None
    return {
        "enabled": CROSS_ENCODER_ENABLED,
        "loaded": loaded,
        "load_failed": _load_failed,
        "model": CROSS_ENCODER_MODEL,
        "ranking_mode": get_effective_ranking_mode(caller_type),
        "configured_mode": _CONFIGURED_MODE or (
            "xgboost" if RERANKING_MODE == "xgboost" else "hybrid"
        ),
        "fallback_state": get_fallback_state(caller_type),
        "top_k": CROSS_ENCODER_TOP_K,
        "weight": CROSS_ENCODER_WEIGHT,
        "batch_size": CROSS_ENCODER_BATCH_SIZE,
        "hybrid_formula": (
            f"{HYBRID_CE_WEIGHT}*norm_ce + {HYBRID_EXISTING_WEIGHT}*norm_existing"
        ),
    }
