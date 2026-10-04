"""XGBoost learn-to-rank re-ranker for Helpdesk Copilot hybrid search."""

from __future__ import annotations

import logging
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from embedding_model import SentenceTransformer

from kb_manager import build_branch_embed_text, get_kb
from model_io import load_bundle, save_bundle
from kb_search import (
    compute_keyword_score,
    expand_query,
    keyword_matches_query,
    normalize_query,
)

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent / "models"
MODEL_PATH = MODEL_DIR / "xgboost_ranker.pkl"

FEATURE_NAMES = [
    "semantic_score",
    "keyword_score",
    "exact_name_match",
    "query_length",
    "has_question_mark",
    "synonym_match",
    "keyword_overlap_ratio",
    "branch_popularity",
]

HINGLISH_TEMPLATES = [
    "{q} karna hai",
    "{q} kaise kare",
    "mera {q} problem hai",
    "{q} nahi ho raha",
    "{q} band karna hai",
]

SENTENCE_TEMPLATES = [
    "how do I {q}",
    "how to {q}",
    "I need help with {q}",
    "please help me {q}",
    "what is the process for {q}",
]

PARAPHRASE_MAP = {
    "close": "account closure",
    "delete": "remove",
    "update": "change",
    "otp": "login code",
    "invoice": "bill",
    "courier": "shipping",
    "bank": "bank account",
    "profile": "profile details",
    "listing": "product",
}

_ranker_bundle: dict[str, Any] | None = None


def _branches_for_training(caller_type: str) -> list[dict]:
    """Supervisor-approved branches when enough for contrast; else full KB."""
    store = get_kb(caller_type)
    all_branches = list(store.branches)
    supervisor_branches = [
        b for b in all_branches if b.get("source") in ("supervisor", "database")
    ]
    if len(supervisor_branches) >= 2:
        return supervisor_branches
    return all_branches


def _introduce_typo(text: str) -> str:
    if len(text) < 4:
        return text
    chars = list(text)
    index = random.randint(0, len(chars) - 2)
    chars[index], chars[index + 1] = chars[index + 1], chars[index]
    if random.random() < 0.3 and index < len(chars):
        chars[index] = random.choice("aeiou")
    return "".join(chars)


def _keyword_fragments(branch: dict) -> list[str]:
    keywords = branch.get("trigger_keywords", [])
    fragments: list[str] = []
    for keyword in keywords:
        keyword_norm = normalize_query(keyword)
        for word in keyword_norm.split():
            if len(word) > 2:
                fragments.append(word)
        if len(keyword_norm) <= 20:
            fragments.append(keyword_norm)
    return list(dict.fromkeys(fragments))


def _paraphrase_query(text: str) -> str:
    lower = text.lower()
    for source, target in PARAPHRASE_MAP.items():
        if source in lower:
            return lower.replace(source, target, 1)
    words = lower.split()
    if len(words) >= 2:
        return " ".join(reversed(words))
    return lower


def generate_query_variations(branch: dict, count: int) -> list[str]:
    """Generate diverse query strings for a single branch."""
    name = branch.get("branch_name", "issue")
    name_lower = name.lower()
    keywords = _keyword_fragments(branch)
    variations: list[str] = []

    def add(query: str) -> None:
        query = normalize_query(query)
        if query and query not in variations:
            variations.append(query)

    add(name_lower)
    add(name_lower.replace(" ", ""))

    for keyword in keywords[:8]:
        add(keyword)
        add(_paraphrase_query(keyword))

    for template in HINGLISH_TEMPLATES:
        seed = keywords[0] if keywords else name_lower
        add(template.format(q=seed))

    for template in SENTENCE_TEMPLATES:
        seed = keywords[0] if keywords else name_lower
        add(template.format(q=seed))

    for keyword in keywords[:5]:
        add(_introduce_typo(keyword))
        add(_introduce_typo(name_lower))

    if keywords:
        add(" ".join(keywords[:3]))
        add(" ".join(keywords[:2]))

    add(f"how do I {name_lower}")
    add(f"{name_lower}?")

    while len(variations) < count:
        if keywords:
            pick = random.sample(keywords, k=min(2, len(keywords)))
            add(" ".join(pick))
            add(_introduce_typo(random.choice(keywords)))
        else:
            add(_introduce_typo(name_lower))
        if len(variations) >= count * 2:
            break

    return variations[:count]


def generate_training_data(
    caller_type: str,
    samples_per_branch: int = 50,
    *,
    negatives_per_query: int = 2,
    seed: int = 42,
) -> list[dict]:
    """
    Build labeled (query, branch, label) rows for XGBoost training.

    label=1 when the query was generated for that branch; 0 for random negatives.
    """
    random.seed(seed)
    branches = _branches_for_training(caller_type)
    if not branches:
        return []

    rows: list[dict] = []
    branch_ids = [b["branch_id"] for b in branches]
    store = get_kb(caller_type)
    negative_pool = list(store.branches)

    for branch in branches:
        queries = generate_query_variations(branch, samples_per_branch)
        others = [b for b in branches if b["branch_id"] != branch["branch_id"]]
        if not others:
            others = [b for b in negative_pool if b["branch_id"] != branch["branch_id"]]

        for query in queries:
            rows.append(
                {
                    "query": query,
                    "branch": branch,
                    "branch_id": branch["branch_id"],
                    "label": 1,
                    "caller_type": caller_type,
                }
            )
            if not others:
                continue
            for negative in random.sample(
                others, k=min(negatives_per_query, len(others))
            ):
                rows.append(
                    {
                        "query": query,
                        "branch": negative,
                        "branch_id": negative["branch_id"],
                        "label": 0,
                        "caller_type": caller_type,
                    }
                )

    random.shuffle(rows)
    logger.info(
        "Generated %s training rows for %s (%s branches)",
        len(rows),
        caller_type,
        len(branch_ids),
    )
    return rows


def _count_synonym_matches(
    query: str, branch: dict, synonym_lookup: dict[str, frozenset[str]]
) -> int:
    query_words = set(normalize_query(query).split())
    keyword_words: set[str] = set()
    for keyword in branch.get("trigger_keywords", []):
        keyword_words.update(normalize_query(keyword).split())

    matched_groups: set[frozenset[str]] = set()
    for word in query_words:
        group = synonym_lookup.get(word)
        if not group:
            continue
        if keyword_words & group:
            matched_groups.add(group)
    return len(matched_groups)


def _keyword_overlap_ratio(query: str, branch: dict) -> float:
    query_words = [w for w in normalize_query(query).split() if len(w) > 1]
    if not query_words:
        return 0.0
    keywords = branch.get("trigger_keywords", [])
    if not keywords:
        return 0.0
    matched = sum(
        1
        for word in query_words
        if any(keyword_matches_query(word, keyword) for keyword in keywords)
    )
    return matched / len(query_words)


def _exact_name_match(query: str, branch_name: str) -> float:
    query_norm = normalize_query(query)
    name_norm = normalize_query(branch_name)
    if not query_norm or not name_norm:
        return 0.0
    if name_norm in query_norm or query_norm in name_norm:
        return 1.0
    name_words = set(name_norm.split())
    query_words = set(query_norm.split())
    if name_words and name_words <= query_words:
        return 1.0
    return 0.0


def compute_semantic_score(
    query: str,
    branch: dict,
    embed_model: SentenceTransformer,
    *,
    expanded_query: str | None = None,
) -> float:
    text = expanded_query or normalize_query(query)
    if not text:
        return 0.0
    query_vec = embed_model.encode(
        [text],
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype("float32")
    branch_vec = embed_model.encode(
        [build_branch_embed_text(branch)],
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype("float32")
    score = float(np.dot(query_vec[0], branch_vec[0]))
    return round(max(0.0, min(1.0, score)), 4)


def extract_features(
    query: str,
    branch: dict,
    store,
    embed_model: SentenceTransformer,
    *,
    semantic_score: float | None = None,
) -> list[float]:
    normalized = normalize_query(query)
    expanded = expand_query(normalized, store.synonym_lookup)

    if semantic_score is None:
        semantic_score = compute_semantic_score(
            query, branch, embed_model, expanded_query=expanded
        )

    keyword_score = round(
        compute_keyword_score(normalized, expanded, branch), 4
    )
    exact_name = _exact_name_match(normalized, branch.get("branch_name", ""))
    query_length = float(len(normalized.split()))
    has_question = 1.0 if "?" in query else 0.0
    synonym_match = float(
        _count_synonym_matches(normalized, branch, store.synonym_lookup)
    )
    overlap = round(_keyword_overlap_ratio(normalized, branch), 4)
    popularity = float(branch.get("click_count", 0) or 0)

    return [
        semantic_score,
        keyword_score,
        exact_name,
        query_length,
        has_question,
        synonym_match,
        overlap,
        popularity,
    ]


def features_to_matrix(
    rows: list[dict],
    store,
    embed_model: SentenceTransformer,
) -> tuple[np.ndarray, np.ndarray]:
    x_rows: list[list[float]] = []
    y_rows: list[int] = []
    for row in rows:
        semantic = compute_semantic_score(row["query"], row["branch"], embed_model)
        x_rows.append(
            extract_features(
                row["query"],
                row["branch"],
                store,
                embed_model,
                semantic_score=semantic,
            )
        )
        y_rows.append(int(row["label"]))
    return np.array(x_rows, dtype=np.float32), np.array(y_rows, dtype=np.int32)


def _split_rows_by_query(
    rows: list[dict],
    *,
    val_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    """Hold out whole queries so the same synthetic query is not in train and val."""
    queries = sorted({row["query"] for row in rows})
    rng = random.Random(seed)
    rng.shuffle(queries)
    if len(queries) < 2:
        return rows, []
    split_at = max(1, int(len(queries) * (1.0 - val_ratio)))
    train_queries = set(queries[:split_at])
    val_queries = set(queries[split_at:])
    train_rows = [row for row in rows if row["query"] in train_queries]
    val_rows = [row for row in rows if row["query"] in val_queries]
    return train_rows, val_rows


def _classification_metrics(y_true: np.ndarray, y_prob: np.ndarray) -> dict[str, float]:
    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    y_pred = (y_prob >= 0.5).astype(np.int32)
    metrics: dict[str, float] = {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
    }
    if len(np.unique(y_true)) > 1:
        metrics["roc_auc"] = round(float(roc_auc_score(y_true, y_prob)), 4)
    return metrics


def train_xgboost_ranker(
    caller_type: str,
    *,
    samples_per_branch: int = 50,
    embed_model: SentenceTransformer | None = None,
    val_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[Any, dict[str, Any]]:
    """Train an XGBClassifier for one caller type; return model + training report."""
    import xgboost as xgb

    from kb_manager import get_registry

    if embed_model is None:
        embed_model = get_registry().embed_model

    store = get_kb(caller_type)
    all_rows = generate_training_data(
        caller_type, samples_per_branch=samples_per_branch, seed=seed
    )
    if not all_rows:
        raise ValueError(f"No training data for caller_type={caller_type}")

    train_rows, val_rows = _split_rows_by_query(all_rows, val_ratio=val_ratio, seed=seed)
    x_train, y_train = features_to_matrix(train_rows, store, embed_model)
    train_pos = int(y_train.sum())
    train_neg = len(y_train) - train_pos
    if train_pos == 0 or train_neg == 0:
        raise ValueError(
            f"Need both positive and negative training rows for {caller_type} "
            f"(got {train_pos} pos / {train_neg} neg)"
        )

    scale_pos_weight = train_neg / train_pos if train_pos else 1.0
    model = xgb.XGBClassifier(
        n_estimators=120,
        max_depth=5,
        learning_rate=0.1,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="binary:logistic",
        eval_metric="logloss",
        scale_pos_weight=scale_pos_weight,
        random_state=seed,
        n_jobs=-1,
    )
    model.fit(x_train, y_train)

    train_prob = model.predict_proba(x_train)[:, 1]
    report: dict[str, Any] = {
        "caller_type": caller_type,
        "dataset_size": len(all_rows),
        "train_size": len(train_rows),
        "val_size": len(val_rows),
        "train_positives": train_pos,
        "train_negatives": train_neg,
        "val_positives": int(sum(row["label"] for row in val_rows)),
        "val_negatives": len(val_rows) - int(sum(row["label"] for row in val_rows)),
        "samples_per_branch": samples_per_branch,
        "val_ratio": val_ratio,
        "seed": seed,
        "train_metrics": _classification_metrics(y_train, train_prob),
    }
    if val_rows:
        x_val, y_val = features_to_matrix(val_rows, store, embed_model)
        val_prob = model.predict_proba(x_val)[:, 1]
        report["val_metrics"] = _classification_metrics(y_val, val_prob)

    logger.info(
        "Trained XGBoost ranker for %s: train=%s (%s pos / %s neg), val=%s, "
        "train_f1=%s val_f1=%s",
        caller_type,
        len(train_rows),
        train_pos,
        train_neg,
        len(val_rows),
        report["train_metrics"].get("f1"),
        report.get("val_metrics", {}).get("f1"),
    )
    return model, report


def save_ranker_bundle(bundle: dict[str, Any]) -> Path:
    save_bundle(MODEL_PATH, bundle)
    logger.info("Saved XGBoost ranker bundle to %s", MODEL_PATH)
    return MODEL_PATH


def load_xgboost_ranker(*, force: bool = False) -> dict[str, Any] | None:
    """Load ranker models from disk; returns None if missing or corrupt."""
    global _ranker_bundle
    if os.getenv("DISABLE_XGBOOST", "false").lower() == "true":
        return None
    if _ranker_bundle is not None and not force:
        return _ranker_bundle
    if not MODEL_PATH.exists():
        _ranker_bundle = None
        return None
    _ranker_bundle = load_bundle(MODEL_PATH)
    if _ranker_bundle is None:
        return None
    if not isinstance(_ranker_bundle, dict) or "models" not in _ranker_bundle:
        logger.warning("Invalid XGBoost ranker bundle at %s", MODEL_PATH)
        _ranker_bundle = None
        return None
    logger.info("Loaded XGBoost ranker from %s", MODEL_PATH)
    return _ranker_bundle


def get_xgboost_model(caller_type: str) -> Any | None:
    bundle = load_xgboost_ranker()
    if not bundle:
        return None
    models = bundle.get("models", {})
    return models.get(caller_type)


def train_and_save_all(
    *,
    samples_per_branch: int = 50,
    embed_model: SentenceTransformer | None = None,
    val_ratio: float = 0.2,
    seed: int = 42,
) -> Path:
    from kb_manager import VALID_CALLER_TYPES, get_registry

    if embed_model is None:
        embed_model = get_registry().embed_model

    models: dict[str, Any] = {}
    reports: dict[str, Any] = {}
    for caller_type in VALID_CALLER_TYPES:
        model, report = train_xgboost_ranker(
            caller_type,
            samples_per_branch=samples_per_branch,
            embed_model=embed_model,
            val_ratio=val_ratio,
            seed=seed,
        )
        models[caller_type] = model
        reports[caller_type] = report
        print(
            f"[{caller_type}] rows={report['dataset_size']} "
            f"train={report['train_size']} val={report['val_size']} "
            f"train_f1={report['train_metrics']['f1']} "
            f"val_f1={report.get('val_metrics', {}).get('f1', 'n/a')}"
        )

    bundle = {
        "version": 1,
        "feature_names": FEATURE_NAMES,
        "models": models,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_config": {
            "samples_per_branch": samples_per_branch,
            "val_ratio": val_ratio,
            "seed": seed,
            "embed_model": "all-MiniLM-L6-v2",
        },
        "training_reports": reports,
        "supported_caller_types": list(VALID_CALLER_TYPES),
    }
    path = save_ranker_bundle(bundle)
    load_xgboost_ranker(force=True)
    return path


def get_ranking_mode(caller_type: str) -> str:
    return "xgboost" if is_ranker_available(caller_type) else "hybrid_fallback"


def get_ranker_health() -> dict[str, Any]:
    bundle = load_xgboost_ranker()
    rel_path = f"models/{MODEL_PATH.name}"
    if not bundle:
        return {
            "loaded": False,
            "path": rel_path,
            "ranking_mode": "hybrid_fallback",
            "supported_caller_types": [],
        }
    models = bundle.get("models", {})
    return {
        "loaded": True,
        "path": rel_path,
        "version": bundle.get("version"),
        "trained_at": bundle.get("trained_at"),
        "feature_names": bundle.get("feature_names", FEATURE_NAMES),
        "supported_caller_types": sorted(models.keys()),
        "seller_loaded": "seller" in models,
        "buyer_loaded": "buyer" in models,
        "ranking_mode": "xgboost" if models else "hybrid_fallback",
        "training_config": bundle.get("training_config"),
        "validation_metrics": {
            caller: (bundle.get("training_reports") or {})
            .get(caller, {})
            .get("val_metrics")
            for caller in sorted(models.keys())
        },
    }


def rank_with_xgboost(
    query: str,
    faiss_results: list[dict],
    caller_type: str,
    store,
    embed_model: SentenceTransformer,
) -> list[dict]:
    """
    Re-rank top FAISS hits using XGBoost predicted relevance probability.

    Each faiss_result must include: branch, semantic_score, branch_id, branch_name.
    """
    model = get_xgboost_model(caller_type)
    if model is None or not faiss_results:
        return faiss_results

    feature_rows: list[list[float]] = []
    for item in faiss_results:
        branch = item["branch"]
        feature_rows.append(
            extract_features(
                query,
                branch,
                store,
                embed_model,
                semantic_score=item.get("semantic_score"),
            )
        )

    matrix = np.array(feature_rows, dtype=np.float32)
    probabilities = model.predict_proba(matrix)[:, 1]

    reranked: list[dict] = []
    for item, score in zip(faiss_results, probabilities):
        enriched = dict(item)
        enriched["xgboost_score"] = round(float(score), 4)
        enriched["final_score"] = enriched["xgboost_score"]
        reranked.append(enriched)

    reranked.sort(key=lambda row: row["xgboost_score"], reverse=True)
    return reranked


def is_ranker_available(caller_type: str) -> bool:
    return get_xgboost_model(caller_type) is not None
