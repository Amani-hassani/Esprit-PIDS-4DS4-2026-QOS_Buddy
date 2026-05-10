"""Fuse XGBoost and LSTM probabilities (Prophet is never blended here)."""

from __future__ import annotations

import numpy as np

from config import ENSEMBLE_LSTM_WEIGHT, ENSEMBLE_XGB_WEIGHT, TARGET_NAMES


def ensemble_predict(xgb_probs: np.ndarray, lstm_probs: np.ndarray) -> np.ndarray:
    """
    ``final_prob = 0.55 * xgb + 0.45 * lstm`` for shape ``(N, 6)``.
    """
    if xgb_probs.shape != lstm_probs.shape:
        raise ValueError("XGB and LSTM probability tensors must have identical shape.")
    if xgb_probs.shape[-1] != len(TARGET_NAMES):
        raise ValueError(f"Expected {len(TARGET_NAMES)} targets.")
    
    # HIGH FIX: Validate input probabilities are in valid range [0, 1]
    if not (np.all(xgb_probs >= 0) and np.all(xgb_probs <= 1)):
        raise ValueError(
            f"XGB probabilities out of range [0, 1]. "
            f"Min: {np.nanmin(xgb_probs):.4f}, Max: {np.nanmax(xgb_probs):.4f}"
        )
    if not (np.all(lstm_probs >= 0) and np.all(lstm_probs <= 1)):
        raise ValueError(
            f"LSTM probabilities out of range [0, 1]. "
            f"Min: {np.nanmin(lstm_probs):.4f}, Max: {np.nanmax(lstm_probs):.4f}"
        )
    
    ensemble = ENSEMBLE_XGB_WEIGHT * xgb_probs + ENSEMBLE_LSTM_WEIGHT * lstm_probs
    
    # HIGH FIX: Validate output probabilities are in valid range [0, 1]
    if not (np.all(ensemble >= 0) and np.all(ensemble <= 1)):
        raise ValueError(
            f"Ensemble probabilities out of range [0, 1] after fusion. "
            f"Min: {np.nanmin(ensemble):.4f}, Max: {np.nanmax(ensemble):.4f}. "
            f"Weights: XGB={ENSEMBLE_XGB_WEIGHT}, LSTM={ENSEMBLE_LSTM_WEIGHT}"
        )
    
    return ensemble


def probs_to_dict(row: np.ndarray) -> dict[str, float]:
    arr = np.asarray(row, dtype=float).reshape(-1)
    if arr.size != len(TARGET_NAMES):
        raise ValueError("Row vector length must match targets.")
    return {name: np.asarray(arr[i]).item() for i, name in enumerate(TARGET_NAMES)}
