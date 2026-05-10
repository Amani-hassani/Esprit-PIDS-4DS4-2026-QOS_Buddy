FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/.cache/hf \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/st

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && \
    pip install \
      "fastapi>=0.110" \
      "uvicorn[standard]>=0.27" \
      "pydantic>=2.6" \
      "chromadb>=0.5,<0.6" \
      "sentence-transformers>=2.7"

COPY rag-service/main.py /app/main.py
COPY rag-service/seed_operator_memory.jsonl /app/seed_operator_memory.jsonl
COPY rag-service/seed_network_docs.jsonl /app/seed_network_docs.jsonl

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=20 --start-period=60s \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
