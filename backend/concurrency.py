"""Process-wide locks shared by request threads and the inbox watcher.

STORE_LOCK guards every load-modify-save of the JSON stores (KB, queue, metadata,
categories). It is re-entrant so composite operations (approve -> merge into KB ->
set metadata) can hold it end to end. Never hold it across an LLM call.

MODEL_LOCK serialises calls into HuggingFace models: their fast tokenizers raise
"Already borrowed" when used from several threads at once. Always acquire it
innermost (after STORE_LOCK, never the other way round).
"""

from __future__ import annotations

import functools
import threading
from typing import Any

STORE_LOCK = threading.RLock()
MODEL_LOCK = threading.RLock()


def guard_model_method(model: Any, method_name: str) -> Any:
    """Wrap ``model.<method_name>`` so every call runs under MODEL_LOCK. Idempotent."""
    original = getattr(model, method_name)
    if getattr(original, "_model_lock_guarded", False):
        return model

    @functools.wraps(original)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        with MODEL_LOCK:
            return original(*args, **kwargs)

    guarded._model_lock_guarded = True  # type: ignore[attr-defined]
    setattr(model, method_name, guarded)
    return model
