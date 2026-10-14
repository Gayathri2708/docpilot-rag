# DocPilot as a public, read-only demo. Defaults below are the safe public settings; override any
# of them with environment variables. Secrets (DATABASE_URL, LLM_API_KEY) come from the host at
# runtime and are never baked into the image.
FROM python:3.12-slim

# Hugging Face Spaces runs containers as UID 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/home/user/models
WORKDIR /home/user/app

COPY --chown=user backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir --user -r backend/requirements.txt

COPY --chown=user backend/app backend/app
COPY --chown=user evals/sample_docs sample_docs

# Download the embedding model and reranker at build time, so a cold start doesn't fetch ~150 MB.
RUN cd backend && python -c "from app.embeddings import _model, _reranker; _model(); _reranker()"

ENV PORT=7860 \
    SEED_DEMO_KEYS=false \
    PUBLIC_DEMO_KEY=dp_public_demo \
    PRELOAD_DIR=/home/user/app/sample_docs \
    UPLOADS_ENABLED=false \
    RATE_LIMIT_PER_MINUTE=6 \
    ASK_DAILY_LIMIT=100 \
    TRUST_PROXY_HEADERS=true \
    RETRIEVAL_MODE=hybrid \
    RERANK=false \
    LLM_BASE_URL=https://api.groq.com/openai/v1 \
    LLM_MODEL=openai/gpt-oss-20b

EXPOSE 7860
WORKDIR /home/user/app/backend
# One worker: the rate limits are kept in process memory.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
