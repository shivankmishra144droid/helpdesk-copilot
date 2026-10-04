"""Put a few unresolved demo questions into the supervisor queue.

    py -3 scripts/seed_demo_queue.py

Uses the same functions as the agent's "send to supervisor" button, with
KB-template drafts (no LLM call). Skips if the queue already has pending items.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import demo_content  # noqa: E402
from json_store import (  # noqa: E402
    count_pending_review_issues,
    create_pending_issue,
    draft_resolution_for_pending,
    log_issue_audit,
)
from kb_manager import KnowledgeRegistry, bind_registry  # noqa: E402
from embedding_model import SentenceTransformer  # noqa: E402


def main() -> None:
    if count_pending_review_issues():
        print("Supervisor queue already has pending items; nothing to do.")
        return
    registry = KnowledgeRegistry(SentenceTransformer("all-MiniLM-L6-v2"))
    bind_registry(registry)
    registry.reload_all()
    for caller_type, query in demo_content.DEMO_PENDING_QUERIES:
        pending_id, issue_id = create_pending_issue(query, caller_type)
        drafted = draft_resolution_for_pending(pending_id, query, caller_type)
        log_issue_audit(issue_id, "kb_template_drafted", notes=str(drafted.get("draft_source")))
        print(f"queued #{issue_id} [{caller_type}] {query!r} ({drafted.get('draft_source')})")


if __name__ == "__main__":
    main()
