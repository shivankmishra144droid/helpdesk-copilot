"""Append-only local search telemetry for drift monitoring (prototype)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(__file__).resolve().parent.parent / ".runtime"
TELEMETRY_DIR = RUNTIME_DIR / "telemetry"
SEARCH_LOG = TELEMETRY_DIR / "search_log.jsonl"


def _enabled() -> bool:
    raw = os.environ.get("SEARCH_TELEMETRY_ENABLED", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def log_search_event(payload: dict[str, Any]) -> None:
    """Append one JSON line per search. Never raises to caller."""
    if not _enabled():
        return
    try:
        TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        with SEARCH_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def summarize_recent(*, max_lines: int = 5000) -> dict[str, Any]:
    """Lightweight weekly-style summary from local log file."""
    if not SEARCH_LOG.exists():
        return {"status": "no_data", "path": str(SEARCH_LOG)}

    lines = SEARCH_LOG.read_text(encoding="utf-8", errors="ignore").splitlines()
    rows = []
    for line in lines[-max_lines:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not rows:
        return {"status": "empty", "path": str(SEARCH_LOG)}

    scores = [float(r["top_score"]) for r in rows if r.get("top_score") is not None]
    outliers = sum(1 for r in rows if r.get("is_outlier"))
    escalated = sum(1 for r in rows if r.get("escalated"))
    corrected = sum(1 for r in rows if r.get("correction_applied"))
    low_conf = sum(
        1 for r in rows if (r.get("intent_confidence") or 0) < 0.55 and r.get("predicted_category")
    )

    return {
        "status": "ok",
        "path": str(SEARCH_LOG),
        "events": len(rows),
        "avg_top_score": round(sum(scores) / len(scores), 4) if scores else None,
        "outlier_rate_pct": round(100.0 * outliers / len(rows), 2),
        "escalation_rate_pct": round(100.0 * escalated / len(rows), 2),
        "correction_rate_pct": round(100.0 * corrected / len(rows), 2),
        "low_intent_confidence_rate_pct": round(100.0 * low_conf / len(rows), 2),
    }
