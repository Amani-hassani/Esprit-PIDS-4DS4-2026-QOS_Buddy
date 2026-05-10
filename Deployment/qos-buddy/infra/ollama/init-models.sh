#!/bin/sh
# Pull Qwen2.5-3B (primary) and Llama 3.2-3B (fallback) on first boot.
# Idempotent — `ollama pull` is a no-op if the model is already present.

set -eu

OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
PRIMARY_MODEL="${PRIMARY_MODEL:-qwen2.5:3b-instruct-q4_K_M}"
FALLBACK_MODEL="${FALLBACK_MODEL:-llama3.2:3b-instruct-q4_K_M}"

echo "[ollama-init] waiting for ollama at ${OLLAMA_HOST}..."
until wget -q -O - "${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; do
  sleep 2
done

echo "[ollama-init] pulling primary: ${PRIMARY_MODEL}"
wget -q -O - --post-data="{\"name\":\"${PRIMARY_MODEL}\"}" \
  --header="Content-Type: application/json" \
  "${OLLAMA_HOST}/api/pull" | tail -c 200 || true

echo "[ollama-init] pulling fallback: ${FALLBACK_MODEL}"
wget -q -O - --post-data="{\"name\":\"${FALLBACK_MODEL}\"}" \
  --header="Content-Type: application/json" \
  "${OLLAMA_HOST}/api/pull" | tail -c 200 || true

echo "[ollama-init] done. Available models:"
wget -q -O - "${OLLAMA_HOST}/api/tags"
