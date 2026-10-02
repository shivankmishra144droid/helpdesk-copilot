"""Topic clustering for pending supervisor queries — embeddings + KMeans + c-TF-IDF labels."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer

logger = logging.getLogger(__name__)

KNOWLEDGE_ROOT = Path(__file__).parent / "knowledge"
ASSIGNMENTS_PATH = KNOWLEDGE_ROOT / "supervisor_assignments.json"

MAX_CLUSTERS = 8
MIN_CLUSTERS = 2

_cache_fingerprint: str | None = None
_cache_result: dict[str, Any] | None = None  # Note: in-memory only; stale until queue fingerprint changes.


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _issue_text(issue: dict[str, Any]) -> str:
    return str(
        issue.get("query") or issue.get("issue_name") or issue.get("problem_statement") or ""
    ).strip()


def _issue_key(issue: dict[str, Any]) -> str:
    issue_id = issue.get("id")
    pending_id = issue.get("pending_id")
    text = _issue_text(issue)
    return f"{issue_id}:{pending_id}:{text}"


def _queue_fingerprint(issues: list[dict[str, Any]]) -> str:
    return "|".join(sorted(_issue_key(issue) for issue in issues))


def _get_embed_model():
    from kb_manager import get_registry

    return get_registry().embed_model


def _choose_k(n: int) -> int:
    if n <= 1:
        return 1
    heuristic = max(MIN_CLUSTERS, int(round(n**0.5)))
    return min(n, MAX_CLUSTERS, heuristic)


def _label_from_texts(texts: list[str]) -> str:
    cleaned = [t for t in texts if t.strip()]
    if not cleaned:
        return "General"
    if len(cleaned) == 1:
        words = re.findall(r"[a-zA-Z]{3,}", cleaned[0].lower())
        if words:
            return " · ".join(words[:3]).title()
        return "General"

    try:
        vectorizer = TfidfVectorizer(
            max_features=200,
            stop_words="english",
            ngram_range=(1, 2),
            min_df=1,
        )
        matrix = vectorizer.fit_transform(cleaned)
        scores = np.asarray(matrix.mean(axis=0)).ravel()
        terms = vectorizer.get_feature_names_out()
        ranked = sorted(zip(scores, terms), reverse=True)
        keywords = [term for score, term in ranked if score > 0][:3]
        if keywords:
            return " · ".join(keywords).title()
    except ValueError:
        pass

    return "General"


def _cluster_labels(
    cluster_ids: list[int], documents: list[str]
) -> dict[int, str]:
    grouped: dict[int, list[str]] = {}
    for cluster_id, doc in zip(cluster_ids, documents):
        grouped.setdefault(cluster_id, []).append(doc)

    return {cluster_id: _label_from_texts(texts) for cluster_id, texts in grouped.items()}


def compute_topic_clusters(issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Cluster pending issues by query text; return assignments and cluster metadata."""
    global _cache_fingerprint, _cache_result

    fingerprint = _queue_fingerprint(issues)
    if _cache_fingerprint == fingerprint and _cache_result is not None:
        return _cache_result

    documents = [_issue_text(issue) for issue in issues]
    assignments: dict[str, dict[str, Any]] = {}

    if not issues:
        result = {"clusters": [], "assignments": assignments, "computed_at": _now_iso()}
        _cache_fingerprint = fingerprint
        _cache_result = result
        return result

    if len(issues) == 1:
        issue = issues[0]
        key = str(issue.get("id", issue.get("pending_id", "0")))
        label = _label_from_texts(documents)
        assignments[key] = {
            "topic_cluster_id": 0,
            "topic_label": label,
        }
        clusters = [
            {
                "cluster_id": 0,
                "topic_label": label,
                "count": 1,
                "sample_queries": documents[:3],
            }
        ]
        result = {
            "clusters": clusters,
            "assignments": assignments,
            "computed_at": _now_iso(),
        }
        _cache_fingerprint = fingerprint
        _cache_result = result
        return result

    embed_model = _get_embed_model()
    embeddings = embed_model.encode(
        documents,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    k = _choose_k(len(issues))
    if k <= 1:
        cluster_ids = [0] * len(issues)
    else:
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        cluster_ids = kmeans.fit_predict(embeddings).tolist()

    label_by_cluster = _cluster_labels(cluster_ids, documents)

    cluster_samples: dict[int, list[str]] = {}
    cluster_counts: dict[int, int] = {}

    for issue, cluster_id, doc in zip(issues, cluster_ids, documents):
        key = str(issue.get("id", issue.get("pending_id", "")))
        label = label_by_cluster.get(cluster_id, "General")
        assignments[key] = {
            "topic_cluster_id": int(cluster_id),
            "topic_label": label,
        }
        cluster_counts[cluster_id] = cluster_counts.get(cluster_id, 0) + 1
        samples = cluster_samples.setdefault(cluster_id, [])
        if len(samples) < 3 and doc:
            samples.append(doc)

    clusters = [
        {
            "cluster_id": cluster_id,
            "topic_label": label_by_cluster.get(cluster_id, "General"),
            "count": cluster_counts.get(cluster_id, 0),
            "sample_queries": cluster_samples.get(cluster_id, []),
        }
        for cluster_id in sorted(cluster_counts)
    ]

    result = {
        "clusters": clusters,
        "assignments": assignments,
        "computed_at": _now_iso(),
    }
    _cache_fingerprint = fingerprint
    _cache_result = result
    return result


def enrich_issue_with_topic(
    issue: dict[str, Any], clustering: dict[str, Any]
) -> dict[str, Any]:
    key = str(issue.get("id", issue.get("pending_id", "")))
    assignment = clustering["assignments"].get(key, {})
    enriched = dict(issue)
    enriched["topic_cluster_id"] = assignment.get("topic_cluster_id")
    enriched["topic_label"] = assignment.get("topic_label", "General")
    return enriched


def filter_issues_by_cluster(
    issues: list[dict[str, Any]],
    *,
    cluster_id: int | None = None,
    supervisor_id: str | None = None,
    my_clusters_only: bool = False,
) -> list[dict[str, Any]]:
    clustering = compute_topic_clusters(issues)
    enriched = [enrich_issue_with_topic(issue, clustering) for issue in issues]

    if cluster_id is not None:
        enriched = [
            item
            for item in enriched
            if item.get("topic_cluster_id") == cluster_id
        ]

    if my_clusters_only and supervisor_id:
        specs = get_supervisor_specializations(supervisor_id)
        allowed = set(specs.get("cluster_ids", []))
        if allowed:
            enriched = [
                item
                for item in enriched
                if item.get("topic_cluster_id") in allowed
            ]

    return enriched


def _load_assignments_store() -> dict[str, Any]:
    if not ASSIGNMENTS_PATH.exists():
        return {"supervisors": {}}
    try:
        with ASSIGNMENTS_PATH.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {"supervisors": {}}
    if not isinstance(payload, dict):
        return {"supervisors": {}}
    payload.setdefault("supervisors", {})
    return payload


def _save_assignments_store(data: dict[str, Any]) -> None:
    ASSIGNMENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = ASSIGNMENTS_PATH.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temp.replace(ASSIGNMENTS_PATH)


def get_supervisor_specializations(supervisor_id: str) -> dict[str, Any]:
    store = _load_assignments_store()
    record = store["supervisors"].get(supervisor_id, {})
    return {
        "supervisor_id": supervisor_id,
        "cluster_ids": list(record.get("cluster_ids", [])),
        "updated_at": record.get("updated_at"),
    }


def set_supervisor_specializations(
    supervisor_id: str, cluster_ids: list[int]
) -> dict[str, Any]:
    store = _load_assignments_store()
    unique_ids = sorted({int(cid) for cid in cluster_ids})
    store["supervisors"][supervisor_id] = {
        "cluster_ids": unique_ids,
        "updated_at": _now_iso(),
    }
    _save_assignments_store(store)
    return get_supervisor_specializations(supervisor_id)


def invalidate_cluster_cache() -> None:
    global _cache_fingerprint, _cache_result
    _cache_fingerprint = None
    _cache_result = None
