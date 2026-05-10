# CLEANED: added target key to each SHAP explanation row for per-target filtering
"""SHAP explanations for the per-target XGBoost models."""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd
import shap
from xgboost import XGBClassifier

from config import TARGET_NAMES


def _shap_values_for_model(model: XGBClassifier, x_row: np.ndarray):
    explainer = shap.TreeExplainer(model)
    sv = explainer.shap_values(x_row)
    if isinstance(sv, list):
        return np.asarray(sv[1], dtype=float)
    return np.asarray(sv, dtype=float)


def explain_tabular_row(
    models: Dict[str, XGBClassifier],
    feature_names: List[str],
    x_row: pd.Series | np.ndarray,
    per_target_feature_cols: Dict[str, List[str]] | None = None,
) -> List[dict]:
    """
    Return per-target SHAP contributions for each available classifier.
    
    If per_target_feature_cols is provided, uses per-target feature subsets for each model.
    Each returned item includes a ``target`` key with the source model name.
    
    Raises:
        ValueError: if target features are missing from feature_names
    """
    if isinstance(x_row, pd.Series):
        x_full = x_row[feature_names].to_numpy(dtype=np.float32).reshape(1, -1)
    else:
        x_full = np.asarray(x_row, dtype=np.float32).reshape(1, -1)

    out: List[dict] = []
    for name in TARGET_NAMES:
        model = models.get(name)
        if model is None:
            continue
        
        # Get per-target features if available, else use all
        if per_target_feature_cols is not None and name in per_target_feature_cols:
            target_cols = per_target_feature_cols[name]
            # Validate all target features exist in feature_names
            missing = [c for c in target_cols if c not in feature_names]
            if missing:
                raise ValueError(
                    f"Missing features in input for target '{name}': {missing}\n"
                    f"Expected features: {target_cols}\n"
                    f"Available features: {sorted(feature_names)}"
                )
            col_indices = [feature_names.index(c) for c in target_cols]
            vec = x_full[:, col_indices].astype(np.float32)
        else:
            col_indices = None
            target_cols = feature_names
            vec = x_full
        
        try:
            shap_mat = _shap_values_for_model(model, vec)
            shap_arr = np.asarray(shap_mat, dtype=float).reshape(-1)
            
            # Validate SHAP output dimension matches input features
            if len(shap_arr) != len(target_cols):
                raise ValueError(
                    f"SHAP output dimension mismatch for {name}: "
                    f"got {len(shap_arr)} values but expected {len(target_cols)} "
                    f"(features: {target_cols})"
                )
            
            # Map SHAP values back to full feature space
            if col_indices is not None:
                row = np.zeros(len(feature_names), dtype=float)
                for i, col_idx in enumerate(col_indices):
                    row[col_idx] = shap_arr[i]
            else:
                row = shap_arr
            
            order = np.argsort(-np.abs(row))[:5]
            for idx in order:
                direction = "increases_risk" if row[idx] >= 0 else "decreases_risk"
                out.append(
                    {
                        "target": name,
                        "feature": feature_names[idx],
                        "value": np.asarray(row[idx]).item(),
                        "direction": direction,
                    }
                )
        except ValueError:
            # Re-raise validation errors
            raise
        except Exception:
            # Skip models that fail for other reasons (e.g., internal SHAP errors)
            continue
    return out
