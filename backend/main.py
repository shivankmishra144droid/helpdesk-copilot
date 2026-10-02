import env_file  # noqa: F401  (must run before modules read settings)
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
from pathlib import Path

from sentence_transformers import SentenceTransformer

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from ingest import ingest_file, ingest_text_into_kb, load_kb, scan_all_inboxes, scan_inbox
from concurrency import STORE_LOCK
from inbox_watcher import InboxWatcher
from category_utils import (
    category_name_by_id,
    count_branches_by_category,
    load_topic_categories,
)
from kb_manager import (
    DEFAULT_SYNONYM_GROUPS,
    VALID_CALLER_TYPES,
    KnowledgeRegistry,
    bind_registry,
    kb_path,
    normalize_caller_type,
)
from kb_search import (
    build_issue_path,
    get_agent_script,
    hybrid_search,
    normalize_query,
    search_kb_with_outlier_gate,
)
from outlier_gate import (
    get_outlier_status,
    is_model_available,
    is_outlier,
    preload_outlier_models,
    suggested_queries,
)
from model_io import model_file_report
from xgboost_ranker import get_ranker_health, load_xgboost_ranker
from cross_encoder_reranker import get_cross_encoder_health
from intent_classifier import get_intent_classifier_status
from query_corrector import get_query_corrector_status
from llm import check_llm_available, get_llm_status
from json_store import (
    count_buyer_active_branches,
    count_json_db_branches,
    count_pending_review_issues,
    count_seller_active_branches,
    count_total_issues,
    get_kb_sync_stats,
    get_metadata,
    rebuild_kb_from_db,
    upload_manual_pdf,
)
from request_guard import install_request_guard
from supervisor import router as supervisor_router

LLM_AVAILABLE = False


EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
SEARCH_TOP_K = 10
# Agent UI: hide results below MIN; offer supervisor escalation when the top hit is below WEAK.
SEARCH_MIN_MATCH_SCORE = 0.28
SEARCH_WEAK_MATCH_SCORE = 0.45
# Model loads on first use (startup), not at import, so tests/tools can import main cheaply.
KB_REGISTRY = KnowledgeRegistry(lambda: SentenceTransformer(EMBED_MODEL_NAME))
bind_registry(KB_REGISTRY)


def _kb_paths() -> dict[str, Path]:
    return {caller_type: kb_path(caller_type) for caller_type in VALID_CALLER_TYPES}


def ingest_drop_folders() -> dict:
    summary = scan_all_inboxes(_kb_paths())
    KB_REGISTRY.reload_all()
    return summary


def _on_inbox_ingested(caller_type: str, summary: dict) -> None:
    KB_REGISTRY.reload(caller_type)
    files = [item.get("file") for item in summary.get("files_ingested", [])]
    logger.info("Reloaded %s KB after inbox ingest: %s", caller_type, files)


INBOX_WATCHER = InboxWatcher(on_ingested=_on_inbox_ingested)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global LLM_AVAILABLE

    ingest_drop_folders()
    KB_REGISTRY.reload_all()
    seller_store = KB_REGISTRY.get("seller")
    buyer_store = KB_REGISTRY.get("buyer")
    logger.info(
        "Startup complete: %s seller, %s buyer branches loaded",
        len(seller_store.branches),
        len(buyer_store.branches),
    )
    ranker = load_xgboost_ranker()
    if ranker:
        logger.info(
            "XGBoost ranker loaded (%s)",
            ", ".join(sorted(ranker.get("models", {}).keys())),
        )
    else:
        logger.info(
            "XGBoost ranker not found — using hybrid 0.7*semantic + 0.3*keyword scoring"
        )
    ce_health = get_cross_encoder_health()
    if ce_health.get("enabled"):
        logger.info(
            "Cross-encoder configured: mode=%s model=%s (lazy load)",
            ce_health.get("configured_mode"),
            ce_health.get("model"),
        )
    else:
        logger.info("Cross-encoder disabled — set CROSS_ENCODER_ENABLED=true to enable")
    outlier_loaded = preload_outlier_models()
    if outlier_loaded:
        logger.info("Outlier gate loaded for: %s", ", ".join(outlier_loaded))
    else:
        logger.info("Outlier gate models not found — search gate disabled")
    LLM_AVAILABLE = check_llm_available()
    llm_status = get_llm_status()
    if LLM_AVAILABLE:
        logger.info("AI drafting via %s (%s)", llm_status["provider"], llm_status["model"])
    else:
        logger.warning(
            "AI drafting off (%s) — supervisor drafts use KB templates",
            llm_status["detail"],
        )

    INBOX_WATCHER.start()
    logger.info("Inbox watcher running — drop .txt/.pdf into knowledge/*/inbox/")
    yield
    INBOX_WATCHER.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(supervisor_router)
install_request_guard(app)  # before CORS so CORS wraps (and decorates) its 403s

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DiagnoseRequest(BaseModel):
    query: str = ""
    caller_type: str = "seller"
    topic_category: str | None = None


class SelectBranchRequest(BaseModel):
    branch_id: str
    caller_type: str = "seller"


class VerifyStepRequest(BaseModel):
    branch_id: str
    step_index: int
    status: str  # "done" or "blocked"
    caller_type: str = "seller"


class IngestTextRequest(BaseModel):
    text: str
    source_name: str = "paste"
    caller_type: str = "seller"


def get_branch_steps(branch: dict) -> list:
    steps = branch.get("steps")
    if isinstance(steps, list) and steps:
        return list(steps)

    if isinstance(steps, dict):
        merged: list = []
        for value in steps.values():
            if isinstance(value, list):
                merged.extend(value)
        if merged:
            return merged

    fallback: list = []
    for key, value in branch.items():
        if key.startswith("steps_") and isinstance(value, list):
            fallback.extend(value)

    return fallback if fallback else ["Contact the support team for assistance."]


def get_branch_documents(branch: dict) -> list:
    docs: list = []
    if "documents" in branch:
        if isinstance(branch["documents"], list):
            docs = list(branch["documents"])
        elif isinstance(branch["documents"], dict):
            for value in branch["documents"].values():
                if isinstance(value, list):
                    docs.extend(value)

    for key, value in branch.items():
        if key.startswith("documents_") and isinstance(value, list):
            docs.extend(value)

    seen = set()
    unique_docs = []
    for doc in docs:
        if doc not in seen:
            seen.add(doc)
            unique_docs.append(doc)

    return unique_docs if unique_docs else ["No specific documents required"]


def build_branch_response(branch: dict, store) -> dict:
    return {
        "branch_id": branch["branch_id"],
        "branch_name": branch["branch_name"],
        "category_id": store.category["id"],
        "category_name": store.category["name"],
        "path": build_issue_path(branch, store.category, store.caller_type),
        "agent_script": get_agent_script(branch),
        "steps": get_branch_steps(branch),
        "documents": get_branch_documents(branch),
        "escalation": branch.get("escalation", "Support Desk"),
        "escalation_person": branch.get("escalation_person", "Support Desk"),
    }


def find_branch_by_id(branch_id: str, store) -> dict | None:
    return store.branch_by_id.get(branch_id)


def search_results_response(
    query: str, caller_type: str, topic_category: str | None = None
) -> dict:
    return search_kb_with_outlier_gate(
        query,
        caller_type,
        top_k=SEARCH_TOP_K,
        topic_category=topic_category,
    )


@app.get("/search/check-query")
def check_query(query: str, caller_type: str = "seller"):
    """Real-time outlier check for debounced frontend validation."""
    normalized = normalize_query(query)
    if not normalized:
        return {
            "status": "ok",
            "is_outlier": False,
            "anomaly_score": 0.0,
            "model_loaded": is_model_available(caller_type),
            "suggested_queries": [],
        }

    result = is_outlier(query, caller_type)
    payload = {
        "status": "outlier" if result["is_outlier"] else "ok",
        "query": normalized,
        "caller_type": normalize_caller_type(caller_type),
        "is_outlier": result["is_outlier"],
        "anomaly_score": result["anomaly_score"],
        "model_loaded": result.get("model_loaded", False),
        "suggested_queries": suggested_queries(caller_type) if result["is_outlier"] else [],
    }
    if result["is_outlier"]:
        from outlier_gate import OUTLIER_MESSAGE

        payload["message"] = OUTLIER_MESSAGE
    return payload


def selected_branch_response(branch: dict, store) -> dict:
    topic_id = branch.get("topic_category")
    return {
        "status": "diagnosed",
        "branch": build_branch_response(branch, store),
        "confidence": "high",
        "problem": store.data.get("problem_name", store.category["name"]),
        "category_id": store.category["id"],
        "category_name": store.category["name"],
        "topic_category": topic_id,
        "topic_category_name": category_name_by_id(store.caller_type, topic_id),
        "path": build_issue_path(branch, store.category, store.caller_type),
    }


def run_search(body: DiagnoseRequest) -> dict:
    result = search_results_response(
        body.query, body.caller_type, body.topic_category
    )
    if result.get("predicted_category") or result.get("correction_applied"):
        logger.info(
            "Search NLP: caller=%s original=%r corrected=%r category=%s confidence=%.2f",
            result.get("caller_type"),
            result.get("original_query", body.query),
            result.get("corrected_query", body.query),
            result.get("predicted_category"),
            result.get("intent_confidence", 0.0),
        )
    return result


@app.post("/search")
def search(body: DiagnoseRequest):
    return run_search(body)


@app.post("/select-branch")
def select_branch(body: SelectBranchRequest):
    store = KB_REGISTRY.get(body.caller_type)
    branch = find_branch_by_id(body.branch_id, store)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    return selected_branch_response(branch, store)


@app.post("/verify-step")
def verify_step(body: VerifyStepRequest):
    store = KB_REGISTRY.get(body.caller_type)
    branch = find_branch_by_id(body.branch_id, store)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    steps = get_branch_steps(branch)

    if body.status == "blocked":
        docs = get_branch_documents(branch)
        return {
            "status": "blocked",
            "message": "Do not proceed to the next step. This issue is blocked.",
            "action": "Escalate immediately to "
            + branch.get("escalation", "Support Desk"),
            "escalation_person": branch.get("escalation_person", "Support Desk"),
            "documents_needed": docs,
        }

    next_step = body.step_index + 1
    if next_step >= len(steps):
        docs = get_branch_documents(branch)
        escalation = branch.get("escalation", "Support Desk")
        person = branch.get("escalation_person", "")
        return {
            "status": "completed",
            "message": "All steps verified. Issue should be resolved.",
            "documents_to_collect": docs,
            "escalation_if_still_failing": f"{escalation} ({person})".strip(),
        }

    return {
        "status": "next_step",
        "step_index": next_step,
        "step_text": steps[next_step],
        "progress": f"{next_step + 1} of {len(steps)}",
    }


@app.post("/ingest")
async def ingest_document(
    file: UploadFile = File(...),
    caller_type: str = Form("seller"),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    normalized = normalize_caller_type(caller_type)
    path = kb_path(normalized)

    try:
        # Parsing + re-embedding is blocking; keep it off the event loop.
        stats = await run_in_threadpool(ingest_file, path, data, file.filename)
        reload_info = await run_in_threadpool(KB_REGISTRY.reload, normalized)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "ingested",
        "filename": file.filename,
        "caller_type": normalized,
        **stats,
        **reload_info,
    }


@app.post("/ingest/inbox")
def ingest_inbox(caller_type: str | None = None):
    """Scan knowledge/{seller|buyer}/inbox/ for .txt/.pdf files and ingest them."""
    if caller_type:
        normalized = normalize_caller_type(caller_type)
        summary = {normalized: scan_inbox(kb_path(normalized))}
        KB_REGISTRY.reload(normalized)
    else:
        summary = ingest_drop_folders()

    return {"status": "inbox_scan_complete", "results": summary}


@app.post("/ingest/text")
def ingest_text(body: IngestTextRequest):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="No text provided")

    normalized = normalize_caller_type(body.caller_type)
    path = kb_path(normalized)
    with STORE_LOCK:
        kb = load_kb(path)
        stats = ingest_text_into_kb(kb, body.text, source_name=body.source_name)
        KB_REGISTRY.save(normalized, kb)
        reload_info = KB_REGISTRY.reload(normalized)

    return {
        "status": "ingested",
        "source": body.source_name,
        "caller_type": normalized,
        **stats,
        **reload_info,
    }


@app.get("/branches")
def list_branches(caller_type: str = "seller", topic_category: str | None = None):
    store = KB_REGISTRY.get(caller_type)
    branches = store.branches
    if topic_category:
        branches = [
            branch
            for branch in branches
            if branch.get("topic_category") == topic_category
        ]
    return {
        "caller_type": store.caller_type,
        "kb_name": store.data.get("kb_name", store.caller_type),
        "topic_category": topic_category,
        "total": len(branches),
        "branches": [
            {
                "branch_id": branch["branch_id"],
                "branch_name": branch["branch_name"],
                "topic_category": branch.get("topic_category"),
            }
            for branch in branches
        ],
    }


@app.get("/search/config")
def search_config(caller_type: str = "seller"):
    """Display tuning the agent UI needs, so it isn't duplicated in the frontend."""
    store = KB_REGISTRY.get(caller_type)
    return {
        "caller_type": store.caller_type,
        "synonym_groups": store.data.get("synonym_groups", DEFAULT_SYNONYM_GROUPS),
        "min_match_score": SEARCH_MIN_MATCH_SCORE,
        "weak_match_score": SEARCH_WEAK_MATCH_SCORE,
    }


@app.get("/topic-categories")
def topic_categories(caller_type: str = "seller"):
    store = KB_REGISTRY.get(caller_type)
    categories = load_topic_categories(store.caller_type)
    return {
        "caller_type": store.caller_type,
        "categories": count_branches_by_category(store.branches, categories),
    }


@app.post("/manuals/upload")
async def upload_manual(
    file: UploadFile = File(...),
    caller_type: str = Form("seller"),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    lower = file.filename.lower()
    if not lower.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF manuals are supported")

    try:
        result = await run_in_threadpool(
            upload_manual_pdf, data, file.filename, caller_type=caller_type
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "parsed", **result}


@app.get("/health")
def health():
    seller = KB_REGISTRY.get("seller")
    buyer = KB_REGISTRY.get("buyer")

    seller_faiss = seller.faiss_index is not None
    buyer_faiss = buyer.faiss_index is not None
    llm = get_llm_status()
    sync_stats = get_kb_sync_stats()
    ranker = get_ranker_health()
    cross_encoder = get_cross_encoder_health()
    outlier = get_outlier_status()
    intent_classifier = get_intent_classifier_status()
    query_corrector = get_query_corrector_status()

    return {
        "status": "ok",
        "db": {
            "seller_active": count_seller_active_branches(),
            "buyer_active": count_buyer_active_branches(),
            "pending_review": count_pending_review_issues(),
            "total_issues": count_total_issues(),
        },
        "cache": {
            "json_seller": count_json_db_branches("seller"),
            "json_buyer": count_json_db_branches("buyer"),
            "faiss_loaded": seller_faiss and buyer_faiss,
        },
        "ml": {
            "embedding_model": EMBED_MODEL_NAME,
            "faiss_seller_loaded": seller_faiss,
            "faiss_buyer_loaded": buyer_faiss,
            "xgboost": ranker,
            "cross_encoder": cross_encoder,
            "ranking_mode": cross_encoder.get(
                "ranking_mode", ranker.get("ranking_mode", "hybrid_fallback")
            ),
            "outlier": outlier,
            "outlier_status": outlier.get("status", "disabled"),
            "intent_classifier": intent_classifier,
            "query_corrector": query_corrector,
            "model_files": model_file_report(),
        },
        "sync": {
            "seller_synced": sync_stats["caller_types"]["seller"]["in_sync"],
            "buyer_synced": sync_stats["caller_types"]["buyer"]["in_sync"],
            "last_rebuild": get_metadata("last_rebuild"),
        },
        "llm": llm,
    }
