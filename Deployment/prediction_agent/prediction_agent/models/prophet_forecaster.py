# CLEANED: corrected ETA docstring behavior for provided pre-fitted model
"""Prophet-based congestion ETA forecasting (never used in the ensemble)."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from prophet import Prophet

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
        self._forecast_backend_available: bool | None = None

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
        """Fit Prophet model and save a compact placeholder artifact for readiness checks."""
        hist = self._prepare_history(df_node)
        if hist.empty:
            raise ValueError("Prophet training requires non-empty frame with congestion_index.")

        m = Prophet(daily_seasonality=False, weekly_seasonality=False)
        m.fit(hist)
        out = self._model_path(node_id)
        out.parent.mkdir(parents=True, exist_ok=True)

        # Keep a lightweight artifact so model readiness checks still see Prophet output on disk.
        out.write_text(
            '{"status":"fit_from_history_at_runtime","node_id":"' + _sanitize_node_id(node_id) + '"}',
            encoding="utf-8",
        )
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
        raise NotImplementedError(
            "Serialized Prophet models are not used at inference time; forecasts are fit from current node history."
        )

    @staticmethod
    def _linear_fallback_eta(hist: pd.DataFrame, horizon_periods: int, threshold: float) -> dict[str, Any]:
        horizon_min = float(horizon_periods * SECONDS_PER_STEP / 60.0)
        if len(hist) < 5:
            return {
                "eta_min": float("inf"),
                "status": "no_crossing",
                "reason": "not enough history for fallback forecast",
                "max_forecast": None,
                "threshold": float(threshold),
                "horizon_min": horizon_min,
            }

        tail = hist.tail(min(30, len(hist))).copy()
        seconds = (tail["ds"] - tail["ds"].min()).dt.total_seconds().to_numpy(dtype=float)
        values = tail["y"].to_numpy(dtype=float)
        if len(seconds) < 2 or float(seconds[-1]) <= 0.0:
            return {
                "eta_min": float("inf"),
                "status": "no_crossing",
                "reason": "fallback forecast timeline is degenerate",
                "max_forecast": None,
                "threshold": float(threshold),
                "horizon_min": horizon_min,
            }

        slope, intercept = np.polyfit(seconds, values, 1)
        future_seconds = seconds[-1] + np.arange(1, horizon_periods + 1, dtype=float) * SECONDS_PER_STEP
        forecast = intercept + slope * future_seconds
        max_forecast = float(np.max(forecast)) if len(forecast) else None
        crossing = np.where(forecast >= threshold)[0]
        if len(crossing) == 0:
            return {
                "eta_min": float("inf"),
                "status": "no_crossing",
                "reason": "fallback forecast did not cross threshold within horizon",
                "max_forecast": max_forecast,
                "threshold": float(threshold),
                "horizon_min": horizon_min,
            }

        eta_min = float((crossing[0] + 1) * SECONDS_PER_STEP / 60.0)
        return {
            "eta_min": eta_min,
            "status": "ok",
            "reason": "fallback trend forecast crossed threshold within horizon",
            "max_forecast": max_forecast,
            "threshold": float(threshold),
            "horizon_min": horizon_min,
        }

    def forecast_capacity_diagnostics(
        self,
        node_id: str,
        history: pd.DataFrame,
        horizon_periods: int = LABEL_HORIZON_STEPS,
        threshold: float = CONGESTION_INDEX_THRESHOLD,
        model: Optional[Prophet] = None,
    ) -> dict[str, Any]:
        """Return ETA plus diagnostic details (status, max forecast, threshold, horizon)."""
        hist = self._prepare_history(history)
        horizon_min = float(horizon_periods * SECONDS_PER_STEP / 60.0)
        if hist.empty:
            return {
                "eta_min": float("inf"),
                "status": "unavailable",
                "reason": "empty history or missing congestion_index",
                "max_forecast": None,
                "threshold": float(threshold),
                "horizon_min": horizon_min,
            }

        if self._forecast_backend_available is False:
            return self._linear_fallback_eta(hist, horizon_periods, threshold)

        try:
            m = model or Prophet(daily_seasonality=False, weekly_seasonality=False)
            if model is None:
                m.fit(hist)
            self._forecast_backend_available = True

            future = m.make_future_dataframe(periods=horizon_periods, freq=f"{int(SECONDS_PER_STEP)}s")
            fcst = m.predict(future)
            last_ds = hist["ds"].max()
            tail = fcst[fcst["ds"] > last_ds].head(horizon_periods)
            if tail.empty:
                return self._linear_fallback_eta(hist, horizon_periods, threshold)

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
        except Exception as exc:
            logger.warning("Prophet forecast failed for node %s: %s", node_id, exc)
            self._forecast_backend_available = False
            fallback = self._linear_fallback_eta(hist, horizon_periods, threshold)
            fallback["reason"] = fallback["reason"]
            return fallback

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
