"""Intent / topic-category classifier for Helpdesk Copilot search."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression

from category_utils import (
    category_name_by_id,
    load_topic_categories,
    normalize_caller_type,
)
from kb_manager import build_branch_embed_text, get_branch_description, get_kb
from model_io import load_bundle, save_bundle

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent / "models"
DEFAULT_MODEL_PATH = MODEL_DIR / "intent_classifier.pkl"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
INTENT_CATEGORY_BOOST = 0.05

_supervised_bundle: dict[str, Any] | None = None
_prototype_cache: dict[str, dict[str, np.ndarray]] = {}


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


def is_intent_enabled() -> bool:
    return _env_bool("INTENT_CLASSIFIER_ENABLED", True)


def intent_mode() -> str:
    mode = os.environ.get("INTENT_CLASSIFIER_MODE", "prototype").strip().lower()
    if mode in {"prototype", "supervised", "disabled"}:
        return mode
    return "prototype"


def confidence_threshold() -> float:
    return _env_float("INTENT_CONFIDENCE_THRESHOLD", 0.55)


def model_path() -> Path:
    custom = os.environ.get("INTENT_MODEL_PATH", "").strip()
    return Path(custom) if custom else DEFAULT_MODEL_PATH


def _category_texts(caller_type: str, category_id: str) -> list[str]:
    normalized = normalize_caller_type(caller_type)
    texts: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        cleaned = " ".join(str(text or "").lower().split())
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            texts.append(cleaned)

    name = category_name_by_id(normalized, category_id)
    if name:
        add(name)
        add(f"{name} issue")
    add(category_id.replace("_", " "))

    store = get_kb(normalized)
    for branch in store.branches:
        if branch.get("topic_category") != category_id:
            continue
        add(branch.get("branch_name", ""))
        for keyword in branch.get("trigger_keywords", []):
            add(str(keyword))
        add(get_branch_description(branch)[:200])
        add(build_branch_embed_text(branch))

    return texts


def build_category_prototypes(
    caller_type: str,
    embed_model: SentenceTransformer,
) -> dict[str, np.ndarray]:
    normalized = normalize_caller_type(caller_type)
    categories = load_topic_categories(normalized)
    prototypes: dict[str, np.ndarray] = {}

    for item in categories:
        category_id = item["id"]
        texts = _category_texts(normalized, category_id)
        if not texts:
            continue
        vectors = embed_model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).astype(np.float32)
        prototypes[category_id] = np.mean(vectors, axis=0)
        norm = np.linalg.norm(prototypes[category_id])
        if norm > 0:
            prototypes[category_id] = prototypes[category_id] / norm

    return prototypes


def _get_prototypes(
    caller_type: str,
    embed_model: SentenceTransformer,
) -> dict[str, np.ndarray]:
    normalized = normalize_caller_type(caller_type)
    if normalized not in _prototype_cache:
        _prototype_cache[normalized] = build_category_prototypes(
            normalized, embed_model
        )
    return _prototype_cache[normalized]


def clear_prototype_cache() -> None:
    _prototype_cache.clear()


def _predict_prototype(
    query: str,
    caller_type: str,
    embed_model: SentenceTransformer,
    *,
    top_n: int = 3,
) -> dict[str, Any] | None:
    prototypes = _get_prototypes(caller_type, embed_model)
    if not prototypes:
        return None

    vector = embed_model.encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype(np.float32)[0]

    scores: list[tuple[str, float]] = []
    for category_id, prototype in prototypes.items():
        score = float(np.dot(vector, prototype))
        scores.append((category_id, score))

    scores.sort(key=lambda item: item[1], reverse=True)
    if not scores:
        return None

    top_scores = scores[:top_n]
    best_id, best_score = top_scores[0]
    confidence = round(max(0.0, min(1.0, best_score)), 4)
    return {
        "predicted_category": best_id,
        "intent_confidence": confidence,
        "intent_top_categories": [
            {
                "category_id": category_id,
                "category_name": category_name_by_id(caller_type, category_id),
                "confidence": round(max(0.0, min(1.0, score)), 4),
            }
            for category_id, score in top_scores
        ],
        "intent_mode_used": "prototype",
    }


def load_supervised_model(*, force: bool = False) -> dict[str, Any] | None:
    global _supervised_bundle
    if _supervised_bundle is not None and not force:
        return _supervised_bundle

    path = model_path()
    if not path.exists():
        return None

    bundle = load_bundle(path)
    if bundle is None:
        return None

    if not isinstance(bundle, dict) or "models" not in bundle:
        logger.warning("Invalid intent classifier bundle at %s", path)
        return None

    _supervised_bundle = bundle
    return bundle


def _predict_supervised(
    query: str,
    caller_type: str,
    embed_model: SentenceTransformer,
    *,
    top_n: int = 3,
) -> dict[str, Any] | None:
    bundle = load_supervised_model()
    if not bundle:
        return None

    normalized = normalize_caller_type(caller_type)
    model: LogisticRegression | None = bundle.get("models", {}).get(normalized)
    label_encoder = bundle.get("label_encoders", {}).get(normalized)
    if model is None or label_encoder is None:
        return None

    vector = embed_model.encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype(np.float32)

    if not hasattr(model, "predict_proba"):
        return None

    probabilities = model.predict_proba(vector)[0]
    classes = list(label_encoder.classes_)
    ranked = sorted(
        zip(classes, probabilities),
        key=lambda item: item[1],
        reverse=True,
    )[:top_n]
    best_id, best_prob = ranked[0]
    confidence = round(float(best_prob), 4)
    return {
        "predicted_category": str(best_id),
        "intent_confidence": confidence,
        "intent_top_categories": [
            {
                "category_id": str(category_id),
                "category_name": category_name_by_id(normalized, str(category_id)),
                "confidence": round(float(prob), 4),
            }
            for category_id, prob in ranked
        ],
        "intent_mode_used": "supervised",
    }


def predict_intent(
    query: str,
    caller_type: str,
    embed_model: SentenceTransformer,
    *,
    top_n: int = 3,
) -> dict[str, Any]:
    normalized = " ".join((query or "").lower().split())
    empty = {
        "predicted_category": None,
        "intent_confidence": 0.0,
        "intent_top_categories": [],
        "intent_mode_used": "disabled",
    }
    if not normalized or not is_intent_enabled() or intent_mode() == "disabled":
        return empty

    mode = intent_mode()
    prediction: dict[str, Any] | None = None

    if mode == "supervised":
        prediction = _predict_supervised(
            normalized, caller_type, embed_model, top_n=top_n
        )
        if prediction is None:
            prediction = _predict_prototype(
                normalized, caller_type, embed_model, top_n=top_n
            )
    else:
        prediction = _predict_prototype(
            normalized, caller_type, embed_model, top_n=top_n
        )

    if not prediction:
        return empty

    if prediction["intent_confidence"] < confidence_threshold():
        prediction = {
            **prediction,
            "predicted_category": None,
        }

    logger.info(
        "Intent prediction (%s): category=%s confidence=%.2f query=%r",
        prediction.get("intent_mode_used"),
        prediction.get("predicted_category"),
        prediction.get("intent_confidence", 0.0),
        normalized,
    )
    return prediction


def apply_intent_category_boost(
    results: list[dict],
    caller_type: str,
    predicted_category: str | None,
    confidence: float,
    *,
    branch_lookup: dict[str, dict] | None = None,
) -> list[dict]:
    if (
        not predicted_category
        or confidence < confidence_threshold()
        or not results
    ):
        return results

    if branch_lookup is None:
        store = get_kb(caller_type)
        branch_lookup = {b["branch_id"]: b for b in store.branches}

    boosted: list[dict] = []
    for row in results:
        item = dict(row)
        branch = branch_lookup.get(item.get("branch_id", ""))
        if branch and branch.get("topic_category") == predicted_category:
            item["final_score"] = round(
                item.get("final_score", 0.0) + INTENT_CATEGORY_BOOST, 4
            )
            item["intent_boost_applied"] = True
        boosted.append(item)

    boosted.sort(key=lambda row: row.get("final_score", 0.0), reverse=True)
    return boosted


def train_supervised_intent_classifier(
  caller_type: str,
  embed_model: SentenceTransformer,
  *,
  texts: list[str],
  labels: list[str],
) -> tuple[LogisticRegression, Any]:
    from sklearn.preprocessing import LabelEncoder

    label_encoder = LabelEncoder()
    encoded_labels = label_encoder.fit_transform(labels)
    vectors = embed_model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype(np.float32)

    model = LogisticRegression(
        max_iter=1000,
        class_weight="balanced",
    )
    model.fit(vectors, encoded_labels)
    return model, label_encoder


def save_supervised_bundle(bundle: dict[str, Any], path: Path | None = None) -> Path:
    target = path or model_path()
    save_bundle(target, bundle)
    global _supervised_bundle
    _supervised_bundle = bundle
    return target


def get_intent_classifier_status() -> dict[str, Any]:
    path = model_path()
    bundle = load_supervised_model()
    mode = intent_mode()
    enabled = is_intent_enabled() and mode != "disabled"
    supervised_loaded = bundle is not None

    status = "prototype_active"
    if not enabled:
        status = "disabled"
    elif mode == "supervised" and supervised_loaded:
        status = "supervised_active"
    elif mode == "supervised":
        status = "supervised_missing_fallback_prototype"

    return {
        "enabled": enabled,
        "mode": mode,
        "confidence_threshold": confidence_threshold(),
        "status": status,
        "path": f"models/{path.name}",
        "supervised_loaded": supervised_loaded,
        "prototype_cached": sorted(_prototype_cache.keys()),
        "trained_at": bundle.get("trained_at") if bundle else None,
        "validation_metrics": bundle.get("validation_metrics") if bundle else None,
        "supported_caller_types": sorted((bundle or {}).get("models", {}).keys()),
    }
