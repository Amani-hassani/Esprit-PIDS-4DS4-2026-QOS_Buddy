"""Time-series–aware evaluation with comprehensive metrics (no shuffle)."""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import TimeSeriesSplit

from config import N_SPLITS, TARGET_NAMES


def evaluate_multilabel(
    y_true: np.ndarray,
    y_score: np.ndarray,
    n_splits: int = N_SPLITS,
) -> Dict[str, Dict[str, float]]:
    """
    Compute comprehensive metrics on the last TimeSeriesSplit holdout.
    
    Args:
        y_true: Shape (n_samples, n_targets), binary labels
        y_score: Shape (n_samples, n_targets), predicted probabilities [0,1]
        n_splits: Number of TimeSeriesSplit folds
        
    Returns:
        Dict mapping target names to performance metrics:
        {
            'call_drop_risk': {
                'roc_auc': 0.82,
                'average_precision': 0.75,
                'f1_score': 0.68,
                'sensitivity': 0.72,
                'specificity': 0.85,
                'precision': 0.68,
                'optimal_threshold': 0.45,
                ...
            },
            ...
        }
        
    Notes:
        - Evaluates only on last fold (production-like deployment)
        - No shuffling (TimeSeriesSplit preserves temporal order)
        - Optimal threshold computed per target for F1 maximization
    """
    if y_true.shape != y_score.shape:
        raise ValueError(f"y_true shape {y_true.shape} != y_score shape {y_score.shape}")
    
    # Validate probability range
    if not (np.all(y_score >= 0) and np.all(y_score <= 1)):
        raise ValueError(
            f"y_score probabilities out of range [0, 1]. "
            f"Min: {np.nanmin(y_score):.4f}, Max: {np.nanmax(y_score):.4f}"
        )
    
    # Extract last fold
    tss = TimeSeriesSplit(n_splits=n_splits)
    last_train, last_test = None, None
    for tr, te in tss.split(y_true):
        last_train, last_test = tr, te
    
    assert last_train is not None and last_test is not None, "No folds created"
    
    yt = y_true[last_test]
    ys = y_score[last_test]
    
    per_target: Dict[str, Dict[str, float]] = {}
    for i, name in enumerate(TARGET_NAMES):
        col_y = yt[:, i]
        col_s = ys[:, i]
        
        # Baseline metrics (threshold-independent)
        if len(np.unique(col_y)) < 2:
            # Single class (all 0 or all 1) - cannot compute AUC
            per_target[name] = {
                "roc_auc": float("nan"),
                "average_precision": float("nan"),
                "sensitivity": float("nan"),
                "specificity": float("nan"),
                "precision": float("nan"),
                "f1_score": float("nan"),
                "optimal_threshold": 0.5,
                "n_positives": int(col_y.sum()),
                "n_negatives": int((col_y == 0).sum()),
                "positive_rate_pct": float(100.0 * col_y.mean()),
            }
            continue
        
        roc_auc = float(roc_auc_score(col_y, col_s))
        ap = float(average_precision_score(col_y, col_s))
        
        # Find optimal threshold (maximize F1)
        fpr, tpr, thresholds = roc_curve(col_y, col_s)
        f1_scores = [
            f1_score(col_y, (col_s >= t).astype(int), zero_division=0)
            for t in thresholds
        ]
        optimal_idx = np.argmax(f1_scores)
        optimal_threshold = float(thresholds[optimal_idx])
        
        # Metrics at optimal threshold
        y_pred_optimal = (col_s >= optimal_threshold).astype(int)
        
        tn, fp, fn, tp = confusion_matrix(col_y, y_pred_optimal, labels=[0, 1]).ravel()
        
        sensitivity = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        specificity = float(tn / (tn + fp)) if (tn + fp) > 0 else 0.0
        precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
        f1 = f1_score(col_y, y_pred_optimal, zero_division=0)
        
        # Metrics at 0.5 threshold (default)
        y_pred_default = (col_s >= 0.5).astype(int)
        tn05, fp05, fn05, tp05 = confusion_matrix(col_y, y_pred_default, labels=[0, 1]).ravel()
        sensitivity05 = float(tp05 / (tp05 + fn05)) if (tp05 + fn05) > 0 else 0.0
        specificity05 = float(tn05 / (tn05 + fp05)) if (tn05 + fp05) > 0 else 0.0
        
        per_target[name] = {
            "roc_auc": roc_auc,
            "average_precision": ap,
            "sensitivity_optimal": sensitivity,
            "specificity_optimal": specificity,
            "precision_optimal": precision,
            "f1_score_optimal": f1,
            "sensitivity_at_0p5": sensitivity05,
            "specificity_at_0p5": specificity05,
            "optimal_threshold": optimal_threshold,
            "n_positives": int(col_y.sum()),
            "n_negatives": int((col_y == 0).sum()),
            "positive_rate_pct": float(100.0 * col_y.mean()),
            "tp_optimal": int(tp),
            "fp_optimal": int(fp),
            "tn_optimal": int(tn),
            "fn_optimal": int(fn),
        }
    
    return per_target


def compute_macro_metrics(per_target_metrics: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    """Compute macro-averaged metrics across all targets."""
    valid_targets = {
        name: metrics
        for name, metrics in per_target_metrics.items()
        if not np.isnan(metrics.get("roc_auc", np.nan))
    }
    
    if not valid_targets:
        return {
            "macro_roc_auc": float("nan"),
            "macro_average_precision": float("nan"),
            "macro_sensitivity": float("nan"),
            "macro_specificity": float("nan"),
        }
    
    macro_auc = float(
        np.mean([m["roc_auc"] for m in valid_targets.values()])
    )
    macro_ap = float(
        np.mean([m["average_precision"] for m in valid_targets.values()])
    )
    macro_sensitivity = float(
        np.mean([m.get("sensitivity_optimal", 0.0) for m in valid_targets.values()])
    )
    macro_specificity = float(
        np.mean([m.get("specificity_optimal", 0.0) for m in valid_targets.values()])
    )
    
    return {
        "macro_roc_auc": macro_auc,
        "macro_average_precision": macro_ap,
        "macro_sensitivity": macro_sensitivity,
        "macro_specificity": macro_specificity,
    }


def dataframe_subset(df: pd.DataFrame, indices: np.ndarray) -> pd.DataFrame:
    """Extract subset of DataFrame by indices."""
    return df.iloc[indices].reset_index(drop=True)
