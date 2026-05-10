"""ChromaDB-backed incident retrieval (RAG)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import logging
import re

import chromadb
import numpy as np
import pandas as pd
from chromadb.utils import embedding_functions

from config import RAG_CHROMA_DIR
from data_pipeline.loader import load_incidents

logger = logging.getLogger(__name__)


def _scalar_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    arr = np.asarray(val, dtype=float).ravel()
    if arr.size == 0:
        return None
    return float(arr[0])


class IncidentStore:
    """Persistent Chroma store embedding incident narratives."""

    def __init__(self, persist_dir: Path | None = None, collection_name: str = "qos_incidents") -> None:
        self.persist_dir = Path(persist_dir) if persist_dir is not None else RAG_CHROMA_DIR
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.disabled_reason: str | None = None
        self._embedding_fn = None
        self._client = None
        self._collection = None
        try:
            self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="sentence-transformers/all-MiniLM-L6-v2"
            )
            self._client = chromadb.PersistentClient(path=str(self.persist_dir))
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                embedding_function=self._embedding_fn,
            )
        except Exception as exc:
            self.disabled_reason = f"{type(exc).__name__}: {exc}"
            logger.warning("IncidentStore disabled: %s", self.disabled_reason)

    @staticmethod
    def _incident_text(row: pd.Series) -> str:
        return (
            f"{row.get('incident_type', '')} severity={row.get('severity', '')} "
            f"node={row.get('node_id', '')} duration={row.get('duration_sec', '')} "
            f"score={row.get('max_score', '')}"
        ).strip()

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {token for token in re.findall(r"[a-zA-Z0-9_.-]+", text.lower()) if len(token) > 1}

    def _fallback_query(self, text: str, top_k: int = 3) -> List[Dict[str, Any]]:
        incidents = load_incidents()
        if incidents.empty:
            return []
        query_tokens = self._tokenize(text)
        if not query_tokens:
            return []

        ranked: List[Dict[str, Any]] = []
        for _, row in incidents.iterrows():
            doc = self._incident_text(row)
            doc_tokens = self._tokenize(doc)
            overlap = len(query_tokens & doc_tokens)
            union = max(len(query_tokens | doc_tokens), 1)
            similarity = overlap / union
            if similarity <= 0.0:
                continue
            ranked.append(
                {
                    "incident_id": str(row.get("incident_id", "")),
                    "document": doc,
                    "distance": float(max(0.0, 1.0 - similarity)),
                    "metadata": {
                        "incident_type": str(row.get("incident_type", "")),
                        "severity": str(row.get("severity", "")),
                        "node_id": str(row.get("node_id", "")),
                    },
                }
            )

        ranked.sort(key=lambda item: item["distance"])
        return ranked[:top_k]

    def ingest(self, incidents: pd.DataFrame, replace: bool = False) -> int:
        if self._collection is None or self._client is None:
            logger.info("Skipping incident ingest because IncidentStore is disabled.")
            return 0
        if incidents.empty:
            return 0
        required = [
            "incident_id",
            "incident_type",
            "severity",
            "node_id",
            "duration_sec",
            "max_score",
        ]
        missing = [c for c in required if c not in incidents.columns]
        if missing:
            raise ValueError(f"Incidents frame missing columns: {missing}")

        if replace:
            name = self._collection.name
            self._client.delete_collection(name)
            self._collection = self._client.get_or_create_collection(
                name=name,
                embedding_function=self._embedding_fn,
            )

        ids: List[str] = []
        docs: List[str] = []
        metas: List[Dict[str, Any]] = []
        for _, row in incidents.iterrows():
            iid = str(row["incident_id"])
            text = (
                f"{row['incident_type']} | severity={row['severity']} | "
                f"node={row['node_id']} | duration={row['duration_sec']}s | score={row['max_score']}"
            )
            ids.append(iid)
            docs.append(text)
            metas.append(
                {
                    "incident_type": str(row["incident_type"]),
                    "severity": str(row["severity"]),
                    "node_id": str(row["node_id"]),
                    "duration_sec": _scalar_float(row["duration_sec"]) or 0.0,
                    "max_score": _scalar_float(row["max_score"]) or 0.0,
                }
            )

        self._collection.upsert(ids=ids, documents=docs, metadatas=metas)
        return len(ids)

    def query(self, text: str, top_k: int = 3) -> List[Dict[str, Any]]:
        if self._collection is None:
            return self._fallback_query(text, top_k=top_k)
        if not text.strip():
            return []
        try:
            res = self._collection.query(query_texts=[text], n_results=top_k)
            ids = (res.get("ids") or [[]])[0]
            docs = (res.get("documents") or [[]])[0]
            dists = (res.get("distances") or [[]])[0] if res.get("distances") is not None else [None] * len(ids)
            metas = (res.get("metadatas") or [[]])[0]
            out: List[Dict[str, Any]] = []
            for i in range(len(ids)):
                out.append(
                    {
                        "incident_id": ids[i],
                        "document": docs[i],
                        "distance": _scalar_float(dists[i]),
                        "metadata": metas[i] if i < len(metas) else {},
                    }
                )
            return out
        except Exception as exc:
            logger.warning("IncidentStore vector query failed, using lexical fallback: %s", exc)
            return self._fallback_query(text, top_k=top_k)
