# CLEANED: corrected ETA docstring behavior for provided pre-fitted model
"""Prophet-based congestion ETA forecasting (never used in the ensemble)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from prophet import Prophet
from prophet.serialize import model_from_json, model_to_json

from config import (
    CONGESTION_INDEX_THRESHOLD,
    LABEL_HORIZON_STEPS,
    SAVED_MODELS_DIR,
    SECONDS_PER_STEP,
)

logger = logging.getLogger(__name__)


def _sanitize_node_id(node_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(node_id))


class ProphetForecaster:
    """Fit per-node Prophet models on ``congestion_index`` and forecast capacity exhaustion."""

    def __init__(self, model_dir: Path | None = None) -> None:
        self.model_dir = Path(model_dir) if model_dir is not None else SAVED_MODELS_DIR

    def _model_path(self, node_id: str) -> Path:
        return self.model_dir / f"prophet_{_sanitize_node_id(node_id)}.json"

    @staticmethod
    def _prepare_history(history: pd.DataFrame) -> pd.DataFrame:
        if history.empty or "congestion_index" not in history.columns:
            return pd.DataFrame(columns=["ds", "y"])
        hist = history[["timestamp", "congestion_index"]].copy()
        hist["ds"] = pd.to_datetime(hist["timestamp"], utc=True).dt.tz_localize(None)
        hist["y"] = hist["congestion_index"].astype(float)
        return hist[["ds", "y"]].dropna().sort_values("ds")

    def fit_node(self, node_id: str, df_node: pd.DataFrame) -> Path:
        """Fit Prophet model and save with version tracking."""
        hist = self._prepare_history(df_node)
        if hist.empty:
            raise ValueError("Prophet training requires non-empty frame with congestion_index.")

        m = Prophet(daily_seasonality=False, weekly_seasonality=False)
        m.fit(hist)
        out = self._model_path(node_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        
        # Save with metadata including Prophet version
        metadata = {
            "prophet_version": Prophet.__module__.split(".")[0] + " " + str(Prophet.__module__),
            "model": model_to_json(m),
            "created_at": datetime.utcnow().isoformat(),
            "node_id": str(node_id),
        }
        
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=2)
        return out

    def fit_all_nodes(self, df: pd.DataFrame) -> dict[str, Path]:
        paths: dict[str, Path] = {}
        if "node_id" not in df.columns:
            return paths
        for node_id, g in df.groupby("node_id"):
            try:
                paths[str(node_id)] = self.fit_node(str(node_id), g)
            except ValueError:
                continue
        return paths

    def load_model(self, node_id: str) -> Prophet:
        """Load Prophet model with version checking."""
        p = self._model_path(node_id)
        if not p.exists():
            raise FileNotFoundError(f"No saved Prophet model for node {node_id}: {p}")
        
        with open(p, encoding="utf-8") as fh:
            try:
                data = json.load(fh)
                # Handle both new format (dict with metadata) and old format (plain JSON string)
                if isinstance(data, dict) and "model" in data:
                    saved_version = data.get("prophet_version", "unknown")
                    current_version = str(__version__)
                    # HIGH FIX: Add version compatibility check
                    if saved_version != "unknown" and saved_version != current_version:
                        logger.warning(
                            f"Prophet version mismatch for node {node_id}: "
                            f"model saved with {saved_version}, current version {current_version}. "
                            f"This may cause compatibility issues or silent failures."
                        )
                    logger.debug(f"Loading Prophet model for {node_id} saved with version: {saved_version}")
                    json_data = data["model"]
                else:
                    # Old format: plain JSON string
                    logger.warning(
                        f"Prophet model for {node_id} in old format (no version info). "
                        f"Cannot validate version compatibility."
                    )
                    json_data = data if isinstance(data, str) else json.dumps(data)
            except json.JSONDecodeError:
                # Fallback: try reading as plain JSON string
                fh.seek(0)
                json_data = fh.read()
        
        return model_from_json(json_data)

    def forecast_capacity_diagnostics(
        self,
        node_id: str,
        history: pd.DataFrame,
        horizon_periods: int = LABEL_HORIZON_STEPS,
        threshold: float = CONGESTION_INDEX_THRESHOLD,
        model: Optional[Prophet] = None,
    ) -> dict[str, Any]:
        """Return ETA plus diagnostic details (status, max forecast, threshold, horizon)."""
        del node_id  # retained for API symmetry / logging hooks
        hist = self._prepare_history(history)
        horizon_min = float(horizon_periods * SECONDS_PER_STEP / 60.0)
        if hist.empty:
            return {
                "eta_min": float("inf"),
                "status": "prophet_error",
                "reason": "empty history or missing congestion_index",
                "max_forecast": None,
                "threshold": float(threshold),
                "horizon_min": horizon_min,
            }

        m = model or Prophet(daily_seasonality=False, weekly_seasonality=False)
        if model is None:
            m.fit(hist)

        future = m.make_future_dataframe(periods=horizon_periods, freq=f"{int(SECONDS_PER_STEP)}s")
        fcst = m.predict(future)
        last_ds = hist["ds"].max()
        tail = fcst[fcst["ds"] > last_ds].head(horizon_periods)
        if tail.empty:
            return {
                "eta_min": float("inf"),
                "status": "no_crossing",
                "reason": "forecast tail is empty",
                "max_forecast": None,
                "threshold": float(threshold),
                "horizon_min": horizon_min,
            }

        max_forecast = float(tail["yhat"].max()) if "yhat" in tail.columns else None
        hit = tail[tail["yhat"] >= threshold]
        if hit.empty:
            return {
                "eta_min": float("inf"),
                "status": "no_crossing",
                "reason": "forecast succeeded, but threshold was not crossed within horizon",
                "max_forecast": max_forecast,
                "threshold": float(threshold),
                "horizon_min": horizon_min,
            }

        first_ds = hit.iloc[0]["ds"]
        delta = (first_ds - last_ds).total_seconds() / 60.0
        return {
            "eta_min": float(max(delta, 0.0)),
            "status": "ok",
            "reason": "threshold crossed within forecast horizon",
            "max_forecast": max_forecast,
            "threshold": float(threshold),
            "horizon_min": horizon_min,
        }

    def forecast_capacity_exhaustion_eta_min(
        self,
        node_id: str,
        history: pd.DataFrame,
        horizon_periods: int = LABEL_HORIZON_STEPS,
        threshold: float = CONGESTION_INDEX_THRESHOLD,
        model: Optional[Prophet] = None,
    ) -> float:
        """
        Minutes until ``congestion_index`` first reaches/exceeds ``threshold`` within the horizon.
        If ``model`` is omitted, fits on the supplied ``history`` to track latest telemetry.
        If a pre-fitted ``model`` is passed, forecasting uses it directly (no refit).
        If the threshold is never crossed, returns ``float('inf')``.
        """
        diag = self.forecast_capacity_diagnostics(
            node_id=node_id,
            history=history,
            horizon_periods=horizon_periods,
            threshold=threshold,
            model=model,
        )
        return float(diag.get("eta_min", float("inf")))
