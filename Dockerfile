# Single-container image for a public demo (e.g. a Hugging Face Docker Space).
# The browser only talks to Next.js on $PORT; Next proxies /api/* to the FastAPI
# backend on 127.0.0.1:8000 inside the container. For local development use
# docker-compose.yml instead (separate services).

FROM node:22-bookworm-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV NEXT_PUBLIC_API_BASE=/api
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf-cache \
    NODE_ENV=production \
    DEMO_MODE=true \
    SEARCH_TELEMETRY_ENABLED=false \
    PORT=7860

# Node runtime for `next start` (same Debian base, so the binary is compatible).
COPY --from=web /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY backend/ backend/
COPY scripts/ scripts/
# Model files aren't committed; train them from the synthetic data (a few minutes).
RUN python scripts/train_all.py
COPY deploy/start.sh start.sh
COPY --from=web /app/frontend frontend/

# Spaces run the container as uid 1000; the app writes approvals to backend/knowledge.
RUN useradd --create-home --uid 1000 user \
    && mkdir -p /app/.runtime \
    && chown -R user:user /app /opt/hf-cache
USER user

EXPOSE 7860
CMD ["bash", "/app/start.sh"]
