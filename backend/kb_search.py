"""Hybrid semantic + keyword search over seller/buyer knowledge bases."""

from __future__ import annotations

import logging
import re

from category_utils import category_name_by_id
from kb_manager import get_kb, get_registry
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

SEARCH_TOP_K = 10
# Minimum score to include in optional "might be relevant" suggestions.
MIN_POSSIBLE_MATCH_SCORE = 0.2
MAX_POSSIBLE_MATCHES = 3

GENERIC_QUERY_WORDS = frozenset(
    {
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
        "pay",
        "paid",
        "payment",
        "error",
        "issue",
        "problem",
        "help",
        "wrong",
        "working",
        "failed",
        "fail",
        "unable",
        "cannot",
        "showing",
        "show",
        "option",
        "options",
    }
)


def normalize_query(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def get_agent_script(branch: dict) -> str:
    for key in (
        "agent_script",
        "auto_script",
        "manual_script",
        "agent_script_pan",
        "agent_script_aadhaar",
        "agent_script_90_percent",
        "agent_script_eligible_no",
    ):
        if branch.get(key):
            return branch[key]
    return "Sir, please follow the steps below and confirm after each one."


def build_issue_path(branch: dict, category: dict, caller_type: str = "seller") -> list[str]:
    topic_id = branch.get("topic_category")
    topic_name = category_name_by_id(caller_type, topic_id) if topic_id else None
    path = [category["caller_type"]]
    if topic_name:
        path.append(topic_name)
    path.append(branch["branch_name"])
    return path


def expand_query(query: str, synonym_lookup: dict[str, frozenset[str]]) -> str:
    words = [word for word in query.split() if word]
    expanded: list[str] = []
    seen: set[str] = set()
    for word in words:
        if word not in seen:
            expanded.append(word)
            seen.add(word)

        synonym_group = synonym_lookup.get(word)
        if not synonym_group:
            continue

        for synonym in sorted(synonym_group):
            if synonym not in seen:
                expanded.append(synonym)
                seen.add(synonym)

    return " ".join(expanded) if expanded else query


def keyword_matches_query(query_text: str, keyword: str) -> bool:
    query_norm = normalize_query(query_text)
    keyword_norm = normalize_query(keyword)
    if not query_norm or not keyword_norm:
        return False
    if keyword_norm in query_norm or query_norm in keyword_norm:
        return True
    query_words = set(query_norm.split())
    keyword_words = set(keyword_norm.split())
    return bool(query_words & keyword_words)


def compute_keyword_score(
    normalized_query: str, expanded_query: str, branch: dict
) -> float:
    keywords = branch.get("trigger_keywords", [])
    if not keywords:
        return 0.0

    matching = sum(
        1
        for keyword in keywords
        if keyword_matches_query(normalized_query, keyword)
        or keyword_matches_query(expanded_query, keyword)
    )
    return matching / len(keywords)


def compute_branch_name_bonus(normalized_query: str, branch_name: str) -> float:
    bonus = 0.0
    name_lower = branch_name.lower()
    query_words = [word for word in normalized_query.split() if word]

    if any(word in name_lower for word in query_words):
        bonus += 0.1
    if normalized_query in name_lower:
        bonus += 0.05

    return bonus


def compute_exact_phrase_bonus(
    normalized_query: str, expanded_query: str, branch: dict
) -> float:
    for keyword in branch.get("trigger_keywords", []):
        keyword_norm = normalize_query(keyword)
        if keyword_norm == normalized_query or keyword_norm == expanded_query:
            return 0.2
    return 0.0


def _query_matches_branch_name(query: str, branch_name: str) -> bool:
    """True when query tokens appear as words in the branch title."""
    query_norm = normalize_query(query)
    name_norm = normalize_query(branch_name)
    if not query_norm or not name_norm:
        return False
    if query_norm in name_norm:
        return True
    name_words = set(name_norm.split())
    return any(word in name_words for word in query_norm.split() if len(word) > 2)


def apply_search_result_policy(query: str, results: list[dict]) -> list[dict]:
    """
    Tighten result lists for short/vague queries so single tokens like "pan"
    do not surface many weak semantic-only matches.
    """
    if not results:
        return []

    normalized = normalize_query(query)
    words = [word for word in normalized.split() if word]
    word_count = len(words)
    is_short = word_count <= 2
    top_score = results[0]["final_score"]

    def has_keyword_signal(row: dict) -> bool:
        return (row.get("keyword_score") or 0) > 0

    def has_name_signal(row: dict) -> bool:
        return _query_matches_branch_name(normalized, row.get("branch_name", ""))

    filtered: list[dict] = []
    for row in results:
        score = row["final_score"]
        semantic = row.get("semantic_score", 0)
        keyword = row.get("keyword_score", 0)

        if word_count == 1 and len(words[0]) <= 4:
            if not has_keyword_signal(row) and not has_name_signal(row) and semantic < 0.6:
                continue
            if score < max(0.32, top_score - 0.1):
                continue
        elif is_short:
            if keyword <= 0 and not has_name_signal(row) and semantic < 0.5:
                continue
            if score < max(0.28, top_score - 0.12):
                continue
        elif score < 0.22:
            continue

        filtered.append(row)

    if not filtered and top_score >= 0.25:
        filtered = [results[0]]

    if word_count == 1 and len(words[0]) <= 4:
        max_results = 3
    elif is_short:
        max_results = 5
    else:
        max_results = SEARCH_TOP_K

    return filtered[:max_results]


def _hybrid_final_score(
    normalized: str,
    expanded_query: str,
    branch: dict,
    semantic_score: float,
    keyword_score: float,
) -> float:
    final_score = 0.7 * semantic_score + 0.3 * keyword_score
    final_score += compute_branch_name_bonus(normalized, branch["branch_name"])
    final_score += compute_exact_phrase_bonus(normalized, expanded_query, branch)
    return round(final_score, 4)


def _build_search_result(
    branch: dict,
    store,
    *,
    semantic_score: float,
    keyword_score: float,
    final_score: float,
    xgboost_score: float | None = None,
    cross_encoder_score: float | None = None,
) -> dict:
    keywords = branch.get("trigger_keywords", [])
    script = get_agent_script(branch)
    result = {
        "branch_id": branch["branch_id"],
        "branch_name": branch["branch_name"],
        "semantic_score": semantic_score,
        "keyword_score": keyword_score,
        "final_score": final_score,
        "path": build_issue_path(branch, store.category, store.caller_type),
        "agent_script_preview": script[:100],
        "keywords_preview": keywords[:3],
    }
    if xgboost_score is not None:
        result["xgboost_score"] = xgboost_score
    if cross_encoder_score is not None:
        result["cross_encoder_score"] = cross_encoder_score
    return result


def faiss_semantic_search(
    query: str,
    store,
    embed_model: SentenceTransformer,
    *,
    top_k: int = SEARCH_TOP_K,
    topic_category: str | None = None,
) -> list[dict]:
    """Return top FAISS hits with branch payloads and semantic scores."""
    normalized = normalize_query(query)
    if not normalized or store.faiss_index is None or not store.branches:
        return []

    expanded_query = expand_query(normalized, store.synonym_lookup)
    query_vector = embed_model.encode(
        [expanded_query],
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype("float32")

    k = min(len(store.branches), max(top_k, SEARCH_TOP_K))
    scores, indices = store.faiss_index.search(query_vector, k)

    candidates: list[dict] = []
    for score, branch_index in zip(scores[0], indices[0]):
        if branch_index < 0:
            continue

        branch = store.branches[int(branch_index)]
        if topic_category and branch.get("topic_category") != topic_category:
            continue

        semantic_score = round(float(max(0.0, min(1.0, score))), 4)
        keyword_score = round(
            compute_keyword_score(normalized, expanded_query, branch), 4
        )
        candidates.append(
            {
                "branch": branch,
                "branch_id": branch["branch_id"],
                "branch_name": branch["branch_name"],
                "semantic_score": semantic_score,
                "keyword_score": keyword_score,
                "expanded_query": expanded_query,
                "normalized_query": normalized,
            }
        )

    return candidates


def _hybrid_formula_results(
    query: str, candidates: list[dict], store, top_k: int
) -> list[dict]:
    results: list[dict] = []
    for item in candidates:
        branch = item["branch"]
        final_score = _hybrid_final_score(
            item["normalized_query"],
            item["expanded_query"],
            branch,
            item["semantic_score"],
            item["keyword_score"],
        )
        results.append(
            _build_search_result(
                branch,
                store,
                semantic_score=item["semantic_score"],
                keyword_score=item["keyword_score"],
                final_score=final_score,
            )
        )
    results.sort(key=lambda row: row["final_score"], reverse=True)
    return apply_search_result_policy(query, results[:top_k])


def _reranked_to_results(reranked: list[dict], store, top_k: int) -> list[dict]:
    return [
        _build_search_result(
            item["branch"],
            store,
            semantic_score=item["semantic_score"],
            keyword_score=item["keyword_score"],
            final_score=item["final_score"],
            xgboost_score=item.get("xgboost_score"),
            cross_encoder_score=item.get("cross_encoder_score"),
        )
        for item in reranked[:top_k]
    ]


def hybrid_search(
    query: str,
    store,
    embed_model: SentenceTransformer,
    top_k: int = SEARCH_TOP_K,
    topic_category: str | None = None,
    *,
    ranking_mode: str | None = None,
    combine_xgboost_ce: bool = False,
) -> list[dict]:
    caller_type = store.caller_type
    try:
        from cross_encoder_reranker import (
            RERANKING_MODE,
            faiss_candidate_k,
            get_effective_ranking_mode,
            rank_with_cross_encoder,
        )
    except ImportError:
        RERANKING_MODE = "hybrid"  # type: ignore[misc, assignment]
        faiss_candidate_k = lambda tk, _ct: max(tk, SEARCH_TOP_K)  # type: ignore[assignment]
        get_effective_ranking_mode = lambda _ct: "hybrid_fallback"  # type: ignore[assignment]
        rank_with_cross_encoder = None  # type: ignore[assignment]

    mode = ranking_mode or get_effective_ranking_mode(caller_type)
    faiss_k = faiss_candidate_k(top_k, caller_type)

    candidates = faiss_semantic_search(
        query,
        store,
        embed_model,
        top_k=faiss_k,
        topic_category=topic_category,
    )
    if not candidates:
        return []

    try:
        from xgboost_ranker import is_ranker_available, rank_with_xgboost
    except ImportError:
        is_ranker_available = lambda _ct: False  # type: ignore[assignment]
        rank_with_xgboost = None  # type: ignore[assignment]

    if mode == "cross_encoder" and rank_with_cross_encoder is not None:
        reranked = rank_with_cross_encoder(
            query,
            candidates,
            caller_type,
            store,
            embed_model,
            combine_with_xgboost=combine_xgboost_ce,
        )
        if reranked is not None:
            results = _reranked_to_results(reranked, store, top_k)
            return apply_search_result_policy(query, results)

    if (
        mode in ("cross_encoder", "xgboost")
        and rank_with_xgboost
        and is_ranker_available(caller_type)
    ):
        reranked = rank_with_xgboost(
            query, candidates, caller_type, store, embed_model
        )
        results = _reranked_to_results(reranked, store, top_k)
        return apply_search_result_policy(query, results)

    return _hybrid_formula_results(query, candidates, store, top_k)

def _search_ranking_mode(caller_type: str) -> str:
    try:
        from cross_encoder_reranker import get_effective_ranking_mode

        return get_effective_ranking_mode(caller_type)
    except ImportError:
        try:
            from xgboost_ranker import get_ranking_mode

            return get_ranking_mode(caller_type)
        except ImportError:
            return "hybrid_fallback"


def _reranker_metadata(caller_type: str) -> dict:
    try:
        from cross_encoder_reranker import get_cross_encoder_health

        return {"cross_encoder": get_cross_encoder_health(caller_type)}
    except ImportError:
        return {}


def _correction_payload(correction: dict) -> dict:
    return {
        "original_query": correction.get("original_query", ""),
        "normalized_query": correction.get("normalized_query", ""),
        "corrected_query": correction.get("corrected_query", ""),
        "correction_applied": correction.get("correction_applied", False),
        "correction_confidence": correction.get("correction_confidence", 1.0),
        "correction_changes": correction.get("correction_changes", []),
    }


def _intent_payload(intent: dict) -> dict:
    return {
        "predicted_category": intent.get("predicted_category"),
        "predicted_category_name": None,
        "intent_confidence": intent.get("intent_confidence", 0.0),
        "intent_top_categories": intent.get("intent_top_categories", []),
        "intent_mode_used": intent.get("intent_mode_used", "disabled"),
    }


def search_kb_with_outlier_gate(
    query: str,
    caller_type: str,
    *,
    top_k: int = SEARCH_TOP_K,
    topic_category: str | None = None,
) -> dict:
    """Search pipeline: correction → intent → outlier gate → FAISS hybrid search."""
    original_query = query or ""

    try:
        from query_corrector import correct_query

        correction = correct_query(original_query, caller_type=caller_type)
    except ImportError:
        correction = {
            "original_query": original_query,
            "normalized_query": normalize_query(original_query),
            "corrected_query": normalize_query(original_query),
            "correction_applied": False,
            "correction_confidence": 1.0,
            "correction_changes": [],
        }

    search_query = correction.get("corrected_query") or correction.get(
        "normalized_query", original_query
    )

    store = get_kb(caller_type)
    embed_model = get_registry().embed_model

    intent: dict = {
        "predicted_category": None,
        "intent_confidence": 0.0,
        "intent_top_categories": [],
        "intent_mode_used": "disabled",
    }
    try:
        from intent_classifier import apply_intent_category_boost, predict_intent

        intent = predict_intent(search_query, caller_type, embed_model)
    except ImportError:
        pass

    try:
        from outlier_gate import outlier_response

        blocked = outlier_response(search_query, caller_type)
        if blocked is not None:
            payload = {
                **blocked,
                **_correction_payload(correction),
                **_intent_payload(intent),
            }
            predicted = intent.get("predicted_category")
            if predicted:
                payload["predicted_category_name"] = category_name_by_id(
                    caller_type, predicted
                )
            try:
                from search_telemetry import log_search_event

                log_search_event(
                    {
                        "query": original_query,
                        "caller_type": caller_type,
                        "predicted_category": intent.get("predicted_category"),
                        "intent_confidence": intent.get("intent_confidence", 0.0),
                        "top_score": None,
                        "selected_branch": None,
                        "correction_applied": correction.get("correction_applied", False),
                        "is_outlier": True,
                        "escalated": False,
                        "ranking_mode": _search_ranking_mode(caller_type),
                    }
                )
            except ImportError:
                pass
            return payload
    except ImportError:
        pass

    results = hybrid_search(
        search_query,
        store,
        embed_model,
        top_k=top_k,
        topic_category=topic_category,
    )

    predicted_category = intent.get("predicted_category")
    if not topic_category and predicted_category:
        try:
            from intent_classifier import apply_intent_category_boost

            branch_lookup = {b["branch_id"]: b for b in store.branches}
            results = apply_intent_category_boost(
                results,
                caller_type,
                predicted_category,
                intent.get("intent_confidence", 0.0),
                branch_lookup=branch_lookup,
            )
        except ImportError:
            pass

    intent_fields = _intent_payload(intent)
    if predicted_category:
        intent_fields["predicted_category_name"] = category_name_by_id(
            caller_type, predicted_category
        )

    payload = {
        "status": "search_results",
        "caller_type": store.caller_type,
        "topic_category": topic_category,
        "query": normalize_query(search_query),
        "ranking_mode": _search_ranking_mode(caller_type),
        "results": results,
        **_reranker_metadata(caller_type),
        **_correction_payload(correction),
        **intent_fields,
    }

    try:
        from search_telemetry import log_search_event

        top = (results or [{}])[0]
        log_search_event(
            {
                "query": original_query,
                "caller_type": caller_type,
                "predicted_category": intent.get("predicted_category"),
                "intent_confidence": intent.get("intent_confidence", 0.0),
                "top_score": top.get("final_score"),
                "selected_branch": top.get("branch_id"),
                "correction_applied": correction.get("correction_applied", False),
                "is_outlier": False,
                "escalated": False,
                "ranking_mode": payload.get("ranking_mode"),
            }
        )
    except ImportError:
        pass

    return payload


def search_kb_branches(
    query: str,
    caller_type: str,
    *,
    top_k: int = 3,
    topic_category: str | None = None,
) -> list[dict]:
    store = get_kb(caller_type)
    embed_model = get_registry().embed_model
    return hybrid_search(
        query,
        store,
        embed_model,
        top_k=top_k,
        topic_category=topic_category,
    )


def _significant_query_words(query: str) -> set[str]:
    return {
        word
        for word in normalize_query(query).split()
        if len(word) > 2 and word not in GENERIC_QUERY_WORDS
    }


def _branch_text_haystack(branch: dict) -> str:
    parts = [
        branch.get("branch_name", ""),
        " ".join(branch.get("trigger_keywords", [])),
        get_agent_script(branch),
        " ".join(str(step) for step in branch.get("steps", [])),
    ]
    return " ".join(parts).lower()


def _branch_matches_significant_words(
    branch: dict,
    significant_words: set[str],
    *,
    synonym_lookup: dict[str, frozenset[str]] | None = None,
) -> bool:
    if not significant_words:
        return False

    haystack = _branch_text_haystack(branch)
    for word in significant_words:
        if word in haystack:
            return True
        if synonym_lookup:
            group = synonym_lookup.get(word)
            if group and any(synonym in haystack for synonym in group):
                return True
    return False


def find_possible_kb_matches(
    query: str,
    caller_type: str,
    *,
    top_k: int = MAX_POSSIBLE_MATCHES,
) -> list[dict]:
    """Top KB branches that may relate to the query — optional hints, never blocking."""
    store = get_kb(caller_type)
    branch_by_id = {branch["branch_id"]: branch for branch in store.branches}
    matches = search_kb_branches(query, caller_type, top_k=10)
    scored = [
        match
        for match in matches
        if match["final_score"] >= MIN_POSSIBLE_MATCH_SCORE
    ]
    if not scored:
        return []

    def _with_topic_category(match: dict) -> dict:
        enriched = dict(match)
        branch = branch_by_id.get(match["branch_id"])
        if branch:
            enriched["topic_category"] = branch.get("topic_category")
        return enriched

    significant_words = _significant_query_words(query)
    if significant_words:
        relevant = []
        for match in scored:
            branch = branch_by_id.get(match["branch_id"])
            if branch and _branch_matches_significant_words(
                branch,
                significant_words,
                synonym_lookup=store.synonym_lookup,
            ):
                relevant.append(_with_topic_category(match))
        if relevant:
            return relevant[:top_k]
        # Fallback: keep top semantic hits when wording differs (showing vs visible).
        return [
            _with_topic_category(match)
            for match in scored
            if match.get("semantic_score", 0) >= 0.35
        ][:top_k]

    return [
        _with_topic_category(match)
        for match in scored
        if match["final_score"] >= 0.25
    ][:top_k]
