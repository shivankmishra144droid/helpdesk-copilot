"""Exercise the Claude and OpenAI paths end to end against a local stub server.

The real SDKs send real HTTP requests; the stub records them and returns canned
responses, so these tests check request shape and response handling offline.
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import llm_provider  # noqa: E402

DRAFT_JSON = json.dumps(
    {
        "issue_name": "Courier missed pickup",
        "category": "shipping_logistics",
        "problem_statement": "The courier did not arrive.",
        "policy": "Rebook missed pickups the same day.",
        "resolution_steps": ["Check status", "Rebook pickup", "Confirm slot"],
        "required_documents": ["Order number"],
        "l1_team": "Logistics Partner Desk",
        "l1_person": "Shipment Exceptions Analyst",
    }
)


class _Stub(BaseHTTPRequestHandler):
    requests: list[dict] = []
    anthropic_reply: dict = {}
    openai_reply: dict = {}

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        type(self).requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        reply = self.openai_reply if "chat/completions" in self.path else self.anthropic_reply
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def _anthropic_message(content, stop_reason="end_turn", stop_details=None):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "stop_details": stop_details,
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }


class TestProvidersOverHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        _Stub.requests = []

    def _anthropic_env(self):
        return patch.dict(
            "os.environ",
            {
                "LLM_PROVIDER": "anthropic",
                "ANTHROPIC_API_KEY": "test-key",
                "ANTHROPIC_BASE_URL": self.base,
                "ANTHROPIC_AUTH_TOKEN": "",
                "ANTHROPIC_MODEL": "",
                "ANTHROPIC_EFFORT": "",
            },
        )

    def test_claude_request_shape_and_text(self):
        _Stub.anthropic_reply = _anthropic_message(
            [
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "text", "text": DRAFT_JSON},
            ]
        )
        with self._anthropic_env():
            text = llm_provider.complete("draft this", system="sys", max_tokens=500)
        self.assertEqual(json.loads(text)["issue_name"], "Courier missed pickup")

        request = _Stub.requests[-1]
        body = request["body"]
        headers = {k.lower(): v for k, v in request["headers"].items()}
        self.assertEqual(body["model"], "claude-opus-5-5")
        self.assertEqual(body["fallbacks"], "default")
        self.assertEqual(body["output_config"], {"effort": "medium"})
        self.assertGreaterEqual(body["max_tokens"], 16000)
        self.assertEqual(body["system"], "sys")
        self.assertIn("server-side-fallback-2026-07-01", headers.get("anthropic-beta", ""))
        self.assertEqual(headers.get("x-api-key"), "test-key")

    def test_claude_refusal_raises(self):
        _Stub.anthropic_reply = _anthropic_message(
            [], stop_reason="refusal", stop_details={"type": "refusal", "category": None, "explanation": "declined"}
        )
        with self._anthropic_env():
            with self.assertRaises(llm_provider.LLMRefusalError):
                llm_provider.complete("draft this")

    def test_drafter_falls_back_to_template_on_refusal(self):
        import llm_drafter

        _Stub.anthropic_reply = _anthropic_message(
            [], stop_reason="refusal", stop_details={"type": "refusal", "category": None, "explanation": "declined"}
        )
        with self._anthropic_env(), patch.object(
            llm_drafter, "_rank_unified_examples", return_value=[]
        ), patch.object(llm_drafter, "load_unified_kb", return_value=[]):
            result = llm_drafter.draft_resolution("courier never came for pickup", "seller")
        self.assertIn("AI drafting unavailable", result.get("error", ""))
        self.assertEqual(result["draft_source"], "fallback")

    def test_openai_request_shape_and_text(self):
        _Stub.openai_reply = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": DRAFT_JSON}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        env = {
            "LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "test-model",
            "OPENAI_BASE_URL": f"{self.base}/v1",
        }
        with patch.dict("os.environ", env):
            text = llm_provider.complete("draft this", system="sys", max_tokens=700)
        self.assertIn("Courier missed pickup", text)
        body = _Stub.requests[-1]["body"]
        self.assertEqual(body["model"], "test-model")
        self.assertEqual(body["max_completion_tokens"], 700)
        self.assertEqual(body["messages"][0], {"role": "system", "content": "sys"})


if __name__ == "__main__":
    unittest.main()
