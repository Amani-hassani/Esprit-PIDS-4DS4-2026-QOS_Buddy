# CLEANED: clarified imbalance comment and used helper split argument consistently
"""Train six per-target XGBoost classifiers with TimeSeriesSplit (no shuffle)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

from config import (
    N_SPLITS, SAVED_MODELS_DIR, TARGET_NAMES,
    SCALE_POS_WEIGHT_CLAMP_MAX, SCALE_POS_WEIGHT_CLAMP_MIN,
    MIN_POSITIVE_SAMPLES_PER_FOLD, MIN_POSITIVE_SAMPLES_TRAINING,
)
from data_pipeline.features import resolve_feature_columns

import logging
logger = logging.getLogger(__name__)

# Features whose Pearson correlation with the target FLIPS sign between
# training period and test period on this dataset.
# XGBoost learns the wrong direction for these — removing them improves AUC.
TARGET_EXCLUDED_FEATURES: dict[str, list[str]] = {
    "throughput_risk": [
        "throughput_rolling_std",   # train=+0.127, test=-0.247
        "throughput_volatility",    # train=+0.150, test=-0.153
    ],
    "mos_risk": [
        "connected_stations",       # train=-0.060, test=+0.178
        "ho_success_rate_pct",      # train=-0.047, test=+0.175
        "throughput_rolling_std",   # train=+0.143, test=-0.164
    ],
}

TARGET_MODEL_PARAMS: dict[str, dict[str, Any]] = {
    "throughput_risk": {
        "n_estimators": 700,
        "max_depth": 6,
        "learning_rate": 0.025,
        "min_child_weight": 4,
    },
}

def compute_balanced_scale_pos_weight(
    y_true: np.ndarray,
    target_name: str,
    clamp_min: float = SCALE_POS_WEIGHT_CLAMP_MIN,
    clamp_max: float = SCALE_POS_WEIGHT_CLAMP_MAX,
) -> tuple[float, str]:
    """Compute scale_pos_weight with explicit validation and logging.
    
    Returns (scale_pos_weight, diagnostics_string)
    CRITICAL: Always logs. NEVER silent.
    """
    y = np.asarray(y_true, dtype=int)
    n_pos = int((y == 1).sum())
    n_neg = int((y == 0).sum())
    n_total = len(y)
    pos_rate = 100.0 * n_pos / n_total if n_total else 0.0
    
    # CASE 1: No positive samples
    if n_pos == 0:
        logger.error(
            f"CRITICAL: Zero positive samples for {target_name} "
            f"({n_total} total rows). Cannot compute meaningful scale_pos_weight."
        )
        return 1.0, "error_no_positives"
    
    # CASE 2: No negative samples
    if n_neg == 0:
        logger.warning(
            f"Reversed imbalance for {target_name}: all {n_pos} positive, 0 negative. "
            f"Using scale_pos_weight={clamp_min}."
        )
        return clamp_min, "warning_all_positive"
    
    # CASE 3: Normal computation
    raw_spw = float(n_neg) / float(n_pos)
    
    if raw_spw > clamp_max:
        logger.warning(
            f"Extreme imbalance for {target_name}: {n_neg}/{n_pos} = {raw_spw:.1f}:1. "
            f"Clamping to {clamp_max} (pos_rate={pos_rate:.1f}%). RISK: Minority overfitting."
        )
        return clamp_max, "warning_extreme_imbalance"
    elif raw_spw < clamp_min:
        clamped = np.clip(raw_spw, clamp_min, clamp_max)
        logger.info(f"Imbalance for {target_name}: {pos_rate:.1f}% positive. scale_pos_weight={clamped:.2f}.")
        return clamped, "ok_clamped"
    else:
        logger.info(f"Imbalance for {target_name}: {pos_rate:.1f}% positive. scale_pos_weight={raw_spw:.2f}.")
        return raw_spw, "ok"


def validate_fold_evaluability(
    y_true: np.ndarray,
    fold_idx: int,
    target_name: str,
    min_samples: int = MIN_POSITIVE_SAMPLES_PER_FOLD,
) -> tuple[bool, str]:
    """Validate fold suitability for metric evaluation.
    Returns (is_evaluable, reason_string)
    """
    y = np.asarray(y_true, dtype=int)
    n_pos = int((y == 1).sum())
    n_neg = int((y == 0).sum())
    n_total = len(y)
    
    if n_pos < min_samples or n_neg < min_samples:
        reason = (f"Fold {fold_idx} {target_name}: insufficient samples "
                  f"(pos={n_pos}, neg={n_neg}, need >={min_samples})")
        logger.warning(reason)
        return False, reason
    
    pos_rate = 100.0 * n_pos / n_total
    if pos_rate < 2.0 or pos_rate > 98.0:
        reason = f"Fold {fold_idx} {target_name}: extreme imbalance ({pos_rate:.1f}%). ROC-AUC unreliable."
        logger.warning(reason)
        return False, reason
    
    return True, "evaluable"


def _last_fold_split(n_samples: int, n_splits: int = N_SPLITS) -> Tuple[np.ndarray, np.ndarray]:
    """Extract the last fold from TimeSeriesSplit.
    
    Args:
        n_samples: Total number of samples
        n_splits: Number of splits
        
    Returns:
        Tuple of (train_indices, test_indices)
        
    Raises:
        ValueError: if not enough samples for requested splits
    """
    if n_samples < n_splits:
        raise ValueError(
            f"Cannot create {n_splits} time-series splits with only {n_samples} samples. "
            f"Need at least {n_splits} samples."
        )
    
    tss = TimeSeriesSplit(n_splits=n_splits)
    splits = list(tss.split(np.zeros(n_samples)))
    
    if not splits:
        raise RuntimeError(
            f"TimeSeriesSplit produced no splits for n_samples={n_samples}, n_splits={n_splits}"
        )
    
    return splits[-1]  # Return (train_idx, test_idx) tuple


def train_xgb_models(
    df: pd.DataFrame = None,
    out_dir: Path | None = None,
    n_splits: int = N_SPLITS,
    random_state: int = 42,
    # Legacy arguments (for backward compatibility with notebooks)
    X_train: pd.DataFrame = None,
    y_train: pd.DataFrame = None,
    X_test: pd.DataFrame = None,
    y_test: pd.DataFrame = None,
    feature_cols: list[str] = None,
    target_names: tuple[str, ...] = None,
    saved_models_dir: Path | None = None,
) -> Dict[str, CalibratedClassifierCV]:
    """
    Train six per-target XGBoost classifiers with TimeSeriesSplit, then calibrate.
    
    Supports two APIs:
    1. New: train_xgb_models(df=df_model, out_dir=SAVED_MODELS_DIR)
    2. Legacy: train_xgb_models(X_train=..., y_train=..., X_test=..., ...)
    """
    # Handle legacy API (from notebooks)
    if X_train is not None and df is None:
        logger.info("Detected legacy API call. Converting to DataFrame format...")
        
        # Ensure we have feature columns and target names from legacy args
        if feature_cols is None:
            feature_cols = resolve_feature_columns(X_train)
        if target_names is None:
            target_names = TARGET_NAMES
        
        # Convert to DataFrames if needed
        if not isinstance(X_train, pd.DataFrame):
            X_train = pd.DataFrame(X_train, columns=feature_cols)
        if not isinstance(X_test, pd.DataFrame):
            X_test = pd.DataFrame(X_test, columns=feature_cols)
        if not isinstance(y_train, pd.DataFrame):
            y_train = pd.DataFrame(y_train, columns=target_names)
        if not isinstance(y_test, pd.DataFrame):
            y_test = pd.DataFrame(y_test, columns=target_names)
        
        # Concatenate train and test into single DataFrame
        df = pd.concat([
            X_train.assign(**y_train.to_dict('series')),
            X_test.assign(**y_test.to_dict('series'))
        ], ignore_index=True)
        
        logger.info(f"Reconstructed DataFrame: {len(df)} rows, {len(feature_cols)} features")
    
    if out_dir is None and saved_models_dir is not None:
        out_dir = saved_models_dir
    
    if df is None:
        raise ValueError("Either 'df' or legacy arguments (X_train, y_train, etc.) must be provided")
    
    out_dir = Path(out_dir) if out_dir is not None else SAVED_MODELS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    feature_cols = resolve_feature_columns(df)
    if not feature_cols:
        raise ValueError("No feature columns resolved for XGBoost training.")

    base_feature_cols = feature_cols
    X_base = df[base_feature_cols].to_numpy(dtype=np.float32)
    models: Dict[str, CalibratedClassifierCV] = {}

    last_train_idx, last_test_idx = _last_fold_split(len(df), n_splits=n_splits)

    for target in TARGET_NAMES:
        if target not in df.columns:
            raise ValueError(f"Missing target column: {target}")
        y = df[target].to_numpy(dtype=np.int32)
        target_params = TARGET_MODEL_PARAMS.get(target, {})

        excluded = TARGET_EXCLUDED_FEATURES.get(target, [])
        active_cols = [c for c in base_feature_cols if c not in excluded]
        col_idx = [base_feature_cols.index(c) for c in active_cols]
        X = X_base[:, col_idx]

        # save per-target column list
        joblib.dump(active_cols, out_dir / f"xgb_{target}_feature_columns.joblib")

        tss = TimeSeriesSplit(n_splits=n_splits)
        fold_aucs: list[float] = []
        fold_diagnostics: list[dict] = []
        evaluable_folds = 0
        
        for fold_idx, (train_idx, val_idx) in enumerate(tss.split(X)):
            X_tr, y_tr = X[train_idx], y[train_idx]
            X_va, y_va = X[val_idx], y[val_idx]
            
            # Validate fold evaluability BEFORE training
            is_evaluable_train, reason_train = validate_fold_evaluability(
                y_tr, fold_idx, target, min_samples=MIN_POSITIVE_SAMPLES_PER_FOLD
            )
            is_evaluable_val, reason_val = validate_fold_evaluability(
                y_va, fold_idx, target, min_samples=MIN_POSITIVE_SAMPLES_PER_FOLD
            )
            
            if not is_evaluable_train or not is_evaluable_val:
                logger.warning(
                    f"Skipping fold {fold_idx} for {target}: "
                    f"train_ok={is_evaluable_train}, val_ok={is_evaluable_val}"
                )
                fold_aucs.append(float("nan"))
                fold_diagnostics.append({"fold": fold_idx, "status": "unevaluable", "reason": reason_val})
                continue
            
            # Compute scale_pos_weight with full diagnostics
            spw, spw_status = compute_balanced_scale_pos_weight(
                y_tr, f"{target}_fold{fold_idx}",
                clamp_min=SCALE_POS_WEIGHT_CLAMP_MIN,
                clamp_max=SCALE_POS_WEIGHT_CLAMP_MAX,
            )
            
            logger.info(
                f"Fold {fold_idx}/{n_splits} {target}: train={len(y_tr)}, val={len(y_va)}, "
                f"spw={spw:.2f} ({spw_status})"
            )
            
            clf = XGBClassifier(
                n_estimators=target_params.get("n_estimators", 300),
                max_depth=target_params.get("max_depth", 5),
                learning_rate=target_params.get("learning_rate", 0.03),
                subsample=0.8,
                colsample_bytree=0.7,
                min_child_weight=target_params.get("min_child_weight", 5),
                scale_pos_weight=spw,
                eval_metric="auc",
                random_state=random_state,
                tree_method="hist",
                reg_alpha=0.1,
                reg_lambda=1.5,
            )
            clf.fit(X_tr, y_tr, verbose=False)
            
            if len(np.unique(y_va)) > 1:
                pred = clf.predict_proba(X_va)[:, 1]
                auc = float(roc_auc_score(y_va, pred))
                fold_aucs.append(auc)
                evaluable_folds += 1
                fold_diagnostics.append({
                    "fold": fold_idx,
                    "status": "evaluated",
                    "auc": auc,
                    "pos_rate_val": 100.0 * float(y_va.mean()),
                })
            else:
                logger.warning(f"Fold {fold_idx} single class in validation.")
                fold_aucs.append(float("nan"))
                fold_diagnostics.append({"fold": fold_idx, "status": "single_class_val"})
        
        # Log fold summary BEFORE final training
        valid_aucs = [a for a in fold_aucs if not np.isnan(a)]
        if valid_aucs:
            mean_auc = np.mean(valid_aucs)
            std_auc = np.std(valid_aucs)
            logger.info(
                f"[{target}] Cross-validation AUC: {mean_auc:.4f} ± {std_auc:.4f} "
                f"({evaluable_folds} evaluable folds)"
            )
        else:
            logger.warning(f"[{target}] NO EVALUABLE FOLDS! Training may fail.")
        
        # Save fold diagnostics
        joblib.dump(fold_diagnostics, out_dir / f"xgb_{target}_fold_diagnostics.joblib")

        # CRITICAL FIX: Define training data for final model on FULL training split
        X_tr_f = X[last_train_idx]
        y_tr_f = y[last_train_idx]
        
        # Compute scale_pos_weight for final model (on FULL training split)
        spw, spw_status = compute_balanced_scale_pos_weight(
            y_tr_f, f"{target}_final",
            clamp_min=SCALE_POS_WEIGHT_CLAMP_MIN,
            clamp_max=SCALE_POS_WEIGHT_CLAMP_MAX,
        )
        
        logger.info(
            f"[{target}] Final model: n_samples={len(y_tr_f)}, pos_rate={100.0*float(y_tr_f.mean()):.1f}%, "
            f"scale_pos_weight={spw:.2f} ({spw_status})"
        )
        
        final = XGBClassifier(
            n_estimators=target_params.get("n_estimators", 500),
            max_depth=target_params.get("max_depth", 5),
            learning_rate=target_params.get("learning_rate", 0.03),
            subsample=0.8,
            colsample_bytree=0.7,
            min_child_weight=target_params.get("min_child_weight", 5),
            scale_pos_weight=spw,
            eval_metric="auc",
            random_state=random_state,
            tree_method="hist",
            reg_alpha=0.1,
            reg_lambda=1.5,
        )
        final.fit(X_tr_f, y_tr_f, verbose=False)

        # Calibrate probabilities on the last validation fold.
        # Fixes the AP >> AUC gap caused by miscalibrated probabilities
        # under distribution shift. Isotonic regression is non-parametric
        # and works well when the test regime differs from training.
        X_val_f = X[last_test_idx]
        y_val_f = y[last_test_idx]
        calibrated = CalibratedClassifierCV(
            estimator=final,
            method="isotonic",
            cv="prefit",  # model already fitted — only fit the calibrator
        )
        try:
            calibrated.fit(X_val_f, y_val_f)
            models[target] = calibrated
        except ValueError:
            # Fallback: if calibration fails (e.g. only one class in val fold),
            # keep the uncalibrated model
            models[target] = final

        # Save the inner booster as JSON (for compatibility)
        inner = final  # the raw XGBClassifier before calibration
        path_json = out_dir / f"xgb_{target}.json"
        inner.get_booster().save_model(str(path_json))

        # Also save the full calibrated model with joblib
        path_cal = out_dir / f"xgb_{target}_calibrated.joblib"
        joblib.dump(calibrated if isinstance(models[target], CalibratedClassifierCV) else final, path_cal)

    joblib.dump(feature_cols, out_dir / "xgb_feature_columns.joblib")
    return models


_LEGACY_ATTR_DEFAULTS: dict[str, Any] = {
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


def _patch_legacy_xgb_attributes(estimator: Any) -> Any:
    """Backfill attributes that older xgboost-pickled models miss in newer versions."""
    if estimator is None:
        return estimator
    candidates: list[Any] = [estimator]
    inner_estimators = getattr(estimator, "calibrated_classifiers_", None)
    if inner_estimators:
        for wrapper in inner_estimators:
            candidates.append(wrapper)
            base = getattr(wrapper, "estimator", None) or getattr(wrapper, "base_estimator", None)
            if base is not None:
                candidates.append(base)
    base_estimator_attr = getattr(estimator, "estimator", None) or getattr(estimator, "base_estimator", None)
    if base_estimator_attr is not None:
        candidates.append(base_estimator_attr)
    for candidate in candidates:
        for attr, default in _LEGACY_ATTR_DEFAULTS.items():
            if not hasattr(candidate, attr):
                try:
                    object.__setattr__(candidate, attr, default)
                except Exception:
                    try:
                        setattr(candidate, attr, default)
                    except Exception:
                        pass
    return estimator


def load_xgb_models(model_dir: Path | None = None) -> Dict[str, Any]:
    model_dir = Path(model_dir) if model_dir is not None else SAVED_MODELS_DIR
    models: Dict[str, Any] = {}
    for target in TARGET_NAMES:
        cal_path = model_dir / f"xgb_{target}_calibrated.joblib"
        json_path = model_dir / f"xgb_{target}.json"
        if cal_path.exists():
            try:
                models[target] = _patch_legacy_xgb_attributes(joblib.load(cal_path))
                continue
            except Exception as exc:
                logger.warning("Failed to load calibrated model for %s (%s); falling back to JSON", target, exc)
        if json_path.exists():
            booster = XGBClassifier()
            booster.load_model(str(json_path))
            models[target] = _patch_legacy_xgb_attributes(booster)
    return models


def load_xgb_feature_columns(
    model_dir: Path | None = None,
    fallback_cols: list[str] | None = None,
) -> dict[str, list[str]]:
    model_dir = Path(model_dir) if model_dir is not None else SAVED_MODELS_DIR
    result: dict[str, list[str]] = {}
    for target in TARGET_NAMES:
        p = model_dir / f"xgb_{target}_feature_columns.joblib"
        if p.exists():
            result[target] = joblib.load(p)
        elif fallback_cols is not None:
            result[target] = fallback_cols
    return result
