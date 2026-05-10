"""
QOS-Buddy shared RAG service.

A standalone FastAPI wrapper around a persistent Chroma collection so every
agent (prediction, diagnostic, optimization, network-consultant) can read and
write the same incident memory instead of each pinning its own embedding
store. Designed to be the upgrade path for the prediction agent's
`rag/incident_store.py`.

Endpoints
---------
POST /ingest    bulk-upsert {id, text, metadata?}
POST /query     text → top-k {id, document, distance, metadata}
DELETE /collections/{name}   drop a collection (test/dev only)
GET  /health    readiness probe

Persistence is on the `RAG_PERSIST_DIR` path (default `/app/chroma`),
backed by the `qos-rag-data` docker volume in compose. The embedding
function is sentence-transformers/all-MiniLM-L6-v2 — same model the
prediction agent already pinned, so prior runs' embeddings stay
compatible if they're migrated in.
"""

from __future__ import annotations

import logging
import os
import hashlib
import json
import csv
import glob
from pathlib import Path
from typing import Any

import chromadb
import httpx
from chromadb.utils import embedding_functions
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

PERSIST_DIR = Path(os.getenv("RAG_PERSIST_DIR", "/app/chroma"))
DEFAULT_COLLECTION = os.getenv("RAG_DEFAULT_COLLECTION", "qos_incidents")
OPERATOR_MEMORY_COLLECTION = os.getenv("RAG_OPERATOR_MEMORY_COLLECTION", "qos_operator_memory")
USER_PREFERENCE_COLLECTION = os.getenv("RAG_USER_PREFERENCE_COLLECTION", "qos_user_preferences")
RUNBOOK_COLLECTION = os.getenv("RAG_RUNBOOK_COLLECTION", "qos_runbooks")
INCIDENT_DATA_DIR = Path(os.getenv("RAG_INCIDENT_DATA_DIR", "/app/incident-data"))
EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
PRIMARY_MODEL = os.getenv("LLM_PRIMARY", "qwen2.5:3b-instruct-q4_K_M")
FALLBACK_MODEL = os.getenv("LLM_FALLBACK", "llama3.2:3b-instruct-q4_K_M")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "8.0"))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("qos.rag")

PERSIST_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="QOS-Buddy RAG", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "RAG_CORS",
            "http://localhost:3000,http://127.0.0.1:3000,http://shell:3000",
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
_client = chromadb.PersistentClient(path=str(PERSIST_DIR))


@app.on_event("shutdown")
async def shutdown() -> None:
    log.info("Shutdown complete")

@app.on_event("startup")
async def startup() -> None:
    """Seed shared memory so chat/RAG returns value on first boot."""
    _seed_jsonl("seed_operator_memory.jsonl", OPERATOR_MEMORY_COLLECTION, "lesson")
    _seed_jsonl("seed_network_docs.jsonl", RUNBOOK_COLLECTION, "text")
    _seed_incidents()


def _seed_jsonl(filename: str, collection_name: str, text_key: str) -> None:
    seed_path = Path(__file__).with_name(filename)
    if not seed_path.exists():
        return
    try:
        coll = _collection(collection_name)
        items: list[IngestItem] = []
        with seed_path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                _id = str(obj.get("id") or "").strip()
                text = str(obj.get(text_key) or obj.get("lesson") or obj.get("text") or "").strip()
                if not _id or not text:
                    continue
                meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
                items.append(IngestItem(id=_id, text=text, metadata=meta))
        if not items:
            return
        coll.upsert(
            ids=[i.id for i in items],
            documents=[i.text for i in items],
            metadatas=[i.metadata if i.metadata else {"_src": "seed"} for i in items],
        )
        log.info("seeded collection=%s items=%d", collection_name, len(items))
    except Exception as exc:  # noqa: BLE001
        log.warning("memory seed failed collection=%s: %s", collection_name, exc)


def _seed_incidents() -> None:
    if not INCIDENT_DATA_DIR.exists():
        return
    try:
        coll = _collection(DEFAULT_COLLECTION)
        items: list[IngestItem] = []
        seen: set[str] = set()
        for path in sorted(glob.glob(str(INCIDENT_DATA_DIR / "incidents*.csv"))):
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    incident_id = str(row.get("incident_id") or "").strip()
                    if not incident_id or incident_id in seen:
                        continue
                    seen.add(incident_id)
                    incident_type = str(row.get("incident_type") or "incident").strip()
                    severity = str(row.get("severity") or "unknown").strip()
                    node_id = str(row.get("node_id") or "unknown").strip()
                    duration = str(row.get("duration_sec") or row.get("duration") or "unknown").strip()
                    score = str(row.get("max_score") or row.get("score") or "unknown").strip()
                    text = (
                        f"{incident_type} incident with {severity} severity on node {node_id}. "
                        f"Duration {duration} seconds. Maximum score {score}."
                    )
                    items.append(
                        IngestItem(
                            id=incident_id,
                            text=text,
                            metadata={
                                "source": "prediction_incidents_csv",
                                "incident_type": incident_type,
                                "severity": severity,
                                "node_id": node_id,
                                "duration_sec": duration,
                                "max_score": score,
                            },
                        )
                    )
        if not items:
            return
        coll.upsert(
            ids=[i.id for i in items],
            documents=[i.text for i in items],
            metadatas=[i.metadata for i in items],
        )
        log.info("seeded incidents collection=%s items=%d", DEFAULT_COLLECTION, len(items))
    except Exception as exc:  # noqa: BLE001
        log.warning("incident seed failed: %s", exc)


def _collection(name: str):
    return _client.get_or_create_collection(name=name, embedding_function=_embedding_fn)


class IngestItem(BaseModel):
    id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestRequest(BaseModel):
    collection: str = DEFAULT_COLLECTION
    items: list[IngestItem]
    replace: bool = False


class IngestResponse(BaseModel):
    collection: str
    upserted: int


class QueryRequest(BaseModel):
    collection: str = DEFAULT_COLLECTION
    text: str
    top_k: int = 3


class QueryHit(BaseModel):
    id: str
    document: str
    distance: float | None
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    hits: list[QueryHit]


class VoiceQueryRequest(BaseModel):
    transcript: str
    context: dict[str, Any] = Field(default_factory=dict)


class MemorySaveRequest(BaseModel):
    lesson: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemorySearchRequest(BaseModel):
    q: str
    top_k: int = 3


class PreferenceRequest(BaseModel):
    user_id: str
    preference_type: str
    value: Any


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "persist_dir": str(PERSIST_DIR), "embedding_model": EMBEDDING_MODEL}


@app.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest) -> IngestResponse:
    if not req.items:
        return IngestResponse(collection=req.collection, upserted=0)

    if req.replace:
        try:
            _client.delete_collection(req.collection)
        except Exception:  # noqa: BLE001
            pass

    coll = _collection(req.collection)
    # Chroma 0.5 rejects empty metadata dicts — use a sentinel key when caller
    # doesn't supply metadata so upsert always gets a non-empty dict.
    metadatas = [i.metadata if i.metadata else {"_src": "qos"} for i in req.items]
    coll.upsert(
        ids=[i.id for i in req.items],
        documents=[i.text for i in req.items],
        metadatas=metadatas,
    )
    return IngestResponse(collection=req.collection, upserted=len(req.items))


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    if not req.text.strip():
        return QueryResponse(hits=[])
    coll = _collection(req.collection)
    try:
        res = coll.query(query_texts=[req.text], n_results=max(1, req.top_k))
    except Exception as exc:
        log.exception("chroma query failed")
        raise HTTPException(status_code=500, detail=f"query failed: {exc}") from exc

    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    dists = (res.get("distances") or [[None] * len(ids)])[0]
    metas = (res.get("metadatas") or [[]])[0]
    hits = [
        QueryHit(
            id=ids[i],
            document=docs[i] if i < len(docs) else "",
            distance=float(dists[i]) if i < len(dists) and dists[i] is not None else None,
            metadata=metas[i] if i < len(metas) else {},
        )
        for i in range(len(ids))
    ]
    return QueryResponse(hits=hits)


@app.post("/api/voice-query")
async def voice_query(body: VoiceQueryRequest) -> dict[str, str]:
    transcript = body.transcript.strip()
    if not transcript:
        return {"answer": "I did not catch a question to search for."}

    coll = _collection(OPERATOR_MEMORY_COLLECTION)
    try:
        results = coll.query(query_texts=[transcript], n_results=3)
    except Exception as exc:  # noqa: BLE001
        log.exception("voice query failed")
        raise HTTPException(status_code=500, detail=f"voice query failed: {exc}") from exc

    documents = (results.get("documents") or [[]])[0]
    if not documents:
        # Still respond with a best-effort one-liner so voice never feels broken.
        answer = await _generate(
            system=(
                "You answer NOC operator voice queries in one spoken sentence. "
                "No technical jargon. Provide one next check."
            ),
            user=f"Query: {transcript}",
        )
        return {"answer": answer or "No matching lesson yet — check live KPIs and record the resolution as a new operator lesson."}

    context = "\n".join(str(doc) for doc in documents if doc)
    answer = await _generate(
        system=(
            "You answer NOC operator voice queries in one spoken sentence. "
            "No technical jargon."
        ),
        user=f"Query: {transcript}\n\nRelevant lessons:\n{context}",
    )
    return {"answer": answer or _voice_fallback(transcript, documents)}


@app.post("/api/memory/save")
def save_memory(body: MemorySaveRequest) -> dict[str, Any]:
    lesson = body.lesson.strip()
    if not lesson:
        raise HTTPException(status_code=400, detail="lesson is required")
    coll = _collection(OPERATOR_MEMORY_COLLECTION)
    metadata = body.metadata if body.metadata else {"_src": "reporting"}
    memory_id = str(metadata.get("event_id") or f"lesson-{hashlib.sha256(lesson.encode('utf-8')).hexdigest()[:16]}")
    coll.upsert(ids=[memory_id], documents=[lesson], metadatas=[metadata])
    return {"saved": True, "id": memory_id}


@app.post("/api/memory/search")
def search_memory(body: MemorySearchRequest) -> dict[str, Any]:
    query_text = body.q.strip()
    if not query_text:
        return {"hits": []}
    coll = _collection(OPERATOR_MEMORY_COLLECTION)
    res = coll.query(query_texts=[query_text], n_results=max(1, body.top_k))
    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    dists = (res.get("distances") or [[None] * len(ids)])[0]
    metas = (res.get("metadatas") or [[]])[0]
    return {
        "hits": [
            {
                "id": ids[i],
                "lesson": docs[i] if i < len(docs) else "",
                "distance": float(dists[i]) if i < len(dists) and dists[i] is not None else None,
                "metadata": metas[i] if i < len(metas) else {},
            }
            for i in range(len(ids))
        ]
    }


@app.post("/api/memory/preference")
def save_preference(body: PreferenceRequest) -> dict[str, Any]:
    preference_type = body.preference_type.strip()
    if preference_type not in {"preferred_page", "alert_filter", "cell_focus"}:
        raise HTTPException(status_code=400, detail="unknown preference_type")
    user_id = body.user_id.strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    value_json = json.dumps(body.value, separators=(",", ":"), sort_keys=True)
    pref_id = f"pref-{hashlib.sha256(f'{user_id}:{preference_type}'.encode('utf-8')).hexdigest()[:24]}"
    coll = _collection(USER_PREFERENCE_COLLECTION)
    coll.upsert(
        ids=[pref_id],
        documents=[f"{preference_type}: {value_json}"],
        metadatas=[
            {
                "user_id": user_id,
                "preference_type": preference_type,
                "value_json": value_json,
            }
        ],
    )
    return {"saved": True, "id": pref_id}


@app.get("/api/memory/preference/{user_id}")
def get_preferences(user_id: str) -> dict[str, Any]:
    coll = _collection(USER_PREFERENCE_COLLECTION)
    res = coll.get(where={"user_id": user_id})
    preferences: dict[str, Any] = {}
    for meta in res.get("metadatas") or []:
        if not isinstance(meta, dict):
            continue
        pref_type = str(meta.get("preference_type") or "")
        raw_value = str(meta.get("value_json") or "null")
        try:
            preferences[pref_type] = json.loads(raw_value)
        except json.JSONDecodeError:
            preferences[pref_type] = raw_value
    return {"user_id": user_id, "preferences": preferences}


@app.delete("/collections/{name}")
def drop(name: str) -> dict[str, Any]:
    try:
        _client.delete_collection(name)
        return {"deleted": name}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def _generate(system: str, user: str) -> str:
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            async with httpx.AsyncClient(base_url=OLLAMA_URL, timeout=LLM_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    "/api/generate",
                    json={
                        "model": model,
                        "prompt": f"<|system|>\n{system}\n<|user|>\n{user}\n<|assistant|>\n",
                        "stream": False,
                        "options": {
                            "temperature": 0.2,
                            "num_predict": 80,
                            "top_p": 0.9,
                        },
                    },
                )
                resp.raise_for_status()
                text = (resp.json().get("response") or "").strip()
                if text:
                    return text.splitlines()[0].strip()
        except Exception as exc:  # noqa: BLE001
            log.debug("voice llm failed model=%s: %s", model, exc)
    return ""


def _voice_fallback(transcript: str, documents: list[str]) -> str:
    lesson = str(documents[0]).strip()
    if not lesson:
        return "No matching lessons found in operator memory."
    return lesson[:220]
