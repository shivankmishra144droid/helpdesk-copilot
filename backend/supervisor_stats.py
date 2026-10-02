"""Supervisor analytics — aggregate stats from JSON queue, audit log, and KB files."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from category_utils import category_name_by_id
from topic_clustering import compute_topic_clusters

KNOWLEDGE_ROOT = Path(__file__).parent / "knowledge"
PENDING_QUEUE_PATH = KNOWLEDGE_ROOT / "pending_queue.json"
AUDIT_LOG_PATH = KNOWLEDGE_ROOT / "audit_log.jsonl"
SELLER_KB_PATH = KNOWLEDGE_ROOT / "seller" / "unified_knowledge.json"
BUYER_KB_PATH = KNOWLEDGE_ROOT / "buyer" / "unified_knowledge.json"

STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_REJECTED = "rejected"

APPROVE_ACTIONS = frozenset(
    {
        "approve",
        "approved",
        "approve_and_add",
        "approved_and_added",
        "approved_send_only",
        "added_to_kb",
        "kb_add",
    }
)
REJECT_ACTIONS = frozenset({"reject", "rejected"})
SUBMIT_ACTIONS = frozenset({"queued_by_agent", "parsed_from_manual"})

TREND_DAYS = 14
TOP_CATEGORIES = 8
TOP_QUERIES = 8


def _parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _date_key(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.date().isoformat()


def load_pending_queue() -> list[dict[str, Any]]:
    if not PENDING_QUEUE_PATH.exists():
        return []
    try:
        with PENDING_QUEUE_PATH.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return []
    issues = payload.get("issues", [])
    return [item for item in issues if isinstance(item, dict)]


def load_audit_log() -> list[dict[str, Any]]:
    if not AUDIT_LOG_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with AUDIT_LOG_PATH.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows


def _count_kb_branches(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return 0
    branches = payload.get("branches", [])
    if isinstance(branches, list):
        return len(branches)
    return 0


def count_kb_entries() -> dict[str, int]:
    seller = _count_kb_branches(SELLER_KB_PATH)
    buyer = _count_kb_branches(BUYER_KB_PATH)
    return {
        "seller_kb_count": seller,
        "buyer_kb_count": buyer,
        "kb_total_issues": seller + buyer,
    }


def _issue_key(issue: dict[str, Any]) -> str:
    issue_id = issue.get("id")
    if issue_id is not None:
        return f"id:{issue_id}"
    pending_id = issue.get("pending_id")
    if pending_id:
        return f"pending:{pending_id}"
    name = str(issue.get("issue_name", "")).strip().lower()
    created = str(issue.get("created_at", "")).strip()
    category = str(issue.get("category_id", "")).strip()
    return f"fallback:{name}|{created}|{category}"


def _normalize_category(issue: dict[str, Any]) -> str:
    caller_type = str(issue.get("caller_type", "seller"))
    raw = (
        issue.get("category_id")
        or issue.get("category")
        or issue.get("crm_category")
        or issue.get("issue_category")
        or issue.get("type")
        or ""
    )
    raw = str(raw).strip()
    if not raw:
        return "Uncategorized"
    display = category_name_by_id(caller_type, raw)
    return display or raw.replace("_", " ").title()


def _resolve_status(issue: dict[str, Any], audit_by_issue: dict[int, list[dict]]) -> str:
    status = str(issue.get("status", "")).lower().strip()
    if status == STATUS_ACTIVE:
        return "Approved"
    if status == STATUS_REJECTED:
        return "Rejected"
    if status == STATUS_PENDING:
        return "Pending"

    issue_id = issue.get("id")
    if isinstance(issue_id, int):
        for row in reversed(audit_by_issue.get(issue_id, [])):
            action = str(row.get("action", "")).lower()
            if action in REJECT_ACTIONS or "reject" in action:
                return "Rejected"
            if action in APPROVE_ACTIONS or "approv" in action:
                return "Approved"
    return "Pending"


def _issue_query_text(issue: dict[str, Any]) -> str:
    return str(
        issue.get("problem_statement")
        or issue.get("issue_name")
        or issue.get("query")
        or ""
    ).strip()


def calculate_status_breakdown(issues: list[dict[str, Any]], audit: list[dict]) -> list[dict]:
    audit_by_issue: dict[int, list[dict]] = defaultdict(list)
    for row in audit:
        iid = row.get("issue_id")
        if isinstance(iid, int):
            audit_by_issue[iid].append(row)

    counts = Counter(
        _resolve_status(issue, audit_by_issue) for issue in issues
    )
    order = ["Pending", "Approved", "Rejected"]
    return [{"status": name, "count": counts.get(name, 0)} for name in order if counts.get(name, 0)]


def calculate_daily_trend(issues: list[dict[str, Any]], audit: list[dict]) -> list[dict]:
    by_date: dict[str, dict[str, int]] = defaultdict(
        lambda: {"submitted": 0, "approved": 0, "rejected": 0, "pending": 0}
    )

    submit_by_issue: dict[int, str] = {}
    for issue in issues:
        iid = issue.get("id")
        day = _date_key(_parse_ts(issue.get("created_at")))
        if isinstance(iid, int) and day:
            submit_by_issue[iid] = day
            by_date[day]["submitted"] += 1

    for row in audit:
        action = str(row.get("action", "")).lower()
        day = _date_key(_parse_ts(row.get("timestamp")))
        if not day:
            continue
        iid = row.get("issue_id")
        if action in SUBMIT_ACTIONS and isinstance(iid, int) and iid not in submit_by_issue:
            submit_by_issue[iid] = day
            by_date[day]["submitted"] += 1
        elif action in APPROVE_ACTIONS or "approv" in action:
            by_date[day]["approved"] += 1
        elif action in REJECT_ACTIONS or "reject" in action:
            by_date[day]["rejected"] += 1

    for day, bucket in by_date.items():
        bucket["pending"] = max(
            0, bucket["submitted"] - bucket["approved"] - bucket["rejected"]
        )

    if not by_date:
        return []

    sorted_days = sorted(by_date.keys())[-TREND_DAYS:]
    return [{"date": day, **by_date[day]} for day in sorted_days]


def calculate_category_counts(issues: list[dict[str, Any]]) -> list[dict]:
    counts = Counter(_normalize_category(issue) for issue in issues)
    ranked = counts.most_common(TOP_CATEGORIES)
    return [{"category": name, "count": count} for name, count in ranked]


def calculate_kb_growth(audit: list[dict], kb_total: int) -> list[dict]:
    adds_by_date: Counter[str] = Counter()
    for row in audit:
        action = str(row.get("action", "")).lower()
        is_add = action in {
            "approved_and_added",
            "added_to_kb",
            "approve_and_add",
        } or ("approv" in action and "add" in action)
        if not is_add:
            continue
        day = _date_key(_parse_ts(row.get("timestamp")))
        if day:
            adds_by_date[day] += 1

    if not adds_by_date:
        today = datetime.now(timezone.utc).date().isoformat()
        return [{"date": today, "kb_size": kb_total, "added": 0}]

    sorted_days = sorted(adds_by_date.keys())[-TREND_DAYS:]
    total_added = sum(adds_by_date[day] for day in sorted_days)
    running = max(0, kb_total - total_added)
    growth: list[dict] = []
    for day in sorted_days:
        added = adds_by_date[day]
        running += added
        growth.append({"date": day, "kb_size": running, "added": added})
    return growth


def calculate_resolution_funnel(summary: dict[str, Any]) -> list[dict]:
    return [
        {"stage": "Submitted", "count": summary["total_submitted"]},
        {"stage": "Reviewed", "count": summary["reviewed"]},
        {"stage": "Approved", "count": summary["approved"]},
        {"stage": "Added to KB", "count": summary["added_to_kb"]},
    ]


def calculate_topic_cluster_counts(issues: list[dict[str, Any]]) -> list[dict]:
    pending = [issue for issue in issues if str(issue.get("status", "")).lower() == STATUS_PENDING]
    if not pending:
        return []
    clustering = compute_topic_clusters(pending)
    return [
        {
            "cluster_id": cluster["cluster_id"],
            "topic_label": cluster["topic_label"],
            "count": cluster["count"],
        }
        for cluster in clustering.get("clusters", [])
    ]


def calculate_top_repeated_queries(issues: list[dict[str, Any]]) -> list[dict]:
    bucket: dict[str, dict[str, Any]] = {}
    for issue in issues:
        query = _issue_query_text(issue)
        if not query:
            continue
        key = query.lower()
        if key not in bucket:
            bucket[key] = {
                "query": query,
                "count": 0,
                "category": _normalize_category(issue),
            }
        bucket[key]["count"] += 1
    ranked = sorted(bucket.values(), key=lambda item: item["count"], reverse=True)
    return ranked[:TOP_QUERIES]


def _avg_review_time_minutes(issues: list[dict[str, Any]], audit: list[dict]) -> float | None:
    audit_by_issue: dict[int, list[dict]] = defaultdict(list)
    for row in audit:
        iid = row.get("issue_id")
        if isinstance(iid, int):
            audit_by_issue[iid].append(row)

    deltas: list[float] = []
    for issue in issues:
        iid = issue.get("id")
        if not isinstance(iid, int):
            continue
        submitted = _parse_ts(issue.get("created_at"))
        if submitted is None:
            for row in audit_by_issue.get(iid, []):
                if str(row.get("action", "")).lower() in SUBMIT_ACTIONS:
                    submitted = _parse_ts(row.get("timestamp"))
                    break
        reviewed: datetime | None = None
        for row in reversed(audit_by_issue.get(iid, [])):
            action = str(row.get("action", "")).lower()
            if action in APPROVE_ACTIONS or action in REJECT_ACTIONS or "approv" in action or "reject" in action:
                reviewed = _parse_ts(row.get("timestamp"))
                break
        if submitted and reviewed and reviewed >= submitted:
            deltas.append((reviewed - submitted).total_seconds() / 60.0)

    if not deltas:
        return None
    return round(sum(deltas) / len(deltas), 1)


def generate_insights(
    summary: dict[str, Any],
    category_counts: list[dict[str, Any]],
) -> list[str]:
    insights: list[str] = []
    total = summary.get("total_submitted", 0)
    if total == 0:
        return [
            "No supervisor analytics yet — submit issues from the agent UI to populate this dashboard.",
        ]

    if category_counts:
        top = category_counts[0]
        pct = round(100 * top["count"] / max(total, 1), 1)
        insights.append(
            f"{top['category']} issues form {pct}% of submitted queries."
        )

    reviewed = summary.get("reviewed", 0)
    if reviewed > 0:
        insights.append(
            f"Approval rate is {summary.get('approval_rate', 0)}% across reviewed issues."
        )
        insights.append(
            f"Rejection rate is {summary.get('rejection_rate', 0)}% across reviewed issues."
        )

    added = summary.get("added_to_kb", 0)
    if added:
        insights.append(
            f"{added} submitted issue{'s' if added != 1 else ''} were converted into reusable KB entries."
        )

    kb_total = summary.get("kb_total_issues", 0)
    if kb_total:
        insights.append(
            f"The knowledge base currently contains {kb_total} approved branches across seller and buyer."
        )

    pending = summary.get("pending", 0)
    if pending:
        insights.append(
            f"{pending} issue{'s' if pending != 1 else ''} still waiting for supervisor review."
        )

    return insights[:6]


def build_supervisor_stats() -> dict[str, Any]:
    issues = load_pending_queue()
    audit = load_audit_log()
    kb_counts = count_kb_entries()

    audit_by_issue: dict[int, list[dict]] = defaultdict(list)
    for row in audit:
        iid = row.get("issue_id")
        if isinstance(iid, int):
            audit_by_issue[iid].append(row)

    status_map: dict[str, str] = {}
    for issue in issues:
        status_map[_issue_key(issue)] = _resolve_status(issue, audit_by_issue)

    pending = sum(1 for s in status_map.values() if s == "Pending")
    approved = sum(1 for s in status_map.values() if s == "Approved")
    rejected = sum(1 for s in status_map.values() if s == "Rejected")
    total_submitted = len(status_map)
    reviewed = approved + rejected
    added_to_kb = approved

    approval_rate = round(100 * approved / reviewed, 1) if reviewed else 0.0
    rejection_rate = round(100 * rejected / reviewed, 1) if reviewed else 0.0

    summary = {
        "total_submitted": total_submitted,
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
        "added_to_kb": added_to_kb,
        "reviewed": reviewed,
        "approval_rate": approval_rate,
        "rejection_rate": rejection_rate,
        "kb_total_issues": kb_counts["kb_total_issues"],
        "seller_kb_count": kb_counts["seller_kb_count"],
        "buyer_kb_count": kb_counts["buyer_kb_count"],
        "avg_review_time_minutes": _avg_review_time_minutes(issues, audit),
    }

    category_counts = calculate_category_counts(issues)
    daily_trend = calculate_daily_trend(issues, audit)
    kb_growth = calculate_kb_growth(audit, kb_counts["kb_total_issues"])
    topic_cluster_counts = calculate_topic_cluster_counts(issues)

    return {
        "summary": summary,
        "status_breakdown": calculate_status_breakdown(issues, audit),
        "daily_trend": daily_trend,
        "category_counts": category_counts,
        "topic_cluster_counts": topic_cluster_counts,
        "kb_growth": kb_growth,
        "resolution_funnel": calculate_resolution_funnel(summary),
        "top_repeated_queries": calculate_top_repeated_queries(issues),
        "insights": generate_insights(summary, category_counts),
    }
