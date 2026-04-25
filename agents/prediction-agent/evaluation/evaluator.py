"""Time-series–aware evaluation helpers (no shuffle)."""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

from config import N_SPLITS, TARGET_NAMES


def evaluate_multilabel(
    y_true: np.ndarray,
    y_score: np.ndarray,
    n_splits: int = N_SPLITS,
) -> Dict[str, Dict[str, float]]:
    """
    Compute ROC-AUC and average precision on the last TimeSeriesSplit holdout.
    ``y_true`` / ``y_score`` shapes: ``(n_samples, n_targets)``.
    """
    if y_true.shape != y_score.shape:
        raise ValueError("y_true and y_score must share the same shape.")
    tss = TimeSeriesSplit(n_splits=n_splits)
    last_train, last_test = None, None
    for tr, te in tss.split(y_true):
        last_train, last_test = tr, te
    assert last_train is not None and last_test is not None

    yt = y_true[last_test]
    ys = y_score[last_test]
    per_target: Dict[str, Dict[str, float]] = {}
    for i, name in enumerate(TARGET_NAMES):
        col_y = yt[:, i]
        col_s = ys[:, i]
        if len(np.unique(col_y)) < 2:
            per_target[name] = {"roc_auc": float("nan"), "average_precision": float("nan")}
            continue
        per_target[name] = {
            "roc_auc": float(roc_auc_score(col_y, col_s)),
            "average_precision": float(average_precision_score(col_y, col_s)),
        }
    return per_target


def dataframe_subset(df: pd.DataFrame, indices: np.ndarray) -> pd.DataFrame:
    return df.iloc[indices].reset_index(drop=True)
