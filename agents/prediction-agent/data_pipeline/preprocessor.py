# CLEANED: removed dead legacy helpers encode_categoricals/impute_numerics
"""Categorical encoding and numeric imputation (fit on training data only)."""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer

logger = logging.getLogger(__name__)

# Unknown category code (reserved for out-of-vocabulary categories)
UNKNOWN_CATEGORY_CODE = -1

# Categorical columns from the QoS schema (string-like fields used as categories)
CATEGORICAL_COLUMNS: tuple[str, ...] = (
    "zone_id",
    "cell_id",
    "node_id",
    "device_type",
    "traffic_type",
    "detection_method",
    "ho_status",
    "anomaly_type",
    "cell_id_router",
    "network_type_router",
    "wifi_signal_category",
    "cellular_signal_category",
    "signal_health_overall",
    "signal_dominant_link",
    "data_quality_issues",
    "data_quality_rating",
    "baseline_phase",
    "data_source",
)


class Preprocessor:
    """
    ``fit`` learns category mappings and median imputers on training rows only.
    ``transform`` applies the same mappings to any frame.
    """

    def __init__(self) -> None:
        self._category_maps: dict[str, dict[str, int]] = {}
        self._imputer: Optional[SimpleImputer] = None
        self._numeric_columns: List[str] = []

    def fit(self, df: pd.DataFrame) -> "Preprocessor":
        df = df.copy()
        # CRITICAL FIX: Store dtype information for validation during transform()
        self._category_dtypes: dict[str, str] = {}
        
        for col in CATEGORICAL_COLUMNS:
            if col not in df.columns:
                continue
            s = df[col].astype("string").fillna("__NA__")
            uniq = pd.unique(s)
            mapping = {v: i for i, v in enumerate(sorted(map(str, uniq)))}
            self._category_maps[col] = mapping
            # Store the dtype seen during training for validation
            self._category_dtypes[col] = str(df[col].dtype)

        numeric_cols = [
            c
            for c in df.columns
            if pd.api.types.is_numeric_dtype(df[c])
            and not pd.api.types.is_bool_dtype(df[c])
            and c not in ("skip_for_training",)
        ]
        self._numeric_columns = numeric_cols
        # Guard: only fit imputer if there are numeric columns
        if numeric_cols:
            self._imputer = SimpleImputer(strategy="median")
            self._imputer.fit(df[numeric_cols].to_numpy(dtype=float))
        else:
            logger.debug("No numeric columns found for imputation")
            self._imputer = None
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply learned category mappings and numeric imputation.
        
        Args:
            df: DataFrame to transform
            
        Returns:
            Transformed DataFrame with encoded categories and imputed numerics
        """
        out = df.copy()
        for col, mapping in self._category_maps.items():
            if col not in out.columns:
                continue
            s = out[col].astype("string").fillna("__NA__")
            
            # Track OOV categories
            oov_categories = set()
            codes = []
            oov_count = 0
            for val in s:
                str_val = str(val)
                if str_val in mapping:
                    codes.append(mapping[str_val])
                else:
                    oov_categories.add(str_val)
                    codes.append(UNKNOWN_CATEGORY_CODE)
                    oov_count += 1
            
            # Log OOV occurrences with detailed info
            if oov_categories:
                pct = 100.0 * oov_count / len(s) if len(s) else 0
                examples = sorted(list(oov_categories))[:3]
                logger.warning(
                    f"OOV categories in '{col}': {oov_count}/{len(s)} rows ({pct:.1f}%), "
                    f"{len(oov_categories)} unique values. Examples: {examples}. "
                    f"Encoding as {UNKNOWN_CATEGORY_CODE} (unknown category code)."
                )
            
            out[col] = np.asarray(codes, dtype=np.int32)

        # Convert boolean columns to int (required for model feature compatibility)
        for col in out.columns:
            if pd.api.types.is_bool_dtype(out[col]):
                out[col] = out[col].fillna(False).astype(np.int32)

        if self._imputer is None or not self._numeric_columns:
            return out

        present = [c for c in self._numeric_columns if c in out.columns]
        if not present:
            return out

        mat = out[present].to_numpy(dtype=float)
        imputed = self._imputer.transform(mat)
        out[present] = imputed
        return out

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.fit(df).transform(df)
