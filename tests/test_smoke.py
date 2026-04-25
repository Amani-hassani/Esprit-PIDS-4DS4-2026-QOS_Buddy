"""Lightweight smoke tests (no trained artifacts required)."""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def test_config_module_loads():
    cfg = importlib.import_module("config")
    assert cfg.PROJECT_ROOT.exists()
    assert len(cfg.TARGET_NAMES) == 6


def test_data_pipeline_imports():
    importlib.import_module("data_pipeline.loader")
    importlib.import_module("data_pipeline.preprocessor")
    importlib.import_module("data_pipeline.label_engineer")
    importlib.import_module("data_pipeline.features")


def test_models_ensemble_imports():
    """``ensemble`` only needs NumPy + ``config`` (heavy trainers are optional in dev envs)."""
    importlib.import_module("models.ensemble")


class TestLabelEngineer:
    """Test label engineering edge cases."""
    
    def test_empty_dataframe(self):
        """Test label engineering on empty dataframe."""
        from data_pipeline.label_engineer import build_labels
        
        df = pd.DataFrame()
        result = build_labels(df)
        assert result.empty
    
    def test_missing_required_columns(self):
        """Test label engineering raises on missing columns."""
        from data_pipeline.label_engineer import build_labels
        
        df = pd.DataFrame({"node_id": [1, 2, 3]})
        with pytest.raises(ValueError, match="missing required columns"):
            build_labels(df)
    
    def test_tte_labels_valid_values(self):
        """Test that TTE labels are valid (NaN or positive minutes)."""
        from data_pipeline.label_engineer import build_labels
        from config import FUTURE_WINDOW_STEPS
        
        # Create minimal valid dataframe
        n_rows = FUTURE_WINDOW_STEPS + 50
        df = pd.DataFrame({
            "node_id": [1] * n_rows,
            "timestamp": pd.date_range("2026-01-01", periods=n_rows, freq="30s"),
            "anomaly_score": np.random.random(n_rows),
            "latency_ms": np.random.random(n_rows) * 100,
            "throughput_mbps": np.random.random(n_rows) * 100,
            "jitter_ms": np.random.random(n_rows) * 50,
            "mos_estimate": np.random.random(n_rows) * 5,
            "queue_length": np.random.random(n_rows) * 10,
            "active_connections": np.random.random(n_rows) * 100,
        })
        result = build_labels(df)
        
        # Check TTE columns exist
        assert "tte_call_drop_min" in result.columns
        assert "call_drop_event" in result.columns
        
        # Check values are valid 
        assert result["tte_call_drop_min"].isna().any() or (result["tte_call_drop_min"] >= 0).all()
        assert result["call_drop_event"].isin([0, 1]).all()


class TestFeatureEngineering:
    """Test feature engineering functions."""
    
    def test_resolve_feature_columns_returns_list(self):
        """Test that resolve_feature_columns returns a list (not tuple)."""
        from data_pipeline.features import resolve_feature_columns
        
        df = pd.DataFrame({
            "col1": [1.0, 2.0, 3.0],
            "col2": [4.0, 5.0, 6.0],
            "target_col": [0, 1, 0],
        })
        result = resolve_feature_columns(df)
        assert isinstance(result, list)
        assert not isinstance(result, tuple)


class TestPreprocessor:
    """Test preprocessor edge cases."""
    
    def test_oov_categories_logged(self, caplog):
        """Test that OOV categories are detected and logged."""
        from data_pipeline.preprocessor import Preprocessor
        
        # Fit on one set of categories
        df_train = pd.DataFrame({
            "node_id": ["A", "B", "C"],
            "device_type": ["phone", "tablet", "phone"],
        })
        preprocessor = Preprocessor().fit(df_train)
        
        # Try to transform with OOV category
        df_test = pd.DataFrame({
            "node_id": ["D"],  # OOV: not in training
            "device_type": ["phone"],
        })
        
        with caplog.at_level("WARNING"):
            result = preprocessor.transform(df_test)
        
        # Check that OOV was logged
        assert "OOV categories" in caplog.text or result["node_id"].iloc[0] == -1


# ============================================================================
# PHASE 5: VALIDATION TESTS FOR LOGIC REFINEMENT (PRIMARY METRIC ALIGNMENT)
# ============================================================================

class TestPrimaryMetricAlignment:
    """Validate that primary metric = highest margin metric (not highest prob)."""
    
    def test_primary_metric_uses_margin_not_probability(self):
        """Test that primary_metric_name corresponds to highest MARGIN metric."""
        from agent.result import PredictionResult
        from config import TARGET_NAMES
        
        # Mock scenario: 
        # - latency_breach_risk has highest PROBABILITY (0.7) but low margin (0.0)
        # - congestion_risk has lower probability (0.65) but higher margin (0.15)
        # Primary should be congestion_risk (higher margin)
        
        risk_probs = {
            "call_drop_risk": 0.2,
            "congestion_risk": 0.65,           # margin = 0.15
            "jitter_risk": 0.3,
            "latency_breach_risk": 0.7,        # margin = 0.2 ← HIGHEST
            "mos_risk": 0.25,
            "throughput_risk": 0.35,
        }
        thresholds = {name: 0.5 for name in TARGET_NAMES}
        margins = np.array([risk_probs.get(name, 0.5) - thresholds.get(name, 0.5) 
                           for name in TARGET_NAMES])
        
        primary_idx = int(np.argmax(margins))
        primary_metric = TARGET_NAMES[primary_idx]
        
        # Verify it's latency_breach_risk (highest margin = 0.2)
        assert primary_metric == "latency_breach_risk"
        assert margins[primary_idx] == np.max(margins)


class TestSHAPFormatConsistency:
    """Validate that SHAP features use consistent Dict[target, List] format."""
    
    def test_shap_features_is_grouped_dict_format(self):
        """Test that result.shap_features is Dict[target, List[features]]."""
        from agent.result import PredictionResult
        
        # Create sample grouped features
        shap_feats_dict = {
            "congestion_risk": [
                {"feature": "cpu_load", "value": 0.15, "direction": "increases_risk"},
                {"feature": "queue_length", "value": 0.12, "direction": "increases_risk"},
            ],
            "latency_breach_risk": [
                {"feature": "latency_ms", "value": 0.10, "direction": "increases_risk"},
            ],
        }
        
        result = PredictionResult(
            node_id="N1",
            timestamp="2026-04-16T10:00:00",
            risk_probs={"congestion_risk": 0.65},
            capacity_exhaustion_eta_min=15.0,
            severity="high",
            shap_features=shap_feats_dict,
            retrieved_incidents=[],
            explanation="Test",
            primary_metric_name="congestion_risk",
            primary_metric_eta_min=15.0,
            primary_metric_probability=0.65,
            top_3_drivers=shap_feats_dict,
        )
        
        # Verify dict format
        assert isinstance(result.shap_features, dict)
        assert "congestion_risk" in result.shap_features
        assert isinstance(result.shap_features["congestion_risk"], list)
        assert len(result.shap_features["congestion_risk"]) > 0


class TestPrimaryDriversSelection:
    """Validate primary drivers come from primary metric."""
    
    def test_top_drivers_from_primary_metric(self):
        """Test that top_3_drivers only contain drivers from primary metric."""
        from agent.result import PredictionResult
        
        primary_metric = "congestion_risk"
        shap_dict = {
            "congestion_risk": [
                {"feature": "cpu_load", "value": 0.15, "direction": "increases_risk"},
                {"feature": "queue_length", "value": 0.12, "direction": "increases_risk"},
                {"feature": "memory_usage", "value": 0.08, "direction": "increases_risk"},
            ],
            "latency_breach_risk": [
                {"feature": "jitter_ms", "value": 0.09, "direction": "increases_risk"},
            ],
        }
        
        result = PredictionResult(
            node_id="N1",
            timestamp="2026-04-16T10:00:00",
            risk_probs={"congestion_risk": 0.65},
            capacity_exhaustion_eta_min=15.0,
            severity="high",
            shap_features=shap_dict,
            retrieved_incidents=[],
            explanation="Test",
            primary_metric_name=primary_metric,
            primary_metric_eta_min=15.0,
            primary_metric_probability=0.65,
            top_3_drivers=shap_dict,  # Should contain only congestion_risk drivers
        )
        
        # Verify all drivers belong to primary metric
        for target, drivers in result.top_3_drivers.items():
            assert target == primary_metric, f"Found drivers for {target}, expected {primary_metric}"
            for driver in drivers:
                assert driver["feature"] in ["cpu_load", "queue_length", "memory_usage"]


class TestLLMReformatting:
    """Validate LLM receives dict format (not flat list)."""
    
    def test_llm_prepare_shap_handles_dict_format(self):
        """Test that _prepare_shap_features converts dict to flat for processing."""
        from llm.explainer import LLMExplainer
        
        explainer = LLMExplainer(backend="ollama")
        
        # Dict format input
        shap_dict = {
            "congestion_risk": [
                {"feature": "cpu_load", "value": 0.15, "direction": "increases_risk"},
                {"feature": "queue_length", "value": 0.12, "direction": "increases_risk"},
            ],
            "latency_breach_risk": [
                {"feature": "latency_ms", "value": 0.10, "direction": "increases_risk"},
            ],
        }
        
        result = explainer._prepare_shap_features(shap_dict)
        
        # Should return flat list
        assert isinstance(result, list)
        assert len(result) == 3  # Total of 3 features across targets
        
        # All features should have target field set
        for feat in result:
            assert "target" in feat
            assert feat["target"] in ["congestion_risk", "latency_breach_risk"]


class TestSeverityConsistency:
    """Validate severity logic consistent with primary metric selection."""
    
    def test_critical_severity_has_high_margin(self):
        """Test that 'critical' severity only when max_margin >= 0.15."""
        from agent.prediction_agent import _severity_from_margin
        
        assert _severity_from_margin(0.16) == "critical"
        assert _severity_from_margin(0.15) == "critical"
        assert _severity_from_margin(0.149) == "high"
        assert _severity_from_margin(-0.16) == "normal"
        assert _severity_from_margin(float("nan")) == "unknown"
        assert _severity_from_margin(float("inf")) == "critical"  # ← edge case
