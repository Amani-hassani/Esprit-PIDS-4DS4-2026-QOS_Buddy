from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from threading import RLock
from typing import Any

import joblib
import numpy as np
import pandas as pd

try:
    import faiss  # type: ignore
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "Native FAISS is mandatory for deployment. Use the Linux Docker image "
        "or install faiss-cpu in the runtime environment."
    ) from exc


ROOT_CAUSE_TAGS = {
    "RC_CAPACITY_OVERLOAD": ("CAP OVLD", "CAPACITY", "high"),
    "RC_TRANSPORT_DELAY": ("TRANS DLY", "TRANSPORT", "medium"),
    "RC_JITTER_INSTABILITY": ("JIT INST", "TRANSPORT", "medium"),
    "RC_PACKET_LOSS": ("PKT LOSS", "TRANSPORT", "high"),
    "RC_RETRANSMISSION": ("RETRANS", "TRANSPORT", "medium"),
    "RC_RADIO_SIGNAL_WEAK": ("WEAK SIG", "RADIO", "low"),
    "RC_HANDOVER_INSTABILITY": ("HO FAIL", "RADIO", "medium"),
    "RC_CQI_MISMATCH": ("CQI MISM", "MIXED", "medium"),
}


ROLLING_METRICS = [
    "latency_ms",
    "jitter_ms",
    "packet_loss_pct",
    "throughput_mbps",
    "bler_pct_model",
    "queue_length",
    "bandwidth_util_pct",
]


def now_iso() -> str:
    return pd.Timestamp.utcnow().isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        numeric = float(value)
        if math.isnan(numeric) or math.isinf(numeric):
            return default
        return numeric
    except Exception:
        return default


def clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    return max(low, min(high, safe_float(value, default)))


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -60, 60)))


def risk_level(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def normalize_scores(scores: dict[str, float], labels: list[str]) -> dict[str, float]:
    cleaned = {label: max(0.0, safe_float(scores.get(label), 0.0)) for label in labels}
    total = sum(cleaned.values())
    if total <= 0:
        uniform = 1.0 / max(len(labels), 1)
        return {label: uniform for label in labels}
    return {label: value / total for label, value in cleaned.items()}


def softmax_scores(scores: dict[str, float]) -> dict[str, float]:
    labels = list(scores.keys())
    values = np.array([safe_float(scores[label]) for label in labels], dtype="float64")
    values = values - np.max(values)
    probs = np.exp(values)
    probs = probs / max(float(probs.sum()), 1e-12)
    return {label: float(prob) for label, prob in zip(labels, probs)}


class NumpyGruAutoencoder:
    def __init__(self, artifact_path: Path):
        data = np.load(artifact_path)
        self.input_dim = int(data["input_dim"])
        self.hidden_dim = int(data["hidden_dim"])
        self.latent_dim = int(data["latent_dim"])
        self.window_size = int(data["window_size"])
        self.weight_ih = data["weight_ih"].astype("float32")
        self.weight_hh = data["weight_hh"].astype("float32")
        self.bias_ih = data["bias_ih"].astype("float32")
        self.bias_hh = data["bias_hh"].astype("float32")
        self.to_latent_weight = data["to_latent_weight"].astype("float32")
        self.to_latent_bias = data["to_latent_bias"].astype("float32")
        self.from_latent_weight = data["from_latent_weight"].astype("float32")
        self.from_latent_bias = data["from_latent_bias"].astype("float32")
        self.decoder_weight_ih = data["decoder_weight_ih"].astype("float32")
        self.decoder_weight_hh = data["decoder_weight_hh"].astype("float32")
        self.decoder_bias_ih = data["decoder_bias_ih"].astype("float32")
        self.decoder_bias_hh = data["decoder_bias_hh"].astype("float32")
        self.output_weight = data["output_weight"].astype("float32")
        self.output_bias = data["output_bias"].astype("float32")

    def _gru_last(self, sequence: np.ndarray) -> np.ndarray:
        x = np.asarray(sequence, dtype="float32")
        if x.ndim == 2:
            x = x[None, :, :]

        h = np.zeros((x.shape[0], self.hidden_dim), dtype="float32")
        wi_r, wi_z, wi_n = np.split(self.weight_ih, 3, axis=0)
        wh_r, wh_z, wh_n = np.split(self.weight_hh, 3, axis=0)
        bi_r, bi_z, bi_n = np.split(self.bias_ih, 3)
        bh_r, bh_z, bh_n = np.split(self.bias_hh, 3)

        for t in range(x.shape[1]):
            x_t = x[:, t, :]
            r = sigmoid(x_t @ wi_r.T + bi_r + h @ wh_r.T + bh_r)
            z = sigmoid(x_t @ wi_z.T + bi_z + h @ wh_z.T + bh_z)
            n = np.tanh(x_t @ wi_n.T + bi_n + r * (h @ wh_n.T + bh_n))
            h = (1.0 - z) * n + z * h

        return h

    def encode(self, sequence: np.ndarray) -> np.ndarray:
        h = self._gru_last(sequence)
        return (h @ self.to_latent_weight.T + self.to_latent_bias).astype("float32")

    def reconstruct(self, sequence: np.ndarray) -> np.ndarray:
        x = np.asarray(sequence, dtype="float32")
        squeeze = x.ndim == 2
        if squeeze:
            x = x[None, :, :]
        z = self.encode(x)
        decoder_input = z @ self.from_latent_weight.T + self.from_latent_bias
        h = np.zeros((x.shape[0], self.hidden_dim), dtype="float32")
        wi_r, wi_z, wi_n = np.split(self.decoder_weight_ih, 3, axis=0)
        wh_r, wh_z, wh_n = np.split(self.decoder_weight_hh, 3, axis=0)
        bi_r, bi_z, bi_n = np.split(self.decoder_bias_ih, 3)
        bh_r, bh_z, bh_n = np.split(self.decoder_bias_hh, 3)
        outputs = []
        for _ in range(x.shape[1]):
            r = sigmoid(decoder_input @ wi_r.T + bi_r + h @ wh_r.T + bh_r)
            z_gate = sigmoid(decoder_input @ wi_z.T + bi_z + h @ wh_z.T + bh_z)
            n = np.tanh(decoder_input @ wi_n.T + bi_n + r * (h @ wh_n.T + bh_n))
            h = (1.0 - z_gate) * n + z_gate * h
            outputs.append(h @ self.output_weight.T + self.output_bias)
        reconstructed = np.stack(outputs, axis=1).astype("float32")
        return reconstructed[0] if squeeze else reconstructed

    def reconstruction_error(self, sequence: np.ndarray) -> np.ndarray:
        x = np.asarray(sequence, dtype="float32")
        recon = self.reconstruct(x)
        if x.ndim == 2:
            return np.array([float(np.mean((x - recon) ** 2))], dtype="float32")
        return np.mean((x - recon) ** 2, axis=(1, 2)).astype("float32")


class LlmExplainer:
    def __init__(self):
        self.api_key = os.environ.get("QOS_LLM_API_KEY", "").strip()
        self.base_url = os.environ.get("QOS_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.environ.get("QOS_LLM_MODEL", "gpt-4.1-mini")
        self.timeout_sec = float(os.environ.get("QOS_LLM_TIMEOUT_SEC", "8"))
        self.required = os.environ.get("QOS_LLM_REQUIRED", "false").lower() == "true"
        if self.required and not self.api_key:
            raise RuntimeError(
                "QOS_LLM_REQUIRED=true but QOS_LLM_API_KEY is not set. "
                "Provide an OpenAI-compatible key or disable the requirement."
            )

    @property
    def status(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.api_key),
            "required": self.required,
            "provider": "openai_compatible" if self.api_key else "model_grounded_fallback",
            "model": self.model if self.api_key else None,
            "base_url": self.base_url if self.api_key else None,
        }

    def explain(self, context: dict[str, Any]) -> dict[str, Any]:
        fallback = self._fallback(context)
        if not self.api_key:
            return fallback

        prompt = self._prompt(context)
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the QoS Buddy Diagnostic Agent explanation layer. "
                        "Return concise JSON only. Ground every statement in the provided metrics, "
                        "model probabilities, FAISS neighbors, and feature contributions. Do not invent data."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                raw = json.loads(response.read().decode("utf-8"))
            content = raw["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return {
                "provider": "openai_compatible",
                "model": self.model,
                "summary": str(parsed.get("summary", fallback["summary"])),
                "causal_chain": parsed.get("causal_chain", fallback["causal_chain"]),
                "feature_contribution_narrative": parsed.get(
                    "feature_contribution_narrative",
                    fallback["feature_contribution_narrative"],
                ),
                "operator_note": str(parsed.get("operator_note", fallback["operator_note"])),
            }
        except Exception as exc:
            if self.required:
                raise RuntimeError(f"LLM explanation failed and QOS_LLM_REQUIRED=true: {exc}") from exc
            fallback["provider"] = "model_grounded_fallback_after_llm_error"
            fallback["llm_error"] = str(exc)
            return fallback

    def _prompt(self, context: dict[str, Any]) -> str:
        slim_context = {
            "root_cause": context["root_cause"],
            "confidence": context["confidence"],
            "top3": context["top3"],
            "evidence": context["evidence"],
            "feature_contributions": context["feature_contributions"],
            "prototype_neighbors": context["prototype_neighbors"][:3],
            "prediction": context.get("prediction", {}),
            "detection": context.get("detection", {}),
        }
        return (
            "Create the Diagnostic Agent explanation JSON with keys: "
            "summary, causal_chain, feature_contribution_narrative, operator_note. "
            "causal_chain must be a list of four objects with title, field, value, description. "
            f"Input context: {json.dumps(slim_context, default=str)}"
        )

    def _fallback(self, context: dict[str, Any]) -> dict[str, Any]:
        evidence = context["evidence"]
        contributions = context["feature_contributions"]
        root_cause = context["root_cause"]
        top_features = ", ".join(item["feature"] for item in contributions[:3])
        summary = (
            f"{root_cause} is selected because the model confidence is "
            f"{context['confidence'] * 100:.1f}% and the strongest contributors are {top_features}."
        )
        chain = []
        for idx, item in enumerate(evidence[:4], start=1):
            chain.append(
                {
                    "title": f"Evidence Step {idx}",
                    "field": item["field"],
                    "value": item["value"],
                    "description": item["message"],
                }
            )
        while len(chain) < 4:
            feature = contributions[len(chain) % max(len(contributions), 1)]
            chain.append(
                {
                    "title": f"Feature Step {len(chain) + 1}",
                    "field": feature["feature"],
                    "value": feature["value"],
                    "description": f"{feature['feature']} is {feature['direction']} and supports {root_cause}.",
                }
            )
        return {
            "provider": "model_grounded_fallback",
            "model": None,
            "summary": summary,
            "causal_chain": chain[:4],
            "feature_contribution_narrative": (
                f"The Random Forest feature-importance profile and current deviation from baseline "
                f"rank {top_features} as the main drivers. FAISS retrieval adds similar-case support "
                f"from {context['prototype_neighbors'][0]['root_cause']} with similarity "
                f"{context['prototype_neighbors'][0]['similarity']:.2f}."
            ),
            "operator_note": "LLM API is not configured; explanation is generated from model-grounded evidence.",
        }


class DynamicDiagnosticRuntime:
    def __init__(self, artifact_dir: Path):
        self.lock = RLock()
        self.artifact_dir = artifact_dir
        self.contracts = self._load_json("root_cause_contracts_8rc.json")
        self.feature_cols = self._load_json("feature_columns_8rc.json")
        self.summary = self._load_json("deployment_summary_8rc.json")
        self.rf_model = joblib.load(artifact_dir / "random_forest_8rc.joblib")
        self.label_encoder = joblib.load(artifact_dir / "label_encoder_8rc.joblib")
        self.sequence_imputer = joblib.load(artifact_dir / "sequence_imputer_8rc.joblib")
        self.sequence_scaler = joblib.load(artifact_dir / "sequence_scaler_8rc.joblib")
        self.prototype_latent_scaler = joblib.load(artifact_dir / "prototype_latent_scaler_8rc.joblib")
        self.gru_autoencoder = NumpyGruAutoencoder(artifact_dir / "gru_autoencoder_numpy_8rc.npz")
        self.window_size = self.gru_autoencoder.window_size
        self.prototype_weight = float(self.summary["prototype_retrieval"]["rf_probability_vector_weight"])
        self.llm = LlmExplainer()

        memory = np.load(artifact_dir / "sequence_windows_8rc.npz", allow_pickle=True)
        self.memory_sequences = np.ascontiguousarray(memory["X_train"].astype("float32"))
        self.memory_labels = memory["y_train"].astype(str)
        memory_latents = self.gru_autoencoder.encode(self.memory_sequences)
        self.prototype_vectors = np.ascontiguousarray(
            self.prototype_latent_scaler.transform(memory_latents).astype("float32")
        )
        self.prototype_labels = self.memory_labels
        self.faiss_index = faiss.IndexFlatL2(self.prototype_vectors.shape[1])
        self.faiss_index.add(self.prototype_vectors)
        faiss.write_index(self.faiss_index, str(artifact_dir / "faiss_prototype_index_8rc.faiss"))
        self.memory_reconstruction_errors = self.gru_autoencoder.reconstruction_error(self.memory_sequences)
        self.reconstruction_baseline = {
            "p50": float(np.percentile(self.memory_reconstruction_errors, 50)),
            "p90": float(np.percentile(self.memory_reconstruction_errors, 90)),
            "p95": float(np.percentile(self.memory_reconstruction_errors, 95)),
        }

        self.benchmark_df = pd.read_csv(artifact_dir / "benchmark_8rc_engineered.csv")
        self.benchmark_df["timestamp"] = pd.to_datetime(self.benchmark_df["timestamp"], errors="coerce")
        self.benchmark_df = self.benchmark_df.dropna(subset=["timestamp"]).copy()
        self._coerce_features(self.benchmark_df)

        self.contexts: dict[str, dict[str, Any]] = {}
        self.context_order: list[str] = []
        self.context_ttl_sec = int(os.environ.get("QOS_CONTEXT_TTL_SEC", "120"))
        self.incidents: list[dict[str, Any]] = []
        self.live_rows = pd.DataFrame(columns=list(self.benchmark_df.columns))
        self.raw_events: list[dict[str, Any]] = []
        self.optimization_outbox: list[dict[str, Any]] = []
        self.optimization_log: list[dict[str, Any]] = []
        self.version = 0
        self.started_at = time.time()
        self.optimization_url = os.environ.get("OPTIMIZATION_AGENT_URL", "").strip()
        self.auto_send_optimization = (
            os.environ.get("AUTO_SEND_TO_OPTIMIZATION", "false").lower() == "true"
        )

        if os.environ.get("QOS_SEED_DEMO_INCIDENTS", "true").lower() == "true":
            self._seed_from_benchmark()

    def _load_json(self, name: str) -> Any:
        with open(self.artifact_dir / name, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _coerce_features(self, df: pd.DataFrame) -> None:
        for col in self.feature_cols:
            if col not in df.columns:
                df[col] = np.nan
            df[col] = pd.to_numeric(df[col], errors="coerce")

    def _seed_from_benchmark(self) -> None:
        test_df = self.benchmark_df[self.benchmark_df["split"].eq("test")].copy()
        selected = []
        for root_cause in self.contracts:
            rows = test_df[test_df["root_cause_label"].eq(root_cause)].sort_values("timestamp")
            if not rows.empty:
                selected.append(rows.iloc[[min(7, len(rows) - 1)]])
        selected.append(test_df.sort_values("timestamp", ascending=False).head(24))
        seed_rows = pd.concat(selected, ignore_index=False).drop_duplicates(subset=["row_id"])
        seed_rows = seed_rows.sort_values("timestamp", ascending=False).head(12)
        for _, row in seed_rows.iterrows():
            diagnosis = self._diagnose_engineered_row(row, source="seed")
            diagnosis["id"] = self._next_incident_id()
            self.incidents.append(diagnosis)
        self.version += 1

    def _next_incident_id(self) -> str:
        return f"INC_{3302 + len(self.incidents)}"

    def ingest_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.receive_agent_event(payload, source_hint="combined")
        if result.get("status") == "waiting_for_monitoring":
            return result
        return result

    def receive_agent_event(self, payload: dict[str, Any], source_hint: str) -> dict[str, Any]:
        with self.lock:
            component = self._agent_component(payload, source_hint)
            context = self._merge_context(component)
            if not context["monitoring"]:
                return {
                    "status": "waiting_for_monitoring",
                    "context_key": context["context_key"],
                    "diagnostic_state": self._context_state(context),
                }

            event = self._normalize_payload(context)
            data_quality = self._data_quality_gate(event, context)
            engineered = self._engineer_live_features(event)
            engineered["data_quality"] = data_quality
            engineered["context_state"] = self._context_state(context)
            self.raw_events.append(event)
            self.live_rows = pd.concat([self.live_rows, pd.DataFrame([engineered])], ignore_index=True)
            if len(self.live_rows) > 2000:
                self.live_rows = self.live_rows.tail(2000).reset_index(drop=True)

            diagnosis = self._diagnose_engineered_row(engineered, source="live")
            diagnosis["id"] = context.get("incident_id") or event.get("incident_id") or self._next_incident_id()
            context["incident_id"] = diagnosis["id"]
            diagnosis["context_key"] = context["context_key"]
            diagnosis["source_event_id"] = event["event_id"]
            diagnosis["pipeline_inputs"] = {
                "monitoring": event.get("monitoring", {}),
                "detection": event.get("detection", {}),
                "prediction": event.get("prediction", {}),
            }
            self.incidents = [item for item in self.incidents if item["id"] != diagnosis["id"]]
            self.incidents.insert(0, diagnosis)
            self.incidents = self.incidents[:100]
            handoff = self.upsert_optimization_handoff(diagnosis)
            diagnosis["optimization_handoff"] = handoff
            if self.auto_send_optimization:
                diagnosis["optimization_push"] = self.send_to_optimization(diagnosis["id"])
            self.version += 1
            return diagnosis

    def _agent_component(self, payload: dict[str, Any], source_hint: str) -> dict[str, Any]:
        source = source_hint.lower()
        known_keys = {
            "event_id",
            "incident_id",
            "correlation_id",
            "timestamp",
            "node_id",
            "cell_id",
            "zone_id",
            "region",
            "monitoring",
            "features",
            "detection",
            "prediction",
            "metadata",
            "source",
        }
        root_metrics = {
            key: value
            for key, value in payload.items()
            if key not in known_keys and key in self.feature_cols
        }
        monitoring = dict(payload.get("monitoring") or payload.get("features") or {})
        detection = dict(payload.get("detection") or {})
        prediction = dict(payload.get("prediction") or {})
        metadata = dict(payload.get("metadata") or {})
        if source == "monitoring" and not monitoring:
            monitoring = root_metrics
        if source == "detection" and not detection:
            detection = {key: value for key, value in payload.items() if key not in known_keys}
        if source == "prediction" and not prediction:
            prediction = {key: value for key, value in payload.items() if key not in known_keys}
        if source in {"combined", "prediction_detection"}:
            monitoring.update(root_metrics)

        timestamp = str(
            payload.get("timestamp")
            or monitoring.get("timestamp")
            or detection.get("timestamp")
            or prediction.get("timestamp")
            or now_iso()
        )
        node_id = str(payload.get("node_id") or monitoring.get("node_id") or metadata.get("node_id") or "N1")
        cell_id = str(payload.get("cell_id") or monitoring.get("cell_id") or metadata.get("cell_id") or "C1")
        zone_id = str(
            payload.get("zone_id")
            or payload.get("region")
            or monitoring.get("zone_id")
            or metadata.get("zone_id")
            or "Z1"
        )
        event_id = str(
            payload.get("event_id")
            or payload.get("incident_id")
            or payload.get("correlation_id")
            or monitoring.get("event_id")
            or detection.get("event_id")
            or prediction.get("event_id")
            or ""
        )
        return {
            "context_key": self._context_key(event_id, timestamp, node_id, cell_id),
            "event_id": event_id or str(uuid.uuid4()),
            "timestamp": timestamp,
            "node_id": node_id,
            "cell_id": cell_id,
            "zone_id": zone_id,
            "monitoring": monitoring,
            "detection": detection,
            "prediction": prediction,
            "metadata": metadata,
            "source": source,
            "received_at": now_iso(),
        }

    def _context_key(self, event_id: str, timestamp: str, node_id: str, cell_id: str) -> str:
        if event_id:
            return event_id
        parsed = pd.to_datetime(timestamp, errors="coerce", utc=True)
        if pd.isna(parsed):
            bucket = int(time.time() // 30)
        else:
            bucket = int(parsed.timestamp() // 30)
        return f"{node_id}|{cell_id}|{bucket}"

    def _merge_context(self, component: dict[str, Any]) -> dict[str, Any]:
        self._prune_contexts()
        key = component["context_key"]
        context = self.contexts.get(key)
        if context is None:
            context = {
                "context_key": key,
                "event_id": component["event_id"],
                "timestamp": component["timestamp"],
                "node_id": component["node_id"],
                "cell_id": component["cell_id"],
                "zone_id": component["zone_id"],
                "monitoring": {},
                "detection": {},
                "prediction": {},
                "metadata": {},
                "sources": {},
                "created_at": component["received_at"],
                "updated_at": component["received_at"],
            }
            self.contexts[key] = context
            self.context_order.append(key)
        for block in ["monitoring", "detection", "prediction", "metadata"]:
            context[block].update(component.get(block, {}))
        for field in ["event_id", "timestamp", "node_id", "cell_id", "zone_id"]:
            if component.get(field):
                context[field] = component[field]
        context["sources"][component["source"]] = component["received_at"]
        context["updated_at"] = component["received_at"]
        return context

    def _prune_contexts(self) -> None:
        now = pd.Timestamp.utcnow()
        keep_order = []
        for key in self.context_order[-500:]:
            context = self.contexts.get(key)
            if context is None:
                continue
            updated = pd.to_datetime(context.get("updated_at"), errors="coerce", utc=True)
            if pd.isna(updated) or (now - updated).total_seconds() <= self.context_ttl_sec:
                keep_order.append(key)
            else:
                self.contexts.pop(key, None)
        self.context_order = keep_order

    def _context_state(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "context_key": context["context_key"],
            "event_id": context.get("event_id"),
            "node_id": context.get("node_id"),
            "cell_id": context.get("cell_id"),
            "zone_id": context.get("zone_id"),
            "present_sources": sorted(context.get("sources", {}).keys()),
            "has_monitoring": bool(context.get("monitoring")),
            "has_detection": bool(context.get("detection")),
            "has_prediction": bool(context.get("prediction")),
            "updated_at": context.get("updated_at"),
        }

    def _normalize_payload(self, context: dict[str, Any]) -> dict[str, Any]:
        monitoring = dict(context.get("monitoring") or {})
        detection = dict(context.get("detection") or {})
        prediction = dict(context.get("prediction") or {})
        metadata = dict(context.get("metadata") or {})
        event = {
            **monitoring,
            **metadata,
            "monitoring": monitoring,
            "detection": detection,
            "prediction": prediction,
            "event_id": str(context.get("event_id") or uuid.uuid4()),
            "timestamp": str(context.get("timestamp") or monitoring.get("timestamp") or detection.get("timestamp") or now_iso()),
            "node_id": str(context.get("node_id") or monitoring.get("node_id") or metadata.get("node_id") or "N1"),
            "cell_id": str(context.get("cell_id") or monitoring.get("cell_id") or metadata.get("cell_id") or "C1"),
            "zone_id": str(context.get("zone_id") or monitoring.get("zone_id") or metadata.get("zone_id") or "Z1"),
            "anomaly_type": str(detection.get("anomaly_type") or "live_anomaly"),
            "anomaly_score": safe_float(detection.get("anomaly_score"), 0.0),
            "external_prediction_root_cause": prediction.get("root_cause"),
            "external_prediction_confidence": safe_float(prediction.get("confidence"), 0.0),
        }
        return event

    def _data_quality_gate(self, event: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        required_fields = [
            "latency_ms",
            "jitter_ms",
            "packet_loss_pct",
            "throughput_mbps",
            "bandwidth_util_pct",
            "queue_length",
            "sinr_db",
            "cqi",
            "bler_proxy_pct",
        ]
        monitoring = event.get("monitoring", {})
        missing = [
            field
            for field in required_fields
            if field not in monitoring or monitoring.get(field) in {None, "", "null", "NaN"}
        ]
        availability_score = 1.0 - (len(missing) / len(required_fields))

        timestamp = pd.to_datetime(event.get("timestamp"), errors="coerce", utc=True)
        if pd.isna(timestamp):
            freshness_score = 0.45
            staleness_sec = None
        else:
            staleness_sec = max(0.0, (pd.Timestamp.utcnow() - timestamp).total_seconds())
            freshness_score = max(0.2, min(1.0, 1.0 - (staleness_sec / 600.0)))

        range_checks = {
            "latency_ms": (0, 5000),
            "jitter_ms": (0, 2000),
            "packet_loss_pct": (0, 100),
            "throughput_mbps": (0, 100000),
            "bandwidth_util_pct": (0, 100),
            "queue_length": (0, 100000),
            "sinr_db": (-30, 60),
            "cqi": (0, 15),
            "bler_proxy_pct": (0, 100),
        }
        valid_checks = []
        for field, (low, high) in range_checks.items():
            if field in monitoring:
                value = safe_float(monitoring.get(field), default=float("nan"))
                valid_checks.append(low <= value <= high)
        range_score = float(np.mean(valid_checks)) if valid_checks else 0.65

        present_sources = set(context.get("sources", {}).keys())
        source_score = 0.0
        source_score += 0.65 if context.get("monitoring") else 0.0
        source_score += 0.18 if context.get("detection") else 0.0
        source_score += 0.17 if context.get("prediction") else 0.0
        if "combined" in present_sources:
            source_score = max(source_score, 0.85)

        trust_score = 100.0 * (
            availability_score * 0.40
            + freshness_score * 0.25
            + range_score * 0.20
            + min(source_score, 1.0) * 0.15
        )
        confidence_penalty = max(0.0, min(0.42, (100.0 - trust_score) / 100.0 * 0.42))
        return {
            "trust_score": round(trust_score, 2),
            "confidence_penalty": round(confidence_penalty, 4),
            "availability_score": round(availability_score, 4),
            "freshness_score": round(freshness_score, 4),
            "range_score": round(range_score, 4),
            "source_score": round(min(source_score, 1.0), 4),
            "missing_fields": missing,
            "present_sources": sorted(present_sources),
            "staleness_sec": round(staleness_sec, 2) if staleness_sec is not None else None,
        }

    def _history_for(self, event: dict[str, Any]) -> pd.DataFrame:
        if self.live_rows.empty:
            return pd.DataFrame()
        group = self._sequence_group(event)
        return self.live_rows[self.live_rows["sequence_group"].eq(group)].tail(20).copy()

    def _sequence_group(self, event: dict[str, Any]) -> str:
        return f"live|{event.get('node_id', 'N1')}|{event.get('cell_id', 'C1')}"

    def _engineer_live_features(self, event: dict[str, Any]) -> dict[str, Any]:
        row = dict(event.get("monitoring", {}))
        row.update({k: v for k, v in event.items() if k not in {"monitoring", "detection", "prediction"}})
        timestamp = pd.to_datetime(row.get("timestamp") or now_iso(), errors="coerce")
        if pd.isna(timestamp):
            timestamp = pd.Timestamp.utcnow()

        defaults = self._feature_medians()
        for col in self.feature_cols:
            row.setdefault(col, defaults.get(col, 0.0))

        row["timestamp"] = timestamp.isoformat()
        row["row_id"] = int(time.time() * 1000) + len(self.raw_events)
        row["split"] = "live"
        row["source_file"] = "monitoring_agent_stream"
        row["sequence_group"] = self._sequence_group(row)
        row["root_cause_label"] = row.get("root_cause_label", "")
        row["is_augmented_contract"] = False
        row["augmentation_origin"] = "live_agent_input"
        row["prediction"] = event.get("prediction", {})
        row["detection"] = event.get("detection", {})

        self._derive_current_features(row)
        history = self._history_for(row)
        self._derive_rolling_features(row, history)
        for col in self.feature_cols:
            row[col] = safe_float(row.get(col), defaults.get(col, 0.0))
        return row

    def _feature_medians(self) -> dict[str, float]:
        return {
            col: safe_float(value)
            for col, value in zip(self.feature_cols, self.sequence_imputer.statistics_)
        }

    def _derive_current_features(self, row: dict[str, Any]) -> None:
        row["handover_event"] = int(bool(row.get("handover_event", False)))
        row["jitter_increasing"] = int(bool(row.get("jitter_increasing", False)))
        row["bler_pct_model"] = clamp(row.get("bler_proxy_pct"), 0, 100)
        row["latency_jitter_ratio"] = safe_float(row.get("latency_ms")) / (safe_float(row.get("jitter_ms")) + 1.0)
        row["throughput_util_ratio"] = safe_float(row.get("throughput_mbps")) / (
            safe_float(row.get("bandwidth_util_pct")) + 1.0
        )
        row["flag_latency_warn"] = int(safe_float(row.get("latency_ms")) >= 100)
        row["flag_latency_crit"] = int(safe_float(row.get("latency_ms")) >= 250)
        row["flag_pl_warn"] = int(safe_float(row.get("packet_loss_pct")) >= 1)
        row["flag_pl_crit"] = int(safe_float(row.get("packet_loss_pct")) >= 5)
        row["flag_high_util"] = int(safe_float(row.get("bandwidth_util_pct")) >= 75)
        row["flag_queue_high"] = int(safe_float(row.get("queue_length")) >= 80)
        row["bler_pressure_score"] = (
            safe_float(row.get("bler_pct_model")) * 0.55
            + safe_float(row.get("tcp_retransmit_rate")) * 1.5
            + safe_float(row.get("packet_loss_pct")) * 1.2
        )
        row["bler_sinr_gap"] = safe_float(row.get("bler_pct_model")) - max(safe_float(row.get("sinr_db")), 0.0)
        row["bler_mcs_stress"] = safe_float(row.get("bler_pct_model")) * (
            (safe_float(row.get("mcs")) + 1.0) / (safe_float(row.get("cqi")) + 1.0)
        )
        row["handover_instability_index"] = (
            safe_float(row.get("handover_event")) * 15
            + safe_float(row.get("handover_count")) * 6
            + (100 - safe_float(row.get("ho_success_rate_pct"), 100)) * 0.45
            + (100 - safe_float(row.get("cssr_proxy_pct"), 100)) * 0.20
        )
        row["transport_pressure_score"] = (
            safe_float(row.get("latency_ms")) * 0.18
            + safe_float(row.get("jitter_ms")) * 0.12
            + safe_float(row.get("queue_length")) * 0.22
            + safe_float(row.get("tcp_retransmit_rate")) * 1.8
        )
        row["throughput_loss_explainer"] = (
            (100 - min(safe_float(row.get("throughput_mbps")) * 10, 100)) * 0.35
            + safe_float(row.get("bandwidth_util_pct")) * 0.30
            + safe_float(row.get("queue_length")) * 0.20
        )
        row["congestion_index"] = (
            safe_float(row.get("bandwidth_util_pct")) * 0.35
            + safe_float(row.get("queue_length")) * 0.25
            + safe_float(row.get("active_connections")) * 0.15
            + safe_float(row.get("cpu_pct")) * 0.15
        )
        row["radio_efficiency_score"] = (
            safe_float(row.get("signal_health_score")) * 0.35
            + safe_float(row.get("cqi")) * 4
            + max(safe_float(row.get("sinr_db")), 0.0) * 1.5
            - safe_float(row.get("bler_pct_model")) * 1.2
        )
        row["radio_vs_transport_score"] = row["radio_efficiency_score"] - row["transport_pressure_score"]

    def _derive_rolling_features(self, row: dict[str, Any], history: pd.DataFrame) -> None:
        for metric in ROLLING_METRICS:
            values = [safe_float(v) for v in history.get(metric, pd.Series(dtype=float)).tolist()]
            values.append(safe_float(row.get(metric)))
            series = pd.Series(values, dtype=float)
            for window in [3, 5]:
                win = series.tail(window)
                row[f"{metric}_rollmean_{window}"] = float(win.mean())
                row[f"{metric}_rollstd_{window}"] = float(win.std()) if len(win) > 1 else 0.0
                row[f"{metric}_delta_{window}"] = float(series.iloc[-1] - series.iloc[-window - 1]) if len(series) > window else 0.0

    def _row_features(self, row: pd.Series | dict[str, Any]) -> pd.DataFrame:
        data = row.to_dict() if isinstance(row, pd.Series) else dict(row)
        return pd.DataFrame([{col: data.get(col, np.nan) for col in self.feature_cols}])

    def _build_sequence(self, row: pd.Series | dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
        data = row.to_dict() if isinstance(row, pd.Series) else dict(row)
        source_df = self.live_rows if data.get("split") == "live" else self.benchmark_df
        group = data.get("sequence_group")
        row_id = data.get("row_id")
        group_df = source_df[source_df["sequence_group"].eq(group)].sort_values(["timestamp", "row_id"])
        observed_length = 1
        if not group_df.empty and row_id in set(group_df["row_id"].tolist()):
            pos = group_df.index.get_loc(group_df[group_df["row_id"].eq(row_id)].index[0])
            seq = group_df.iloc[max(0, pos - self.window_size + 1) : pos + 1][self.feature_cols].copy()
            observed_length = len(seq)
        else:
            seq = self._row_features(data)
        while len(seq) < self.window_size:
            seq = pd.concat([seq.iloc[[0]], seq], ignore_index=True)
        imputed = self.sequence_imputer.transform(seq.tail(self.window_size)[self.feature_cols])
        sequence = self.sequence_scaler.transform(imputed).astype("float32")
        info = {
            "window_size": self.window_size,
            "observed_samples": int(observed_length),
            "padded_samples": int(max(0, self.window_size - observed_length)),
            "sequence_group": str(group),
        }
        return sequence, info

    def _sequence_for_row(self, row: pd.Series | dict[str, Any]) -> np.ndarray:
        return self._build_sequence(row)[0]

    def _search_prototypes(self, scaled_latent: np.ndarray, k: int = 5) -> tuple[list[dict[str, Any]], dict[str, float]]:
        distances, indices = self.faiss_index.search(np.ascontiguousarray(scaled_latent.astype("float32")), k)
        out = []
        for rank, (distance, index) in enumerate(zip(distances[0], indices[0]), start=1):
            label = str(self.prototype_labels[int(index)])
            similarity = 1.0 / (1.0 + math.sqrt(max(float(distance), 0.0)))
            out.append(
                {
                    "rank": rank,
                    "root_cause": str(label),
                    "distance": round(float(distance), 4),
                    "similarity": round(float(similarity), 4),
                }
            )
        vote_scores = {root_cause: 0.0 for root_cause in self.contracts}
        for item in out:
            vote_scores[item["root_cause"]] += safe_float(item["similarity"])
        return out, normalize_scores(vote_scores, list(self.contracts.keys()))

    def _autoencoder_evidence(self, sequence: np.ndarray) -> dict[str, Any]:
        latent = self.gru_autoencoder.encode(sequence)
        scaled_latent = self.prototype_latent_scaler.transform(latent).astype("float32")
        reconstructed = self.gru_autoencoder.reconstruct(sequence)
        feature_mse = np.mean((sequence - reconstructed) ** 2, axis=0)
        reconstruction_mse = float(np.mean(feature_mse))
        p50 = self.reconstruction_baseline["p50"]
        p95 = max(self.reconstruction_baseline["p95"], p50 + 1e-6)
        severity = max(0.0, min(1.0, (reconstruction_mse - p50) / (p95 - p50)))
        top_indices = np.argsort(feature_mse)[::-1][:6]
        top_errors = [
            {
                "feature": self.feature_cols[int(index)],
                "mse": round(float(feature_mse[int(index)]), 5),
            }
            for index in top_indices
        ]
        return {
            "latent": latent,
            "scaled_latent": scaled_latent,
            "reconstruction_mse": round(reconstruction_mse, 6),
            "baseline_p50": round(p50, 6),
            "baseline_p95": round(p95, 6),
            "reconstruction_severity": round(severity, 4),
            "sequence_confidence_factor": round(1.0 - severity * 0.12, 4),
            "top_reconstruction_errors": top_errors,
        }

    def _feature_contributions(self, row: pd.Series | dict[str, Any]) -> list[dict[str, Any]]:
        importances = self.rf_model.named_steps["classifier"].feature_importances_
        row_df = self._row_features(row)
        medians = pd.Series(self.sequence_imputer.statistics_, index=self.feature_cols)
        values = row_df.iloc[0].fillna(medians)
        deviations = (values - medians).abs()
        scores = deviations.rank(pct=True).to_numpy() * importances
        top_indices = np.argsort(scores)[::-1][:8]
        out = []
        for index in top_indices:
            feature = self.feature_cols[int(index)]
            direction = "above baseline" if values[feature] >= medians[feature] else "below baseline"
            signed = float(scores[int(index)] if direction == "above baseline" else -scores[int(index)])
            out.append(
                {
                    "feature": feature,
                    "value": round(float(values[feature]), 3),
                    "baseline": round(float(medians[feature]), 3),
                    "direction": direction,
                    "contribution": round(signed, 4),
                }
            )
        return out

    def _evidence(self, row: pd.Series | dict[str, Any], root_cause: str) -> list[dict[str, Any]]:
        data = row.to_dict() if isinstance(row, pd.Series) else dict(row)
        evidence = []
        for field in self.contracts[root_cause]["primary_evidence"]:
            value = round(safe_float(data.get(field)), 3)
            evidence.append({"field": field, "value": value, "message": self._evidence_message(field)})
        return evidence

    def _evidence_message(self, field: str) -> str:
        messages = {
            "latency_ms": "latency above 100ms is degraded; above 250ms is critical",
            "jitter_ms": "jitter above 60ms indicates instability",
            "packet_loss_pct": "packet loss above 5% is critical",
            "throughput_mbps": "low throughput under pressure indicates capacity loss",
            "bandwidth_util_pct": "utilization above 75% indicates congestion pressure",
            "queue_length": "queue length above 80 indicates backlog",
            "active_connections": "high connection count increases capacity pressure",
            "tcp_retransmit_rate": "high retransmission rate indicates retry pressure",
            "bler_proxy_pct": "high BLER indicates radio or link error pressure",
            "rssi_dbm": "RSSI below -85 dBm indicates weak signal",
            "rsrp_dbm": "RSRP below -105 dBm indicates weak cellular coverage",
            "signal_health_score": "low signal-health score indicates radio impairment",
            "wifi_signal_score": "low Wi-Fi score indicates weak access link",
            "cellular_signal_score": "low cellular score indicates poor radio link",
            "handover_count": "repeated handovers indicate mobility instability",
            "ho_success_rate_pct": "low handover success indicates handover failure risk",
            "cssr_proxy_pct": "low setup success indicates access instability",
            "cqi": "low CQI with high MCS or BLER indicates CQI mismatch",
            "mcs": "high MCS under bad channel quality indicates coding mismatch",
            "sinr_db": "SINR contextualizes radio channel quality",
            "bler_mcs_stress": "high stress means BLER is inconsistent with MCS/CQI",
        }
        return messages.get(field, f"{field} supports this diagnosis")

    def _rf_probabilities(self, row: pd.Series | dict[str, Any]) -> dict[str, float]:
        row_df = self._row_features(row)
        probabilities = self.rf_model.predict_proba(row_df)[0]
        out = {}
        for index, probability in enumerate(probabilities):
            root_cause = str(self.label_encoder.inverse_transform([index])[0])
            out[root_cause] = float(probability)
        return normalize_scores(out, list(self.contracts.keys()))

    def _radio_transport_discriminator(self, row: pd.Series | dict[str, Any]) -> dict[str, Any]:
        data = row.to_dict() if isinstance(row, pd.Series) else dict(row)
        radio_raw = (
            max(0.0, (-safe_float(data.get("rsrp_dbm"), -95) - 100) / 20.0)
            + max(0.0, (-safe_float(data.get("rssi_dbm"), -75) - 82) / 18.0)
            + max(0.0, (15 - safe_float(data.get("sinr_db"), 15)) / 15.0)
            + max(0.0, (8 - safe_float(data.get("cqi"), 8)) / 8.0)
            + safe_float(data.get("bler_proxy_pct")) / 18.0
            + safe_float(data.get("handover_instability_index")) / 80.0
        )
        transport_raw = (
            safe_float(data.get("latency_ms")) / 260.0
            + safe_float(data.get("jitter_ms")) / 110.0
            + safe_float(data.get("packet_loss_pct")) / 7.0
            + safe_float(data.get("tcp_retransmit_rate")) / 8.0
            + safe_float(data.get("transport_pressure_score")) / 160.0
        )
        capacity_raw = (
            safe_float(data.get("bandwidth_util_pct")) / 88.0
            + safe_float(data.get("queue_length")) / 180.0
            + safe_float(data.get("active_connections")) / 180.0
            + max(0.0, (10.0 - safe_float(data.get("throughput_mbps"))) / 10.0)
            + safe_float(data.get("congestion_index")) / 130.0
        )
        mixed_raw = (radio_raw * transport_raw) ** 0.5 if radio_raw > 0 and transport_raw > 0 else 0.1
        scope_scores = softmax_scores(
            {
                "RADIO": radio_raw,
                "TRANSPORT": transport_raw,
                "CAPACITY": capacity_raw,
                "MIXED": mixed_raw,
            }
        )
        root_scores = {}
        for root_cause in self.contracts:
            _, scope, _ = ROOT_CAUSE_TAGS[root_cause]
            if scope == "MIXED":
                root_scores[root_cause] = scope_scores["MIXED"]
            else:
                root_scores[root_cause] = scope_scores.get(scope, 0.0)
        return {
            "macro_scope": max(scope_scores, key=scope_scores.get),
            "scope_scores": {key: round(value, 4) for key, value in scope_scores.items()},
            "root_scope_prior": normalize_scores(root_scores, list(self.contracts.keys())),
            "raw": {
                "radio": round(radio_raw, 4),
                "transport": round(transport_raw, 4),
                "capacity": round(capacity_raw, 4),
                "mixed": round(mixed_raw, 4),
            },
        }

    def _prediction_prior(self, prediction: dict[str, Any]) -> dict[str, float]:
        labels = list(self.contracts.keys())
        if not prediction:
            return {label: 0.0 for label in labels}

        if isinstance(prediction.get("root_cause_probabilities"), dict):
            return normalize_scores(prediction["root_cause_probabilities"], labels)

        ranked = prediction.get("ranked_root_causes")
        if isinstance(ranked, list):
            scores = {label: 0.0 for label in labels}
            for index, item in enumerate(ranked):
                if isinstance(item, dict):
                    root_cause = item.get("root_cause")
                    score = safe_float(item.get("probability"), 1.0 / (index + 1))
                else:
                    root_cause = str(item)
                    score = 1.0 / (index + 1)
                if root_cause in scores:
                    scores[root_cause] += score
            return normalize_scores(scores, labels)

        root_cause = prediction.get("root_cause")
        if root_cause in labels:
            confidence = max(0.05, min(1.0, safe_float(prediction.get("confidence"), 0.5)))
            scores = {label: (1.0 - confidence) / (len(labels) - 1) for label in labels}
            scores[root_cause] = confidence
            return normalize_scores(scores, labels)
        return {label: 0.0 for label in labels}

    def _fuse_branches(
        self,
        rf_scores: dict[str, float],
        prototype_scores: dict[str, float],
        scope_prior: dict[str, float],
        prediction_prior: dict[str, float],
        data_quality: dict[str, Any],
        autoencoder: dict[str, Any],
    ) -> dict[str, Any]:
        labels = list(self.contracts.keys())
        prediction_available = sum(prediction_prior.values()) > 0.0
        weights = {
            "random_forest": 0.60,
            "latent_prototype": 0.24,
            "radio_transport_scope": 0.10,
            "prediction_prior": 0.06 if prediction_available else 0.0,
        }
        if not prediction_available:
            scale = 1.0 / (1.0 - 0.06)
            for key in ["random_forest", "latent_prototype", "radio_transport_scope"]:
                weights[key] *= scale

        fused = {}
        for label in labels:
            fused[label] = (
                rf_scores.get(label, 0.0) * weights["random_forest"]
                + prototype_scores.get(label, 0.0) * weights["latent_prototype"]
                + scope_prior.get(label, 0.0) * weights["radio_transport_scope"]
                + prediction_prior.get(label, 0.0) * weights["prediction_prior"]
            )
        fused = normalize_scores(fused, labels)
        order = sorted(labels, key=lambda label: fused[label], reverse=True)
        primary = order[0]
        prototype_agreement = prototype_scores.get(primary, 0.0)
        sequence_factor = safe_float(autoencoder.get("sequence_confidence_factor"), 1.0)
        quality_penalty = safe_float(data_quality.get("confidence_penalty"), 0.0)
        agreement_factor = 0.88 + min(0.12, prototype_agreement * 0.12)
        adjusted_confidence = fused[primary] * (1.0 - quality_penalty) * sequence_factor * agreement_factor
        return {
            "primary_root_cause": primary,
            "raw_confidence": round(fused[primary], 4),
            "adjusted_confidence": round(max(0.0, min(0.99, adjusted_confidence)), 4),
            "ranked_causes": [
                {"root_cause": label, "probability": round(float(fused[label]), 4)}
                for label in order
            ],
            "branch_weights": {key: round(value, 4) for key, value in weights.items()},
            "branch_scores": {
                "random_forest": {label: round(rf_scores.get(label, 0.0), 4) for label in labels},
                "latent_prototype": {label: round(prototype_scores.get(label, 0.0), 4) for label in labels},
                "radio_transport_scope": {label: round(scope_prior.get(label, 0.0), 4) for label in labels},
                "prediction_prior": {label: round(prediction_prior.get(label, 0.0), 4) for label in labels},
            },
            "confidence_adjustments": {
                "data_quality_penalty": round(quality_penalty, 4),
                "sequence_confidence_factor": round(sequence_factor, 4),
                "prototype_agreement_factor": round(agreement_factor, 4),
            },
        }

    def _diagnose_engineered_row(self, row: pd.Series | dict[str, Any], source: str) -> dict[str, Any]:
        data = row.to_dict() if isinstance(row, pd.Series) else dict(row)
        sequence, sequence_info = self._build_sequence(data)
        autoencoder = self._autoencoder_evidence(sequence)
        neighbors, prototype_scores = self._search_prototypes(autoencoder["scaled_latent"], k=5)
        rf_scores = self._rf_probabilities(data)
        discriminator = self._radio_transport_discriminator(data)
        prediction_prior = self._prediction_prior(data.get("prediction", {}))
        data_quality = data.get("data_quality", {})
        fusion = self._fuse_branches(
            rf_scores=rf_scores,
            prototype_scores=prototype_scores,
            scope_prior=discriminator["root_scope_prior"],
            prediction_prior=prediction_prior,
            data_quality=data_quality,
            autoencoder=autoencoder,
        )
        primary = fusion["primary_root_cause"]
        confidence = fusion["adjusted_confidence"]
        top3 = fusion["ranked_causes"][:3]
        tag, scope, default_risk = ROOT_CAUSE_TAGS[primary]
        risk_score = max(
            0.2,
            min(
                0.99,
                confidence * 0.62
                + safe_float(data.get("anomaly_score")) * 0.18
                + autoencoder["reconstruction_severity"] * 0.10
                + (1.0 - neighbors[0]["similarity"]) * 0.10,
            ),
        )
        evidence = self._evidence(data, primary)
        contributions = self._feature_contributions(data)
        context = {
            "root_cause": primary,
            "confidence": confidence,
            "top3": top3,
            "evidence": evidence,
            "feature_contributions": contributions,
            "prototype_neighbors": neighbors,
            "prediction": data.get("prediction", {}),
            "detection": data.get("detection", {}),
        }
        llm_explanation = self.llm.explain(context)
        anomaly_type = str(data.get("anomaly_type", primary)).replace("contract_", "").replace("_", " ")
        diagnosis = {
            "id": str(data.get("incident_id", "")),
            "timestamp": str(data.get("timestamp", now_iso())),
            "node_id": str(data.get("node_id", "N1")),
            "cell_id": str(data.get("cell_id", "C1")),
            "region": str(data.get("zone_id", "Z1")),
            "anomaly_type": anomaly_type.title(),
            "actual_root_cause": str(data.get("root_cause_label", primary) or primary),
            "root_cause": primary,
            "root_tag": tag,
            "scope": scope,
            "confidence": round(confidence, 4),
            "confidence_pct": round(confidence * 100, 1),
            "score": round(max(confidence * 10, safe_float(data.get("anomaly_score")) * 10), 2),
            "risk_score": round(risk_score, 4),
            "risk_level": risk_level(risk_score) if default_risk == "low" else default_risk,
            "top3": top3,
            "evidence": evidence,
            "causal_chain": llm_explanation["causal_chain"],
            "feature_contributions": contributions,
            "feature_contribution_narrative": llm_explanation["feature_contribution_narrative"],
            "prototype_neighbors": neighbors,
            "protocol_pipeline": {
                "context_fusion": data.get("context_state", {}),
                "data_quality_gate": data_quality,
                "feature_builder": {
                    "feature_count": len(self.feature_cols),
                    "engineered_features": [
                        "transport_pressure_score",
                        "congestion_index",
                        "radio_efficiency_score",
                        "radio_vs_transport_score",
                        "handover_instability_index",
                        "bler_mcs_stress",
                    ],
                },
                "sequence_builder": sequence_info,
                "memory_guided_autoencoder": {
                    key: value
                    for key, value in autoencoder.items()
                    if key not in {"latent", "scaled_latent"}
                },
                "prototype_diagnosis": {
                    "backend": "faiss.IndexFlatL2",
                    "space": "scaled_gru_latent",
                    "class_scores": {key: round(value, 4) for key, value in prototype_scores.items()},
                    "neighbors": neighbors,
                },
                "random_forest_classifier": {
                    "class_scores": {key: round(value, 4) for key, value in rf_scores.items()},
                },
                "radio_transport_discriminator": discriminator,
                "fusion_confidence": fusion,
                "llm_explanation": {
                    "provider": llm_explanation["provider"],
                    "model": llm_explanation.get("model"),
                },
            },
            "data_quality": data_quality,
            "fusion": fusion,
            "autoencoder_evidence": {
                key: value
                for key, value in autoencoder.items()
                if key not in {"latent", "scaled_latent"}
            },
            "radio_transport_discriminator": discriminator,
            "recommended_action": self._recommended_action(primary),
            "llm_explanation": llm_explanation,
            "source": source,
            "is_augmented_contract": bool(data.get("is_augmented_contract", False)),
            "augmentation_origin": str(data.get("augmentation_origin", source)),
        }
        return diagnosis

    def _recommended_action(self, root_cause: str) -> dict[str, str]:
        actions = {
            "RC_CAPACITY_OVERLOAD": "Shift load, increase capacity, or apply congestion-control policy for the affected segment.",
            "RC_TRANSPORT_DELAY": "Inspect path latency, queueing, routing asymmetry, and backhaul congestion before reroute.",
            "RC_JITTER_INSTABILITY": "Stabilize delay variation through buffer, scheduler, and real-time traffic priority checks.",
            "RC_PACKET_LOSS": "Investigate drop source, BLER, retransmission pressure, and link-layer error counters.",
            "RC_RETRANSMISSION": "Tune retry pressure and inspect link errors causing repeated retransmissions.",
            "RC_RADIO_SIGNAL_WEAK": "Improve radio side first: antenna tilt, power, beam, coverage, or access-link quality.",
            "RC_HANDOVER_INSTABILITY": "Review neighbor relations, handover thresholds, and mobility parameters.",
            "RC_CQI_MISMATCH": "Check CQI reporting, MCS selection, BLER stress, and scheduler adaptation.",
        }
        return {"title": "Begin on primary root-cause side", "message": actions[root_cause]}

    def enqueue_for_optimization(self, incident: dict[str, Any]) -> dict[str, Any]:
        handoff = {
            "handoff_id": str(uuid.uuid4()),
            "status": "queued",
            "created_at": now_iso(),
            "incident_id": incident["id"],
            "root_cause": incident["root_cause"],
            "confidence": incident["confidence"],
            "risk_level": incident["risk_level"],
            "recommended_action": incident["recommended_action"],
            "top3": incident["top3"],
            "evidence": incident["evidence"],
            "prototype_neighbors": incident["prototype_neighbors"],
            "llm_summary": incident["llm_explanation"]["summary"],
            "data_quality": incident.get("data_quality", {}),
            "fusion": incident.get("fusion", {}),
            "autoencoder_evidence": incident.get("autoencoder_evidence", {}),
            "radio_transport_discriminator": incident.get("radio_transport_discriminator", {}),
        }
        self.optimization_outbox.append(handoff)
        return handoff

    def upsert_optimization_handoff(self, incident: dict[str, Any]) -> dict[str, Any]:
        existing = self._active_handoff_for_incident(incident)
        if existing is None:
            return self.enqueue_for_optimization(incident)
        existing.update(
            {
                "status": existing.get("status", "queued"),
                "updated_at": now_iso(),
                "root_cause": incident["root_cause"],
                "confidence": incident["confidence"],
                "risk_level": incident["risk_level"],
                "recommended_action": incident["recommended_action"],
                "top3": incident["top3"],
                "evidence": incident["evidence"],
                "prototype_neighbors": incident["prototype_neighbors"],
                "llm_summary": incident["llm_explanation"]["summary"],
                "data_quality": incident.get("data_quality", {}),
                "fusion": incident.get("fusion", {}),
                "autoencoder_evidence": incident.get("autoencoder_evidence", {}),
                "radio_transport_discriminator": incident.get("radio_transport_discriminator", {}),
            }
        )
        return existing

    def _active_handoff_for_incident(self, incident: dict[str, Any]) -> dict[str, Any] | None:
        existing = incident.get("optimization_handoff")
        if isinstance(existing, dict) and existing.get("incident_id") == incident["id"]:
            return existing
        for item in reversed(self.optimization_outbox):
            if item.get("incident_id") == incident["id"] and item.get("status") != "acknowledged":
                return item
        return None

    def send_to_optimization(self, incident_id: str) -> dict[str, Any]:
        incident = self.incident_detail(incident_id)
        if incident is None:
            raise KeyError(f"Incident not found: {incident_id}")
        handoff = self._active_handoff_for_incident(incident)
        if handoff is None:
            handoff = self.enqueue_for_optimization(incident)
            incident["optimization_handoff"] = handoff
        if not self.optimization_url:
            handoff["status"] = "queued_no_push_url"
            self.version += 1
            return handoff

        request = urllib.request.Request(
            self.optimization_url,
            data=json.dumps(handoff).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=6) as response:
                body = response.read().decode("utf-8")
            handoff["status"] = "pushed"
            handoff["optimization_status_code"] = response.status
            handoff["optimization_response"] = body[:1000]
        except urllib.error.URLError as exc:
            handoff["status"] = "push_failed_queued"
            handoff["error"] = str(exc)
        self.optimization_log.append(handoff)
        self.version += 1
        return handoff

    def ack_optimization(self, handoff_id: str) -> dict[str, Any]:
        for item in self.optimization_outbox:
            if item["handoff_id"] == handoff_id:
                item["status"] = "acknowledged"
                item["acknowledged_at"] = now_iso()
                return item
        raise KeyError(f"Handoff not found: {handoff_id}")

    def incident_detail(self, incident_id: str) -> dict[str, Any] | None:
        with self.lock:
            for incident in self.incidents:
                if incident["id"] == incident_id:
                    return incident
        return None

    def dashboard(self) -> dict[str, Any]:
        with self.lock:
            incidents = list(self.incidents)
            avg_conf = float(np.mean([item["confidence"] for item in incidents])) if incidents else 0.0
            max_score = max([item["score"] for item in incidents], default=0.0)
            high_risk = sum(1 for item in incidents if item["risk_level"] == "high")
            live = self._latest_live_monitoring()
            updated = 0
            if incidents:
                parsed = pd.to_datetime(incidents[0]["timestamp"], errors="coerce", utc=True)
                updated = max(0, int(time.time() - parsed.timestamp())) if pd.notna(parsed) else 0
            return {
                "phase": "ANALYZE",
                "phase_state": "Active",
                "updated_seconds_ago": updated,
                "version": self.version,
                "summary": {
                    "current_anomaly_score": round(max_score, 2),
                    "active_incidents": len(incidents),
                    "avg_confidence_pct": round(avg_conf * 100, 1),
                    "sla_risk_index": round(min(0.99, 0.28 + high_risk * 0.1), 2),
                    "data_quality_trust_score": round(self._data_quality_score(), 1),
                },
                "live_monitoring": live,
                "incidents": incidents,
                "faiss": {
                    "backend": "faiss.IndexFlatL2",
                    "vectors": int(self.faiss_index.ntotal),
                    "dimension": int(self.prototype_vectors.shape[1]),
                    "space": "scaled_gru_latent",
                },
                "llm": self.llm.status,
                "protocol": {
                    "context_fusion_contexts": len(self.contexts),
                    "pipeline": [
                        "context_fusion",
                        "data_quality_gate",
                        "feature_builder",
                        "sequence_builder",
                        "memory_guided_autoencoder",
                        "prototype_diagnosis_faiss",
                        "random_forest_classifier",
                        "radio_transport_discriminator",
                        "fusion_confidence",
                        "llm_causal_chain",
                        "optimization_handoff",
                    ],
                },
                "optimization": {
                    "push_url_configured": bool(self.optimization_url),
                    "queued": sum(1 for item in self.optimization_outbox if item["status"].startswith("queued")),
                    "total_handoffs": len(self.optimization_outbox),
                },
            }

    def _data_quality_score(self) -> float:
        if self.incidents and self.incidents[0].get("data_quality"):
            return safe_float(self.incidents[0]["data_quality"].get("trust_score"), 94.0)
        if self.live_rows.empty:
            return 94.0
        latest = self.live_rows.tail(25)
        available = latest[self.feature_cols].notna().mean().mean()
        return max(0.0, min(100.0, available * 100.0))

    def _latest_live_monitoring(self) -> dict[str, Any]:
        if self.live_rows.empty:
            source = self.benchmark_df.tail(1).iloc[0]
        else:
            source = self.live_rows.tail(1).iloc[0]
        return {
            "qos_kpis": {
                "Avg MOS": round(safe_float(source.get("mos_estimate"), 3.8), 2),
                "Throughput": f"{round(safe_float(source.get('throughput_mbps'), 0), 1)} Mbps",
                "Latency": f"{round(safe_float(source.get('latency_ms'), 0), 1)} ms",
                "Call Drop Rate": f"{round(safe_float(source.get('packet_loss_pct'), 0), 1)}%",
            },
            "radio_metrics": {
                "Avg SINR": f"{round(safe_float(source.get('sinr_db'), 0), 1)} dB",
                "Avg CQI": round(safe_float(source.get("cqi"), 0), 1),
                "BLER": f"{round(safe_float(source.get('bler_proxy_pct'), 0), 1)}%",
                "PRB Utilization": f"{round(safe_float(source.get('bandwidth_util_pct'), 0), 1)}%",
            },
            "handover_coverage": {
                "HO Success Rate": f"{round(safe_float(source.get('ho_success_rate_pct'), 100), 1)}%",
                "HO Failure Count": int(safe_float(source.get("handover_count"), 0)),
                "Avg Neighbor Count": int(safe_float(source.get("neighbor_count"), 0)),
                "Coverage Indicator": "Normal" if safe_float(source.get("signal_health_score"), 90) > 70 else "Weak",
            },
            "congestion_quality": {
                "Queue Pressure": "High" if safe_float(source.get("queue_length"), 0) > 80 else "Medium",
                "Scheduler Load": f"{round(safe_float(source.get('bandwidth_util_pct'), 0), 1)}%",
                "Data Quality %": f"{round(self._data_quality_score(), 1)}%",
                "Collection Completion": "100%",
            },
        }

    def model_health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "uptime_sec": round(time.time() - self.started_at, 1),
            "version": self.version,
            "artifacts": {
                "random_forest": "loaded",
                "gru_autoencoder_numpy": "loaded",
                "faiss_index": "loaded",
                "feature_columns": len(self.feature_cols),
            },
            "protocol_pipeline": [
                "context_fusion",
                "data_quality_gate",
                "feature_builder",
                "sequence_builder",
                "memory_guided_autoencoder",
                "prototype_diagnosis_faiss",
                "random_forest_classifier",
                "radio_transport_discriminator",
                "fusion_confidence",
                "llm_causal_chain",
                "optimization_handoff",
            ],
            "autoencoder": {
                "window_size": self.window_size,
                "latent_dim": self.gru_autoencoder.latent_dim,
                "reconstruction_baseline": self.reconstruction_baseline,
            },
            "llm": self.llm.status,
            "optimization": {
                "push_url_configured": bool(self.optimization_url),
                "outbox_size": len(self.optimization_outbox),
            },
            "metrics": {
                "rf": self.summary["random_forest"]["metrics"],
                "prototype": self.summary["prototype_retrieval"]["metrics"],
                "gru": self.summary["gru_autoencoder"],
            },
        }

    def demo_ingest_next(self) -> dict[str, Any]:
        index = len(self.raw_events) % len(self.benchmark_df)
        row = self.benchmark_df.iloc[index]
        monitoring = {col: safe_float(row.get(col)) for col in self.feature_cols}
        monitoring.update(
            {
                "timestamp": now_iso(),
                "node_id": row.get("node_id", "N1"),
                "cell_id": row.get("cell_id", "C1"),
                "zone_id": row.get("zone_id", "Z1"),
            }
        )
        payload = {
            "event_id": f"demo-{uuid.uuid4()}",
            "monitoring": monitoring,
            "detection": {
                "anomaly_detected": True,
                "anomaly_type": row.get("anomaly_type", "demo_anomaly"),
                "anomaly_score": safe_float(row.get("anomaly_score"), 0.7),
            },
            "prediction": {
                "horizon_minutes": 15,
                "sla_risk": 0.75,
                "confidence": 0.8,
            },
            "metadata": {
                "node_id": row.get("node_id", "N1"),
                "cell_id": row.get("cell_id", "C1"),
                "zone_id": row.get("zone_id", "Z1"),
            },
        }
        return self.ingest_event(payload)


def build_runtime() -> DynamicDiagnosticRuntime:
    artifact_dir = Path(os.environ.get("QOS_ARTIFACT_DIR", "outputs_8rc")).resolve()
    return DynamicDiagnosticRuntime(artifact_dir)
