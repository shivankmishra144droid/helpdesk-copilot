"""Load/save pickled model bundles and surface library-version skew.

Pickled sklearn/xgboost models can break or silently change behaviour when the
installed library differs from the one used for training. Every loader goes
through ``load_bundle`` so mismatches and load failures show up in /health
instead of search quietly falling back to the hybrid formula.
"""

from __future__ import annotations

import logging
import pickle
import warnings
from importlib import metadata
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TRACKED_LIBRARIES = ("scikit-learn", "xgboost", "numpy", "sentence-transformers")

_issues: dict[str, dict[str, Any]] = {}


def library_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in TRACKED_LIBRARIES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def save_bundle(path: Path, bundle: dict[str, Any]) -> None:
    """Pickle a bundle, stamping it with the library versions used to train it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = {**bundle, "library_versions": library_versions()}
    with path.open("wb") as handle:
        pickle.dump(stamped, handle)


def _version_mismatches(bundle: Any) -> list[str]:
    if not isinstance(bundle, dict):
        return []
    recorded = bundle.get("library_versions")
    if not isinstance(recorded, dict):
        return []  # older bundle: versions unknown, not a mismatch
    current = library_versions()
    return [
        f"{name}: trained with {recorded[name]}, installed {current.get(name)}"
        for name in TRACKED_LIBRARIES
        if recorded.get(name) and recorded[name] != current.get(name)
    ]


def load_bundle(path: Path) -> Any | None:
    """Unpickle ``path``; record version warnings / failures for /health."""
    key = path.name
    _issues.pop(key, None)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with path.open("rb") as handle:
                bundle = pickle.load(handle)
    except Exception as exc:
        logger.warning("Failed to load model bundle %s: %s", path, exc)
        _issues[key] = {"status": "load_failed", "error": str(exc)}
        return None

    messages = _version_mismatches(bundle) + [
        str(item.message)
        for item in caught
        if "version" in str(item.message).lower()
        and not issubclass(item.category, ResourceWarning)
    ]
    if messages:
        logger.warning("Model bundle %s has version skew: %s", path.name, messages)
        _issues[key] = {"status": "version_mismatch", "warnings": messages}
    return bundle


def model_file_report() -> dict[str, Any]:
    return {
        "status": "warnings" if _issues else "ok",
        "installed": library_versions(),
        "issues": dict(_issues),
    }
