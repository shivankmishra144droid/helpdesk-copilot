"""Tests for pickled-bundle loading and version-skew reporting."""

from __future__ import annotations

import pickle
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import model_io  # noqa: E402


class TestModelIO(unittest.TestCase):
    def setUp(self):
        model_io._issues.clear()
        self.tmp = Path(tempfile.mkdtemp())

    def test_round_trip_stamps_versions_and_reports_ok(self):
        path = self.tmp / "ok.pkl"
        model_io.save_bundle(path, {"models": {}})
        bundle = model_io.load_bundle(path)
        self.assertEqual(bundle["library_versions"], model_io.library_versions())
        self.assertEqual(model_io.model_file_report()["status"], "ok")

    def test_mismatched_versions_are_reported(self):
        path = self.tmp / "old.pkl"
        with path.open("wb") as handle:
            pickle.dump({"models": {}, "library_versions": {"scikit-learn": "0.0.1"}}, handle)
        self.assertIsNotNone(model_io.load_bundle(path))
        issue = model_io.model_file_report()["issues"]["old.pkl"]
        self.assertEqual(issue["status"], "version_mismatch")
        self.assertIn("scikit-learn", issue["warnings"][0])

    def test_unstamped_bundle_is_not_a_mismatch(self):
        path = self.tmp / "legacy.pkl"
        with path.open("wb") as handle:
            pickle.dump({"models": {}}, handle)
        model_io.load_bundle(path)
        self.assertEqual(model_io.model_file_report()["status"], "ok")

    def test_corrupt_file_reports_load_failure(self):
        path = self.tmp / "bad.pkl"
        path.write_bytes(b"not a pickle")
        self.assertIsNone(model_io.load_bundle(path))
        self.assertEqual(
            model_io.model_file_report()["issues"]["bad.pkl"]["status"], "load_failed"
        )


if __name__ == "__main__":
    unittest.main()
