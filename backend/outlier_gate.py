"""IsolationForest outlier gate — blocks off-topic queries before FAISS search."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from embedding_model import SentenceTransformer
from sklearn.ensemble import IsolationForest

from kb_manager import get_kb, normalize_caller_type
from model_io import load_bundle, save_bundle
from kb_search import normalize_query

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent / "models"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
# Note: IF alone misses very short off-topic text; min cosine sim to KB corpus catches them
MIN_DOMAIN_SIMILARITY = 0.31
# Note: short valid queries can look anomalous to IF; trust corpus similarity above this
SAFE_IN_DOMAIN_SIMILARITY = 0.32

# Note: tiny phrase list for queries that embed too close to generic KB text (e.g. "tell me a joke")
_OBVIOUS_OFF_TOPIC_PHRASES = (
    "tell me a joke",
    "what is the weather",
    "who won the football",
    "who won the match",
    "cricket score today",
    "movie recommendation",
)

_model_cache: dict[str, dict[str, Any]] = {}


def _obvious_off_topic(query: str) -> bool:
    normalized = normalize_query(query)
    return any(phrase in normalized for phrase in _OBVIOUS_OFF_TOPIC_PHRASES)


def model_path(caller_type: str) -> Path:
    normalized = normalize_caller_type(caller_type)
    return MODEL_DIR / f"isolation_forest_{normalized}.pkl"


def is_model_available(caller_type: str) -> bool:
    return model_path(caller_type).exists()


def load_training_corpus(caller_type: str) -> list[str]:
    """Collect in-distribution texts from KB branches."""
    normalized = normalize_caller_type(caller_type)
    texts: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        cleaned = normalize_query(text)
        if cleaned and cleaned not in seen and len(cleaned) > 1:
            seen.add(cleaned)
            texts.append(cleaned)

    store = get_kb(normalized)
    for branch in store.branches:
        add(branch.get("branch_name", ""))
        for field in ("problem_statement", "policy"):
            value = branch.get(field)
            if value:
                add(str(value)[:300])
        steps = branch.get("steps") or []
        if isinstance(steps, list):
            for step in steps[:6]:
                add(str(step))
        script = (
            branch.get("agent_script")
            or branch.get("auto_script")
            or branch.get("manual_script")
            or ""
        )
        if script:
            add(script[:300])
        for keyword in branch.get("trigger_keywords", []):
            add(str(keyword))

    return texts


def train_outlier_model(
    caller_type: str,
    *,
    embed_model: SentenceTransformer | None = None,
    contamination: float = 0.05,
    n_estimators: int = 100,
) -> Path:
    """Train IsolationForest on embeddings of active-issue corpus texts."""
    normalized = normalize_caller_type(caller_type)
    corpus = load_training_corpus(normalized)
    if len(corpus) < 10:
        raise ValueError(
            f"Need at least 10 training texts for {normalized}; got {len(corpus)}"
        )

    if embed_model is None:
        embed_model = SentenceTransformer(EMBED_MODEL_NAME)

    embeddings = embed_model.encode(
        corpus,
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype(np.float32)

    model = IsolationForest(
        contamination=contamination,
        n_estimators=n_estimators,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(embeddings)

    bundle = {
        "version": 1,
        "model": model,
        "caller_type": normalized,
        "embed_model_name": EMBED_MODEL_NAME,
        "corpus_size": len(corpus),
        "corpus_embeddings": embeddings,
        "contamination": contamination,
        "n_estimators": n_estimators,
        "min_domain_similarity": MIN_DOMAIN_SIMILARITY,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }

    path = model_path(normalized)
    save_bundle(path, bundle)

    _model_cache[normalized] = bundle
    logger.info(
        "Trained outlier model for %s on %s texts (contamination=%s) → %s",
        normalized,
        len(corpus),
        contamination,
        path,
    )
    print(
        f"[{normalized}] outlier corpus={len(corpus)} "
        f"contamination={contamination} estimators={n_estimators}"
    )
    return path


def _load_bundle(caller_type: str) -> dict[str, Any] | None:
    normalized = normalize_caller_type(caller_type)
    if normalized in _model_cache:
        return _model_cache[normalized]

    path = model_path(normalized)
    if not path.exists():
        return None

    bundle = load_bundle(path)
    if bundle is None:
        return None
    if not isinstance(bundle, dict) or "model" not in bundle:
        logger.warning("Invalid outlier bundle at %s", path)
        return None
    _model_cache[normalized] = bundle
    return bundle


def is_outlier(
    query: str,
    caller_type: str,
    *,
    embed_model: SentenceTransformer | None = None,
) -> dict[str, Any]:
    """
    Predict whether a query is off-topic for the caller's knowledge base.

    Returns {"is_outlier": bool, "anomaly_score": float, "model_loaded": bool}.
    anomaly_score is higher when the query is more anomalous.
    """
    normalized = normalize_query(query)
    if not normalized:
        return {"is_outlier": False, "anomaly_score": 0.0, "model_loaded": False}

    if _obvious_off_topic(normalized):
        return {
            "is_outlier": True,
            "anomaly_score": 1.0,
            "max_domain_similarity": 0.0,
            "model_loaded": bool(_load_bundle(caller_type)),
        }

    bundle = _load_bundle(caller_type)
    if bundle is None:
        return {"is_outlier": False, "anomaly_score": 0.0, "model_loaded": False}

    if embed_model is None:
        from kb_manager import get_registry

        embed_model = get_registry().embed_model

    vector = embed_model.encode(
        [normalized],
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype(np.float32)

    model: IsolationForest = bundle["model"]
    prediction = int(model.predict(vector)[0])
    decision = float(model.decision_function(vector)[0])
    anomaly_score = round(float(-decision), 4)

    corpus_embeddings = bundle.get("corpus_embeddings")
    min_similarity = float(bundle.get("min_domain_similarity", MIN_DOMAIN_SIMILARITY))
    max_similarity = 1.0
    if corpus_embeddings is not None and len(corpus_embeddings):
        similarities = np.dot(corpus_embeddings, vector[0])
        max_similarity = round(float(np.max(similarities)), 4)

    forest_outlier = prediction == -1
    similarity_outlier = max_similarity < min_similarity

    if max_similarity >= SAFE_IN_DOMAIN_SIMILARITY:
        is_anomaly = False
    else:
        is_anomaly = forest_outlier or similarity_outlier

    return {
        "is_outlier": is_anomaly,
        "anomaly_score": anomaly_score,
        "max_domain_similarity": max_similarity,
        "model_loaded": True,
    }


def suggested_queries(caller_type: str, *, limit: int = 5) -> list[str]:
    """Example in-domain queries to show when input looks off-topic."""
    store = get_kb(caller_type)
    suggestions: list[str] = []
    for branch in store.branches:
        name = branch.get("branch_name", "").strip()
        if name and name not in suggestions:
            suggestions.append(name)
        if len(suggestions) >= limit:
            break
    return suggestions[:limit]


OUTLIER_MESSAGE = (
    "This query doesn't look related to the portal's support topics. "
    "Try searching with issue keywords like listing not visible, password reset, or invoice error."
)


def outlier_response(query: str, caller_type: str) -> dict[str, Any] | None:
    """Return an outlier payload if the gate fires; otherwise None."""
    result = is_outlier(query, caller_type)
    if not result.get("model_loaded") or not result["is_outlier"]:
        return None

    normalized = normalize_caller_type(caller_type)
    return {
        "status": "outlier",
        "caller_type": normalized,
        "query": normalize_query(query),
        "message": OUTLIER_MESSAGE,
        "is_outlier": True,
        "anomaly_score": result["anomaly_score"],
        "suggested_queries": suggested_queries(normalized),
    }


def preload_outlier_models() -> list[str]:
    """Load all available outlier models into memory; returns caller types loaded."""
    loaded: list[str] = []
    for path in MODEL_DIR.glob("isolation_forest_*.pkl"):
        caller_type = path.stem.replace("isolation_forest_", "")
        if _load_bundle(caller_type):
            loaded.append(caller_type)
    return loaded


def get_outlier_status() -> dict[str, Any]:
    seller_bundle = _load_bundle("seller")
    buyer_bundle = _load_bundle("buyer")
    seller_loaded = seller_bundle is not None
    buyer_loaded = buyer_bundle is not None

    if seller_loaded and buyer_loaded:
        gate_status = "seller_and_buyer_active"
    elif seller_loaded:
        gate_status = "seller_only"
    elif buyer_loaded:
        gate_status = "buyer_only"
    else:
        gate_status = "disabled"

    def _info(caller: str, bundle: dict[str, Any] | None) -> dict[str, Any]:
        path = model_path(caller)
        if not bundle:
            return {"loaded": False, "path": f"models/{path.name}"}
        return {
            "loaded": True,
            "path": f"models/{path.name}",
            "version": bundle.get("version"),
            "trained_at": bundle.get("trained_at"),
            "corpus_size": bundle.get("corpus_size"),
            "contamination": bundle.get("contamination"),
            "embed_model_name": bundle.get("embed_model_name"),
        }

    return {
        "status": gate_status,
        "seller": _info("seller", seller_bundle),
        "buyer": _info("buyer", buyer_bundle),
    }
