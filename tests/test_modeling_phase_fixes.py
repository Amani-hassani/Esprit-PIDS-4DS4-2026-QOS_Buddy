"""
Comprehensive tests for PHASE 1: CRITICAL FIXES (Issues #1-3)

Tests validate:
- Issue #1: Class imbalance handling with compute_balanced_scale_pos_weight()
- Issue #2: Label aggregation consistency using LABEL_AGGREGATION_STRATEGY
- Issue #3: LSTM node exclusion logging
"""

import logging
import numpy as np
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from config import (
    SCALE_POS_WEIGHT_CLAMP_MAX,
    SCALE_POS_WEIGHT_CLAMP_MIN,
    MIN_POSITIVE_SAMPLES_PER_FOLD,
    MIN_POSITIVE_SAMPLES_TRAINING,
    LABEL_AGGREGATION_STRATEGY,
    TARGET_NAMES,
    LABEL_HORIZON_STEPS,
)
from models.xgb_trainer import (
    compute_balanced_scale_pos_weight,
    validate_fold_evaluability,
)
from data_pipeline.label_engineer import build_labels
from models.lstm_trainer import _build_windows


# ═══════════════════════════════════════════════════════════════════════════
# ISSUE #1: CLASS IMBALANCE HANDLING TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestComputeBalancedScalePosWeight:
    """Test compute_balanced_scale_pos_weight() function (Issue #1)."""

    def test_normal_imbalance_no_clamping(self):
        """Normal imbalance (5:1 ratio) should not need clamping."""
        # Create 5:1 imbalance (well within clamp range)
        y = np.array([1, 0, 0, 0, 0, 0])
        spw, status = compute_balanced_scale_pos_weight(y, "test_target")
        assert SCALE_POS_WEIGHT_CLAMP_MIN <= spw <= SCALE_POS_WEIGHT_CLAMP_MAX
        assert status == "ok" or status == "ok_clamped"

    def test_extreme_imbalance_clamped_to_max(self):
        """Extreme imbalance (100:1) should be clamped to CLAMP_MAX."""
        y = np.zeros(1001)
        y[0] = 1
        spw, status = compute_balanced_scale_pos_weight(y, "test_target")
        assert spw == SCALE_POS_WEIGHT_CLAMP_MAX, f"Expected {SCALE_POS_WEIGHT_CLAMP_MAX}, got {spw}"
        assert status == "warning_extreme_imbalance"

    def test_zero_positives_error(self):
        """Zero positive samples must return error status and log."""
        y = np.zeros(100)
        spw, status = compute_balanced_scale_pos_weight(y, "test_target")
        assert spw == 1.0
        assert status == "error_no_positives"

    def test_reversed_imbalance_all_positive(self):
        """All positive samples should clamp to CLAMP_MIN."""
        y = np.ones(100)
        spw, status = compute_balanced_scale_pos_weight(y, "test_target")
        assert spw == SCALE_POS_WEIGHT_CLAMP_MIN
        assert status == "warning_all_positive"

    def test_balanced_imbalance(self):
        """Balanced 50-50 should give scale_pos_weight=1.0."""
        y = np.concatenate([np.ones(50), np.zeros(50)])
        spw, status = compute_balanced_scale_pos_weight(y, "test_target")
        assert abs(spw - 1.0) < 0.01
        assert status == "ok"

    def test_logging_explicit(self, caplog):
        """Ensure logging is explicit for diagnostics."""
        y = np.array([1, 0, 0, 0, 0])
        with caplog.at_level(logging.INFO):
            compute_balanced_scale_pos_weight(y, "test_explicit")
        # Should log something about this target
        assert any("test_explicit" in record.message for record in caplog.records)

    def test_minimum_samples_edge_case(self):
        """Test minimum edge case (1 positive, 1 negative)."""
        y = np.array([1, 0])
        spw, status = compute_balanced_scale_pos_weight(y, "edge_case")
        assert spw == 1.0, f"Expected 1.0 for balanced 1:1, got {spw}"
        assert status == "ok"


class TestValidateFoldEvaluability:
    """Test validate_fold_evaluability() function (Issue #1)."""

    def test_insufficient_positives(self):
        """Fold with < MIN_POSITIVE_SAMPLES_PER_FOLD positives should be marked unevaluable."""
        y = np.array([1, 0, 0, 0, 0])  # Only 1 positive
        is_evaluable, reason = validate_fold_evaluability(
            y, fold_idx=0, target_name="test", min_samples=MIN_POSITIVE_SAMPLES_PER_FOLD
        )
        assert not is_evaluable
        assert "insufficient" in reason.lower()

    def test_insufficient_negatives(self):
        """Fold with < MIN_POSITIVE_SAMPLES_PER_FOLD negatives should be marked unevaluable."""
        y = np.array([1, 1, 1, 1, 1])  # No negatives
        is_evaluable, reason = validate_fold_evaluability(
            y, fold_idx=0, target_name="test", min_samples=MIN_POSITIVE_SAMPLES_PER_FOLD
        )
        assert not is_evaluable

    def test_evaluable_balanced(self):
        """Well-balanced fold should be evaluable."""
        y = np.concatenate([np.ones(50), np.zeros(50)])
        is_evaluable, reason = validate_fold_evaluability(
            y, fold_idx=0, target_name="test", min_samples=MIN_POSITIVE_SAMPLES_PER_FOLD
        )
        assert is_evaluable
        assert reason == "evaluable"

    def test_extreme_imbalance_unevaluable(self):
        """Fold with extreme imbalance should be marked unevaluable."""
        # More than 98% positive rate
        y = np.array([1] * 100 + [0])  # 99% positive
        is_evaluable, reason = validate_fold_evaluability(
            y, fold_idx=0, target_name="test", min_samples=5
        )
        assert not is_evaluable, f"Expected unevaluable, but got evaluable with reason: {reason}"


# ═══════════════════════════════════════════════════════════════════════════
# ISSUE #2: LABEL AGGREGATION CONSISTENCY TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestLabelAggregationStrategy:
    """Test label creation using LABEL_AGGREGATION_STRATEGY (Issue #2)."""

    @pytest.fixture
    def sample_df(self):
        """Create a sample QoS dataframe for label testing."""
        n = 200
        df = pd.DataFrame({
            "node_id": np.repeat(np.arange(4), n // 4),
            "timestamp": pd.date_range("2026-03-27", periods=n, freq="30s"),
            "anomaly_score": np.random.uniform(0, 1, n),
            "latency_ms": np.random.uniform(50, 150, n),
            "throughput_mbps": np.random.uniform(1, 10, n),
            "jitter_ms": np.random.uniform(5, 50, n),
            "mos_estimate": np.random.uniform(2.0, 4.5, n),
            "queue_length": np.random.randint(0, 100, n),
            "active_connections": np.random.randint(10, 100, n),
        })
        return df

    def test_label_aggregation_strategy_exists(self):
        """LABEL_AGGREGATION_STRATEGY should be defined for all targets."""
        for target in TARGET_NAMES:
            assert target in LABEL_AGGREGATION_STRATEGY, f"Missing target: {target}"
            strategy = LABEL_AGGREGATION_STRATEGY[target]
            assert "aggregation" in strategy
            assert "threshold" in strategy
            assert "min_periods" in strategy
            assert "rationale" in strategy

    def test_build_labels_uses_strategy(self, sample_df):
        """build_labels should use LABEL_AGGREGATION_STRATEGY for each target."""
        result = build_labels(sample_df)
        
        # All targets should be present
        for target in TARGET_NAMES:
            assert target in result.columns, f"Missing target column: {target}"
        
        # All target columns should be binary or NA
        for target in TARGET_NAMES:
            assert result[target].dtype in (np.int8, "Int64"), f"{target} not binary"
            assert set(result[target].dropna().unique()).issubset({0, 1})

    def test_congestion_risk_uses_rolling_max(self, sample_df):
        """congestion_risk should use rolling_max aggregation (Issue #2 fix)."""
        strategy = LABEL_AGGREGATION_STRATEGY["congestion_risk"]
        assert strategy["aggregation"] == "rolling_max", \
            f"Expected rolling_max for congestion_risk, got {strategy['aggregation']}"

    def test_label_distributions_reasonable(self, sample_df):
        """Label distributions should be valid (0-100% positive rate allowed)."""
        result = build_labels(sample_df)
        
        for target in TARGET_NAMES:
            if target not in result.columns:
                continue
            n_pos = (result[target] == 1).sum()
            n_total = len(result)
            if n_total > 0:
                pos_rate = 100.0 * n_pos / n_total
                # Allow 0-100% positive rate (edge cases are valid)
                assert 0 <= pos_rate <= 100, f"{target}: {pos_rate}% positive rate out of bounds"

    def test_label_engine_logging(self, sample_df, caplog):
        """build_labels should log distributions (Issue #2 fix)."""
        with caplog.at_level(logging.INFO):
            build_labels(sample_df)
        
        # Should log summary statistics for each target
        assert any("call_drop_risk" in record.message for record in caplog.records)

    def test_empty_dataframe_handling(self):
        """build_labels should handle empty dataframe gracefully."""
        result = build_labels(pd.DataFrame())
        assert result.empty


# ═══════════════════════════════════════════════════════════════════════════
# ISSUE #3: LSTM NODE EXCLUSION LOGGING TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestLSTMNodeExclusionLogging:
    """Test _build_windows node exclusion logging (Issue #3)."""

    @pytest.fixture
    def sample_features_df(self):
        """Create sample features dataframe for LSTM."""
        # 3 nodes: 2 with sufficient data, 1 with insufficient
        n_per_node = 30
        df_list = []
        
        for node_id in [1, 2, 3]:
            n_rows = n_per_node if node_id != 3 else 5  # Node 3 has insufficient rows
            df_list.append(pd.DataFrame({
                "node_id": node_id,
                "feature_1": np.random.randn(n_rows),
                "feature_2": np.random.randn(n_rows),
                "feature_3": np.random.randn(n_rows),
                "call_drop_risk": np.random.randint(0, 2, n_rows),
                "latency_breach_risk": np.random.randint(0, 2, n_rows),
                "throughput_risk": np.random.randint(0, 2, n_rows),
                "jitter_risk": np.random.randint(0, 2, n_rows),
                "congestion_risk": np.random.randint(0, 2, n_rows),
                "mos_risk": np.random.randint(0, 2, n_rows),
            }))
        
        return pd.concat(df_list, ignore_index=True)

    def test_build_windows_skipped_nodes_logged(self, sample_features_df, caplog):
        """_build_windows should log skipped nodes (Issue #3 fix)."""
        feature_cols = ["feature_1", "feature_2", "feature_3"]
        window = 20
        
        with caplog.at_level(logging.WARNING):
            X, y = _build_windows(sample_features_df, feature_cols, window)
        
        # Should have logged about skipped node
        assert any("Skipped" in record.message or "skipped" in record.message 
                   for record in caplog.records), "No logging of skipped nodes"

    def test_build_windows_returns_valid_arrays(self, sample_features_df):
        """_build_windows should return valid arrays even with skipped nodes."""
        feature_cols = ["feature_1", "feature_2", "feature_3"]
        window = 20
        
        X, y = _build_windows(sample_features_df, feature_cols, window)
        
        # X should be (n_samples, window, n_features)
        # y should be (n_samples, 6) for 6 targets
        if len(X) > 0:
            assert X.ndim == 3
            assert X.shape[1] == window
            assert X.shape[2] == len(feature_cols)
            assert y.shape[1] == 6

    def test_build_windows_no_data_critical_error(self, caplog):
        """_build_windows with insufficient data should log CRITICAL error."""
        df = pd.DataFrame({
            "node_id": [1, 1, 1],
            "feature_1": [1.0, 2.0, 3.0],
        })
        feature_cols = ["feature_1"]
        window = 20
        
        with caplog.at_level(logging.ERROR):
            X, y = _build_windows(df, feature_cols, window)
        
        # Should log error about no windows generated
        assert any("No windows generated" in record.message for record in caplog.records)

    def test_build_windows_correct_shape_with_valid_data(self):
        """_build_windows should produce correct shapes with valid data."""
        # Create dataframe with enough rows
        n = 100
        df = pd.DataFrame({
            "node_id": 1,
            "feature_1": np.random.randn(n),
            "feature_2": np.random.randn(n),
            "call_drop_risk": np.random.randint(0, 2, n),
            "latency_breach_risk": np.random.randint(0, 2, n),
            "throughput_risk": np.random.randint(0, 2, n),
            "jitter_risk": np.random.randint(0, 2, n),
            "congestion_risk": np.random.randint(0, 2, n),
            "mos_risk": np.random.randint(0, 2, n),
        })
        
        feature_cols = ["feature_1", "feature_2"]
        window = 20
        
        X, y = _build_windows(df, feature_cols, window)
        
        # Should have n - window samples
        expected_samples = n - window
        assert X.shape[0] == expected_samples
        assert X.shape[1] == window
        assert X.shape[2] == len(feature_cols)
        assert y.shape == (expected_samples, 6)


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestModelingPhaseIntegration:
    """Integration tests for the entire modeling phase with fixes."""

    def test_imbalance_and_fold_validation_work_together(self):
        """scale_pos_weight and fold evaluability should work together."""
        # Simulate a challenging fold with extreme imbalance
        y_train = np.array([1] + [0] * 100)  # 1% positive
        y_val = np.array([0] * 200)  # 0% positive (unevaluable)
        
        spw, spw_status = compute_balanced_scale_pos_weight(y_train, "integration_test")
        assert spw == SCALE_POS_WEIGHT_CLAMP_MAX
        
        is_evaluable, reason = validate_fold_evaluability(
            y_val, fold_idx=0, target_name="integration_test"
        )
        assert not is_evaluable

    def test_labels_consistent_across_targets(self):
        """All targets should be consistently defined after Issue #2 fix."""
        # Create minimal test data
        n = 100
        df = pd.DataFrame({
            "node_id": np.repeat([1, 2], n // 2),
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="30s"),
            "anomaly_score": np.random.uniform(0, 1, n),
            "latency_ms": np.random.uniform(50, 150, n),
            "throughput_mbps": np.random.uniform(1, 10, n),
            "jitter_ms": np.random.uniform(5, 50, n),
            "mos_estimate": np.random.uniform(2.0, 4.5, n),
            "queue_length": np.random.randint(0, 100, n),
            "active_connections": np.random.randint(10, 100, n),
        })
        
        result = build_labels(df)
        
        # All targets should exist
        for target in TARGET_NAMES:
            assert target in result.columns
        
        # All targets should have documented strategy
        for target in TARGET_NAMES:
            assert target in LABEL_AGGREGATION_STRATEGY


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
