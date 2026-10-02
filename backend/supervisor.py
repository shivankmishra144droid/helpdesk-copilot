"""Supervisor API — persisted via JSON (knowledge/pending_queue.json)."""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from json_store import (
    approve_issue,
    approve_issue_by_pending_id,
    batch_approve_issues,
    batch_reject_issues,
    create_category,
    create_pending_issue,
    delete_category_if_empty,
    draft_resolution_for_pending,
    regenerate_pending_draft,
    get_issue_by_id,
    get_issue_by_pending_id,
    get_issue_history,
    get_pending_issues,
    list_db_categories,
    log_issue_audit,
    merge_categories,
    rebuild_kb_from_db,
    reject_issue,
    reject_issue_by_id,
    reject_issue_by_pending_id,
    rename_category,
    resolve_supervisor_id,
)
from draft_enrichment import draft_needs_enrichment, enrich_draft_entry, should_llm_redraft
from llm import check_llm_available
from llm_drafter import validate_unified_entry

from supervisor_stats import build_supervisor_stats
from topic_clustering import (
    compute_topic_clusters,
    enrich_issue_with_topic,
    filter_issues_by_cluster,
    get_supervisor_specializations,
    set_supervisor_specializations,
)
from lms_faq_import import faq_entry_to_draft_entry, import_lms_faq

router = APIRouter(prefix="/supervisor", tags=["supervisor"])


class QueueRequest(BaseModel):
    query: str
    caller_type: str = "seller"
    possible_matches: list[dict[str, Any]] | None = None


class RegenerateDraftRequest(BaseModel):
    pending_id: str | None = None
    issue_id: int | None = None
    edited_entry: dict[str, Any] | None = None


class ApproveRequest(BaseModel):
    pending_id: str | None = None
    issue_id: int | None = None
    edited_entry: dict[str, Any] | None = None
    target_kb: str | None = None
    topic_category: str | None = None
    approved_by: str = "supervisor"


class RejectRequest(BaseModel):
    pending_id: str | None = None
    issue_id: int | None = None
    reason: str = ""


class BatchApproveRequest(BaseModel):
    pending_ids: list[str]
    supervisor_id: str | None = None


class BatchRejectRequest(BaseModel):
    pending_ids: list[str]
    supervisor_id: str | None = None
    reason: str = ""


class CreateCategoryRequest(BaseModel):
    category_name: str
    caller_type: str = "seller"


class RenameCategoryRequest(BaseModel):
    category_name: str


class MergeCategoriesRequest(BaseModel):
    source_id: str
    target_id: str


class RebuildKbRequest(BaseModel):
    caller_type: Literal["seller", "buyer", "both"] = "seller"


class ImportLmsFaqRequest(BaseModel):
    faq_path: str | None = None
    dry_run: bool = False


class SpecializationsRequest(BaseModel):
    supervisor_id: str = "supervisor"
    cluster_ids: list[int] = []


def validate_send_to_agent(entry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not str(entry.get("issue_name", "")).strip():
        errors.append("issue_name is required")
    problem = str(entry.get("problem_statement", "")).strip()
    steps = entry.get("resolution_steps") or []
    if not problem and not steps:
        errors.append("problem_statement or resolution_steps is required")
    return errors


def _resolve_issue(*, pending_id: str | None = None, issue_id: int | None = None) -> dict[str, Any]:
    if issue_id is not None:
        issue = get_issue_by_id(issue_id)
    elif pending_id:
        issue = get_issue_by_pending_id(pending_id)
    else:
        raise HTTPException(
            status_code=400,
            detail="issue_id or pending_id is required",
        )
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


def _coalesce_list(*candidates: Any) -> list[Any]:
    for candidate in candidates:
        if isinstance(candidate, list) and candidate:
            return list(candidate)
    for candidate in candidates:
        if isinstance(candidate, list):
            return list(candidate)
    return []


def _form_entry_from_issue(issue: dict[str, Any]) -> dict[str, Any]:
    draft = dict(issue.get("draft") or {})
    return {
        "issue_name": draft.get("issue_name") or issue.get("issue_name", ""),
        "category": draft.get("category") or issue.get("category_id", ""),
        "topic_category": draft.get("topic_category") or issue.get("category_id", ""),
        "problem_statement": draft.get("problem_statement")
        or issue.get("problem_statement", ""),
        "policy": draft.get("policy") or issue.get("policy_text", ""),
        "resolution_steps": _coalesce_list(
            draft.get("resolution_steps"),
            issue.get("resolution_steps"),
        ),
        "required_documents": _coalesce_list(
            draft.get("required_documents"),
            issue.get("documents"),
        ),
        "l1_team": draft.get("l1_team") or issue.get("l1_team", ""),
        "l1_person": draft.get("l1_person") or issue.get("l1_person", ""),
        "trigger_keywords": _coalesce_list(
            draft.get("trigger_keywords"),
            issue.get("trigger_keywords"),
        ),
    }


def _similar_issues_for_detail(issue: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge DB-similar active issues and FAISS KB matches for the detail panel."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in issue.get("extras", {}).get("db_similar", []):
        name = str(row.get("issue_name", "")).strip()
        if not name:
            continue
        key = f"db:{name.lower()}"
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "source": "database",
                "issue_name": name,
                "category_id": row.get("category_id", ""),
                "category": row.get("category_id", ""),
                "problem_statement": row.get("problem_statement", ""),
                "resolution_steps": row.get("resolution_steps", []),
            }
        )

    for match in issue.get("possible_matches", []):
        name = str(match.get("branch_name", "")).strip()
        if not name:
            continue
        key = f"kb:{match.get('branch_id', name)}"
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "source": "kb",
                "issue_name": name,
                "category_id": match.get("topic_category", ""),
                "category": match.get("topic_category", ""),
                "branch_id": match.get("branch_id"),
                "agent_script_preview": match.get("agent_script_preview", ""),
            }
        )

    caller_type = issue.get("caller_type", "seller")
    for match in issue.get("extras", {}).get("lms_matches", []):
        faq_id = str(match.get("lms_faq_id") or "").strip()
        question = str(match.get("question") or match.get("branch_name") or "").strip()
        if not question:
            continue
        key = f"lms:{faq_id or question.lower()}"
        if key in seen:
            continue
        seen.add(key)
        entry = match.get("entry") or {}
        draft = faq_entry_to_draft_entry(entry, caller_type) if entry else {}
        items.append(
            {
                "source": "lms_faq",
                "issue_name": question,
                "lms_faq_id": faq_id,
                "score": match.get("score"),
                "problem_statement": draft.get("problem_statement", question),
                "resolution_steps": draft.get("resolution_steps", []),
                "policy": draft.get("policy", ""),
            }
        )

    return items


def serialize_issue_detail(issue: dict[str, Any]) -> dict[str, Any]:
    working_issue = dict(issue)
    draft = dict(working_issue.get("draft") or {})
    api_status = working_issue.get("api_status", working_issue.get("status"))
    if api_status == "drafted" and draft_needs_enrichment(draft, working_issue["caller_type"]):
        query = (
            working_issue.get("query")
            or working_issue.get("problem_statement")
            or working_issue["issue_name"]
        )
        matches = working_issue.get("possible_matches") or working_issue.get("extras", {}).get(
            "possible_matches", []
        )
        if not matches:
            from kb_search import find_possible_kb_matches

            matches = find_possible_kb_matches(
                query,
                working_issue["caller_type"],
                top_k=3,
            )
        if matches:
            draft = enrich_draft_entry(
                draft,
                query,
                working_issue["caller_type"],
                faiss_matches=matches,
            )
            working_issue["draft"] = draft

    form = _form_entry_from_issue(working_issue)
    return {
        "issue_id": working_issue["id"],
        "pending_id": working_issue.get("pending_id"),
        "query": working_issue.get("query") or working_issue.get("problem_statement") or working_issue["issue_name"],
        "caller_type": working_issue["caller_type"],
        "source_document": working_issue.get("source_document"),
        "status": api_status,
        "created_at": working_issue["created_at"],
        "updated_at": working_issue["updated_at"],
        "submitted_at": working_issue["created_at"],
        "draft": form,
        "form": form,
        "examples_used": working_issue.get("examples_used", []),
        "possible_matches": working_issue.get("possible_matches", []),
        "db_similar": working_issue.get("extras", {}).get("db_similar", []),
        "similar_issues": _similar_issues_for_detail(working_issue),
        "draft_error": working_issue.get("draft_error"),
        "setup_instructions": working_issue.get("setup_instructions"),
        "draft_source": working_issue.get("draft_source"),
        "template_issue_name": working_issue.get("template_issue_name"),
        "reject_reason": working_issue.get("reject_reason"),
        "branch_id": working_issue.get("branch_id"),
        "added_to_kb": working_issue.get("added_to_kb", False),
        "editable": api_status == "drafted",
        "approved_at": working_issue["updated_at"] if api_status == "approved" else None,
        "final_entry": form if api_status == "approved" else None,
        "llm_redraft_recommended": should_llm_redraft(working_issue),
        "llm_available": check_llm_available(),
    }


@router.get("/stats")
def get_supervisor_stats():
    return build_supervisor_stats()


def _serialize_pending_list_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "issue_id": item["id"],
        "pending_id": item.get("pending_id"),
        "query": item.get("query") or item["issue_name"],
        "issue_name": item["issue_name"],
        "caller_type": item["caller_type"],
        "status": item.get("api_status", "drafted"),
        "created_at": item["created_at"],
        "source_document": item.get("source_document"),
        "category_id": item.get("category_id"),
        "topic_cluster_id": item.get("topic_cluster_id"),
        "topic_label": item.get("topic_label"),
    }


@router.get("/topic-clusters")
def list_topic_clusters(caller_type: str | None = None):
    issues = get_pending_issues(caller_type)
    clustering = compute_topic_clusters(issues)
    return {
        "clusters": clustering["clusters"],
        "computed_at": clustering["computed_at"],
        "pending_count": len(issues),
    }


@router.get("/specializations/{supervisor_id}")
def get_specializations(supervisor_id: str):
    return get_supervisor_specializations(supervisor_id)


@router.put("/specializations")
def update_specializations(body: SpecializationsRequest):
    return set_supervisor_specializations(body.supervisor_id, body.cluster_ids)


@router.get("/issues/pending")
def list_db_pending_issues(
    caller_type: str | None = None,
    cluster_id: int | None = None,
    supervisor_id: str | None = None,
    my_clusters_only: bool = False,
):
    issues = get_pending_issues(caller_type)
    if cluster_id is not None or (my_clusters_only and supervisor_id):
        issues = filter_issues_by_cluster(
            issues,
            cluster_id=cluster_id,
            supervisor_id=supervisor_id,
            my_clusters_only=my_clusters_only,
        )
    else:
        clustering = compute_topic_clusters(issues)
        issues = [enrich_issue_with_topic(item, clustering) for item in issues]

    return {
        "issues": [_serialize_pending_list_item(item) for item in issues],
    }


@router.get("/issues/pending/{pending_id}")
def get_pending_issue_detail(pending_id: str):
    if pending_id.startswith("issue-"):
        issue = get_issue_by_id(int(pending_id.replace("issue-", "")))
    else:
        issue = get_issue_by_pending_id(pending_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Pending issue not found")

    return serialize_issue_detail(issue)


@router.post("/regenerate-draft")
def regenerate_draft(body: RegenerateDraftRequest):
    pending_id = body.pending_id
    issue_id = body.issue_id
    if not pending_id and issue_id is None:
        raise HTTPException(status_code=400, detail="pending_id or issue_id required")

    if not check_llm_available():
        raise HTTPException(
            status_code=503,
            detail="No AI provider is configured. Set ANTHROPIC_API_KEY, OPENAI_API_KEY or run Ollama.",
        )

    try:
        result = regenerate_pending_draft(
            pending_id=str(pending_id) if pending_id else None,
            issue_id=int(issue_id) if issue_id is not None else None,
            edited_entry=body.edited_entry,
        )
    except Exception as exc:
        logger.exception("regenerate-draft failed")
        raise HTTPException(
            status_code=500,
            detail=f"AI draft generation failed: {exc}",
        ) from exc

    if result.get("error"):
        raise HTTPException(status_code=400, detail=str(result["error"]))

    if pending_id:
        key = str(pending_id)
    else:
        key = f"issue-{issue_id}"
    if key.startswith("issue-"):
        issue = get_issue_by_id(int(key.replace("issue-", "")))
    else:
        issue = get_issue_by_pending_id(key)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found after regenerate")

    return serialize_issue_detail(issue)


@router.get("/issues/pending/{pending_id}/history")
def get_pending_issue_history(pending_id: str):
    if pending_id.startswith("issue-"):
        issue = get_issue_by_id(int(pending_id.replace("issue-", "")))
    else:
        issue = get_issue_by_pending_id(pending_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Pending issue not found")
    issue_id = int(issue["id"])
    return {"issue_id": issue_id, "history": get_issue_history(issue_id)}


@router.get("/issues/{issue_id}")
def get_issue_detail(issue_id: int):
    issue = get_issue_by_id(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return serialize_issue_detail(issue)


@router.get("/issues/{issue_id}/history")
def issue_history(issue_id: int):
    if not get_issue_by_id(issue_id):
        raise HTTPException(status_code=404, detail="Issue not found")
    return {"issue_id": issue_id, "history": get_issue_history(issue_id)}


@router.get("/issues/category/{category_id}")
def list_issues_for_category(category_id: str, caller_type: str | None = None):
    from json_store import get_issues_by_category

    return {
        "category_id": category_id,
        "issues": get_issues_by_category(category_id, caller_type),
    }


@router.post("/rebuild-kb")
def rebuild_kb_cache(
    body: RebuildKbRequest | None = None,
    caller_type: str | None = None,
):
    selected = body.caller_type if body else (caller_type or "seller")
    if selected not in ("seller", "buyer", "both"):
        raise HTTPException(
            status_code=400,
            detail="caller_type must be seller, buyer, or both",
        )
    caller_types = ["seller", "buyer"] if selected == "both" else [selected]
    start = time.perf_counter()
    branches_count = 0
    for ct in caller_types:
        result = rebuild_kb_from_db(ct)
        branches_count += int(result.get("total_branches", 0))
    time_ms = int((time.perf_counter() - start) * 1000)
    return {"rebuilt": True, "branches_count": branches_count, "time_ms": time_ms}


@router.post("/import-lms-faq")
def import_lms_faq_endpoint(body: ImportLmsFaqRequest | None = None):
    """Refresh FAQ supervisor index; strip FAQ rows from the agent KB."""
    opts = body or ImportLmsFaqRequest()
    try:
        return import_lms_faq(
            faq_path=opts.faq_path,
            dry_run=opts.dry_run,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


LLM_DRAFT_SOURCES = frozenset(
    {"llm_db_fewshot", "llm", "llm_format", "llm_polish"}
)
FAST_DRAFT_SOURCES = frozenset({"kb_fast_draft", "kb_template", "kb_template_fallback"})


@router.post("/queue")
def queue_resolution(body: QueueRequest):
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    caller_type = body.caller_type
    try:
        pending_id, issue_id = create_pending_issue(query, caller_type)
        drafted = draft_resolution_for_pending(
            pending_id,
            query,
            caller_type,
            possible_matches=body.possible_matches,
        )
    except Exception as exc:
        logger.exception("Supervisor queue failed for query=%r", query)
        raise HTTPException(status_code=500, detail=f"Queue submit failed: {exc}") from exc

    draft_entry = drafted.get("draft") or {}
    if not isinstance(draft_entry, dict):
        draft_entry = {}

    draft_source = drafted.get("draft_source")
    if draft_source in LLM_DRAFT_SOURCES:
        audit_action = "draft_generated"
    elif draft_source in FAST_DRAFT_SOURCES:
        audit_action = "kb_template_drafted"
    else:
        audit_action = "draft_failed"
    audit_notes = draft_source or drafted.get("error") or "unknown"
    log_issue_audit(issue_id, audit_action, notes=str(audit_notes))

    response: dict[str, Any] = {
        "pending_id": pending_id,
        "issue_id": issue_id,
        "draft": draft_entry,
        "status": "drafted",
        "draft_source": draft_source,
        "examples_used": drafted.get("examples_used", []),
        "kb_suggestions": drafted.get("possible_matches", []),
        "possible_matches": drafted.get("possible_matches", []),
        "db_similar": drafted.get("db_similar", []),
        "template_issue_name": drafted.get("template_issue_name"),
    }
    if drafted.get("error"):
        response["draft_error"] = drafted["error"]
        response["error"] = drafted["error"]
    return response


@router.get("/check-kb")
def check_kb_before_queue(query: str, caller_type: str = "seller"):
    from kb_search import find_possible_kb_matches

    trimmed = query.strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Query is required")

    possible_matches = find_possible_kb_matches(trimmed, caller_type, top_k=3)
    return {
        "status": "kb_match_found" if possible_matches else "no_kb_match",
        "kb_matches": possible_matches,
        "possible_matches": possible_matches,
        "caller_type": caller_type,
    }


@router.get("/pending")
def list_pending():
    """Backward-compatible queue list keyed by pending_id when present."""
    result = list_db_pending_issues()
    return [
        {
            "pending_id": item.get("pending_id") or f"issue-{item['id']}",
            "issue_id": item["id"],
            "query": item["query"],
            "status": item["status"],
            "created_at": item["created_at"],
            "caller_type": item["caller_type"],
            "topic_cluster_id": item.get("topic_cluster_id"),
            "topic_label": item.get("topic_label"),
        }
        for item in result["issues"]
    ]


@router.get("/pending/{pending_id}")
def get_pending(pending_id: str):
    if pending_id.startswith("issue-"):
        issue = get_issue_by_id(int(pending_id.replace("issue-", "")))
    else:
        issue = get_issue_by_pending_id(pending_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Pending resolution not found")
    return serialize_issue_detail(issue)


@router.post("/approve")
def approve_resolution(body: ApproveRequest):
    return _approve_pending(body, add_to_kb=False)


@router.post("/approve-and-add")
def approve_and_add_resolution(body: ApproveRequest):
    return _approve_pending(body, add_to_kb=True)


def _approve_pending(body: ApproveRequest, *, add_to_kb: bool) -> dict[str, Any]:
    issue = _resolve_issue(pending_id=body.pending_id, issue_id=body.issue_id)
    if issue.get("api_status") != "drafted":
        raise HTTPException(
            status_code=400,
            detail=f"Resolution is already {issue.get('api_status')}",
        )

    entry = body.edited_entry if body.edited_entry is not None else _form_entry_from_issue(issue)
    if not isinstance(entry, dict) or not entry:
        raise HTTPException(status_code=400, detail="No draft entry available to approve")

    if add_to_kb:
        validation_errors = validate_unified_entry(entry)
    else:
        validation_errors = validate_send_to_agent(entry)
    if validation_errors:
        raise HTTPException(status_code=400, detail="; ".join(validation_errors))

    topic_category = (body.topic_category or entry.get("topic_category") or "").strip()
    if add_to_kb and not topic_category:
        raise HTTPException(
            status_code=400,
            detail="topic_category is required — select a topic category before adding to KB",
        )

    supervisor_id = resolve_supervisor_id(body.approved_by)
    if body.pending_id and issue.get("pending_id"):
        branch = approve_issue_by_pending_id(
            issue["pending_id"],
            supervisor_id,
            entry,
            topic_category=topic_category or None,
            add_to_kb=add_to_kb,
        )
    else:
        branch = approve_issue(
            int(issue["id"]),
            supervisor_id,
            entry,
            topic_category=topic_category or None,
            add_to_kb=add_to_kb,
        )

    if add_to_kb:
        target_kb = body.target_kb or issue["caller_type"]
        rebuild_start = time.perf_counter()
        rebuild_result = rebuild_kb_from_db(target_kb)
        rebuild_ms = int((time.perf_counter() - rebuild_start) * 1000)
        logger.info(
            "KB rebuild after approve-and-add completed in %d ms (%s branches)",
            rebuild_ms,
            rebuild_result.get("total_branches", "?"),
        )

    response: dict[str, Any] = {
        "status": "approved",
        "added_to_kb": add_to_kb,
        "issue_id": issue["id"],
        "pending_id": issue.get("pending_id"),
    }
    if add_to_kb:
        response.update(
            {
                "branch_id": branch.get("branch_id"),
                "target_kb": body.target_kb or issue["caller_type"],
                "topic_category": topic_category,
            }
        )
    return response


@router.post("/reject")
def reject_resolution(body: RejectRequest):
    issue = _resolve_issue(pending_id=body.pending_id, issue_id=body.issue_id)
    if issue.get("api_status") != "drafted":
        raise HTTPException(
            status_code=400,
            detail=f"Resolution is already {issue.get('api_status')}",
        )

    supervisor_id = resolve_supervisor_id("supervisor")
    if issue.get("pending_id"):
        reject_issue_by_pending_id(issue["pending_id"], supervisor_id, body.reason)
    else:
        reject_issue_by_id(int(issue["id"]), supervisor_id, body.reason)

    return {
        "status": "rejected",
        "issue_id": issue["id"],
        "pending_id": issue.get("pending_id"),
    }


@router.post("/batch-approve")
def batch_approve_resolutions(body: BatchApproveRequest):
    if not body.pending_ids:
        raise HTTPException(status_code=400, detail="pending_ids is required")

    supervisor_id = resolve_supervisor_id(body.supervisor_id or "supervisor")
    result = batch_approve_issues(body.pending_ids, supervisor_id)

    for caller_type in result.get("caller_types", []):
        rebuild_kb_from_db(caller_type)

    return {
        "approved": result["approved"],
        "failed": result["failed"],
        "issue_ids": result["issue_ids"],
        "errors": result["errors"],
    }


@router.post("/batch-reject")
def batch_reject_resolutions(body: BatchRejectRequest):
    if not body.pending_ids:
        raise HTTPException(status_code=400, detail="pending_ids is required")

    supervisor_id = resolve_supervisor_id(body.supervisor_id or "supervisor")
    result = batch_reject_issues(body.pending_ids, supervisor_id, body.reason)

    return {
        "rejected": result["rejected"],
        "failed": result["failed"],
        "issue_ids": result["issue_ids"],
        "errors": result["errors"],
    }


@router.get("/categories")
def list_supervisor_categories(caller_type: str | None = None):
    return {"categories": list_db_categories(caller_type)}


@router.post("/categories")
def create_supervisor_category(body: CreateCategoryRequest):
    try:
        category = create_category(body.category_name, body.caller_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return category


@router.post("/categories/merge")
def merge_supervisor_categories(body: MergeCategoriesRequest):
    try:
        result = merge_categories(body.source_id, body.target_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rebuild_kb_from_db(result["caller_type"])
    return result


@router.put("/categories/{category_id}")
def rename_supervisor_category(category_id: str, body: RenameCategoryRequest):
    try:
        category = rename_category(category_id, body.category_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return category


@router.delete("/categories/{category_id}")
def delete_supervisor_category(category_id: str):
    try:
        return delete_category_if_empty(category_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
