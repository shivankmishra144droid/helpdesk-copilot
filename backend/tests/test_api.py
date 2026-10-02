"""HTTP-level tests: request guard and error status codes."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from request_guard import install_request_guard  # noqa: E402

CLIENT = {"X-Copilot-Client": "test"}


def _guarded_app() -> FastAPI:
    app = FastAPI()
    install_request_guard(app)

    @app.get("/thing")
    def read_thing():
        return {"ok": True}

    @app.post("/thing")
    def write_thing():
        return {"ok": True}

    return app


class TestRequestGuard(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_guarded_app())

    def test_reads_need_no_header(self):
        self.assertEqual(self.client.get("/thing").status_code, 200)

    def test_writes_without_header_are_rejected(self):
        self.assertEqual(self.client.post("/thing").status_code, 403)
        # A plain multipart form (what a hostile page can send cross-site) is refused too.
        self.assertEqual(
            self.client.post("/thing", files={"file": ("x.txt", b"hi")}).status_code, 403
        )

    def test_writes_with_header_pass(self):
        self.assertEqual(self.client.post("/thing", headers=CLIENT).status_code, 200)

    def test_token_enforced_when_configured(self):
        with patch.dict(os.environ, {"COPILOT_API_TOKEN": "s3cret"}):
            self.assertEqual(self.client.post("/thing", headers=CLIENT).status_code, 401)
            ok = self.client.post("/thing", headers={**CLIENT, "X-API-Token": "s3cret"})
            self.assertEqual(ok.status_code, 200)


class TestDemoMode(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        install_request_guard(app)

        @app.post("/ingest/text")
        def ingest():
            return {"ok": True}

        @app.post("/supervisor/approve")
        def approve():
            return {"ok": True}

        @app.delete("/supervisor/categories/{category_id}")
        def delete_category(category_id: str):
            return {"ok": True}

        self.client = TestClient(app)

    def test_off_by_default(self):
        with patch.dict(os.environ, {"DEMO_MODE": ""}):
            self.assertEqual(self.client.post("/ingest/text", headers=CLIENT).status_code, 200)

    def test_blocks_uploads_and_destructive_actions(self):
        with patch.dict(os.environ, {"DEMO_MODE": "true"}):
            self.assertEqual(self.client.post("/ingest/text", headers=CLIENT).status_code, 403)
            self.assertEqual(self.client.delete("/supervisor/categories/x", headers=CLIENT).status_code, 403)

    def test_review_flow_still_allowed(self):
        with patch.dict(os.environ, {"DEMO_MODE": "true"}):
            self.assertEqual(self.client.post("/supervisor/approve", headers=CLIENT).status_code, 200)


class TestMainApi(unittest.TestCase):
    """Uses the real app without its lifespan (no inbox watcher / startup ingest)."""

    @classmethod
    def setUpClass(cls):
        import main

        cls.client = TestClient(main.app)

    def test_cors_preflight_allowed_for_frontend(self):
        response = self.client.options(
            "/select-branch",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-copilot-client",
            },
        )
        self.assertEqual(response.status_code, 200)

    def test_select_branch_requires_client_header(self):
        response = self.client.post("/select-branch", json={"branch_id": "x"})
        self.assertEqual(response.status_code, 403)

    def test_unknown_branch_is_404(self):
        response = self.client.post(
            "/select-branch",
            json={"branch_id": "definitely-not-a-branch", "caller_type": "seller"},
            headers=CLIENT,
        )
        self.assertEqual(response.status_code, 404)

    def test_verify_unknown_branch_is_404(self):
        response = self.client.post(
            "/verify-step",
            json={"branch_id": "nope", "step_index": 0, "status": "done"},
            headers=CLIENT,
        )
        self.assertEqual(response.status_code, 404)

    def test_search_config_exposes_synonyms_and_thresholds(self):
        data = self.client.get("/search/config", params={"caller_type": "seller"}).json()
        self.assertTrue(data["synonym_groups"])
        self.assertLess(data["min_match_score"], data["weak_match_score"])

    def test_empty_ingest_text_is_400(self):
        response = self.client.post("/ingest/text", json={"text": "  "}, headers=CLIENT)
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
