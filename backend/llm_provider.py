"""One text-completion entry point for every LLM feature, whichever provider is configured.

LLM_PROVIDER selects the backend:
    anthropic  Claude via the official Anthropic SDK (ANTHROPIC_API_KEY)
    openai     OpenAI via the official OpenAI SDK (OPENAI_API_KEY + OPENAI_MODEL)
    ollama     a local Ollama server (OLLAMA_URL, OLLAMA_MODEL)
    none       LLM features off; the app falls back to KB-template drafts
    auto       (default) anthropic if ANTHROPIC_API_KEY is set, else openai if
               OPENAI_API_KEY is set, else ollama if it answers, else none

Keys are read from the environment only; nothing is stored in code or data files.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

PROVIDERS = ("anthropic", "openai", "ollama", "none")

ANTHROPIC_DEFAULT_MODEL = "claude-opus-5-5"
OLLAMA_DEFAULT_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "llama3.2:3b"


class LLMUnavailableError(RuntimeError):
    """No provider is configured or reachable."""


class LLMRefusalError(RuntimeError):
    """The model declined the request."""


def _env(name: str, default: str = "") -> str:
    # Empty counts as unset: Docker's env_file passes `KEY=` through as "".
    return os.environ.get(name, "").strip() or default


def _ollama_url() -> str:
    return _env("OLLAMA_URL", OLLAMA_DEFAULT_URL).rstrip("/")


def _ollama_reachable(timeout: float = 2.0) -> bool:
    try:
        request = urllib.request.Request(f"{_ollama_url()}/api/tags", method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def provider_name() -> str:
    """The provider requests will use right now."""
    configured = _env("LLM_PROVIDER", "auto").lower()
    if configured in PROVIDERS:
        return configured
    if configured != "auto":
        logger.warning("Unknown LLM_PROVIDER=%r; using auto-detection", configured)
    if _env("ANTHROPIC_API_KEY"):
        return "anthropic"
    if _env("OPENAI_API_KEY"):
        return "openai"
    if _ollama_reachable():
        return "ollama"
    return "none"


def model_name(provider: str | None = None) -> str:
    provider = provider or provider_name()
    if provider == "anthropic":
        return _env("ANTHROPIC_MODEL", ANTHROPIC_DEFAULT_MODEL)
    if provider == "openai":
        return _env("OPENAI_MODEL")
    if provider == "ollama":
        return _env("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)
    return ""


def _unavailable_reason(provider: str) -> str | None:
    if provider == "none":
        return "No LLM provider configured. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or run Ollama."
    if provider == "anthropic":
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return "The 'anthropic' package is not installed."
    if provider == "openai":
        try:
            import openai  # noqa: F401
        except ImportError:
            return "The 'openai' package is not installed."
        if not _env("OPENAI_MODEL"):
            return "Set OPENAI_MODEL to the OpenAI model you want to use."
    if provider == "ollama" and not _ollama_reachable():
        return f"Ollama is not reachable at {_ollama_url()}."
    return None


def is_available() -> bool:
    return _unavailable_reason(provider_name()) is None


def status() -> dict[str, Any]:
    provider = provider_name()
    reason = _unavailable_reason(provider)
    return {
        "provider": provider,
        "model": model_name(provider),
        "available": reason is None,
        "detail": reason,
    }


def setup_instructions() -> str:
    return (
        "AI drafting is off. To enable it, set one of these before starting the backend:\n"
        "- ANTHROPIC_API_KEY (Claude; optional ANTHROPIC_MODEL)\n"
        "- OPENAI_API_KEY and OPENAI_MODEL\n"
        "- or run Ollama locally (OLLAMA_URL, OLLAMA_MODEL)\n"
        "See .env.example."
    )


def _complete_anthropic(prompt: str, system: str, max_tokens: int, timeout: float) -> str:
    import anthropic

    client = anthropic.Anthropic(timeout=timeout)
    # Server-side fallbacks re-run a safety-classifier decline on Anthropic's
    # recommended fallback model instead of returning a refusal.
    response = client.beta.messages.create(
        model=model_name("anthropic"),
        # Thinking is always on for this model and shares the budget, so keep headroom.
        max_tokens=max(max_tokens, 16000),
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": _env("ANTHROPIC_EFFORT", "medium")},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None) if response.stop_details else None
        raise LLMRefusalError(f"Claude declined the request (category: {category})")
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise RuntimeError(f"Claude returned no text (stop_reason={response.stop_reason})")
    return text


def _complete_openai(prompt: str, system: str, max_tokens: int, timeout: float) -> str:
    import openai

    client = openai.OpenAI(timeout=timeout)
    response = client.chat.completions.create(
        model=model_name("openai"),
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise RuntimeError("OpenAI returned an empty response")
    return text


def _complete_ollama(prompt: str, system: str, max_tokens: int, timeout: float) -> str:
    payload = {
        "model": model_name("ollama"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 4096, "num_predict": max_tokens},
    }
    request = urllib.request.Request(
        f"{_ollama_url()}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    text = str(body.get("message", {}).get("content", "")).strip()
    if not text:
        raise RuntimeError("Ollama returned an empty response")
    return text


_BACKENDS = {
    "anthropic": _complete_anthropic,
    "openai": _complete_openai,
    "ollama": _complete_ollama,
}


def complete(
    prompt: str,
    *,
    system: str = "You are a helpful support-operations assistant.",
    max_tokens: int = 4000,
    timeout: float = 120.0,
) -> str:
    """Return the model's text reply. Raises LLMUnavailableError if no provider works."""
    provider = provider_name()
    reason = _unavailable_reason(provider)
    if reason:
        raise LLMUnavailableError(reason)
    return _BACKENDS[provider](prompt, system, max_tokens, timeout)
