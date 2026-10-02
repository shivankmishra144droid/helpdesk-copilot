"""Load and search separate seller/buyer knowledge bases."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from concurrency import STORE_LOCK, guard_model_method
from ingest import load_kb, save_kb
from category_utils import enrich_branches, load_topic_categories, normalize_caller_type

KNOWLEDGE_ROOT = Path(__file__).parent / "knowledge"
KB_FILENAME = "unified_knowledge.json"
VALID_CALLER_TYPES = ("seller", "buyer")

# Used only when a knowledge base file defines no synonym_groups of its own.
DEFAULT_SYNONYM_GROUPS = [
    ["close", "closed", "closure"],
    ["delete", "remove"],
    ["visible", "showing", "appear"],
]


def kb_path(caller_type: str) -> Path:
    return KNOWLEDGE_ROOT / normalize_caller_type(caller_type) / KB_FILENAME


@dataclass
class KnowledgeBase:
    caller_type: str
    path: Path
    data: dict = field(default_factory=dict)
    category: dict = field(default_factory=dict)
    branches: list[dict] = field(default_factory=list)
    synonym_lookup: dict[str, frozenset[str]] = field(default_factory=dict)
    topic_categories: list[dict] = field(default_factory=list)
    faiss_index: faiss.IndexFlatIP | None = None
    branch_by_id: dict[str, dict] = field(default_factory=dict)


def build_synonym_lookup(groups: list[list[str]]) -> dict[str, frozenset[str]]:
    lookup: dict[str, frozenset[str]] = {}
    for group in groups:
        frozen = frozenset(word.lower() for word in group)
        for word in frozen:
            lookup[word] = frozen
    return lookup


def build_category(data: dict, caller_type: str) -> dict:
    if caller_type == "buyer":
        return {
            "id": data.get("category", "buyer").lower(),
            "name": data.get("problem_name", "Buyer Account"),
            "short_name": data.get("category", "Buyer"),
            "caller_type": data.get("caller_type", "Buyer"),
            "description": data.get("description", ""),
        }
    return {
        "id": "seller_profile",
        "name": data.get("problem_name", "Seller Profile Update"),
        "short_name": "Seller Profile",
        "caller_type": data.get("caller_type", "Seller"),
        "description": data.get("description", ""),
    }


def get_branch_description(branch: dict) -> str:
    for key in (
        "agent_script",
        "auto_script",
        "manual_script",
        "agent_script_pan",
        "agent_script_aadhaar",
    ):
        if branch.get(key):
            return branch[key]
    return branch["branch_name"]


def build_branch_embed_text(branch: dict) -> str:
    keywords = ", ".join(branch.get("trigger_keywords", []))
    description = get_branch_description(branch)
    return f"{branch['branch_name']} | {keywords} | {description}"


def _encode_branch_texts(
    texts: list[str],
    embed_model: SentenceTransformer,
    cache: dict[str, np.ndarray] | None,
) -> np.ndarray:
    """Encode texts, reusing cached vectors so a KB edit only embeds changed branches."""
    if cache is None:
        return embed_model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        ).astype(np.float32)

    missing = list(dict.fromkeys(text for text in texts if text not in cache))
    if missing:
        vectors = embed_model.encode(
            missing, normalize_embeddings=True, show_progress_bar=False
        ).astype(np.float32)
        cache.update(zip(missing, vectors))
    return np.stack([cache[text] for text in texts])


def build_faiss_index(
    branches: list[dict],
    embed_model: SentenceTransformer,
    cache: dict[str, np.ndarray] | None = None,
) -> faiss.IndexFlatIP | None:
    if not branches:
        return None

    branch_texts = [build_branch_embed_text(branch) for branch in branches]
    embeddings = _encode_branch_texts(branch_texts, embed_model, cache)

    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)
    return index


def load_knowledge_base(
    caller_type: str,
    embed_model: SentenceTransformer,
    embedding_cache: dict[str, np.ndarray] | None = None,
) -> KnowledgeBase:
    normalized = normalize_caller_type(caller_type)
    path = kb_path(normalized)
    if not path.exists():
        raise FileNotFoundError(f"Knowledge base not found: {path}")

    data = load_kb(path)
    raw_branches = data.get("branches", [])
    # Note: filter at load — stale lms_faq rows in JSON are ignored; re-run remove_lms_from_agent_kb to purge.
    branches = enrich_branches(
        [b for b in raw_branches if b.get("source") != "lms_faq"],
        normalized,
    )
    topic_categories = load_topic_categories(normalized)
    synonym_lookup = build_synonym_lookup(
        data.get("synonym_groups", DEFAULT_SYNONYM_GROUPS)
    )
    store = KnowledgeBase(
        caller_type=normalized,
        path=path,
        data=data,
        category=build_category(data, normalized),
        branches=branches,
        topic_categories=topic_categories,
        synonym_lookup=synonym_lookup,
        faiss_index=build_faiss_index(branches, embed_model, embedding_cache),
        # reversed() so the first branch wins on duplicate ids, matching the old linear scan.
        branch_by_id={branch["branch_id"]: branch for branch in reversed(branches)},
    )
    return store


class KnowledgeRegistry:
    def __init__(
        self,
        embed_model: SentenceTransformer | Callable[[], SentenceTransformer],
    ):
        """Accepts a loaded model, or a zero-arg factory that loads it on first use."""
        if hasattr(embed_model, "encode"):
            self._embed_model: SentenceTransformer | None = guard_model_method(
                embed_model, "encode"
            )
            self._embed_factory = None
        else:
            self._embed_model = None
            self._embed_factory = embed_model
        self._embed_load_lock = threading.Lock()
        self.stores: dict[str, KnowledgeBase] = {}
        # Branch embed text -> vector, shared across reloads (same model, same encode args).
        self.embedding_cache: dict[str, np.ndarray] = {}

    @property
    def embed_model(self) -> SentenceTransformer:
        if self._embed_model is None:
            with self._embed_load_lock:
                if self._embed_model is None:
                    self._embed_model = guard_model_method(
                        self._embed_factory(), "encode"
                    )
        return self._embed_model

    def reload_all(self) -> dict:
        summary = {}
        for caller_type in VALID_CALLER_TYPES:
            summary[caller_type] = self.reload(caller_type)
        return summary

    def reload(self, caller_type: str) -> dict:
        normalized = normalize_caller_type(caller_type)
        # Under STORE_LOCK so a slower reload that read the file earlier can't
        # overwrite a newer one (e.g. watcher reload racing an approval).
        with STORE_LOCK:
            store = load_knowledge_base(
                normalized, self.embed_model, self.embedding_cache
            )
            self.stores[normalized] = store
        return {
            "caller_type": normalized,
            "kb_name": store.data.get("kb_name", normalized),
            "kb_path": str(store.path.relative_to(KNOWLEDGE_ROOT.parent)),
            "branches": len(store.branches),
        }

    def get(self, caller_type: str) -> KnowledgeBase:
        normalized = normalize_caller_type(caller_type)
        if normalized not in self.stores:
            self.reload(normalized)
        return self.stores[normalized]

    def save(self, caller_type: str, data: dict) -> None:
        normalized = normalize_caller_type(caller_type)
        path = kb_path(normalized)
        path.parent.mkdir(parents=True, exist_ok=True)
        with STORE_LOCK:
            save_kb(path, data)
            self.reload(normalized)


_registry: KnowledgeRegistry | None = None


def bind_registry(registry: KnowledgeRegistry) -> None:
    global _registry
    _registry = registry


def get_registry() -> KnowledgeRegistry:
    if _registry is None:
        raise RuntimeError("Knowledge registry not bound. Call bind_registry() first.")
    return _registry


def get_kb(caller_type: str) -> KnowledgeBase:
    return get_registry().get(caller_type)


def _unique_branch_id(branch_id: str, existing_ids: set[str]) -> str:
    if branch_id not in existing_ids:
        return branch_id

    suffix = 2
    while f"{branch_id}_{suffix}" in existing_ids:
        suffix += 1
    return f"{branch_id}_{suffix}"


def add_branch(caller_type: str, branch: dict) -> str:
    """Append a branch to seller/buyer KB and rebuild FAISS index."""
    normalized = normalize_caller_type(caller_type)
    with STORE_LOCK:
        return _add_branch_locked(normalized, branch)


def _add_branch_locked(normalized: str, branch: dict) -> str:
    store = get_kb(normalized)
    kb = dict(store.data)
    branches = list(kb.get("branches", []))
    existing_ids = {item.get("branch_id") for item in branches if item.get("branch_id")}

    branch = dict(branch)
    branch["branch_id"] = _unique_branch_id(branch["branch_id"], existing_ids)
    branches.append(branch)
    kb["branches"] = branches

    get_registry().save(normalized, kb)
    return branch["branch_id"]
