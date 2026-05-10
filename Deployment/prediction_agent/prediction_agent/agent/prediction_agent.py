# CLEANED: standalone production contract with trust, fleet-ready outputs, and LLM synthesis.
"""Top-level orchestration for inference, explainability, RAG, trust scoring, and NOC synthesis."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd

from agent.result import PredictionResult
from config import LSTM_WINDOW, SAVED_MODELS_DIR, TARGET_NAMES
from data_pipeline.features import engineer_features
from data_pipeline.loader import apply_qos_schema_cleaning
from data_pipeline.preprocessor import Preprocessor

if TYPE_CHECKING:
    from llm.explainer import LLMExplainer
    from rag.incident_store import IncidentStore

logger = logging.getLogger(__name__)

DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "capacity": ("congestion", "queue", "bandwidth", "throughput", "active_connections", "util"),
    "radio": ("rsrp", "rsrq", "sinr", "cqi", "handover", "signal", "bler"),
    "transport": ("latency", "jitter", "packet_loss", "retransmit", "tcp"),
    "compute": ("cpu", "memory", "resource"),
    "service_quality": ("mos", "voice", "qoe"),
}


def _impute_model_inputs(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    out = df.copy()
    for column in columns:
        if column not in out.columns:
            continue
        series = pd.to_numeric(out[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        median = float(series.median()) if series.notna().any() else 0.0
        out[column] = series.fillna(median if np.isfinite(median) else 0.0)
    return out


def _sanitize_prob_matrix(arr: np.ndarray) -> np.ndarray:
    values = np.asarray(arr, dtype=float)
    values = np.nan_to_num(values, nan=0.0, posinf=1.0, neginf=0.0)
    return np.clip(values, 0.0, 1.0)


def _severity_from_margin(max_margin: float, debug_metric: str = "") -> str:
    if np.isinf(max_margin) and max_margin > 0:
        logger.debug("Severity: infinite positive margin -> critical")
        return "critical"
    if not np.isfinite(max_margin):
        logger.debug("Severity: non-finite margin %s -> unknown", max_margin)
        return "unknown"
    if max_margin < -0.15:
        severity = "normal"
    elif max_margin < -0.05:
        severity = "watch"
    elif max_margin < 0.05:
        severity = "warning"
    elif max_margin < 0.15:
        severity = "high"
    else:
        severity = "critical"
    logger.info(
        "Severity Decision: margin=%+.4f (%s) -> %s",
        max_margin,
        debug_metric or "max across all metrics",
        severity.upper(),
    )
    return severity


def _load_raw_xgb_models(model_dir: Path) -> Dict[str, object]:
    from xgboost import XGBClassifier

    models: Dict[str, object] = {}
    for name in TARGET_NAMES:
        path_json = model_dir / f"xgb_{name}.json"
        if path_json.exists():
            model = XGBClassifier()
            model.load_model(str(path_json))
            models[name] = model
    return models


def _softmax(scores: dict[str, float]) -> list[dict[str, float]]:
    if not scores:
        return []
    keys = list(scores.keys())
    values = np.array([scores[key] for key in keys], dtype=float)
    values = np.exp(values - np.max(values))
    values /= max(float(values.sum()), 1e-8)
    ranked = sorted(
        (
            {"domain": key, "score": round(float(score), 4)}
            for key, score in zip(keys, values, strict=False)
        ),
        key=lambda item: item["score"],
        reverse=True,
    )
    return ranked


def _sanitize_eta_minutes(value: float, *, minimum_minutes: float = 0.5, maximum_minutes: float = 24.0 * 60.0) -> float:
    try:
        eta = float(value)
    except Exception:
        return float("inf")
    if not np.isfinite(eta):
        return float("inf")
    if eta < 0.0:
        return float("inf")
    if eta == 0.0:
        return minimum_minutes
    if eta > maximum_minutes:
        return float("inf")
    return float(max(minimum_minutes, eta))


class PredictionAgent:
    def __init__(
        self,
        model_dir: Path | None = None,
        preprocessor_path: Path | None = None,
        incident_store: IncidentStore | None = None,
        llm: LLMExplainer | None = None,
    ) -> None:
        from llm.explainer import LLMExplainer
        from models.eta_trainer import load_eta_models
        from models.lstm_trainer import QoSLSTM, load_lstm_artifacts
        from models.prophet_forecaster import ProphetForecaster
        from models.xgb_trainer import load_xgb_feature_columns, load_xgb_models
        from rag.incident_store import IncidentStore

        self.model_dir = Path(model_dir) if model_dir is not None else SAVED_MODELS_DIR
        self.preprocessor_path = (
            Path(preprocessor_path) if preprocessor_path is not None else self.model_dir / "preprocessor.joblib"
        )
        self.preprocessor: Optional[Preprocessor] = joblib.load(self.preprocessor_path)
        self.xgb_models = load_xgb_models(self.model_dir)
        self.feature_cols: List[str] = list(joblib.load(self.model_dir / "xgb_feature_columns.joblib"))
        self.xgb_feature_cols_per_target = load_xgb_feature_columns(self.model_dir, fallback_cols=self.feature_cols)
        self.xgb_models_shap = _load_raw_xgb_models(self.model_dir)
        self.eta_models = load_eta_models(self.model_dir)
        self.lstm_artifacts = load_lstm_artifacts(self.model_dir / "lstm_qos.pt")
        self.lstm_model = QoSLSTM(input_dim=len(self.lstm_artifacts.feature_cols))
        self.lstm_model.load_state_dict(self.lstm_artifacts.state_dict)
        self.lstm_model.eval()
        self.prophet = ProphetForecaster(self.model_dir)
        self.incident_store = incident_store or IncidentStore()
        self.llm = llm or LLMExplainer()
        self.decision_thresholds: Dict[str, float] = {name: 0.5 for name in TARGET_NAMES}
        threshold_path = self.model_dir / "decision_thresholds.joblib"
        if threshold_path.exists():
            raw = joblib.load(threshold_path)
            if isinstance(raw, dict):
                for name in TARGET_NAMES:
                    self.decision_thresholds[name] = float(np.clip(float(raw.get(name, 0.5)), 0.01, 0.99))

    def _prepare_frame(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        if self.preprocessor is None:
            raise RuntimeError("Preprocessor is not loaded.")
        cleaned = apply_qos_schema_cleaning(df_raw)
        return engineer_features(self.preprocessor.transform(cleaned.copy()))

    def _predict_xgb_probabilities(self, df: pd.DataFrame, row: pd.Series) -> np.ndarray:
        xgb_probs = np.zeros((1, len(TARGET_NAMES)), dtype=float)
        for index, target in enumerate(TARGET_NAMES):
            model = self.xgb_models.get(target)
            if model is None:
                xgb_probs[0, index] = 0.5
                continue
            target_cols = self.xgb_feature_cols_per_target.get(target, self.feature_cols)
            available = [column for column in target_cols if column in df.columns]
            if not available:
                xgb_probs[0, index] = 0.5
                continue
            matrix = row[available].to_numpy(dtype=np.float32).reshape(1, -1)
            proba = np.asarray(model.predict_proba(matrix), dtype=float)
            xgb_probs[0, index] = float(proba[0, 1] if proba.shape[1] > 1 else proba[0, 0])
        return _sanitize_prob_matrix(xgb_probs)

    def _predict_lstm_probabilities(self, df: pd.DataFrame) -> np.ndarray:
        import torch

        from models.lstm_trainer import scale_window

        feat_cols = self.lstm_artifacts.feature_cols
        window = df.iloc[-LSTM_WINDOW:][feat_cols].to_numpy(dtype=np.float32)
        window = np.nan_to_num(window, nan=0.0, posinf=0.0, neginf=0.0)
        scaled = scale_window(
            window,
            scaler_object=self.lstm_artifacts.scaler_object,
            scaler_min=self.lstm_artifacts.scaler_min,
            scaler_max=self.lstm_artifacts.scaler_max,
        )
        scaled = np.nan_to_num(scaled, nan=0.0, posinf=1.0, neginf=0.0)
        tensor = torch.from_numpy(scaled.reshape(1, LSTM_WINDOW, -1))
        with torch.no_grad():
            logits = self.lstm_model(tensor)
            probs = torch.sigmoid(logits).numpy()
        return _sanitize_prob_matrix(probs)

    def _estimate_recent_risk_windows(self, df: pd.DataFrame, xgb_probs: np.ndarray, lstm_probs: np.ndarray) -> list[float]:
        from models.ensemble import ensemble_predict

        feat_cols = self.lstm_artifacts.feature_cols
        total_windows = max(0, len(df) - LSTM_WINDOW + 1)
        if total_windows <= 1:
            return [float(np.max(ensemble_predict(xgb_probs, lstm_probs)[0]))]

        recent_scores: list[float] = []
        max_windows = min(5, total_windows)
        for offset in range(max_windows):
            subset = df.iloc[: len(df) - (max_windows - offset - 1)].copy()
            row = subset.iloc[-1]
            window_xgb = self._predict_xgb_probabilities(subset, row)
            window_lstm = self._predict_lstm_probabilities(subset)
            recent_scores.append(float(np.max(ensemble_predict(window_xgb, window_lstm)[0])))
        return recent_scores

    def _compute_data_quality(self, history_raw: pd.DataFrame, engineered: pd.DataFrame, model_cols: list[str]) -> dict[str, float]:
        raw_missing = float(history_raw.isna().sum().sum())
        raw_total = float(history_raw.shape[0] * max(history_raw.shape[1], 1))
        raw_completeness = 1.0 - (raw_missing / raw_total if raw_total else 0.0)
        model_frame = engineered[model_cols].replace([np.inf, -np.inf], np.nan)
        missing_ratio = float(model_frame.isna().mean().mean()) if not model_frame.empty else 0.0
        quality_score = float(np.clip(0.75 * raw_completeness + 0.25 * (1.0 - missing_ratio), 0.0, 1.0))
        return {
            "raw_completeness_score": round(raw_completeness, 4),
            "missing_feature_ratio": round(missing_ratio, 4),
            "quality_score": round(quality_score, 4),
        }

    def _compute_drift_score(self, df: pd.DataFrame, row: pd.Series, model_cols: list[str]) -> float:
        sample_cols = [column for column in model_cols if column in df.columns][:40]
        if not sample_cols or len(df) < 5:
            return 0.0
        baseline = df[sample_cols].iloc[:-1]
        if baseline.empty:
            return 0.0
        mean = baseline.mean(axis=0)
        std = baseline.std(axis=0).replace(0.0, 1.0).fillna(1.0)
        z_scores = ((row[sample_cols] - mean) / std).abs().replace([np.inf, -np.inf], 0.0).fillna(0.0)
        drift_score = float(np.clip(z_scores.mean() / 5.0, 0.0, 1.0))
        return round(drift_score, 4)

    def _compute_temporal_signals(
        self,
        primary_metric: str,
        primary_probability: float,
        threshold: float,
        recent_risk_scores: list[float],
        primary_eta: float,
    ) -> dict[str, float | str]:
        recent = np.asarray(recent_risk_scores, dtype=float)
        trailing_mean = float(np.mean(recent[:-1])) if recent.size > 1 else primary_probability
        velocity = float(primary_probability - trailing_mean)
        acceleration = float(0.0)
        if recent.size >= 3:
            acceleration = float((recent[-1] - recent[-2]) - (recent[-2] - recent[-3]))
        persistence = float(np.mean(recent >= threshold)) if recent.size else 0.0
        trend = "rising" if velocity > 0.03 else "cooling" if velocity < -0.03 else "stable"
        return {
            "primary_metric": primary_metric,
            "risk_velocity": round(velocity, 4),
            "risk_acceleration": round(acceleration, 4),
            "risk_persistence": round(persistence, 4),
            "trend_label": trend,
            "time_to_threshold_crossing_min": None if not np.isfinite(primary_eta) else round(float(primary_eta), 2),
        }

    def _infer_domain_hints(
        self,
        primary_metric: str,
        top_drivers: dict[str, list[dict[str, object]]],
        incidents: list[dict[str, object]],
    ) -> list[dict[str, float]]:
        text_parts = [primary_metric]
        for drivers in top_drivers.values():
            text_parts.extend(str(driver.get("feature", "")) for driver in drivers)
        for incident in incidents:
            meta = incident.get("metadata", {})
            text_parts.append(str(meta.get("incident_type", "")))
            text_parts.append(str(incident.get("document", "")))
        blob = " ".join(text_parts).lower()

        scores: dict[str, float] = {}
        for domain, keywords in DOMAIN_KEYWORDS.items():
            scores[domain] = sum(1.0 for keyword in keywords if keyword in blob)
        if primary_metric in ("latency_breach_risk", "jitter_risk", "throughput_risk"):
            scores["transport"] = scores.get("transport", 0.0) + 1.5
        if primary_metric == "congestion_risk":
            scores["capacity"] = scores.get("capacity", 0.0) + 1.5
        if primary_metric == "mos_risk":
            scores["service_quality"] = scores.get("service_quality", 0.0) + 1.5
        if primary_metric == "call_drop_risk":
            scores["radio"] = scores.get("radio", 0.0) + 1.0
            scores["service_quality"] = scores.get("service_quality", 0.0) + 1.0
        return _softmax(scores)[:3]

    def _build_evidence_summary(
        self,
        primary_metric: str,
        top_drivers: dict[str, list[dict[str, object]]],
        incidents: list[dict[str, object]],
    ) -> dict[str, object]:
        drivers = top_drivers.get(primary_metric, [])
        evidence = {
            "top_features": [driver.get("feature", "") for driver in drivers[:3]],
            "incident_count": len(incidents),
            "closest_incident_type": "",
            "closest_incident_similarity_pct": 0.0,
        }
        if incidents:
            first = incidents[0]
            meta = first.get("metadata", {})
            distance = first.get("distance")
            similarity = 0.0 if distance is None else max(0.0, min(100.0, (1.0 - float(distance)) * 100.0))
            evidence["closest_incident_type"] = str(meta.get("incident_type", first.get("incident_type", "")))
            evidence["closest_incident_similarity_pct"] = round(similarity, 1)
        return evidence

    def _build_model_metadata(self, history_raw: pd.DataFrame) -> dict[str, object]:
        fingerprint = hashlib.sha1(
            history_raw.tail(LSTM_WINDOW).to_json(date_format="iso", orient="records").encode("utf-8")
        ).hexdigest()
        return {
            "model_family": "decision_packet",
            "artifacts_dir": str(self.model_dir),
            "feature_count": len(self.feature_cols),
            "input_window_rows": int(min(len(history_raw), LSTM_WINDOW)),
            "input_window_hash": fingerprint,
        }

    def _stabilize_eta_predictions(
        self,
        risk: dict[str, float],
        raw_eta_per_target: dict[str, float],
        thresholds: np.ndarray,
        capacity_eta: float,
    ) -> tuple[dict[str, float], float, dict[str, str]]:
        eta_per_target: dict[str, float] = {}
        eta_notes: dict[str, str] = {}
        for index, target in enumerate(TARGET_NAMES):
            if target == "congestion_risk":
                eta_value = _sanitize_eta_minutes(capacity_eta)
                eta_per_target[target] = eta_value
                eta_notes[target] = "prophet_capacity" if np.isfinite(eta_value) else "no_capacity_crossing"
                continue

            risk_value = float(risk.get(target, 0.0))
            threshold = float(thresholds[index])
            raw_eta = float(raw_eta_per_target.get(target, float("inf")))
            eta_value = _sanitize_eta_minutes(raw_eta)

            if risk_value < max(0.0, threshold - 0.10):
                eta_per_target[target] = float("inf")
                eta_notes[target] = "below_threshold_margin"
            elif np.isfinite(eta_value):
                eta_per_target[target] = eta_value
                eta_notes[target] = "model_eta"
            else:
                eta_per_target[target] = float("inf")
                eta_notes[target] = "eta_unavailable"

        finite_etas = [value for value in eta_per_target.values() if np.isfinite(value)]
        fleet_eta_min = min(finite_etas) if finite_etas else float("inf")
        return eta_per_target, fleet_eta_min, eta_notes

    def predict(
        self,
        node_id: str,
        history_raw: pd.DataFrame,
        timestamp: str | None = None,
        generate_llm: bool = True,
    ) -> PredictionResult:
        from explainability.shap_explainer import explain_tabular_row
        from models.ensemble import ensemble_predict, probs_to_dict
        from models.eta_trainer import ETA_TARGETS, predict_eta_minutes

        if history_raw.empty:
            raise ValueError("history_raw must be non-empty.")
        hist = history_raw[history_raw["node_id"].astype(str) == str(node_id)].copy() if "node_id" in history_raw.columns else history_raw.copy()
        if hist.empty:
            raise ValueError("No rows for requested node_id.")
        hist = hist.sort_values("timestamp" if "timestamp" in hist.columns else hist.columns[0])
        df = self._prepare_frame(hist)
        if len(df) < LSTM_WINDOW:
            raise ValueError(f"Need at least {LSTM_WINDOW} rows after preprocessing.")

        feat_cols = self.lstm_artifacts.feature_cols
        for column in feat_cols:
            if column not in df.columns:
                raise ValueError(f"Missing engineered column required by LSTM: {column}")

        model_cols = sorted(set(self.feature_cols) | set(feat_cols))
        quality = self._compute_data_quality(hist, df, [column for column in model_cols if column in df.columns])
        df = _impute_model_inputs(df, model_cols)
        last_row = df.iloc[-1]
        ts = timestamp or str(last_row.get("timestamp", ""))

        xgb_probs = self._predict_xgb_probabilities(df, last_row)
        lstm_probs = self._predict_lstm_probabilities(df)
        ensemble_row = ensemble_predict(xgb_probs, lstm_probs)[0]
        ensemble_row = _sanitize_prob_matrix(ensemble_row.reshape(1, -1)).reshape(-1)
        risk = probs_to_dict(ensemble_row)

        thresholds = np.array([self.decision_thresholds.get(target, 0.5) for target in TARGET_NAMES], dtype=float)
        margins = ensemble_row - thresholds
        highest_idx = int(np.argmax(margins))
        highest_metric = TARGET_NAMES[highest_idx]
        highest_margin = float(np.max(margins))
        margins_per_metric = {TARGET_NAMES[index]: float(margins[index]) for index in range(len(TARGET_NAMES))}
        severity = _severity_from_margin(highest_margin, debug_metric=highest_metric)

        shap_features = explain_tabular_row(
            self.xgb_models_shap,
            self.feature_cols,
            last_row,
            per_target_feature_cols=self.xgb_feature_cols_per_target,
        )
        shap_features_dict = PredictionResult.reformat_features_to_target_grouped(shap_features)
        primary_drivers = shap_features_dict.get(highest_metric, [])[:3]
        top_3_drivers = PredictionResult.reformat_features_to_target_grouped(primary_drivers)

        rag_text = " ".join(f"{key}={float(value):.3f}" for key, value in risk.items())
        incidents = self.incident_store.query(rag_text, top_k=3)

        eta_debug_status = "ok"
        eta_debug_reason = ""
        eta_debug_max_forecast: float | None = None
        eta_debug_threshold: float | None = None
        eta_debug_horizon_min: float | None = None
        try:
            eta_diag = self.prophet.forecast_capacity_diagnostics(str(node_id), df)
            capacity_eta = float(eta_diag.get("eta_min", float("inf")))
            eta_debug_status = str(eta_diag.get("status", "ok"))
            eta_debug_reason = str(eta_diag.get("reason", ""))
            eta_debug_max_forecast = eta_diag.get("max_forecast")
            eta_debug_threshold = eta_diag.get("threshold")
            eta_debug_horizon_min = eta_diag.get("horizon_min")
        except Exception as exc:
            capacity_eta = float("inf")
            eta_debug_status = "unavailable"
            eta_debug_reason = f"{type(exc).__name__}: {exc}"

        raw_eta_per_target: Dict[str, float] = {}
        for target in ETA_TARGETS:
            model = self.eta_models.get(target)
            if model is None:
                raw_eta_per_target[target] = float("inf")
                continue
            try:
                raw_eta_per_target[target] = float(predict_eta_minutes(model, last_row))
            except Exception:
                raw_eta_per_target[target] = float("inf")

        eta_per_target, _, eta_notes = self._stabilize_eta_predictions(
            risk,
            raw_eta_per_target,
            thresholds,
            capacity_eta,
        )

        primary_probability = float(ensemble_row[highest_idx])
        primary_eta = float(eta_per_target.get(highest_metric, float("inf")))
        recent_scores = self._estimate_recent_risk_windows(df, xgb_probs, lstm_probs)
        temporal_signals = self._compute_temporal_signals(
            highest_metric,
            primary_probability,
            float(thresholds[highest_idx]),
            recent_scores,
            primary_eta,
        )

        disagreement = float(np.mean(np.abs(xgb_probs.reshape(-1) - lstm_probs.reshape(-1))))
        model_agreement = float(np.clip(1.0 - disagreement, 0.0, 1.0))
        drift_score = self._compute_drift_score(df, last_row, model_cols)
        stability = float(np.clip(1.0 - np.std(np.asarray(recent_scores, dtype=float)), 0.0, 1.0))
        confidence_score = float(
            np.clip(
                0.40 * max(0.0, min(1.0, quality["quality_score"]))
                + 0.25 * model_agreement
                + 0.20 * stability
                + 0.15 * (1.0 - drift_score),
                0.0,
                1.0,
            )
        )
        trust_signals = {
            "confidence_score": round(confidence_score, 4),
            "model_agreement_score": round(model_agreement, 4),
            "prediction_stability": round(stability, 4),
            "drift_score": round(drift_score, 4),
            "missing_feature_ratio": quality["missing_feature_ratio"],
            "data_quality_score": quality["quality_score"],
        }
        domain_hints = self._infer_domain_hints(highest_metric, top_3_drivers, incidents)
        evidence_summary = self._build_evidence_summary(highest_metric, top_3_drivers, incidents)
        model_metadata = self._build_model_metadata(hist)

        llm_summary = ""
        operator_brief = ""
        llm_used = False
        if generate_llm:
            llm_summary = self.llm.generate_prediction_brief(
                node_id=str(node_id),
                timestamp=str(ts),
                severity_band=severity,
                primary_metric=highest_metric,
                primary_probability=primary_probability,
                capacity_eta_min=capacity_eta,
                primary_metric_eta_min=primary_eta,
                eta_per_target=eta_per_target,
                eta_notes=eta_notes,
                decision_thresholds={target: float(self.decision_thresholds.get(target, 0.5)) for target in TARGET_NAMES},
                confidence_score=confidence_score,
                domain_hints=domain_hints,
                risk_probs=risk,
                shap_features=shap_features_dict,
                temporal_signals=temporal_signals,
                trust_signals=trust_signals,
                retrieved_incidents=incidents,
            )
            operator_brief = llm_summary
            llm_used = bool(llm_summary)

        eta_clause = (
            f"time-to-event {primary_eta:.1f} min"
            if np.isfinite(primary_eta)
            else "no near-term time-to-event crossing"
        )
        explanation = llm_summary or (
            f"{severity.upper()} risk on {node_id}: {highest_metric} at {primary_probability:.0%}, {eta_clause}."
        )

        recommended_action = ""
        if domain_hints:
            domain = domain_hints[0]["domain"]
            recommended_action = f"Inspect {domain} indicators for {highest_metric} on node {node_id}."

        return PredictionResult(
            node_id=str(node_id),
            timestamp=str(ts),
            risk_probs=risk,
            capacity_exhaustion_eta_min=capacity_eta,
            severity=severity,
            shap_features=shap_features_dict,
            retrieved_incidents=incidents,
            explanation=explanation,
            eta_debug_status=eta_debug_status,
            eta_debug_reason=eta_debug_reason,
            eta_debug_max_forecast=eta_debug_max_forecast,
            eta_debug_threshold=eta_debug_threshold,
            eta_debug_horizon_min=eta_debug_horizon_min,
            primary_metric_name=highest_metric,
            primary_metric_eta_min=primary_eta,
            primary_metric_probability=primary_probability,
            eta_per_target=eta_per_target,
            top_3_drivers=top_3_drivers,
            recommended_action=recommended_action,
            margins_per_metric=margins_per_metric,
            highest_margin_metric=highest_metric,
            highest_margin_value=highest_margin,
            decision_thresholds_used=dict(self.decision_thresholds),
            llm_summary=llm_summary,
            operator_brief=operator_brief,
            confidence_score=confidence_score,
            trust_signals=trust_signals,
            temporal_signals=temporal_signals,
            domain_hints=domain_hints,
            evidence_summary=evidence_summary,
            model_metadata=model_metadata,
            data_quality=quality,
            llm_used=llm_used,
        )
