"""Help-centre FAQ index — supervisor draft search only (not agent /search KB)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from category_utils import CATEGORY_ALIASES, assign_topic_category, infer_topic_category
from concurrency import STORE_LOCK
from ingest import build_keywords, slugify, save_kb, load_kb
from kb_manager import (
    KNOWLEDGE_ROOT,
    VALID_CALLER_TYPES,
    get_registry,
    kb_path,
    normalize_caller_type,
)
from kb_search import normalize_query

logger = logging.getLogger(__name__)

LMS_DIR = KNOWLEDGE_ROOT / "lms"
DEFAULT_FAQ_PATH = LMS_DIR / "faq.json"

LMS_SOURCE = "lms_faq"

# Note: process-global cache; single worker only — use Redis/LRU if multi-worker.
_index_cache: dict[str, dict[str, Any]] | None = None
_faq_mtime: float | None = None

# FAQ taxonomy category names -> topic category ids (from knowledge/taxonomy.json).
CATEGORY_L1_TO_ID: dict[str, str] = CATEGORY_ALIASES


def resolve_faq_path(faq_path: str | Path | None = None) -> Path:
    if faq_path:
        path = Path(faq_path)
        if path.exists():
            return path
        raise FileNotFoundError(f"FAQ file not found: {path}")

    if DEFAULT_FAQ_PATH.exists():
        return DEFAULT_FAQ_PATH
    raise FileNotFoundError(f"No FAQ file at {DEFAULT_FAQ_PATH}")


def _faq_user_type(entry: dict[str, Any]) -> str:
    audience = entry.get("audience") or {}
    return str(audience.get("userType") or entry.get("userType") or "").strip()


def map_faq_to_caller_type(entry: dict[str, Any]) -> str | None:
    """Map FAQ audience to caller_type (seller/buyer)."""
    user_type = _faq_user_type(entry).lower()
    if user_type == "buyer":
        return "buyer"
    if user_type == "seller":
        return "seller"
    return None


def _parse_steps_from_answer(answer: str) -> list[str]:
    if not answer or not answer.strip():
        return []
    lines = [line.strip() for line in answer.splitlines() if line.strip()]
    steps: list[str] = []
    numbered = re.compile(r"^(\d+[\).\:-]|\*)\s*", re.I)
    for line in lines:
        cleaned = numbered.sub("", line).strip()
        if len(cleaned) > 8:
            steps.append(cleaned)
    if steps:
        return steps[:12]
    # fallback: sentence split
    sentences = re.split(r"(?<=[.!?])\s+", answer.strip())
    return [s.strip() for s in sentences if len(s.strip()) > 12][:8]


def _topic_category_from_taxonomy(taxonomy: dict[str, Any], caller_type: str) -> str | None:
    l1 = str(taxonomy.get("categoryL1") or "").strip().lower()
    if l1 in CATEGORY_L1_TO_ID:
        return CATEGORY_L1_TO_ID[l1]
    l2 = str(taxonomy.get("categoryL2") or "").strip().lower()
    for key, category_id in CATEGORY_L1_TO_ID.items():
        if key in l1 or key in l2:
            return category_id
    return None


def faq_entry_to_branch(entry: dict[str, Any], caller_type: str) -> dict[str, Any]:
    content = entry.get("content") or {}
    taxonomy = entry.get("taxonomy") or {}
    query_u = entry.get("queryUnderstanding") or {}
    metadata = entry.get("metadata") or {}

    question = str(content.get("question") or entry.get("question") or "").strip()
    answer = str(content.get("answer") or entry.get("answer") or "").strip()
    short_answer = str(content.get("shortAnswer") or "").strip()
    steps = list(content.get("steps") or [])
    if not steps and answer:
        steps = _parse_steps_from_answer(answer)

    branch_name = (
        str(taxonomy.get("topic") or entry.get("topic") or "").strip()
        or question[:100]
        or f"FAQ {entry.get('id', '')}"
    )

    faq_id = str(entry.get("id") or entry.get("sourceId") or slugify(branch_name))
    branch_id = slugify(f"lms_{faq_id}")

    keyword_parts: list[str] = []
    keyword_parts.extend(query_u.get("searchPhrases") or [])
    keyword_parts.extend(query_u.get("synonyms") or [])
    keyword_parts.extend(entry.get("tags") or [])
    keyword_parts.append(question)
    keyword_blob = " ".join(str(p) for p in keyword_parts if p)
    trigger_keywords = build_keywords(branch_name, keyword_blob)
    if question:
        trigger_keywords = list(dict.fromkeys(trigger_keywords + [question[:120]]))

    agent_script = short_answer or (answer[:600] if answer else f"Answer the caller's question: {question}")
    if not steps:
        steps = [answer] if answer else ["Review FAQ guidance and escalate if unresolved."]

    documents = [
        str(link.get("label") or link.get("url") or "").strip()
        for link in (content.get("links") or [])
        if isinstance(link, dict) and (link.get("label") or link.get("url"))
    ]

    module_owner = str(metadata.get("moduleOwner") or entry.get("moduleOwner") or "Help Centre").strip()
    l1_person = module_owner if module_owner else "FAQ Team"

    branch: dict[str, Any] = {
        "branch_id": branch_id,
        "branch_name": branch_name[:120],
        "trigger_keywords": trigger_keywords[:25],
        "agent_script": agent_script,
        "steps": steps[:15],
        "documents": documents[:10],
        "escalation": f"Assign to {l1_person}" if l1_person.upper() != "TBD" else "Help Centre",
        "escalation_person": l1_person,
        "source": LMS_SOURCE,
        "tagging": " → ".join(
            filter(
                None,
                [
                    taxonomy.get("categoryL1"),
                    taxonomy.get("categoryL2"),
                    taxonomy.get("categoryL3"),
                    branch_name,
                ],
            )
        ),
        "lms_faq_id": faq_id,
        "lms_source_id": entry.get("sourceId"),
        "description": question,
        "policy_notes": answer[:2000] if answer else "",
    }

    topic = _topic_category_from_taxonomy(taxonomy, caller_type)
    if topic:
        branch["topic_category"] = topic
    else:
        assign_topic_category(branch, caller_type)
        if not branch.get("topic_category"):
            branch["topic_category"] = infer_topic_category(branch, caller_type)

    return branch


def _faq_embed_text(entry: dict[str, Any]) -> str:
    if entry.get("searchText"):
        return str(entry["searchText"])[:4000]
    content = entry.get("content") or {}
    parts = [
        content.get("question") or entry.get("question", ""),
        content.get("shortAnswer", ""),
        content.get("answer") or entry.get("answer", ""),
        " ".join(content.get("steps") or []),
    ]
    qu = entry.get("queryUnderstanding") or {}
    parts.extend(qu.get("searchPhrases") or [])
    return " ".join(p for p in parts if p).strip()[:4000]


def _load_faq_entries(faq_path=None) -> list[dict[str, Any]]:
    path = resolve_faq_path(faq_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries") or []
    return [e for e in entries if isinstance(e, dict)]


def _build_caller_index(
    entries: list[dict[str, Any]],
    caller_type: str,
    embed_model: SentenceTransformer,
) -> dict[str, Any]:
    normalized = normalize_caller_type(caller_type)
    filtered: list[dict[str, Any]] = []
    texts: list[str] = []
    for entry in entries:
        mapped = map_faq_to_caller_type(entry)
        if mapped != normalized:
            continue
        text = _faq_embed_text(entry)
        if not text:
            continue
        filtered.append(entry)
        texts.append(text)

    if not texts:
        return {
            "caller_type": normalized,
            "entries": [],
            "texts": [],
            "index": None,
        }

    embeddings = embed_model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype(np.float32)

    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)

    return {
        "caller_type": normalized,
        "entries": filtered,
        "texts": texts,
        "index": index,
    }


def get_lms_faq_index(
    embed_model: SentenceTransformer,
    *,
    faq_path=None,
    force_reload: bool = False,
) -> dict[str, dict[str, Any]]:
    """Per-caller-type FAISS indexes over FAQ entries."""
    global _index_cache, _faq_mtime

    path = resolve_faq_path(faq_path)
    mtime = path.stat().st_mtime
    if not force_reload and _index_cache is not None and _faq_mtime == mtime:
        return _index_cache

    entries = _load_faq_entries(path)
    _index_cache = {
        ct: _build_caller_index(entries, ct, embed_model)
        for ct in VALID_CALLER_TYPES
    }
    _faq_mtime = mtime
    logger.info(
        "FAQ index loaded: seller=%s buyer=%s entries",
        len(_index_cache["seller"]["entries"]),
        len(_index_cache["buyer"]["entries"]),
    )
    return _index_cache


def search_lms_faq(
    query: str,
    caller_type: str,
    *,
    embed_model: SentenceTransformer,
    top_k: int = 5,
    min_score: float = 0.25,
) -> list[dict[str, Any]]:
    """Semantic search over FAQ for supervisor drafting."""
    normalized = normalize_query(query)
    if not normalized:
        return []

    bucket = get_lms_faq_index(embed_model).get(normalize_caller_type(caller_type), {})
    index = bucket.get("index")
    entries: list[dict[str, Any]] = bucket.get("entries") or []
    if index is None or not entries:
        return []

    vector = embed_model.encode(
        [normalized],
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype(np.float32)

    k = min(len(entries), max(top_k, 5))
    scores, indices = index.search(vector, k)

    results: list[dict[str, Any]] = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        semantic = round(float(max(0.0, min(1.0, score))), 4)
        if semantic < min_score:
            continue
        entry = entries[int(idx)]
        content = entry.get("content") or {}
        question = str(content.get("question") or entry.get("question") or "").strip()
        results.append(
            {
                "source": "lms_faq",
                "lms_faq_id": entry.get("id"),
                "score": semantic,
                "question": question,
                "branch_name": str(entry.get("taxonomy", {}).get("topic") or question[:80]),
                "agent_script_preview": str(
                    content.get("shortAnswer")
                    or (content.get("answer") or "")[:200]
                ),
                "entry": entry,
            }
        )

    return results[:top_k]


def faq_entry_to_draft_entry(entry: dict[str, Any], caller_type: str) -> dict[str, Any]:
    """Convert FAQ entry to supervisor draft JSON fields."""
    from draft_enrichment import branch_to_draft_entry

    branch = faq_entry_to_branch(entry, caller_type)
    draft = branch_to_draft_entry(branch, caller_type)
    draft["sources"] = ["lms_faq"]
    if entry.get("id"):
        draft.setdefault("sources", []).append(str(entry["id"]))
    return draft


def invalidate_lms_faq_cache() -> None:
    global _index_cache, _faq_mtime
    _index_cache = None
    _faq_mtime = None


def remove_lms_from_agent_kb(*, dry_run: bool = False) -> dict[str, Any]:
    """Strip FAQ branches from agent unified_knowledge.json files."""
    with STORE_LOCK:
        return _remove_lms_from_agent_kb(dry_run=dry_run)


def _remove_lms_from_agent_kb(*, dry_run: bool) -> dict[str, Any]:
    results: dict[str, Any] = {}
    try:
        registry = get_registry()
    except RuntimeError:
        registry = None

    for caller_type in VALID_CALLER_TYPES:
        normalized = normalize_caller_type(caller_type)
        path = kb_path(normalized)
        kb = load_kb(path)
        branches = list(kb.get("branches") or [])
        kept = [b for b in branches if b.get("source") != LMS_SOURCE]
        removed = len(branches) - len(kept)
        results[normalized] = {
            "removed": removed,
            "remaining": len(kept),
            "dry_run": dry_run,
        }
        if not dry_run and removed:
            kb["branches"] = kept
            save_kb(path, kb)
            if registry:
                registry.reload(normalized)

    return results


def refresh_lms_faq_supervisor_index() -> dict[str, int]:
    """Build in-memory FAQ FAISS index for supervisor drafting."""
    registry = get_registry()
    if not registry:
        raise RuntimeError("KnowledgeRegistry not bound — start app or bind_registry first")
    invalidate_lms_faq_cache()
    buckets = get_lms_faq_index(registry.embed_model, force_reload=True)
    return {
        ct: len(buckets[ct].get("entries") or [])
        for ct in VALID_CALLER_TYPES
    }


def import_lms_faq(
    *,
    faq_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Refresh FAQ supervisor index; strip any FAQ branches from agent KB."""
    faq_file = resolve_faq_path(faq_path)
    payload = json.loads(faq_file.read_text(encoding="utf-8"))
    entries = payload.get("entries") or []
    removal = remove_lms_from_agent_kb(dry_run=dry_run)
    index_counts: dict[str, int] = {}
    if not dry_run:
        index_counts = refresh_lms_faq_supervisor_index()
    return {
        "faq_path": str(faq_file),
        "total_faq_entries": len(entries),
        "removed_from_agent_kb": removal,
        "lms_index_entries": index_counts,
    }


if __name__ == "__main__":
    from kb_manager import KnowledgeRegistry, bind_registry

    embed = SentenceTransformer("all-MiniLM-L6-v2")
    bind_registry(KnowledgeRegistry(embed))
    hits = search_lms_faq(
        "which documents do I need to register as a seller",
        "seller",
        embed_model=embed,
        top_k=3,
        min_score=0.2,
    )
    assert hits, "expected FAQ hits for registration query"
    print(f"self-check ok: {len(hits)} hit(s), top={hits[0].get('question', '')[:60]!r}")
