"""Tests for cross-encoder reranker (mocked model — no download in CI)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import cross_encoder_reranker as ce  # noqa: E402
from cross_encoder_reranker import (  # noqa: E402
    build_rerank_document_text,
    get_cross_encoder_health,
    get_effective_ranking_mode,
    rank_with_cross_encoder,
)


class FakeStore:
    caller_type = "seller"
    data = {"problem_name": "Seller Profile Update"}
    synonym_lookup: dict = {}

    class _Cat:
        name = "Seller Profile"

    category = _Cat()


def _branch(branch_id: str, name: str, keywords: list[str] | None = None) -> dict:
    return {
        "branch_id": branch_id,
        "branch_name": name,
        "trigger_keywords": keywords or [name.lower()],
        "agent_script": f"Script for {name}",
        "steps": [f"Step one for {name}", f"Step two for {name}"],
    }


def _candidate(branch: dict, *, semantic: float = 0.5, keyword: float = 0.3) -> dict:
    return {
        "branch": branch,
        "branch_id": branch["branch_id"],
        "branch_name": branch["branch_name"],
        "semantic_score": semantic,
        "keyword_score": keyword,
        "normalized_query": "tax id validation failed",
        "expanded_query": "tax id validation failed",
    }


class TestDocumentText(unittest.TestCase):
    def test_build_rerank_document_text_includes_branch_fields(self):
        branch = _branch("tax_fail", "Tax ID Validation Failed", ["tax id", "validation"])
        text = build_rerank_document_text(branch, FakeStore())
        self.assertIn("Tax ID Validation Failed", text)
        self.assertIn("tax id", text)
        self.assertIn("Script for", text)
        self.assertIn("Step one", text)


class TestCrossEncoderReranker(unittest.TestCase):
    def setUp(self):
        ce._cross_encoder = None
        ce._load_failed = False

    def tearDown(self):
        ce._cross_encoder = None
        ce._load_failed = False
        ce.CROSS_ENCODER_ENABLED = False
        ce.RERANKING_MODE = "hybrid"

    def test_empty_candidates_returns_empty(self):
        ce.CROSS_ENCODER_ENABLED = True
        ce._cross_encoder = MagicMock()
        result = rank_with_cross_encoder(
            "pan issue", [], "seller", FakeStore(), MagicMock()
        )
        self.assertEqual(result, [])

    def test_malformed_candidates_filtered(self):
        ce.CROSS_ENCODER_ENABLED = True
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([0.5])
        ce._cross_encoder = mock_model

        good = _candidate(_branch("ok", "Good Branch"))
        bad = {"branch": {"branch_name": "no id"}}
        result = rank_with_cross_encoder(
            "query", [bad, good], "seller", FakeStore(), MagicMock()
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["branch_id"], "ok")

    def test_one_candidate_scored(self):
        ce.CROSS_ENCODER_ENABLED = True
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([2.0])
        ce._cross_encoder = mock_model

        branch = _branch("tax", "Tax ID Validation")
        result = rank_with_cross_encoder(
            "tax id validation",
            [_candidate(branch, semantic=0.8)],
            "seller",
            FakeStore(),
            MagicMock(),
        )
        self.assertEqual(len(result), 1)
        self.assertIn("cross_encoder_score", result[0])
        self.assertIn("final_score", result[0])

    def test_multiple_candidates_sorted_by_final_score(self):
        ce.CROSS_ENCODER_ENABLED = True
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([5.0, -1.0, 1.0])
        ce._cross_encoder = mock_model

        candidates = [
            _candidate(_branch("a", "Alpha"), semantic=0.2),
            _candidate(_branch("b", "Beta"), semantic=0.9),
            _candidate(_branch("c", "Gamma"), semantic=0.5),
        ]
        result = rank_with_cross_encoder(
            "tax id validation", candidates, "seller", FakeStore(), MagicMock()
        )
        scores = [row["final_score"] for row in result]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_model_unavailable_returns_none(self):
        ce.CROSS_ENCODER_ENABLED = False
        result = rank_with_cross_encoder(
            "query",
            [_candidate(_branch("x", "X"))],
            "seller",
            FakeStore(),
            MagicMock(),
        )
        self.assertIsNone(result)

    def test_fallback_to_xgboost_mode_when_ce_missing(self):
        ce.CROSS_ENCODER_ENABLED = False
        ce.RERANKING_MODE = "cross_encoder"
        with patch.object(ce, "_xgboost_available", return_value=True):
            mode = get_effective_ranking_mode("seller")
        self.assertEqual(mode, "xgboost_fallback")

    def test_fallback_to_hybrid_when_ce_and_xgboost_missing(self):
        ce.CROSS_ENCODER_ENABLED = False
        ce.RERANKING_MODE = "cross_encoder"
        with patch.object(ce, "_xgboost_available", return_value=False):
            mode = get_effective_ranking_mode("seller")
        self.assertEqual(mode, "hybrid_fallback")

    def test_disabled_mode(self):
        ce.RERANKING_MODE = "disabled"
        self.assertEqual(get_effective_ranking_mode("seller"), "disabled")

    def test_health_reports_unloaded_when_disabled(self):
        ce.CROSS_ENCODER_ENABLED = False
        health = get_cross_encoder_health("seller")
        self.assertFalse(health["loaded"])
        self.assertFalse(health["enabled"])

    def test_buyer_caller_type(self):
        ce.CROSS_ENCODER_ENABLED = True
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([1.0])
        ce._cross_encoder = mock_model

        store = FakeStore()
        store.caller_type = "buyer"
        store.data = {"problem_name": "Buyer Account"}
        branch = _branch("buyer_bid", "Invite Sellers", ["bid", "invite"])
        result = rank_with_cross_encoder(
            "invite sellers",
            [_candidate(branch)],
            "buyer",
            store,
            MagicMock(),
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["branch_id"], "buyer_bid")


class TestHybridSearchIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from kb_manager import KnowledgeRegistry, bind_registry
        from sentence_transformers import SentenceTransformer

        embed = SentenceTransformer("all-MiniLM-L6-v2")
        registry = KnowledgeRegistry(embed)
        bind_registry(registry)
        registry.reload_all()
        cls.registry = registry

    def setUp(self):
        ce._cross_encoder = None
        ce._load_failed = False

    def tearDown(self):
        ce._cross_encoder = None
        ce._load_failed = False
        ce.CROSS_ENCODER_ENABLED = False
        ce.RERANKING_MODE = "hybrid"

    def test_hybrid_search_cross_encoder_mode_with_mock(self):
        from kb_manager import get_kb
        from kb_search import hybrid_search

        ce.CROSS_ENCODER_ENABLED = True
        ce.RERANKING_MODE = "cross_encoder"
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([3.0, 0.0, 1.0])
        ce._cross_encoder = mock_model

        store = get_kb("seller")
        results = hybrid_search(
            "product not visible",
            store,
            self.registry.embed_model,
            top_k=3,
            ranking_mode="cross_encoder",
        )
        self.assertGreater(len(results), 0)
        self.assertIn("final_score", results[0])

    def test_hybrid_search_disabled_uses_formula(self):
        from kb_manager import get_kb
        from kb_search import hybrid_search

        store = get_kb("seller")
        results = hybrid_search(
            "tax id validation",
            store,
            self.registry.embed_model,
            top_k=3,
            ranking_mode="disabled",
        )
        self.assertGreater(len(results), 0)
        self.assertNotIn("cross_encoder_score", results[0])


if __name__ == "__main__":
    unittest.main()
