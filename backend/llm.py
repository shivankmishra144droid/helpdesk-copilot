"""LLM availability for the health endpoint and supervisor UI."""

from __future__ import annotations

from typing import Any

import llm_provider


def check_llm_available() -> bool:
    return llm_provider.is_available()


def get_llm_status() -> dict[str, Any]:
    return llm_provider.status()
