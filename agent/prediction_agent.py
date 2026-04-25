# CLEANED: neutralized eta_debug_reason initializer to avoid misleading default message
"""Top-level orchestration for inference, explainability, RAG, and LLM alerts."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
import torch
from xgboost import XGBClassifier

from agent.result import PredictionResult
from config import FUTURE_WINDOW_STEPS, LSTM_WINDOW, SAVED_MODELS_DIR, SECONDS_PER_STEP, TARGET_NAMES
from data_pipeline.features import engineer_features
from data_pipeline.loader import apply_qos_schema_cleaning
from data_pipeline.preprocessor import Preprocessor
from explainability.shap_explainer import explain_tabular_row
from llm.explainer import LLMExplainer
from models.eta_trainer import ETA_TARGETS, load_eta_models, predict_eta_minutes
from models.ensemble import ensemble_predict, probs_to_dict
from models.lstm_trainer import QoSLSTM, load_lstm_artifacts, scale_window
from models.prophet_forecaster import ProphetForecaster
from models.xgb_trainer import load_xgb_models
from rag.incident_store import IncidentStore


def _impute_model_inputs(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    """Replace NaN/Inf in model feature columns with the column median (or 0)."""
    out = df.copy()
    for c in columns:
        if c not in out.columns:
            continue
        s = pd.to_numeric(out[c], errors="coerce").replace([np.inf, -np.inf], np.nan)
        med = float(s.median()) if s.notna().any() else 0.0
        if not np.isfinite(med):
            med = 0.0
        out[c] = s.fillna(med)
    return out


def _sanitize_prob_matrix(arr: np.ndarray) -> np.ndarray:
    """Ensure finite probabilities in [0, 1] for ensemble inputs/outputs."""
    x = np.asarray(arr, dtype=float)
    x = np.nan_to_num(x, nan=0.0, posinf=1.0, neginf=0.0)
    return np.clip(x, 0.0, 1.0)


def _severity_from_margin(max_margin: float, debug_metric: str = "") -> str:
    """Map probability-threshold margin to a stable operational severity band.
    
    Severity Thresholds (based on margin = probability - threshold):
    - normal:   margin < -0.15  (well below threshold)
    - watch:    -0.15 ≤ margin < -0.05  (approaching threshold)
    - warning:  -0.05 ≤ margin < 0.05   (near threshold boundary)
    - high:     0.05 ≤ margin < 0.15    (clearly above threshold)
    - critical: margin ≥ 0.15   (significantly above threshold)
    
    Args:
        max_margin: Highest margin across all metrics (probability - threshold)
        debug_metric: Metric name that has this margin (for logging)
    
    Returns:
        Severity band as string
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Handle infinity as critical (extremely high margin)
    if np.isinf(max_margin) and max_margin > 0:
        logger.debug(f"Severity: infinite positive margin → 'critical'")
        return "critical"
    
    # Handle NaN and negative infinity as unknown
    if not np.isfinite(max_margin):
        logger.debug(f"Severity: non-finite margin {max_margin} → 'unknown'")
        return "unknown"
    
    # Determine severity with explicit boundaries
    if max_margin < -0.15:
        severity = "normal"
    elif max_margin < -0.05:
        severity = "watch"
    elif max_margin < 0.05:
        severity = "warning"
    elif max_margin < 0.15:
        severity = "high"
    else:  # max_margin >= 0.15
        severity = "critical"
    
    # Log the decision with full context
    logger.info(
        f"Severity Decision: margin={max_margin:+.4f} "
        f"({debug_metric if debug_metric else 'max across all metrics'}) "
        f"→ {severity.upper()}"
    )
    
    return severity


def _load_raw_xgb_models(model_dir: Path) -> Dict[str, XGBClassifier]:
    models: Dict[str, XGBClassifier] = {}
    for name in TARGET_NAMES:
        path_json = model_dir / f"xgb_{name}.json"
        if not path_json.exists():
            continue
        booster = XGBClassifier()
        booster.load_model(str(path_json))
        models[name] = booster
    return models


class PredictionAgent:
    def __init__(
        self,
        model_dir: Path | None = None,
        preprocessor_path: Path | None = None,
        incident_store: IncidentStore | None = None,
        llm: LLMExplainer | None = None,
    ) -> None:
        self.model_dir = Path(model_dir) if model_dir is not None else SAVED_MODELS_DIR
        self.preprocessor_path = (
            Path(preprocessor_path) if preprocessor_path is not None else self.model_dir / "preprocessor.joblib"
        )
        try:
            self.preprocessor: Optional[Preprocessor] = joblib.load(self.preprocessor_path)
            if self.preprocessor is None:
                raise ValueError("Loaded preprocessor is None")
        except FileNotFoundError as e:
            raise RuntimeError(
                f"Preprocessor file not found at {self.preprocessor_path}\n"
                f"Ensure train_all.py was run first."
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Failed to load preprocessor from {self.preprocessor_path}: {type(e).__name__}: {e}"
            ) from e
        self.xgb_models = load_xgb_models(self.model_dir)
        self.feature_cols: List[str] = list(joblib.load(self.model_dir / "xgb_feature_columns.joblib"))
        from models.xgb_trainer import load_xgb_feature_columns

        self.xgb_feature_cols_per_target = load_xgb_feature_columns(
            self.model_dir, fallback_cols=self.feature_cols
        )
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
        thr_path = self.model_dir / "decision_thresholds.joblib"
        if thr_path.exists():
            try:
                raw = joblib.load(thr_path)
                if isinstance(raw, dict):
                    for name in TARGET_NAMES:
                        v = float(raw.get(name, 0.5))
                        self.decision_thresholds[name] = float(np.clip(v, 0.01, 0.99))
                else:
                    # HIGH FIX: Explicit error on invalid threshold format
                    raise TypeError(
                        f"Invalid decision_thresholds format: expected dict, got {type(raw).__name__}. "
                        f"Using defaults (0.5 for all targets)."
                    )
            except (TypeError, KeyError, ValueError) as exc:
                # HIGH FIX: Log explicit error instead of silent failure
                logger.error(
                    f"Failed to load decision thresholds: {exc}. "
                    f"Using defaults (0.5 for all targets)."
                )
                pass

    def _prepare_frame(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        if self.preprocessor is None:
            raise RuntimeError("Preprocessor is not loaded.")
        df_raw = apply_qos_schema_cleaning(df_raw)
        df = engineer_features(self.preprocessor.transform(df_raw.copy()))
        return df

    def predict(
        self,
        node_id: str,
        history_raw: pd.DataFrame,
        timestamp: str | None = None,
        generate_llm: bool = True,
    ) -> PredictionResult:
        if history_raw.empty:
            raise ValueError("history_raw must be non-empty.")
        if "node_id" in history_raw.columns:
            hist = history_raw[history_raw["node_id"].astype(str) == str(node_id)].copy()
        else:
            hist = history_raw.copy()
        if hist.empty:
            raise ValueError("No rows for requested node_id.")

        hist = hist.sort_values("timestamp" if "timestamp" in hist.columns else hist.columns[0])
        df = self._prepare_frame(hist)

        if len(df) < LSTM_WINDOW:
            raise ValueError(f"Need at least {LSTM_WINDOW} rows after preprocessing.")

        feat_cols = self.lstm_artifacts.feature_cols
        for c in feat_cols:
            if c not in df.columns:
                raise ValueError(f"Missing engineered column required by LSTM: {c}")

        model_cols = sorted(set(self.feature_cols) | set(feat_cols))
        df = _impute_model_inputs(df, model_cols)

        last_row = df.iloc[-1]
        ts = timestamp or str(last_row.get("timestamp", ""))

        xgb_probs = np.zeros((1, len(TARGET_NAMES)), dtype=float)
        for i, name in enumerate(TARGET_NAMES):
            m = self.xgb_models.get(name)
            if m is None:
                continue
            target_cols = self.xgb_feature_cols_per_target.get(name, self.feature_cols)
            # HIGH FIX: Validate all required feature columns exist in the dataframe
            available = [c for c in target_cols if c in df.columns]
            missing = set(target_cols) - set(available)
            if missing:
                logger.error(
                    f"Missing required features for {name}: {sorted(missing)}. "
                    f"Expected: {sorted(target_cols)}. "
                    f"Available: {sorted(available)}. "
                    f"Using available features only (may produce incorrect predictions)."
                )
            if not available:
                logger.error(
                    f"No features available for {name}. "
                    f"Cannot make prediction. Using default probability 0.5."
                )
                xgb_probs[0, i] = 0.5
                continue
            xgb_mat = last_row[available].to_numpy(dtype=np.float32).reshape(1, -1)
            proba = np.asarray(m.predict_proba(xgb_mat), dtype=float)
            if proba.ndim != 2 or proba.shape[0] < 1:
                continue
            if proba.shape[1] == 1:
                xgb_probs[0, i] = float(proba[0, 0])
            else:
                xgb_probs[0, i] = float(proba[0, 1])

        xgb_probs = _sanitize_prob_matrix(xgb_probs)

        win = df.iloc[-LSTM_WINDOW:][feat_cols].to_numpy(dtype=np.float32)
        if win.shape[0] < LSTM_WINDOW:
            raise ValueError(
                f"Insufficient data for LSTM window: got {win.shape[0]} rows, "
                f"need {LSTM_WINDOW}. DataFrame has {len(df)} rows total.\n"
                f"Solution: Ensure at least {LSTM_WINDOW} rows of data for the node."
            )
        if win.shape[1] != len(feat_cols):
            raise ValueError(
                f"Feature column mismatch in LSTM window: got {win.shape[1]} columns, "
                f"expected {len(feat_cols)}.\n"
                f"Expected features: {sorted(feat_cols)}\n"
                f"DataFrame columns: {list(df.columns)}"
            )
        
        win = np.nan_to_num(win, nan=0.0, posinf=0.0, neginf=0.0)
        win_scaled = scale_window(
            win, 
            scaler_object=self.lstm_artifacts.scaler_object,
            scaler_min=self.lstm_artifacts.scaler_min,  # Fallback for legacy artifacts
            scaler_max=self.lstm_artifacts.scaler_max,  # Fallback for legacy artifacts
        )
        
        # Verify scaling preserved shape (or padded to batch size)
        expected_shape = (LSTM_WINDOW, len(feat_cols))
        if win_scaled.ndim == 3:  # Batched output
            if win_scaled.shape[1:] != expected_shape:
                raise ValueError(
                    f"LSTM scaling produced unexpected shape: {win_scaled.shape}, "
                    f"expected (..., {expected_shape[0]}, {expected_shape[1]})"
                )
        else:  # Single window
            if win_scaled.shape != expected_shape:
                raise ValueError(
                    f"LSTM scaling produced wrong shape: {win_scaled.shape}, "
                    f"expected {expected_shape}"
                )
        
        win_scaled = np.nan_to_num(win_scaled, nan=0.0, posinf=1.0, neginf=0.0)
        tensor = torch.from_numpy(win_scaled.reshape(1, LSTM_WINDOW, -1))
        with torch.no_grad():
            logits = self.lstm_model(tensor)
            lstm_out = torch.sigmoid(logits).numpy()
        lstm_probs = _sanitize_prob_matrix(lstm_out)

        ens_row = ensemble_predict(xgb_probs, lstm_probs)[0]
        ens_row = _sanitize_prob_matrix(ens_row.reshape(1, -1)).reshape(-1)
        risk = probs_to_dict(ens_row)

        thresholds = np.array([self.decision_thresholds.get(name, 0.5) for name in TARGET_NAMES], dtype=float)
        margins = ens_row - thresholds
        max_margin = float(np.max(margins))
        
        # ===== Identify highest margin metric (for debugging) =====
        highest_margin_idx = int(np.argmax(margins))
        highest_margin_metric = TARGET_NAMES[highest_margin_idx]
        margins_per_metric = {TARGET_NAMES[i]: float(margins[i]) for i in range(len(TARGET_NAMES))}
        
        # ===== Calculate severity WITH transparency =====
        sev = _severity_from_margin(max_margin, debug_metric=highest_margin_metric)

        shap_feats = explain_tabular_row(self.xgb_models_shap, self.feature_cols, last_row, 
                                         per_target_feature_cols=self.xgb_feature_cols_per_target)
        
        # --- Phase 2: Reformat SHAP features early (before LLM, for consistency) ---
        shap_feats_dict = PredictionResult.reformat_features_to_target_grouped(shap_feats)

        rag_text = " ".join(
            f"{k}={float(v):.3f}" if np.isfinite(v) else f"{k}=0.000" for k, v in risk.items()
        )
        incidents = self.incident_store.query(rag_text, top_k=3)

        eta_debug_status = "ok"
        eta_debug_reason = ""
        eta_debug_max_forecast: float | None = None
        eta_debug_threshold: float | None = None
        eta_debug_horizon_min: float | None = None
        try:
            if hasattr(self.prophet, "forecast_capacity_diagnostics"):
                eta_diag = self.prophet.forecast_capacity_diagnostics(str(node_id), df)
                eta = float(eta_diag.get("eta_min", float("inf")))
                eta_debug_status = str(eta_diag.get("status", "ok"))
                eta_debug_reason = str(eta_diag.get("reason", ""))
                eta_debug_max_forecast = eta_diag.get("max_forecast")
                eta_debug_threshold = eta_diag.get("threshold")
                eta_debug_horizon_min = eta_diag.get("horizon_min")
            else:
                eta = self.prophet.forecast_capacity_exhaustion_eta_min(str(node_id), df)
                if np.isfinite(eta) and eta != float("inf"):
                    eta_debug_status = "ok"
                    eta_debug_reason = "forecast succeeded and threshold crossed within horizon (compat mode)"
                else:
                    eta_debug_status = "no_crossing"
                    eta_debug_reason = "forecast succeeded, but threshold was not crossed within horizon (compat mode)"
        except Exception as exc:
            eta = float("inf")
            eta_debug_status = "prophet_error"
            eta_debug_reason = f"prophet failure: {type(exc).__name__}: {str(exc)}"

        eta_per_target: Dict[str, float] = {}
        for target in ETA_TARGETS:
            # CRITICAL FIX: Validate last_row has required columns for ETA prediction
            eta_model = self.eta_models.get(target)
            if eta_model is None:
                logger.warning(f"No ETA model available for {target}")
                eta_per_target[target] = float("inf")
                continue
            
            # Verify last_row completeness (ETA models expect specific columns)
            try:
                eta_per_target[target] = predict_eta_minutes(eta_model, last_row)
            except (KeyError, ValueError) as exc:
                logger.error(
                    f"ETA prediction failed for {target}: {exc}. "
                    f"last_row columns: {list(last_row.index)}. "
                    f"Setting ETA to inf."
                )
                eta_per_target[target] = float("inf")

        if generate_llm:
            explanation = self.llm.generate_alert(
                risk_probs=risk,
                shap_features=shap_feats_dict,
                retrieved_incidents=incidents,
                node_id=str(node_id),
                timestamp=str(ts),
                capacity_eta_min=eta,
                severity_band=sev,
                margin_to_critical=max_margin,
                primary_metric=highest_margin_metric,
            )
        else:
            explanation = ""

        # --- Phase 3: Primary Metric Selection (severity-driven alignment) ---
        # Primary metric = metric with highest margin (not highest probability)
        # This ensures severity and primary metric are semantically consistent
        primary_idx = int(np.argmax(margins))  # Index of metric exceeding threshold most clearly
        primary_metric_name = TARGET_NAMES[primary_idx]
        primary_metric_probability = float(ens_row[primary_idx])  # Probability of this metric

        # ETA for primary metric
        if primary_metric_name == "congestion_risk" and np.isfinite(eta):
            primary_metric_eta_min = eta
        else:
            primary_metric_eta_min = float(eta_per_target.get(primary_metric_name, float("inf")))

        # --- Phase 4: Primary Drivers (robust selection from primary metric) ---
        # Ensure drivers belong to primary metric, with fallback to any available drivers
        primary_drivers = shap_feats_dict.get(primary_metric_name, [])[:3]
        
        # Fallback: if no drivers for primary metric, find first metric with drivers
        if not primary_drivers:
            for target, drivers in shap_feats_dict.items():
                if drivers:
                    primary_drivers = drivers[:3]
                    break
        
        top_3_drivers = PredictionResult.reformat_features_to_target_grouped(primary_drivers)

        # Extract recommended action from explanation
        recommended_action = ""
        if explanation:
            sentences = [s.strip() for s in explanation.replace("\n", " ").split(".") if s.strip()]
            action_verbs = (
                "check", "reduce", "offload", "inspect", "monitor", "restart",
                "investigate", "verify", "increase", "decrease", "limit", "reroute"
            )
            for s in sentences:
                if s.lower().startswith(action_verbs):
                    recommended_action = s + "."
                    break
            if not recommended_action and sentences:
                recommended_action = sentences[-1] + "."

        return PredictionResult(
            node_id=str(node_id),
            timestamp=str(ts),
            risk_probs=risk,
            capacity_exhaustion_eta_min=eta,
            severity=sev,
            shap_features=shap_feats_dict,  # Use pre-formatted dict
            retrieved_incidents=incidents,
            explanation=explanation,
            eta_debug_status=eta_debug_status,
            eta_debug_reason=eta_debug_reason,
            eta_debug_max_forecast=eta_debug_max_forecast,
            eta_debug_threshold=eta_debug_threshold,
            eta_debug_horizon_min=eta_debug_horizon_min,
            primary_metric_name=primary_metric_name,
            primary_metric_eta_min=primary_metric_eta_min,
            primary_metric_probability=primary_metric_probability,  # Updated field name
            eta_per_target=eta_per_target,
            top_3_drivers=top_3_drivers,
            recommended_action=recommended_action,
            # === TRANSPARENCY: Margin breakdown ===
            margins_per_metric=margins_per_metric,
            highest_margin_metric=highest_margin_metric,
            highest_margin_value=max_margin,
            decision_thresholds_used=dict(self.decision_thresholds),
        )
