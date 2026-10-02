"""Tests for optional XGBoost ranker and IsolationForest outlier gate."""

from __future__ import annotations

import pickle
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from xgboost_ranker import (  # noqa: E402
    FEATURE_NAMES,
    MODEL_PATH,
    extract_features,
    get_ranker_health,
    get_ranking_mode,
    load_xgboost_ranker,
)
from outlier_gate import (  # noqa: E402
    get_outlier_status,
    is_outlier,
    model_path,
)


class FakeStore:
    caller_type = "seller"
    synonym_lookup: dict = {}

    class _Cat:
        name = "Test"

    category = _Cat()


class TestFeatureOrder(unittest.TestCase):
    def test_feature_names_length_matches_extractor(self):
        branch = {
            "branch_id": "test_branch",
            "branch_name": "product not visible",
            "trigger_keywords": ["product", "visible"],
            "click_count": 0,
        }
        embed = MagicMock()
        embed.encode.return_value = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        with patch("xgboost_ranker.compute_semantic_score", return_value=0.8):
            with patch("xgboost_ranker.compute_keyword_score", return_value=0.5):
                features = extract_features(
                    "product not visible in marketplace",
                    branch,
                    FakeStore(),
                    embed,
                    semantic_score=0.8,
                )
        self.assertEqual(len(features), len(FEATURE_NAMES))


class TestRankerBundle(unittest.TestCase):
    def test_bundle_loads_when_present(self):
        if not MODEL_PATH.exists():
            self.skipTest("xgboost_ranker.pkl not trained yet")
        bundle = load_xgboost_ranker(force=True)
        self.assertIsNotNone(bundle)
        self.assertEqual(bundle.get("feature_names"), FEATURE_NAMES)
        self.assertIn("seller", bundle.get("models", {}))
        self.assertIn("buyer", bundle.get("models", {}))

    def test_health_reports_xgboost_when_loaded(self):
        health = get_ranker_health()
        if not MODEL_PATH.exists():
            self.assertFalse(health["loaded"])
            self.assertEqual(health["ranking_mode"], "hybrid_fallback")
            return
        self.assertTrue(health["loaded"])
        self.assertEqual(health["ranking_mode"], "xgboost")

    def test_corrupt_ranker_falls_back(self):
        import xgboost_ranker as mod

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "xgboost_ranker.pkl"
            bad.write_bytes(b"not-a-pickle")
            old_path = mod.MODEL_PATH
            mod.MODEL_PATH = bad
            mod._ranker_bundle = None
            try:
                self.assertIsNone(mod.load_xgboost_ranker(force=True))
            finally:
                mod.MODEL_PATH = old_path
                mod._ranker_bundle = None


class TestOutlierGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from kb_manager import KnowledgeRegistry, bind_registry
        from sentence_transformers import SentenceTransformer

        embed = SentenceTransformer("all-MiniLM-L6-v2")
        bind_registry(KnowledgeRegistry(embed))

    def test_seller_model_loads_when_present(self):
        path = model_path("seller")
        if not path.exists():
            self.skipTest("seller outlier model not trained yet")
        result = is_outlier("product not visible", "seller")
        self.assertTrue(result["model_loaded"])

    def test_unrelated_query_blocked_when_model_present(self):
        path = model_path("seller")
        if not path.exists():
            self.skipTest("seller outlier model not trained yet")
        weather = is_outlier("what is the weather today", "seller")
        self.assertTrue(weather["model_loaded"])
        self.assertTrue(weather["is_outlier"])

    def test_valid_support_query_not_always_blocked(self):
        for caller, query in (
            ("seller", "product not visible in marketplace"),
            ("buyer", "invite sellers to published bid"),
        ):
            path = model_path(caller)
            if not path.exists():
                self.skipTest(f"{caller} outlier model not trained yet")
            result = is_outlier(query, caller)
            self.assertTrue(result["model_loaded"])
            self.assertFalse(result["is_outlier"], msg=f"{caller}: {query}")

    def test_joke_blocked_when_model_present(self):
        path = model_path("seller")
        if not path.exists():
            self.skipTest("seller outlier model not trained yet")
        joke = is_outlier("tell me a joke", "seller")
        self.assertTrue(joke["is_outlier"])

    def test_short_valid_query_not_blocked(self):
        for caller, query in (
            ("seller", "create bid"),
            ("buyer", "create bid"),
        ):
            path = model_path(caller)
            if not path.exists():
                self.skipTest(f"{caller} outlier model not trained yet")
            result = is_outlier(query, caller)
            self.assertFalse(result["is_outlier"], msg=f"{caller}: {query}")

    def test_missing_model_disables_gate(self):
        import outlier_gate as mod

        with tempfile.TemporaryDirectory() as tmp:
            old_dir = mod.MODEL_DIR
            mod.MODEL_DIR = Path(tmp)
            mod._model_cache.clear()
            try:
                result = is_outlier("quantum physics homework", "seller")
                self.assertFalse(result["model_loaded"])
                self.assertFalse(result["is_outlier"])
            finally:
                mod.MODEL_DIR = old_dir
                mod._model_cache.clear()

    def test_corrupt_outlier_disables_gate(self):
        import outlier_gate as mod

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "isolation_forest_seller.pkl"
            bad.write_bytes(b"broken")
            old_dir = mod.MODEL_DIR
            mod.MODEL_DIR = Path(tmp)
            mod._model_cache.clear()
            try:
                result = is_outlier("quantum physics homework", "seller")
                self.assertFalse(result["model_loaded"])
                self.assertFalse(result["is_outlier"])
            finally:
                mod.MODEL_DIR = old_dir
                mod._model_cache.clear()

    def test_outlier_health_shape(self):
        status = get_outlier_status()
        self.assertIn(status["status"], {
            "seller_and_buyer_active",
            "seller_only",
            "buyer_only",
            "disabled",
        })
        self.assertIn("seller", status)
        self.assertIn("buyer", status)


class TestRankingIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from kb_manager import KnowledgeRegistry, bind_registry
        from sentence_transformers import SentenceTransformer

        embed = SentenceTransformer("all-MiniLM-L6-v2")
        registry = KnowledgeRegistry(embed)
        bind_registry(registry)
        registry.reload_all()
        cls.registry = registry

    def test_ranking_mode_matches_bundle(self):
        mode = get_ranking_mode("seller")
        if MODEL_PATH.exists():
            self.assertEqual(mode, "xgboost")
        else:
            self.assertEqual(mode, "hybrid_fallback")

    def test_relevant_branch_scores_higher_than_unrelated(self):
        if not MODEL_PATH.exists():
            self.skipTest("xgboost_ranker.pkl not trained yet")

        from kb_manager import get_kb
        from kb_search import faiss_semantic_search
        from xgboost_ranker import rank_with_xgboost

        store = get_kb("seller")
        query = "product not visible in marketplace"
        candidates = faiss_semantic_search(
            query, store, self.registry.embed_model, top_k=10
        )
        self.assertGreaterEqual(len(candidates), 2)

        reranked = rank_with_xgboost(
            query, candidates, "seller", store, self.registry.embed_model
        )
        top = reranked[0]
        bottom = reranked[-1]
        self.assertEqual(top["branch_id"], "listing_missing_from_buyer_search")
        self.assertGreater(top["xgboost_score"], bottom["xgboost_score"])


if __name__ == "__main__":
    unittest.main()
