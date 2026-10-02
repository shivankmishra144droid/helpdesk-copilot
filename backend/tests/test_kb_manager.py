"""Tests for KB loading helpers: embedding cache and branch lookup."""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from concurrency import MODEL_LOCK, guard_model_method  # noqa: E402
from kb_manager import build_faiss_index  # noqa: E402


class FakeEmbedModel:
    """Deterministic stand-in for SentenceTransformer that records what it encodes."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        self.calls.append(list(texts))
        vectors = np.array(
            [[len(text), sum(map(ord, text)) % 97, 1.0] for text in texts],
            dtype=np.float32,
        )
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def _branch(branch_id: str, name: str) -> dict:
    return {"branch_id": branch_id, "branch_name": name, "trigger_keywords": [name]}


class TestEmbeddingCache(unittest.TestCase):
    def test_only_new_branches_are_encoded_on_reload(self):
        model = FakeEmbedModel()
        cache: dict = {}
        first = [_branch("a", "otp not received"), _branch("b", "bid not visible")]
        build_faiss_index(first, model, cache)
        self.assertEqual(len(model.calls[-1]), 2)

        second = first + [_branch("c", "payment pending")]
        index = build_faiss_index(second, model, cache)
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(len(model.calls[-1]), 1)
        self.assertEqual(index.ntotal, 3)

    def test_cached_index_matches_uncached(self):
        branches = [_branch(str(i), f"issue number {i}") for i in range(5)]
        cache: dict = {}
        build_faiss_index(branches[:3], FakeEmbedModel(), cache)
        cached = build_faiss_index(branches, FakeEmbedModel(), cache)
        fresh = build_faiss_index(branches, FakeEmbedModel())
        np.testing.assert_allclose(
            cached.reconstruct_n(0, 5), fresh.reconstruct_n(0, 5), rtol=1e-6
        )


class TestModelGuard(unittest.TestCase):
    def test_guarded_method_holds_model_lock(self):
        model = FakeEmbedModel()
        seen: list[bool] = []
        original = model.encode

        def probe(*args, **kwargs):
            # RLock exposes no public "is held"; a non-blocking acquire from
            # another thread must fail while the guarded call is running.
            result: list[bool] = []
            t = threading.Thread(
                target=lambda: result.append(MODEL_LOCK.acquire(blocking=False))
            )
            t.start()
            t.join()
            seen.append(result[0])
            return original(*args, **kwargs)

        model.encode = probe
        guard_model_method(model, "encode")
        guard_model_method(model, "encode")  # idempotent
        model.encode(["x"])
        self.assertEqual(seen, [False])


if __name__ == "__main__":
    unittest.main()
