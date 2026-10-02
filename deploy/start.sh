#!/usr/bin/env bash
# Entrypoint for the single-container demo image (see the root Dockerfile).
set -euo pipefail

# A few unresolved questions so the supervisor queue isn't empty on first visit.
python /app/scripts/seed_demo_queue.py || echo "Demo queue seeding skipped"

cd /app/backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1 &

cd /app/frontend
node node_modules/next/dist/bin/next start -H 0.0.0.0 -p "${PORT:-7860}" &

# Exit (and let the platform restart us) if either process dies.
wait -n
exit $?
