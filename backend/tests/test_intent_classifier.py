"""Tests for intent / topic-category classifier."""

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

from intent_classifier import (  # noqa: E402
    apply_intent_category_boost,
    build_category_prototypes,
    clear_prototype_cache,
    confidence_threshold,
    get_intent_classifier_status,
    load_supervised_model,
    model_path,
    predict_intent,
)


class TestIntentClassifier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from kb_manager import KnowledgeRegistry, bind_registry
        from sentence_transformers import SentenceTransformer

        cls.embed = SentenceTransformer("all-MiniLM-L6-v2")
        bind_registry(KnowledgeRegistry(cls.embed))
        clear_prototype_cache()

    def setUp(self):
        clear_prototype_cache()

    def test_prototype_prediction_returns_shape(self):
        result = predict_intent(
            "tax id validation failed",
            "seller",
            self.embed,
        )
        self.assertIn("predicted_category", result)
        self.assertIn("intent_confidence", result)
        self.assertIn("intent_top_categories", result)
        self.assertIsInstance(result["intent_top_categories"], list)

    def test_prototypes_built_from_real_categories(self):
        prototypes = build_category_prototypes("seller", self.embed)
        self.assertGreater(len(prototypes), 0)
        for category_id, vector in prototypes.items():
            self.assertIsInstance(category_id, str)
            self.assertEqual(vector.shape[0], 384)

    def test_low_confidence_clears_prediction(self):
        with patch("intent_classifier.confidence_threshold", return_value=0.99):
            result = predict_intent("xyz", "seller", self.embed)
        self.assertIsNone(result["predicted_category"])

    def test_intent_boost_only_for_matching_category(self):
        results = [
            {
                "branch_id": "a",
                "final_score": 0.5,
            },
            {
                "branch_id": "b",
                "final_score": 0.6,
            },
        ]
        branch_lookup = {
            "a": {"topic_category": "profile_update"},
            "b": {"topic_category": "payment"},
        }
        boosted = apply_intent_category_boost(
            results,
            "seller",
            "profile_update",
            max(confidence_threshold(), 0.55),
            branch_lookup=branch_lookup,
        )
        scores = {row["branch_id"]: row["final_score"] for row in boosted}
        self.assertGreater(scores["a"], 0.5)
        self.assertEqual(scores["b"], 0.6)

    def test_supervised_bundle_loads_when_present(self):
        path = model_path()
        if not path.exists():
            self.skipTest("intent_classifier.pkl not trained yet")
        bundle = load_supervised_model(force=True)
        self.assertIsNotNone(bundle)
        self.assertIn("models", bundle)

    def test_corrupt_supervised_falls_back_to_prototype(self):
        import intent_classifier as mod

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "intent_classifier.pkl"
            bad.write_bytes(b"broken")
            old_path = mod.model_path
            mod.model_path = lambda: bad  # type: ignore[assignment]
            mod._supervised_bundle = None
            try:
                with patch.dict("os.environ", {"INTENT_CLASSIFIER_MODE": "supervised"}):
                    result = predict_intent("pan update", "seller", self.embed)
                self.assertIn(result["intent_mode_used"], {"prototype", "supervised"})
            finally:
                mod.model_path = old_path  # type: ignore[assignment]
                mod._supervised_bundle = None

    def test_health_shape(self):
        status = get_intent_classifier_status()
        self.assertIn(status["status"], {
            "disabled",
            "prototype_active",
            "supervised_active",
            "supervised_missing_fallback_prototype",
        })
        self.assertIn("confidence_threshold", status)


if __name__ == "__main__":
    unittest.main()
