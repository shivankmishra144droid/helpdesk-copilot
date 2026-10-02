"""JSON persistence for Helpdesk Copilot supervisor panel and issue queue."""

from __future__ import annotations

import functools
import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from category_utils import (
    assign_topic_category,
    category_name_by_id,
    count_branches_by_category,
    infer_topic_category,
    load_topic_categories,
    resolve_stored_category_id,
    save_topic_categories,
)
from ingest import (
    build_keywords,
    extract_text_from_pdf,
    is_junk_branch_title,
    load_kb,
    merge_branch,
    parse_section_to_branch,
    save_kb,
    slugify,
    split_sections,
)
from concurrency import STORE_LOCK
from draft_enrichment import branch_to_draft_entry
from kb_manager import get_registry, kb_path, normalize_caller_type
from llm_drafter import apply_manual_llm_enrichment, draft_resolution

KNOWLEDGE_ROOT = Path(__file__).parent / "knowledge"
PENDING_QUEUE_PATH = KNOWLEDGE_ROOT / "pending_queue.json"
AUDIT_LOG_PATH = KNOWLEDGE_ROOT / "audit_log.jsonl"
METADATA_PATH = KNOWLEDGE_ROOT / "store_metadata.json"

STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_REJECTED = "rejected"

API_STATUS_MAP = {
    STATUS_PENDING: "drafted",
    STATUS_ACTIVE: "approved",
    STATUS_REJECTED: "rejected",
}

# Shared with ingest/kb_manager so the inbox watcher and request threads never
# interleave a load-modify-save. Process-local: run a single uvicorn worker.
_LOCK = STORE_LOCK


def _locked(func):
    """Run the whole function under the store lock (check-then-write stays atomic)."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _LOCK:
            return func(*args, **kwargs)

    return wrapper
_SUPERVISOR_SOURCE = "supervisor"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temp.replace(path)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_queue_store() -> dict[str, Any]:
    default = {"next_id": 1, "issues": []}
    data = _load_json(PENDING_QUEUE_PATH, default)
    data.setdefault("next_id", 1)
    data.setdefault("issues", [])
    return data


def _save_queue_store(store: dict[str, Any]) -> None:
    _atomic_write_json(PENDING_QUEUE_PATH, store)


def _append_audit(record: dict[str, Any]) -> None:
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_audit_for_issue(issue_id: int) -> list[dict[str, Any]]:
    if not AUDIT_LOG_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if int(row.get("issue_id", -1)) == issue_id:
                rows.append(row)
    rows.sort(key=lambda item: item.get("timestamp", ""))
    return rows


def get_metadata(key: str) -> str | None:
    data = _load_json(METADATA_PATH, {})
    value = data.get(key)
    return str(value) if value is not None else None


def _set_metadata(key: str, value: str) -> None:
    with _LOCK:
        data = _load_json(METADATA_PATH, {})
        data[key] = value
        _atomic_write_json(METADATA_PATH, data)


def resolve_supervisor_id(supervisor_name: str = "supervisor") -> int:
    return 1


def log_issue_audit(
    issue_id: int,
    action: str,
    *,
    supervisor_id: int | None = None,
    notes: str | None = None,
    pending_id: str | None = None,
    actor: str | None = None,
) -> None:
    with _LOCK:
        store = _load_queue_store()
        issue = next((item for item in store["issues"] if int(item["id"]) == issue_id), None)
        if pending_id is None and issue:
            pending_id = issue.get("pending_id")
        record = {
            "id": len(_read_audit_for_issue(issue_id)) + 1,
            "issue_id": issue_id,
            "action": action,
            "supervisor_id": supervisor_id,
            "timestamp": _now_iso(),
            "notes": notes,
            "pending_id": pending_id,
            "actor": actor or (str(supervisor_id) if supervisor_id else None),
            "details": notes,
        }
        _append_audit(record)


def _issue_record_to_dict(data: dict[str, Any]) -> dict[str, Any]:
    draft = {}
    if data.get("draft_json"):
        if isinstance(data["draft_json"], dict):
            draft = dict(data["draft_json"])
        else:
            try:
                draft = json.loads(data["draft_json"])
            except json.JSONDecodeError:
                draft = {}

    extras = {}
    if data.get("extras_json"):
        if isinstance(data["extras_json"], dict):
            extras = dict(data["extras_json"])
        else:
            try:
                extras = json.loads(data["extras_json"])
            except json.JSONDecodeError:
                extras = {}

    api_status = API_STATUS_MAP.get(data["status"], data["status"])
    issue_id = int(data["id"])

    document_records = list(data.get("required_documents") or [])
    if document_records and isinstance(document_records[0], str):
        document_records = [{"doc_name": doc, "is_required": True} for doc in document_records]

    step_records = list(data.get("resolution_step_records") or [])
    if not step_records and data.get("resolution_steps"):
        step_records = [
            {
                "step_number": index,
                "step_text": step,
                "is_blocking": index == 1,
            }
            for index, step in enumerate(data["resolution_steps"], start=1)
            if str(step).strip()
        ]

    documents = [doc["doc_name"] for doc in document_records if isinstance(doc, dict)]
    steps = [step["step_text"] for step in step_records if isinstance(step, dict)]
    resolution = data.get("resolution")

    if not draft.get("resolution_steps") and steps:
        draft["resolution_steps"] = steps
    if not draft.get("required_documents") and documents:
        draft["required_documents"] = documents
    if not draft.get("policy") and data.get("policy_text"):
        draft["policy"] = data["policy_text"]
    if not draft.get("problem_statement") and data.get("problem_statement"):
        draft["problem_statement"] = data["problem_statement"]
    if not draft.get("issue_name"):
        draft["issue_name"] = data["issue_name"]
    if not draft.get("topic_category") and data.get("category_id"):
        draft["topic_category"] = data["category_id"]
        draft["category"] = data["category_id"]

    trigger_keywords: list[str] = list(draft.get("trigger_keywords", []))
    stored_keywords = data.get("trigger_keywords")
    if isinstance(stored_keywords, list):
        trigger_keywords = [str(k) for k in stored_keywords]
    elif isinstance(stored_keywords, str) and stored_keywords:
        try:
            parsed = json.loads(stored_keywords)
            if isinstance(parsed, list):
                trigger_keywords = [str(k) for k in parsed]
        except json.JSONDecodeError:
            pass

    l1_team = draft.get("l1_team") or (resolution or {}).get("l1_team", "")
    l1_person = draft.get("l1_person") or (resolution or {}).get("l1_person", "")
    approved_by = data.get("approved_by") or (resolution or {}).get("approved_by")
    approved_at = data.get("approved_at") or (resolution or {}).get("approved_at")

    if data["status"] == STATUS_PENDING:
        from draft_enrichment import draft_needs_enrichment, enrich_draft_entry

        query_text = data.get("problem_statement") or data["issue_name"]
        possible_matches = extras.get("possible_matches", [])
        if draft_needs_enrichment(draft, data["caller_type"]) and possible_matches:
            draft = enrich_draft_entry(
                draft,
                query_text,
                data["caller_type"],
                faiss_matches=possible_matches,
            )

    return {
        "id": issue_id,
        "issue_id": issue_id,
        "pending_id": data.get("pending_id"),
        "issue_name": data["issue_name"],
        "category": data.get("category_id"),
        "category_id": data.get("category_id"),
        "problem_statement": data.get("problem_statement"),
        "policy": data.get("policy_text"),
        "policy_text": data.get("policy_text"),
        "status": data["status"],
        "api_status": api_status,
        "source_document": data.get("source_document"),
        "caller_type": data["caller_type"],
        "draft": draft,
        "draft_json": draft,
        "extras": extras,
        "reject_reason": data.get("reject_reason"),
        "branch_id": data.get("branch_id"),
        "added_to_kb": bool(data.get("added_to_kb")),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "approved_by": approved_by,
        "approved_at": approved_at,
        "query": data.get("problem_statement") or data["issue_name"],
        "examples_used": extras.get("examples_used", []),
        "possible_matches": extras.get("possible_matches", []),
        "draft_error": extras.get("draft_error"),
        "setup_instructions": extras.get("setup_instructions"),
        "draft_source": extras.get("draft_source"),
        "template_issue_name": extras.get("template_issue_name"),
        "editable": data["status"] == STATUS_PENDING,
        "documents": documents,
        "required_documents": document_records,
        "resolution_steps": steps,
        "resolution_step_records": step_records,
        "l1_team": l1_team,
        "l1_person": l1_person,
        "trigger_keywords": trigger_keywords,
        "resolution": resolution,
    }


def _find_issue_record(store: dict[str, Any], *, issue_id: int | None = None, pending_id: str | None = None) -> dict[str, Any] | None:
    for item in store["issues"]:
        if issue_id is not None and int(item["id"]) == issue_id:
            return item
        if pending_id and item.get("pending_id") == pending_id:
            return item
    return None


def get_issue_by_id(issue_id: int) -> dict[str, Any] | None:
    with _LOCK:
        store = _load_queue_store()
        row = _find_issue_record(store, issue_id=issue_id)
    return _issue_record_to_dict(row) if row else None


def get_issue_by_pending_id(pending_id: str) -> dict[str, Any] | None:
    with _LOCK:
        store = _load_queue_store()
        row = _find_issue_record(store, pending_id=pending_id)
    return _issue_record_to_dict(row) if row else None


def get_pending_issues(caller_type: str | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        store = _load_queue_store()
        rows = [
            item for item in store["issues"] if item.get("status") == STATUS_PENDING
        ]
    if caller_type:
        normalized = normalize_caller_type(caller_type)
        rows = [item for item in rows if item.get("caller_type") == normalized]
    rows.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return [_issue_record_to_dict(row) for row in rows]


def get_pending_queue(caller_type: str | None = None) -> list[dict[str, Any]]:
    issues = get_pending_issues(caller_type)
    results: list[dict[str, Any]] = []
    for issue in issues:
        item = {
            "pending_id": issue.get("pending_id") or f"issue-{issue['id']}",
            "query": issue.get("query") or issue["issue_name"],
            "caller_type": issue["caller_type"],
            "status": issue.get("api_status", issue["status"]),
            "draft_resolution": issue.get("draft"),
            "similar_issues": issue.get("possible_matches", []),
            "notes": issue.get("reject_reason"),
            "submitted_at": issue["created_at"],
            "reviewed_by": issue.get("approved_by"),
            "reviewed_at": issue.get("approved_at"),
            "issue_id": issue["id"],
        }
        results.append(item)
    return results


def create_pending_issue(query: str, caller_type: str) -> tuple[str, int]:
    pending_id = str(uuid.uuid4())
    normalized = normalize_caller_type(caller_type)
    issue_name = query.strip()[:80] or "Pending issue"
    now = _now_iso()

    with _LOCK:
        store = _load_queue_store()
        issue_id = int(store["next_id"])
        store["next_id"] = issue_id + 1
        record = {
            "id": issue_id,
            "issue_name": issue_name,
            "category_id": None,
            "problem_statement": query.strip(),
            "policy_text": "",
            "status": STATUS_PENDING,
            "source_document": "agent_query",
            "caller_type": normalized,
            "pending_id": pending_id,
            "draft_json": {},
            "extras_json": {},
            "reject_reason": None,
            "branch_id": None,
            "added_to_kb": False,
            "created_at": now,
            "updated_at": now,
            "approved_by": None,
            "approved_at": None,
            "trigger_keywords": [],
            "required_documents": [],
            "resolution_steps": [],
            "resolution_step_records": [],
            "resolution": None,
        }
        store["issues"].append(record)
        _save_queue_store(store)

    log_issue_audit(issue_id, "queued_by_agent", notes=query.strip()[:200], pending_id=pending_id)
    return pending_id, issue_id


def draft_resolution_for_pending(
    pending_id: str,
    query: str,
    caller_type: str,
    *,
    possible_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from db_drafter import draft_resolution_for_queue

    issue = get_issue_by_pending_id(pending_id)
    if not issue:
        return {"error": "Issue not found", "draft": None, "draft_source": None}

    # Fast KB template draft — avoids blocking on an LLM call during submit.
    drafted = draft_resolution_for_queue(
        query.strip(),
        caller_type,
        fast=True,
        possible_matches=possible_matches,
    )
    return _persist_pending_draft(pending_id, query.strip(), caller_type, drafted)


def _persist_pending_draft(
    pending_id: str,
    query: str,
    caller_type: str,
    drafted: dict[str, Any],
) -> dict[str, Any]:
    draft_entry = drafted.get("draft") if isinstance(drafted.get("draft"), dict) else {}
    extras = {
        "examples_used": drafted.get("examples_used", []),
        "possible_matches": drafted.get("possible_matches", []),
        "draft_error": drafted.get("error"),
        "setup_instructions": drafted.get("setup_instructions"),
        "draft_source": drafted.get("draft_source"),
        "db_similar": drafted.get("db_similar", []),
        "lms_matches": drafted.get("lms_matches", []),
        "template_issue_name": drafted.get("template_issue_name"),
    }

    issue_name = str(draft_entry.get("issue_name") or query.strip()[:80]).strip()
    if not issue_name:
        issue_name = query.strip()[:80] or "Pending issue"
    category_id = resolve_stored_category_id(
        draft_entry.get("topic_category") or draft_entry.get("category"),
        caller_type,
        issue_name=issue_name,
        problem_statement=str(draft_entry.get("problem_statement") or query),
    )
    now = _now_iso()

    with _LOCK:
        store = _load_queue_store()
        row = _find_issue_record(store, pending_id=pending_id)
        if not row:
            return {"error": "Issue not found", "draft": None, "draft_source": None}
        row["issue_name"] = issue_name
        row["category_id"] = category_id
        row["policy_text"] = str(draft_entry.get("policy", ""))
        row["draft_json"] = draft_entry
        row["extras_json"] = extras
        row["updated_at"] = now
        _save_queue_store(store)

    return drafted


def regenerate_pending_draft(
    *,
    pending_id: str | None = None,
    issue_id: int | None = None,
    edited_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Format or polish supervisor-written draft fields via the LLM."""
    from llm_drafter import format_supervisor_entry_with_llm

    if pending_id:
        issue = get_issue_by_pending_id(pending_id)
    elif issue_id is not None:
        issue = get_issue_by_id(issue_id)
    else:
        return {"error": "pending_id or issue_id required", "draft": None, "draft_source": None}

    if not issue:
        return {"error": "Issue not found", "draft": None, "draft_source": None}

    query = (
        issue.get("query")
        or issue.get("problem_statement")
        or issue.get("issue_name")
        or ""
    ).strip()
    if not query:
        return {"error": "Issue has no query text", "draft": None, "draft_source": None}

    caller_type = issue["caller_type"]
    pid = issue.get("pending_id") or pending_id
    if not pid:
        return {"error": "Issue has no pending_id", "draft": None, "draft_source": None}

    entry = dict(edited_entry or issue.get("draft") or {})
    drafted = format_supervisor_entry_with_llm(
        entry=entry,
        query=query,
        caller_type=caller_type,
    )
    result = _persist_pending_draft(pid, query, caller_type, drafted)

    iid = int(issue["id"])
    draft_source = drafted.get("draft_source") or "unknown"
    if draft_source in {"llm_db_fewshot", "llm", "llm_format", "llm_polish"}:
        action = "draft_generated"
    elif drafted.get("error"):
        action = "draft_failed"
    else:
        action = "kb_template_drafted"
    log_issue_audit(iid, action, notes=str(draft_source), pending_id=pid)

    return result


def create_queue_issue(
    *,
    query: str,
    caller_type: str,
    draft: dict[str, Any],
    examples_used: list[str],
    possible_matches: list[dict[str, Any]],
    draft_error: str | None = None,
    setup_instructions: str | None = None,
    draft_source: str | None = None,
) -> str:
    pending_id, issue_id = create_pending_issue(query, caller_type)
    if draft:
        now = _now_iso()
        extras = {
            "examples_used": examples_used,
            "possible_matches": possible_matches,
            "draft_error": draft_error,
            "setup_instructions": setup_instructions,
            "draft_source": draft_source,
        }
        issue_name = str(draft.get("issue_name") or query[:80]).strip() or query[:80]
        category_id = resolve_stored_category_id(
            draft.get("topic_category") or draft.get("category"),
            caller_type,
            issue_name=issue_name,
            problem_statement=str(draft.get("problem_statement") or query),
        )
        with _LOCK:
            store = _load_queue_store()
            row = _find_issue_record(store, issue_id=issue_id)
            if row:
                row["issue_name"] = issue_name
                row["category_id"] = category_id
                row["policy_text"] = str(draft.get("policy", ""))
                row["draft_json"] = draft
                row["extras_json"] = extras
                row["updated_at"] = now
                _save_queue_store(store)
    return pending_id


def list_queue_items() -> list[dict[str, Any]]:
    with _LOCK:
        store = _load_queue_store()
        rows = [item for item in store["issues"] if item.get("pending_id")]
    rows.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return [
        {
            "pending_id": row["pending_id"],
            "query": row.get("problem_statement") or row["issue_name"],
            "status": API_STATUS_MAP.get(row["status"], row["status"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def find_similar_active_issues(
    query: str,
    caller_type: str,
    *,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Top KB branches by keyword overlap with the query."""
    normalized = normalize_caller_type(caller_type)
    words = {word for word in query.lower().split() if len(word) > 2}
    kb = load_kb(kb_path(normalized))
    results: list[tuple[float, dict[str, Any]]] = []

    for index, branch in enumerate(kb.get("branches", []), start=1):
        haystack = f"{branch.get('branch_name', '')} {branch.get('agent_script', '')}".lower()
        overlap = sum(1 for word in words if word in haystack) if words else 0
        base = overlap / max(len(words), 1)
        steps = branch.get("steps") or []
        if isinstance(steps, dict):
            merged_steps: list[str] = []
            for value in steps.values():
                if isinstance(value, list):
                    merged_steps.extend(str(step) for step in value)
            steps = merged_steps
        documents = branch.get("documents") or []
        if isinstance(documents, dict):
            merged_docs: list[str] = []
            for value in documents.values():
                if isinstance(value, list):
                    merged_docs.extend(str(doc) for doc in value)
            documents = merged_docs
        item = {
            "id": index,
            "issue_name": branch.get("branch_name", ""),
            "category_id": branch.get("topic_category", ""),
            "problem_statement": branch.get("agent_script", ""),
            "policy_text": branch.get("policy", ""),
            "resolution_steps": list(steps),
            "required_documents": list(documents),
            "l1_team": branch.get("escalation", "TBD"),
            "l1_person": branch.get("escalation_person", "TBD"),
            "branch_id": branch.get("branch_id"),
        }
        results.append((base, item))

    results.sort(key=lambda pair: pair[0], reverse=True)
    if not results:
        return []
    if results[0][0] <= 0:
        return [item for _, item in results[:top_k]]
    return [item for score, item in results[:top_k] if score > 0]


def _entry_to_resolution_fields(entry: dict[str, Any]) -> dict[str, Any]:
    problem = str(entry.get("problem_statement", "")).strip()
    policy = str(entry.get("policy", "")).strip()
    agent_script = problem
    if policy:
        agent_script = f"{problem}\n\nPolicy: {policy}" if problem else policy

    l1_team = str(entry.get("l1_team", "TBD")).strip() or "TBD"
    l1_person = str(entry.get("l1_person", "TBD")).strip() or "TBD"
    steps = [
        str(step) for step in entry.get("resolution_steps", []) if str(step).strip()
    ]
    if not steps:
        steps = ["Follow the approved resolution guidance."]

    documents = [
        str(doc) for doc in entry.get("required_documents", []) if str(doc).strip()
    ]
    if not documents:
        documents = ["No specific documents required"]

    return {
        "agent_script": agent_script,
        "escalation_team": l1_team,
        "escalation_person": l1_person,
        "l1_team": l1_team,
        "l1_person": l1_person,
        "steps": steps,
        "documents": documents,
    }


def _issue_to_branch(issue: dict[str, Any], fields: dict[str, Any], branch_id: str) -> dict[str, Any]:
    caller_type = issue["caller_type"]
    caller_label = "Seller" if caller_type == "seller" else "Buyer"
    category_id = issue.get("category_id") or "profile_update"
    category_name = category_name_by_id(caller_type, category_id) or category_id
    issue_name = issue["issue_name"]
    draft = issue.get("draft") or {}
    keyword_source = f"{issue_name} {issue.get('problem_statement') or ''}"
    trigger_keywords = draft.get("trigger_keywords") or build_keywords(issue_name, keyword_source)

    l1_team = fields["l1_team"]
    escalation = l1_team if l1_team.upper() == "TBD" else f"Assign to {l1_team}"

    return {
        "branch_id": branch_id,
        "branch_name": issue_name,
        "topic_category": category_id,
        "trigger_keywords": trigger_keywords,
        "agent_script": fields["agent_script"],
        "steps": fields["steps"],
        "documents": fields["documents"],
        "escalation": escalation,
        "escalation_person": fields["l1_person"],
        "source": _SUPERVISOR_SOURCE,
        "tagging": f"{caller_label} → {category_name} → {issue_name}",
        "queue_issue_id": issue["id"],
    }


@_locked
def _merge_branch_into_kb(caller_type: str, branch: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_caller_type(caller_type)
    path = kb_path(normalized)
    kb = load_kb(path)
    branches = list(kb.get("branches", []))
    branch_id = branch["branch_id"]
    existing = next((item for item in branches if item.get("branch_id") == branch_id), None)
    if existing:
        merged = merge_branch(existing, branch)
        merged["source"] = _SUPERVISOR_SOURCE
        branches = [
            merged if item.get("branch_id") == branch_id else item for item in branches
        ]
    else:
        branches.append(branch)
    kb["branches"] = branches
    save_kb(path, kb)
    reload_info = get_registry().reload(normalized)
    now = _now_iso()
    _set_metadata("last_rebuild", now)
    _set_metadata(f"last_rebuild_{normalized}", now)
    return {
        "caller_type": normalized,
        "db_branches_exported": 1,
        "total_branches": len(branches),
        "last_rebuild": now,
        **reload_info,
    }


@_locked
def approve_issue(
    issue_id: int,
    supervisor_id: int,
    edits: dict[str, Any],
    *,
    topic_category: str | None = None,
    add_to_kb: bool = True,
) -> dict[str, Any]:
    issue = get_issue_by_id(issue_id)
    if not issue:
        raise ValueError("Issue not found")
    if issue["status"] != STATUS_PENDING:
        raise ValueError(f"Issue is already {issue['status']}")

    entry = {**issue.get("draft", {}), **edits}
    fields = _entry_to_resolution_fields(entry)
    caller_type = issue["caller_type"]
    issue_name = str(entry.get("issue_name", issue["issue_name"])).strip()
    category_id = (topic_category or entry.get("topic_category") or issue.get("category_id") or "").strip()
    category_id = resolve_stored_category_id(
        category_id,
        caller_type,
        issue_name=issue_name,
        problem_statement=str(entry.get("problem_statement") or issue.get("problem_statement") or ""),
    ) or ""
    if not category_id:
        branch_probe = {"branch_name": issue_name, "tagging": entry.get("tagging", "")}
        category_id = infer_topic_category(branch_probe, caller_type)

    keywords = entry.get("trigger_keywords")
    if not keywords:
        keywords = build_keywords(
            issue_name,
            f"{entry.get('problem_statement', '')} {issue.get('problem_statement', '')}",
        )
    entry["trigger_keywords"] = keywords

    branch_id = slugify(issue_name)
    now = _now_iso()
    resolution = {
        "agent_script": fields["agent_script"],
        "escalation_team": fields["escalation_team"],
        "escalation_person": fields["escalation_person"],
        "l1_team": fields["l1_team"],
        "l1_person": fields["l1_person"],
        "approved_by": str(supervisor_id),
        "approved_at": now,
    }
    step_records = [
        {
            "step_number": index,
            "step_text": step,
            "is_blocking": index == 1,
        }
        for index, step in enumerate(fields["steps"], start=1)
    ]
    document_records = [
        {
            "doc_name": doc,
            "is_required": 0 if doc.lower().startswith("no specific") else 1,
        }
        for doc in fields["documents"]
    ]

    with _LOCK:
        store = _load_queue_store()
        row = _find_issue_record(store, issue_id=issue_id)
        if not row:
            raise ValueError("Issue not found")
        row.update(
            {
                "issue_name": issue_name,
                "category_id": category_id,
                "problem_statement": str(entry.get("problem_statement", fields["agent_script"])),
                "policy_text": str(entry.get("policy", "")),
                "status": STATUS_ACTIVE,
                "draft_json": entry,
                "branch_id": branch_id if add_to_kb else None,
                "added_to_kb": bool(add_to_kb),
                "approved_by": str(supervisor_id),
                "approved_at": now,
                "trigger_keywords": keywords,
                "updated_at": now,
                "resolution": resolution,
                "resolution_steps": fields["steps"],
                "resolution_step_records": step_records,
                "required_documents": document_records,
            }
        )
        _save_queue_store(store)

    log_issue_audit(
        issue_id,
        "approved_and_added" if add_to_kb else "approved_send_only",
        supervisor_id=supervisor_id,
        notes=f"branch_id={branch_id}" if add_to_kb else "sent to agent only",
        pending_id=issue.get("pending_id"),
        actor=str(supervisor_id),
    )

    branch = _issue_to_branch(
        {
            **issue,
            "issue_name": issue_name,
            "category_id": category_id,
            "problem_statement": row["problem_statement"],
            "draft": entry,
        },
        fields,
        branch_id,
    )
    if add_to_kb:
        _merge_branch_into_kb(caller_type, branch)
    return branch


def approve_issue_by_pending_id(
    pending_id: str,
    supervisor_id: int,
    edits: dict[str, Any],
    *,
    topic_category: str | None = None,
    add_to_kb: bool = True,
) -> dict[str, Any]:
    issue = get_issue_by_pending_id(pending_id)
    if not issue:
        raise ValueError("Pending resolution not found")
    return approve_issue(
        int(issue["id"]),
        supervisor_id,
        edits,
        topic_category=topic_category,
        add_to_kb=add_to_kb,
    )


def _reject_issue_by_id(issue_id: int, supervisor_id: int, reason: str = "") -> None:
    issue = get_issue_by_id(issue_id)
    if not issue:
        raise ValueError("Issue not found")
    if issue["status"] != STATUS_PENDING:
        raise ValueError(f"Issue is already {issue['status']}")

    now = _now_iso()
    with _LOCK:
        store = _load_queue_store()
        row = _find_issue_record(store, issue_id=issue_id)
        if not row:
            raise ValueError("Issue not found")
        row["status"] = STATUS_REJECTED
        row["reject_reason"] = reason.strip() or None
        row["updated_at"] = now
        _save_queue_store(store)

    log_issue_audit(
        issue_id,
        "rejected",
        supervisor_id=supervisor_id,
        notes=reason.strip() or None,
        pending_id=issue.get("pending_id"),
        actor=str(supervisor_id),
    )


def reject_issue(
    issue_or_pending_id: int | str,
    supervisor_id: int,
    reason: str = "",
) -> None:
    if isinstance(issue_or_pending_id, str):
        if issue_or_pending_id.startswith("issue-"):
            _reject_issue_by_id(
                int(issue_or_pending_id.replace("issue-", "")),
                supervisor_id,
                reason,
            )
            return
        if not issue_or_pending_id.isdigit():
            reject_issue_by_pending_id(issue_or_pending_id, supervisor_id, reason)
            return
    _reject_issue_by_id(int(issue_or_pending_id), supervisor_id, reason)


def reject_issue_by_id(issue_id: int, supervisor_id: int, reason: str = "") -> None:
    _reject_issue_by_id(issue_id, supervisor_id, reason)


def reject_issue_by_pending_id(
    pending_id: str, supervisor_id: int, reason: str = ""
) -> None:
    issue = get_issue_by_pending_id(pending_id)
    if not issue:
        raise ValueError("Pending resolution not found")
    _reject_issue_by_id(int(issue["id"]), supervisor_id, reason)


def get_issue_history(issue_id: int) -> list[dict[str, Any]]:
    rows = _read_audit_for_issue(issue_id)
    return [
        {
            "id": row.get("id"),
            "log_id": row.get("id"),
            "issue_id": row.get("issue_id"),
            "action": row.get("action"),
            "supervisor_id": row.get("supervisor_id"),
            "supervisor_name": row.get("actor"),
            "actor": row.get("actor"),
            "timestamp": row.get("timestamp"),
            "notes": row.get("notes"),
            "details": row.get("details") or row.get("notes"),
            "pending_id": row.get("pending_id"),
        }
        for row in rows
    ]


def get_issues_by_category(category_id: str, caller_type: str | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        store = _load_queue_store()
        rows = [item for item in store["issues"] if item.get("category_id") == category_id]
    if caller_type:
        normalized = normalize_caller_type(caller_type)
        rows = [item for item in rows if item.get("caller_type") == normalized]
    rows.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return [_issue_record_to_dict(row) for row in rows]


def _draft_entry_from_issue(issue: dict[str, Any]) -> dict[str, Any] | None:
    draft = issue.get("draft") or {}
    if not draft:
        return None
    return {
        "issue_name": draft.get("issue_name") or issue.get("issue_name", ""),
        "category": draft.get("category") or issue.get("category_id", ""),
        "topic_category": draft.get("topic_category") or issue.get("category_id", ""),
        "problem_statement": draft.get("problem_statement")
        or issue.get("problem_statement", ""),
        "policy": draft.get("policy") or issue.get("policy_text", ""),
        "resolution_steps": draft.get("resolution_steps") or issue.get("resolution_steps", []),
        "required_documents": draft.get("required_documents") or issue.get("documents", []),
        "l1_team": draft.get("l1_team", ""),
        "l1_person": draft.get("l1_person", ""),
        "trigger_keywords": draft.get("trigger_keywords") or issue.get("trigger_keywords", []),
    }


def batch_approve_issues(
    pending_ids: list[str],
    supervisor_id: int,
) -> dict[str, Any]:
    from llm_drafter import validate_unified_entry

    approved = 0
    failed = 0
    issue_ids: list[int] = []
    errors: list[dict[str, str]] = []
    caller_types: set[str] = set()

    for pending_id in pending_ids:
        pid = str(pending_id).strip()
        if not pid:
            failed += 1
            errors.append({"pending_id": pid, "error": "empty pending_id"})
            continue

        issue = get_issue_by_pending_id(pid)
        if not issue:
            failed += 1
            errors.append({"pending_id": pid, "error": "Issue not found"})
            continue

        if issue["status"] != STATUS_PENDING:
            failed += 1
            errors.append(
                {
                    "pending_id": pid,
                    "error": f"Issue is already {issue['status']}",
                }
            )
            continue

        entry = _draft_entry_from_issue(issue)
        if not entry:
            failed += 1
            errors.append({"pending_id": pid, "error": "No draft available"})
            continue

        topic_category = str(entry.get("topic_category") or entry.get("category") or "").strip()
        if not topic_category:
            branch_probe = {
                "branch_name": entry.get("issue_name", ""),
                "tagging": entry.get("tagging", ""),
            }
            topic_category = infer_topic_category(branch_probe, issue["caller_type"])
            entry["topic_category"] = topic_category
            entry["category"] = topic_category

        validation_errors = validate_unified_entry(entry)
        if validation_errors:
            failed += 1
            errors.append({"pending_id": pid, "error": "; ".join(validation_errors)})
            continue

        try:
            approve_issue(
                int(issue["id"]),
                supervisor_id,
                entry,
                topic_category=topic_category,
                add_to_kb=True,
            )
            approved += 1
            issue_ids.append(int(issue["id"]))
            caller_types.add(normalize_caller_type(issue["caller_type"]))
        except ValueError as exc:
            failed += 1
            errors.append({"pending_id": pid, "error": str(exc)})

    return {
        "approved": approved,
        "failed": failed,
        "issue_ids": issue_ids,
        "errors": errors,
        "caller_types": sorted(caller_types),
    }


def batch_reject_issues(
    pending_ids: list[str],
    supervisor_id: int,
    reason: str = "",
) -> dict[str, Any]:
    rejected = 0
    failed = 0
    issue_ids: list[int] = []
    errors: list[dict[str, str]] = []

    for pending_id in pending_ids:
        pid = str(pending_id).strip()
        if not pid:
            failed += 1
            errors.append({"pending_id": pid, "error": "empty pending_id"})
            continue

        try:
            issue = get_issue_by_pending_id(pid)
            if not issue:
                raise ValueError("Issue not found")
            reject_issue(int(issue["id"]), supervisor_id, reason)
            rejected += 1
            issue_ids.append(int(issue["id"]))
        except ValueError as exc:
            failed += 1
            errors.append({"pending_id": pid, "error": str(exc)})

    return {
        "rejected": rejected,
        "failed": failed,
        "issue_ids": issue_ids,
        "errors": errors,
    }


def list_db_categories(caller_type: str | None = None) -> list[dict[str, Any]]:
    caller_types = [normalize_caller_type(caller_type)] if caller_type else ["seller", "buyer"]
    results: list[dict[str, Any]] = []
    for ct in caller_types:
        categories = load_topic_categories(ct)
        kb = load_kb(kb_path(ct))
        counted = {
            item["id"]: item["branch_count"]
            for item in count_branches_by_category(kb.get("branches", []), categories)
        }
        for item in categories:
            branch_count = int(counted.get(item["id"], 0))
            results.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "category_name": item["name"],
                    "caller_type": ct,
                    "branch_count": branch_count,
                    "is_empty": branch_count == 0,
                }
            )
    return results


def _unique_category_id(base: str, caller_type: str, categories: list[dict[str, str]]) -> str:
    candidate = slugify(base) or "category"
    existing = {item["id"] for item in categories}
    if candidate not in existing:
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in existing:
        suffix += 1
    return f"{candidate}_{suffix}"


@_locked
def create_category(category_name: str, caller_type: str) -> dict[str, Any]:
    name = category_name.strip()
    if not name:
        raise ValueError("category_name is required")

    normalized = normalize_caller_type(caller_type)
    categories = load_topic_categories(normalized)
    if any(item["name"].lower() == name.lower() for item in categories):
        raise ValueError(f"Category '{name}' already exists for {normalized}")

    category_id = _unique_category_id(name, normalized, categories)
    categories.append({"id": category_id, "name": name})
    save_topic_categories(normalized, categories)

    return {
        "id": category_id,
        "name": name,
        "category_name": name,
        "caller_type": normalized,
        "branch_count": 0,
        "is_empty": True,
    }


@_locked
def rename_category(category_id: str, new_name: str) -> dict[str, Any]:
    name = new_name.strip()
    if not name:
        raise ValueError("category_name is required")

    caller_type = None
    branch_count = 0
    for ct in ("seller", "buyer"):
        categories = load_topic_categories(ct)
        if not any(item["id"] == category_id for item in categories):
            continue
        if any(item["name"].lower() == name.lower() and item["id"] != category_id for item in categories):
            raise ValueError(f"Category name '{name}' already exists")
        caller_type = ct
        kb = load_kb(kb_path(ct))
        counted = {
            item["id"]: item["branch_count"]
            for item in count_branches_by_category(kb.get("branches", []), categories)
        }
        branch_count = int(counted.get(category_id, 0))
        for item in categories:
            if item["id"] == category_id:
                item["name"] = name
                break
        save_topic_categories(ct, categories)
        break

    if caller_type is None:
        raise ValueError("Category not found")

    return {
        "id": category_id,
        "name": name,
        "category_name": name,
        "caller_type": caller_type,
        "branch_count": branch_count,
        "is_empty": branch_count == 0,
    }


@_locked
def delete_category_if_empty(category_id: str) -> dict[str, Any]:
    caller_type = None
    for ct in ("seller", "buyer"):
        categories = load_topic_categories(ct)
        if not any(item["id"] == category_id for item in categories):
            continue
        kb = load_kb(kb_path(ct))
        counted = {
            item["id"]: item["branch_count"]
            for item in count_branches_by_category(kb.get("branches", []), categories)
        }
        branch_count = int(counted.get(category_id, 0))
        with _LOCK:
            store = _load_queue_store()
            issue_count = sum(
                1 for item in store["issues"] if item.get("category_id") == category_id
            )
        if branch_count > 0 or issue_count > 0:
            raise ValueError(
                "Category cannot be deleted — it has linked issues or KB branches"
            )
        categories = [item for item in categories if item["id"] != category_id]
        save_topic_categories(ct, categories)
        caller_type = ct
        break

    if caller_type is None:
        raise ValueError("Category not found")

    return {"deleted": True, "id": category_id, "caller_type": caller_type}


@_locked
def merge_categories(source_id: str, target_id: str) -> dict[str, Any]:
    if source_id == target_id:
        raise ValueError("source and target must differ")

    caller_type = None
    for ct in ("seller", "buyer"):
        categories = load_topic_categories(ct)
        source_exists = any(item["id"] == source_id for item in categories)
        target_exists = any(item["id"] == target_id for item in categories)
        if source_exists and target_exists:
            caller_type = ct
            break
        if source_exists or target_exists:
            raise ValueError("Categories must belong to the same caller_type")

    if caller_type is None:
        raise ValueError("Source or target category not found")

    moved = 0
    with _LOCK:
        store = _load_queue_store()
        for item in store["issues"]:
            if item.get("category_id") == source_id and item.get("caller_type") == caller_type:
                item["category_id"] = target_id
                moved += 1
        _save_queue_store(store)

    path = kb_path(caller_type)
    kb = load_kb(path)
    for branch in kb.get("branches", []):
        if branch.get("topic_category") == source_id:
            branch["topic_category"] = target_id
    save_kb(path, kb)
    get_registry().reload(caller_type)

    categories = [item for item in load_topic_categories(caller_type) if item["id"] != source_id]
    save_topic_categories(caller_type, categories)

    return {
        "source_id": source_id,
        "target_id": target_id,
        "issues_moved": moved,
        "caller_type": caller_type,
    }


def _parse_manual_sections(manual_text: str, caller_type: str = "seller") -> list[dict[str, Any]]:
    branches: list[dict[str, Any]] = []
    for title, body in split_sections(manual_text):
        if is_junk_branch_title(title):
            continue
        branch = parse_section_to_branch(title, body)
        branch = apply_manual_llm_enrichment(branch, body, caller_type=caller_type)
        branches.append(branch)

    if branches:
        return branches

    drafted = draft_resolution(manual_text[:2000], caller_type)
    draft = drafted.get("draft") if isinstance(drafted.get("draft"), dict) else {}
    if draft.get("issue_name") or draft.get("problem_statement"):
        steps = [
            str(step)
            for step in draft.get("resolution_steps", [])
            if str(step).strip()
        ]
        return [
            {
                "branch_id": slugify(str(draft.get("issue_name", "manual_issue"))),
                "branch_name": str(draft.get("issue_name", "Manual Issue")).strip(),
                "agent_script": str(draft.get("problem_statement", "")).strip(),
                "steps": steps or ["Follow supervisor-approved guidance."],
                "documents": [
                    str(doc)
                    for doc in draft.get("required_documents", [])
                    if str(doc).strip()
                ],
                "escalation": str(draft.get("l1_team", "TBD")),
                "escalation_person": str(draft.get("l1_person", "TBD")),
                "policy": str(draft.get("policy", "")),
            }
        ]
    return []


def add_issue_from_manual(
    manual_text: str,
    filename: str,
    caller_type: str = "seller",
) -> list[int]:
    branches = _parse_manual_sections(manual_text, caller_type=caller_type)
    issue_ids: list[int] = []
    for branch in branches:
        assign_topic_category(branch, caller_type)
        draft = branch_to_draft_entry(branch, caller_type)
        pending_id, issue_id = create_pending_issue(
            str(branch.get("agent_script") or branch.get("branch_name", "")),
            caller_type,
        )
        now = _now_iso()
        with _LOCK:
            store = _load_queue_store()
            row = _find_issue_record(store, issue_id=issue_id)
            if row:
                row["issue_name"] = branch.get("branch_name", "Untitled Issue")
                row["category_id"] = branch.get("topic_category")
                row["problem_statement"] = branch.get(
                    "problem_statement",
                    branch.get("agent_script", ""),
                )
                row["policy_text"] = branch.get("policy", "")
                row["source_document"] = filename
                row["draft_json"] = draft
                row["updated_at"] = now
                _save_queue_store(store)
        log_issue_audit(issue_id, "parsed_from_manual", notes=filename, pending_id=pending_id)
        issue_ids.append(issue_id)
    return issue_ids


def upload_manual_pdf(data: bytes, filename: str, caller_type: str = "seller") -> dict[str, Any]:
    text = extract_text_from_pdf(data)
    if not text.strip():
        raise ValueError("No text could be extracted from the PDF")
    issue_ids = add_issue_from_manual(text, filename, caller_type=caller_type)
    return {
        "filename": filename,
        "issue_ids": issue_ids,
        "parsed_count": len(issue_ids),
    }


def count_supervisor_kb_branches(caller_type: str) -> int:
    kb = load_kb(kb_path(normalize_caller_type(caller_type)))
    return sum(
        1
        for branch in kb.get("branches", [])
        if branch.get("source") in (_SUPERVISOR_SOURCE, "database")
    )


def count_json_db_branches(caller_type: str) -> int:
    return count_supervisor_kb_branches(caller_type)


def count_seller_active_branches() -> int:
    return count_supervisor_kb_branches("seller")


def count_buyer_active_branches() -> int:
    return count_supervisor_kb_branches("buyer")


def count_pending_review_issues() -> int:
    with _LOCK:
        store = _load_queue_store()
        return sum(1 for item in store["issues"] if item.get("status") == STATUS_PENDING)


def count_total_issues() -> int:
    with _LOCK:
        store = _load_queue_store()
        return len(store["issues"])


def get_kb_sync_stats() -> dict[str, Any]:
    stats: dict[str, Any] = {"caller_types": {}, "last_rebuild": get_metadata("last_rebuild")}
    for caller_type in ("seller", "buyer"):
        branch_count = count_supervisor_kb_branches(caller_type)
        stats["caller_types"][caller_type] = {
            "db_branches": branch_count,
            "json_branches": branch_count,
            "in_sync": True,
        }
    stats["db_branches"] = sum(
        stats["caller_types"][ct]["db_branches"] for ct in ("seller", "buyer")
    )
    stats["json_branches"] = stats["db_branches"]
    return stats


def sync_kb_cache_if_needed(force: bool = False) -> dict[str, Any]:
    stats = get_kb_sync_stats()
    rebuilt: list[str] = []
    if force:
        for caller_type in ("seller", "buyer"):
            reload_kb_cache(caller_type)
            rebuilt.append(caller_type)
    stats = get_kb_sync_stats()
    stats["rebuilt"] = rebuilt
    return stats


def reload_kb_cache(caller_type: str) -> dict[str, Any]:
    normalized = normalize_caller_type(caller_type)
    kb = load_kb(kb_path(normalized))
    reload_info = get_registry().reload(normalized)
    now = _now_iso()
    _set_metadata("last_rebuild", now)
    _set_metadata(f"last_rebuild_{normalized}", now)
    return {
        "caller_type": normalized,
        "db_branches_exported": 0,
        "total_branches": len(kb.get("branches", [])),
        "last_rebuild": now,
        **reload_info,
    }


def rebuild_kb_from_db(caller_type: str) -> dict[str, Any]:
    """Reload FAISS from unified_knowledge.json (legacy name kept for API compatibility)."""
    return reload_kb_cache(caller_type)
