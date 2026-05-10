"""Target-specific ETA model training for non-congestion QoS events."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from config import SAVED_MODELS_DIR, SECONDS_PER_STEP, TARGET_NAMES
from data_pipeline.features import resolve_feature_columns
from data_pipeline.label_engineer import EVENT_COLUMN_MAP, ETA_TARGETS, TTE_COLUMN_MAP

logger = logging.getLogger(__name__)


@dataclass
class EtaModelBundle:
    target: str
    feature_cols: list[str]
    model: Any | None
    method: str
    event_rate: float
    median_tte_min: float
    horizon_min: float

    def predict_minutes(self, row: pd.Series) -> float:
        """Predict ETA in minutes using log1p-transformed model with overflow handling."""
        if self.model is None:
            return float("inf")
        
        missing = [c for c in self.feature_cols if c not in row.index]
        if missing:
            logger.warning(f"Missing features for {self.target}: {missing}")
            return float("inf")
        
        x = row[self.feature_cols].to_numpy(dtype=np.float32).reshape(1, -1)
        try:
            raw = np.asarray(self.model.predict(x), dtype=float).reshape(-1)
            if raw.size == 0:
                logger.warning(f"ETA model for {self.target} returned empty prediction")
                return float("inf")
            
            # Check for non-finite predictions
            if not np.isfinite(raw[0]):
                logger.warning(
                    f"ETA model for {self.target} produced non-finite prediction: {raw[0]}"
                )
                return float("inf")
            
            # Apply inverse transform: expm1(log_scale) = exp(log_scale) - 1
            eta = float(np.expm1(raw[0]))
            
            if not np.isfinite(eta):
                logger.warning(
                    f"ETA model for {self.target} expm1 overflow: log_scale={raw[0]:.2f} -> eta={eta}"
                )
                return float("inf")
            
            if eta < 0:
                logger.warning(
                    f"ETA model for {self.target} produced negative ETA: {eta:.2f} min"
                )
                return float("inf")
            
            # Sanity check: ETA > 16 hours (1000 min) likely indicates distribution shift
            if eta > 1000:
                logger.warning(
                    f"ETA model for {self.target} suspiciously large: {eta:.0f} minutes (> 16 hours). "
                    f"Possible model distribution shift. log_scale={raw[0]:.2f}"
                )
            
            return eta
        except Exception as e:
            logger.error(f"Error in ETA prediction for {self.target}: {e}")
            return float("inf")


def _target_short_name(target: str) -> str:
    return target.replace("_risk", "")


def validate_eta_features(
    feature_cols: list[str],
    target_name: str,
    all_targets: tuple[str, ...],
) -> None:
    """
    Validate that ETA feature list contains no leaky columns.
    
    Args:
        feature_cols: Feature column names to validate
        target_name: Current target being trained (for error message)
        all_targets: All target names (for checking target column leakage)
        
    Raises:
        ValueError: If ANY leaky column is detected
        
    Raises:
        ValueError: If any TTE, event, or target column found in features
    """
    blocked_patterns = ("tte_", "_event", "_risk")
    blocked_found = []
    
    # Check for pattern-based leakage
    for c in feature_cols:
        for pattern in blocked_patterns:
            if c.startswith(pattern) or c.endswith(pattern):
                blocked_found.append(c)
                break
    
    # Check for target name leakage
    for c in feature_cols:
        if c in all_targets:
            blocked_found.append(c)
    
    if blocked_found:
        raise ValueError(
            f"ETA trainer for '{target_name}' has leaky columns: {sorted(set(blocked_found))}\n"
            f"These columns MUST be excluded to prevent label leakage:\n"
            f"  - tte_* (time-to-event columns)\n"
            f"  - *_event (event indicator columns)\n"
            f"  - *_risk (target columns)\n"
            f"Run: feature_cols = drop_leaky_feature_columns(feature_cols)[0]"
        )


def train_eta_models(
    df: pd.DataFrame,
    out_dir: Path | None = None,
    random_state: int = 42,
) -> dict[str, EtaModelBundle]:
    """Train per-target ETA models using time-to-event regression.
    
    Args:
        df: DataFrame with TTE and event columns from label_engineer.build_labels()
        out_dir: Output directory for saved models
        random_state: Random seed for reproducibility
        
    Returns:
        Dictionary of {target: EtaModelBundle}
        
    Raises:
        ValueError: If TTE columns missing or no feature columns available
    """
    out_dir = Path(out_dir) if out_dir is not None else SAVED_MODELS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    feature_cols = resolve_feature_columns(df)  # Now returns list, not tuple
    if not feature_cols:
        raise ValueError("No feature columns resolved for ETA training.")

    # Early validation: check for ANY feature leakage across ALL targets
    validate_eta_features(feature_cols, "all targets", TARGET_NAMES)

    horizon_min = float(SECONDS_PER_STEP / 60.0)  # Minimum horizon in minutes
    models: dict[str, EtaModelBundle] = {}

    for target in ETA_TARGETS:
        tte_col = TTE_COLUMN_MAP[target]
        event_col = EVENT_COLUMN_MAP[target]
        
        # Validate TTE/event columns exist
        if tte_col not in df.columns or event_col not in df.columns:
            raise ValueError(
                f"Missing TTE/event columns for {target}: "
                f"requires '{tte_col}' and '{event_col}'. "
                f"Available columns: {list(df.columns)}\n"
                f"Ensure label_engineer.build_labels() was called before training ETA models."
            )

        train_df = df[df[event_col].astype(int) == 1].copy()
        train_df = train_df.dropna(subset=[tte_col])
        event_rate = float(df[event_col].astype(float).mean()) if len(df) else 0.0
        median_tte = float(train_df[tte_col].median()) if not train_df.empty else float("inf")

        # Check for insufficient data
        if train_df.empty:
            logger.error(
                f"Cannot train ETA model for {target}: no events (rows where {event_col}==1)"
            )
            raise ValueError(
                f"Cannot train ETA model for {target}: no events found in training data."
            )

        if len(train_df) < 3:
            logger.error(
                f"Insufficient events for {target}: {len(train_df)} < 3 minimum required"
            )
            raise ValueError(
                f"Insufficient events for {target}: {len(train_df)} < 3 minimum required"
            )
        
        if len(train_df) < 10:
            logger.warning(
                f"ETA model for {target} trained on only {len(train_df)} events. "
                f"Results may be unreliable (recommend >= 10 events)."
            )

        X = train_df[feature_cols].to_numpy(dtype=np.float32)
        y = np.log1p(train_df[tte_col].astype(float).clip(lower=0.0).to_numpy(dtype=np.float32))

        reg = XGBRegressor(
            n_estimators=500,
            max_depth=5,
            learning_rate=0.03,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=4,
            reg_alpha=0.1,
            reg_lambda=1.5,
            random_state=random_state,
            tree_method="hist",
        )
        reg.fit(X, y)

        bundle = EtaModelBundle(
            target=target,
            feature_cols=feature_cols,
            model=reg,
            method="xgb_regressor_log1p_events_only",
            event_rate=event_rate,
            median_tte_min=median_tte,
            horizon_min=horizon_min,
        )
        joblib.dump(bundle, out_dir / f"eta_{_target_short_name(target)}.joblib")
        models[target] = bundle

    joblib.dump(feature_cols, out_dir / "eta_feature_columns.joblib")
    return models


_LEGACY_ETA_ATTR_DEFAULTS: dict[str, Any] = {
    "use_label_encoder": False,
    "gpu_id": None,
    "predictor": None,
    "device": None,
    "feature_types": None,
    "feature_weights": None,
    "enable_categorical": False,
    "max_cat_to_onehot": None,
    "max_cat_threshold": None,
    "max_bin": None,
    "grow_policy": None,
    "sampling_method": None,
    "monotone_constraints": None,
    "interaction_constraints": None,
}


def _patch_legacy_eta_attributes(bundle: "EtaModelBundle") -> "EtaModelBundle":
    model = getattr(bundle, "model", None)
    if model is None:
        return bundle
    for attr, default in _LEGACY_ETA_ATTR_DEFAULTS.items():
        if not hasattr(model, attr):
            try:
                object.__setattr__(model, attr, default)
            except Exception:
                try:
                    setattr(model, attr, default)
                except Exception:
                    pass
    return bundle


def load_eta_models(model_dir: Path | None = None) -> dict[str, EtaModelBundle]:
    model_dir = Path(model_dir) if model_dir is not None else SAVED_MODELS_DIR
    models: dict[str, EtaModelBundle] = {}
    for target in ETA_TARGETS:
        p = model_dir / f"eta_{_target_short_name(target)}.joblib"
        if p.exists():
            models[target] = _patch_legacy_eta_attributes(joblib.load(p))
    return models


def predict_eta_minutes(bundle: EtaModelBundle | None, row: pd.Series) -> float:
    if bundle is None:
        return float("inf")
    return bundle.predict_minutes(row)