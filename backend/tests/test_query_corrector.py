"""Tests for query normalization and correction."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from query_corrector import (  # noqa: E402
    correct_query,
    get_query_corrector_status,
    normalize_query_text,
)
import domain_vocabulary as vocab_mod  # noqa: E402


class TestQueryCorrector(unittest.TestCase):
    def test_unicode_and_whitespace_normalization(self):
        self.assertEqual(
            normalize_query_text("  Tax\u00a0Validation  "),
            "tax validation",
        )

    def test_protected_email_preserved(self):
        result = correct_query("help with email buyer@example.org")
        self.assertIn("buyer@example.org", result["corrected_query"])

    def test_protected_order_number_preserved(self):
        result = correct_query("status for order nw-12345678")
        self.assertIn("nw-12345678", result["corrected_query"].lower())

    def test_abbreviation_expansion(self):
        with patch.dict("os.environ", {"QUERY_CORRECTION_MODE": "dictionary"}):
            result = correct_query("rfq not published")
        self.assertIn("request for quotation", result["corrected_query"])

    def test_low_confidence_does_not_apply_correction(self):
        vocab = {
            "version": 1,
            "terms": ["registration"],
            "phrases": [],
            "source_counts": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            vocab_path = Path(tmp) / "domain_vocabulary.json"
            vocab_path.write_text(json.dumps(vocab), encoding="utf-8")
            old_path = vocab_mod.VOCAB_PATH
            vocab_mod.VOCAB_PATH = vocab_path
            vocab_mod._vocab_cache = None
            vocab_mod._abbrev_cache = None
            try:
                with patch.dict(
                    "os.environ",
                    {
                        "QUERY_CORRECTION_MODE": "symspell",
                        "QUERY_CORRECTION_MIN_CONFIDENCE": "0.99",
                    },
                ):
                    import query_corrector as qc_mod

                    qc_mod._vocab_terms = None
                    result = correct_query("registraton problem")
                self.assertFalse(result["correction_applied"])
            finally:
                vocab_mod.VOCAB_PATH = old_path
                vocab_mod._vocab_cache = None

    def test_spell_tie_break_is_deterministic(self):
        import query_corrector as qc_mod

        old = qc_mod._vocab_terms
        try:
            # Both candidates score the same; the result must not depend on set order.
            for vocab in ({"abcdefgz", "abcdefgy"}, {"abcdefgy", "abcdefgz"}):
                qc_mod._vocab_terms = set(vocab)
                word, _ = qc_mod._spell_correct_word("abcdefgx")
                self.assertEqual(word, "abcdefgy")
        finally:
            qc_mod._vocab_terms = old

    def test_common_english_words_are_not_corrected(self):
        for query in ("unable to login", "problem with process", "not able to upload"):
            self.assertEqual(correct_query(query)["corrected_query"], query)

    def test_disabled_mode_returns_normalized_only(self):
        with patch.dict("os.environ", {"QUERY_CORRECTION_MODE": "disabled"}):
            result = correct_query("  KYC issue  ")
        self.assertEqual(result["normalized_query"], "kyc issue")
        self.assertFalse(result["correction_applied"])

    def test_health_shape(self):
        status = get_query_corrector_status()
        self.assertIn("enabled", status)
        self.assertIn("mode", status)
        self.assertIn("vocabulary", status)


if __name__ == "__main__":
    unittest.main()
