"""Provider selection for AI drafting (no network calls)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import llm_provider  # noqa: E402

CLEAN_ENV = {"LLM_PROVIDER": "", "ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": "", "OPENAI_MODEL": ""}


class TestProviderSelection(unittest.TestCase):
    def _env(self, **values):
        return patch.dict("os.environ", {**CLEAN_ENV, **values})

    def test_auto_prefers_anthropic_key(self):
        with self._env(ANTHROPIC_API_KEY="k", OPENAI_API_KEY="k"):
            self.assertEqual(llm_provider.provider_name(), "anthropic")
            self.assertEqual(llm_provider.model_name(), llm_provider.ANTHROPIC_DEFAULT_MODEL)

    def test_auto_uses_openai_when_only_openai_key(self):
        with self._env(OPENAI_API_KEY="k", OPENAI_MODEL="some-model"):
            self.assertEqual(llm_provider.provider_name(), "openai")
            self.assertEqual(llm_provider.model_name(), "some-model")

    def test_auto_falls_back_to_none_without_keys_or_ollama(self):
        with self._env(), patch.object(llm_provider, "_ollama_reachable", return_value=False):
            self.assertEqual(llm_provider.provider_name(), "none")
            self.assertFalse(llm_provider.is_available())
            self.assertFalse(llm_provider.status()["available"])

    def test_openai_requires_model_name(self):
        with self._env(LLM_PROVIDER="openai", OPENAI_API_KEY="k"):
            self.assertIn("OPENAI_MODEL", llm_provider.status()["detail"])

    def test_complete_raises_when_unavailable(self):
        with self._env(LLM_PROVIDER="none"):
            with self.assertRaises(llm_provider.LLMUnavailableError):
                llm_provider.complete("hi")

    def test_explicit_provider_wins(self):
        with self._env(LLM_PROVIDER="ollama", ANTHROPIC_API_KEY="k"):
            self.assertEqual(llm_provider.provider_name(), "ollama")


if __name__ == "__main__":
    unittest.main()
