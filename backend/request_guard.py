"""Reject state-changing requests that didn't come from the Helpdesk Copilot frontend.

The API has no user accounts. Without this, any website open in the agent's
browser could POST a multipart form to http://localhost:8000/ingest (forms skip
CORS preflight). Requiring a custom header forces a preflight, which CORS only
grants to the local frontend origins.

Set COPILOT_API_TOKEN (and the frontend's NEXT_PUBLIC_API_TOKEN to match) to also
require a shared secret, e.g. if the backend is ever bound to a LAN address.

DEMO_MODE=true (for a public demo) additionally refuses file uploads, bulk
re-imports and destructive category changes; searching, step verification and
supervisor review/approval keep working.
"""

from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

CLIENT_HEADER = "x-copilot-client"
TOKEN_HEADER = "x-api-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# (method or "*", path prefix) refused when DEMO_MODE is on.
DEMO_BLOCKED = (
    ("*", "/ingest"),
    ("*", "/manuals/upload"),
    ("*", "/supervisor/import-lms-faq"),
    ("*", "/supervisor/rebuild-kb"),
    ("*", "/supervisor/categories/merge"),
    ("DELETE", "/supervisor/categories/"),
)


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def _blocked_in_demo(method: str, path: str) -> bool:
    return any(
        (rule_method in ("*", method)) and path.startswith(prefix)
        for rule_method, prefix in DEMO_BLOCKED
    )


def install_request_guard(app: FastAPI) -> None:
    """Register the guard. Call before adding CORSMiddleware so CORS stays outermost."""

    @app.middleware("http")
    async def require_frontend_client(request: Request, call_next):
        if request.method not in SAFE_METHODS:
            if not request.headers.get(CLIENT_HEADER):
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"Missing {CLIENT_HEADER} header"},
                )
            expected = os.environ.get("COPILOT_API_TOKEN", "")
            if expected and not hmac.compare_digest(
                request.headers.get(TOKEN_HEADER, ""), expected
            ):
                return JSONResponse(status_code=401, content={"detail": "Invalid API token"})
            if demo_mode() and _blocked_in_demo(request.method, request.url.path):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "This action is disabled in the public demo."},
                )
        return await call_next(request)
