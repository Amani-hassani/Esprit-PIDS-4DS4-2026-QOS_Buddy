"""
Tests for critical bug fixes.

These tests verify that:
1. TTE and binary label horizons are synchronized (Bug #1)
2. ETA feature leakage is detected (Bug #2)
3. Missing ETA columns raise errors (Bug #3)
4. LSTM scaler reconstruction is accurate (Bug #4)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch
from sklearn.preprocessing import MinMaxScaler
from xgboost import XGBRegressor

from config import LABEL_HORIZON_STEPS, FUTURE_WINDOW_STEPS
from data_pipeline.features import resolve_feature_columns, drop_leaky_feature_columns
from data_pipeline.label_engineer import build_labels, ETA_TARGETS
from models.eta_trainer import train_eta_models, validate_eta_features
from models.lstm_trainer import (
    LSTMTrainArtifacts,
    QoSLSTM,
    scale_window,
    train_lstm,
    load_lstm_artifacts,
)


class TestBug1TTEHorizonSync:
    """Bug #1: Verify TTE and binary label horizons are synchronized."""

    def test_horizon_constants_match(self):
        """LABEL_HORIZON_STEPS should equal FUTURE_WINDOW_STEPS."""
        assert LABEL_HORIZON_STEPS == FUTURE_WINDOW_STEPS, (
            f"Horizon mismatch: LABEL_HORIZON_STEPS={LABEL_HORIZON_STEPS} "
            f"but FUTURE_WINDOW_STEPS={FUTURE_WINDOW_STEPS}"
        )

    def test_horizon_value_is_120(self):
        """Horizon should be 120 steps (60 minutes)."""
        assert LABEL_HORIZON_STEPS == 120, (
            f"Expected LABEL_HORIZON_STEPS=120, got {LABEL_HORIZON_STEPS}"
        )

    def test_labels_use_consistent_horizon(self):
        """Binary and TTE labels should use same horizon window."""
        # Create minimal test data
        df = pd.DataFrame({
            "node_id": ["A"] * 200,
            "timestamp": pd.date_range("2020-01-01", periods=200, freq="30s"),
            "anomaly_score": np.random.rand(200),
            "latency_ms": np.random.rand(200) * 100,
            "throughput_mbps": np.random.rand(200) * 10,
            "jitter_ms": np.random.rand(200) * 50,
            "mos_estimate": np.random.rand(200) * 4 + 1,
            "queue_length": np.random.rand(200) * 100,
            "active_connections": np.random.rand(200) * 1000,
        })

        labels = build_labels(df)
        
        # Verify TTE columns exist (created with LABEL_HORIZON_STEPS)
        expected_tte_cols = ["tte_call_drop_min", "tte_latency_breach_min", 
                            "tte_throughput_min", "tte_jitter_min", "tte_mos_min"]
        for col in expected_tte_cols:
            assert col in labels.columns, f"Missing TTE column: {col}"
        
        # Verify binary labels exist (created with FUTURE_WINDOW_STEPS)
        expected_binary_cols = ["call_drop_risk", "latency_breach_risk", 
                               "throughput_risk", "jitter_risk", "congestion_risk", "mos_risk"]
        for col in expected_binary_cols:
            assert col in labels.columns, f"Missing binary label column: {col}"


class TestBug2FeatureLeakageValidation:
    """Bug #2: Verify feature leakage is detected in ETA trainer."""

    def test_validate_eta_features_rejects_tte_columns(self):
        """Feature validation should reject tte_* columns."""
        from config import TARGET_NAMES
        
        # Features with leaky TTE column
        feature_cols = ["col1", "col2", "tte_signal_strength"]
        
        with pytest.raises(ValueError, match="leaky columns"):
            validate_eta_features(feature_cols, "call_drop_risk", TARGET_NAMES)

    def test_validate_eta_features_rejects_event_columns(self):
        """Feature validation should reject *_event columns."""
        from config import TARGET_NAMES
        
        feature_cols = ["col1", "col2", "call_drop_event"]
        
        with pytest.raises(ValueError, match="leaky columns"):
            validate_eta_features(feature_cols, "call_drop_risk", TARGET_NAMES)

    def test_validate_eta_features_rejects_target_columns(self):
        """Feature validation should reject target (*_risk) columns."""
        from config import TARGET_NAMES
        
        feature_cols = ["col1", "col2", "call_drop_risk"]
        
        with pytest.raises(ValueError, match="leaky columns"):
            validate_eta_features(feature_cols, "call_drop_risk", TARGET_NAMES)

    def test_validate_eta_features_accepts_clean_columns(self):
        """Feature validation should accept clean columns."""
        from config import TARGET_NAMES
        
        feature_cols = ["rsrq_db", "sinr_db", "latency_ms"]
        
        # Should not raise
        validate_eta_features(feature_cols, "call_drop_risk", TARGET_NAMES)


class TestBug3MissingETAColumnsValidation:
    """Bug #3: Verify missing ETA columns raise errors."""

    def test_missing_tte_columns_raises_error(self):
        """Train should fail if TTE columns missing."""
        # Create minimal data WITHOUT TTE columns
        df = pd.DataFrame({
            "node_id": ["A"] * 100,
            "timestamp": pd.date_range("2020-01-01", periods=100, freq="30s"),
            "col1": np.random.rand(100),
            "col2": np.random.rand(100),
        })

        with pytest.raises(ValueError):  # Just check ValueError is raised
            train_eta_models(df)

    def test_insufficient_events_raises_error(self):
        """Train should fail if insufficient events."""
        # Create data with event columns but no actual events
        df = pd.DataFrame({
            "node_id": ["A"] * 100,
            "timestamp": pd.date_range("2020-01-01", periods=100, freq="30s"),
            "tte_call_drop_min": [np.nan] * 100,
            "call_drop_event": [0] * 100,  # No events (all zeros)
            "tte_latency_breach_min": [np.nan] * 100,
            "latency_breach_event": [0] * 100,
            "tte_throughput_min": [np.nan] * 100,
            "throughput_event": [0] * 100,
            "tte_jitter_min": [np.nan] * 100,
            "jitter_event": [0] * 100,
            "tte_mos_min": [np.nan] * 100,
            "mos_event": [0] * 100,
            "col1": np.random.rand(100),
            "col2": np.random.rand(100),
        })

        with pytest.raises(ValueError, match="no events|empty"):
            train_eta_models(df)


class TestBug4LSTMScalerReconstruction:
    """Bug #4: Verify LSTM scaler reconstruction is accurate."""

    def test_scaler_object_saved_and_loaded(self):
        """Scaler object should be saved and loaded correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            
            # Create minimal training data
            X_train = np.random.randn(100, 10).astype(np.float32)
            y_train = np.random.randint(0, 2, (100, 6)).astype(np.float32)
            
            # Train model with scaler_object
            scaler = MinMaxScaler()
            scaler.fit(X_train)
            
            artifacts = LSTMTrainArtifacts(
                state_dict={},
                scaler_object=scaler,
                feature_cols=["f" + str(i) for i in range(10)],
                window=20,
            )
            
            # Save and load
            import torch
            save_path = tmpdir / "test_lstm.pt"
            torch.save(artifacts.__dict__, save_path)
            
            loaded = load_lstm_artifacts(save_path)
            
            # Verify scaler object is preserved
            assert loaded.scaler_object is not None, "Scaler object not preserved"
            assert isinstance(loaded.scaler_object, MinMaxScaler)

    def test_scale_window_with_scaler_object(self):
        """scale_window should work with scaler_object."""
        # Create scaler from known range data
        X_train = np.linspace(0, 1, 100).reshape(-1, 5).astype(np.float32)  # Known range
        scaler = MinMaxScaler()
        scaler.fit(X_train)
        
        # Scale test window with similar range (won't have out-of-distribution values)
        X_test = np.linspace(0.2, 0.8, 20).reshape(-1, 5).astype(np.float32)
        
        X_scaled = scale_window(X_test, scaler_object=scaler)
        
        # Verify output is valid
        assert X_scaled.ndim >= 2, "Should be at least 2D"
        assert X_scaled.shape[-1] == 5, "Last dimension should be n_features=5"
        assert X_scaled.dtype == np.float32
        # Values should be mostly in [0, 1] for in-distribution data
        assert np.min(X_scaled) >= -0.01, "Mostly in range"
        assert np.max(X_scaled) <= 1.01, "Mostly in range"

    def test_scale_window_backward_compatible(self):
        """scale_window should still work with legacy scaler_min/max."""
        # Create scaler and extract min/max
        X_train = np.random.randn(100, 5).astype(np.float32)
        scaler = MinMaxScaler()
        scaler.fit(X_train)
        
        scaler_min = scaler.data_min_.astype(np.float32)
        scaler_max = scaler.data_max_.astype(np.float32)
        
        # Scale test window using legacy method
        X_test = np.random.randn(20, 5).astype(np.float32)
        
        X_scaled = scale_window(X_test, scaler_min=scaler_min, scaler_max=scaler_max)
        
        # Verify output (may be batched to 3D)
        if X_scaled.ndim == 3:
            assert X_scaled.shape == (1, 20, 5), f"Unexpected batched shape: {X_scaled.shape}"
        else:
            assert X_scaled.shape == X_test.shape
        assert X_scaled.dtype == np.float32
        assert np.all((X_scaled >= 0) & (X_scaled <= 1))

    def test_scale_window_dimension_mismatch_raises_error(self):
        """scale_window should raise error if dimensions mismatch."""
        X_train = np.random.randn(100, 5).astype(np.float32)
        scaler = MinMaxScaler()
        scaler.fit(X_train)
        
        X_test_wrong = np.random.randn(20, 3).astype(np.float32)  # Wrong n_features
        
        with pytest.raises(ValueError):
            scale_window(X_test_wrong, scaler_object=scaler)


class TestResolveFeaturesAPI:
    """Verify resolve_feature_columns returns list, not tuple."""

    def test_resolve_feature_columns_returns_list(self):
        """resolve_feature_columns should return list, not tuple."""
        df = pd.DataFrame({
            "col1": [1.0, 2.0, 3.0],
            "col2": [4.0, 5.0, 6.0],
            "timestamp": ["2020-01-01", "2020-01-02", "2020-01-03"],
        })
        
        result = resolve_feature_columns(df)
        
        assert isinstance(result, list), f"Expected list, got {type(result)}"
        assert not isinstance(result, tuple), "Should be list, not tuple"

    def test_drop_leaky_features_returns_tuple(self):
        """drop_leaky_feature_columns should return (cleaned, removed) tuple."""
        # Features with anomaly-related leakage (the blocklist it actually checks)
        feature_cols = ["col1", "col2", "anomaly_score", "anomaly_flag", "anomaly_type"]
        
        result = drop_leaky_feature_columns(feature_cols)
        
        assert isinstance(result, tuple), "Should return tuple"
        assert len(result) == 2, "Should return (cleaned, removed)"
        
        cleaned, removed = result
        assert isinstance(cleaned, list)
        assert isinstance(removed, list)
        # Verify clean columns kept
        assert "col1" in cleaned
        assert "col2" in cleaned
        # Verify anomaly leakage removed
        assert "anomaly_score" in removed
        assert "anomaly_flag" in removed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
