# Build from the repo root: docker build -f backend/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf-cache

WORKDIR /app/backend

# CPU-only torch keeps the image small (the default wheel bundles CUDA).
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model into the image so the container starts offline.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY backend/ .
COPY scripts/ /app/scripts/
# Model files aren't committed; train them from the synthetic data.
RUN python /app/scripts/train_all.py

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/.runtime \
    && chown -R app:app /app /opt/hf-cache
USER app

EXPOSE 8000
# One worker: the JSON stores use an in-process lock (see concurrency.py).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
