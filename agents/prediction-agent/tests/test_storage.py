"""Tests for storage module."""

import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agent.result import PredictionResult
from storage import ResultsStore
from storage.integration import PredictionLogger, AgentWithLogging


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    # Close connection and try to delete with retries
    import gc
    gc.collect()
    try:
        Path(db_path).unlink(missing_ok=True)
    except PermissionError:
        pass  # Windows may keep file locked


@pytest.fixture
def store(temp_db):
    """Create a ResultsStore instance."""
    return ResultsStore(temp_db)


@pytest.fixture
def sample_prediction():
    """Create a sample prediction for testing."""
    return PredictionResult(
        node_id="TEST_NODE_1",
        timestamp="2026-04-17T12:30:00Z",
        risk_probs={
            "call_drop_risk": 0.85,
            "latency_breach_risk": 0.72,
            "congestion_risk": 0.68,
            "jitter_risk": 0.45,
            "mos_risk": 0.38,
            "throughput_risk": 0.52,
        },
        capacity_exhaustion_eta_min=15.5,
        severity="critical",
        shap_features={
            "call_drop_risk": [
                {"feature": "call_volume_t", "value": 0.45, "direction": "increases_risk"},
            ],
        },
        retrieved_incidents=[
            {
                "incident_type": "call_drop_spike",
                "severity": "high",
                "document": "Similar incident",
                "distance": 0.25,
            },
        ],
        explanation="High call drop risk detected.",
        eta_debug_status="ok",
        primary_metric_name="call_drop_risk",
        primary_metric_probability=0.85,
        eta_per_target={"call_drop_risk": 15.5},
        top_3_drivers={
            "call_drop_risk": [
                {"feature": "call_volume_t", "value": 0.45, "direction": "increases_risk"},
            ],
        },
        decision_thresholds_used={"call_drop_risk": 0.70},
        margins_per_metric={"call_drop_risk": 0.15},
    )


class TestResultsStore:
    """Test ResultsStore functionality."""

    def test_init_creates_database(self, temp_db):
        """Test that initializing store creates database."""
        store = ResultsStore(temp_db)
        assert Path(temp_db).exists()

    def test_store_prediction(self, store, sample_prediction):
        """Test storing a prediction."""
        pred_id = store.store_prediction(sample_prediction)
        assert pred_id > 0

    def test_duplicate_prediction_replaced(self, store, sample_prediction):
        """Test that duplicate predictions are replaced."""
        pred_id1 = store.store_prediction(sample_prediction)
        pred_id2 = store.store_prediction(sample_prediction)
        # Same node and timestamp should result in a replacement
        # (ID may differ due to SQLite REPLACE behavior)
        
        # Verify only one record exists for this node/timestamp combo
        predictions = store.get_predictions_for_node("TEST_NODE_1")
        assert len(predictions) == 1
        assert predictions[0].node_id == sample_prediction.node_id

    def test_get_prediction(self, store, sample_prediction):
        """Test retrieving a prediction."""
        pred_id = store.store_prediction(sample_prediction)
        retrieved = store.get_prediction(pred_id)
        
        assert retrieved is not None
        assert retrieved.node_id == sample_prediction.node_id
        assert retrieved.severity == sample_prediction.severity
        assert retrieved.risk_probs == sample_prediction.risk_probs

    def test_get_prediction_not_found(self, store):
        """Test retrieving non-existent prediction."""
        retrieved = store.get_prediction(99999)
        assert retrieved is None

    def test_get_latest_for_node(self, store, sample_prediction):
        """Test getting latest prediction for a node."""
        store.store_prediction(sample_prediction)
        latest = store.get_latest_for_node("TEST_NODE_1")
        
        assert latest is not None
        assert latest.node_id == "TEST_NODE_1"

    def test_get_predictions_for_node(self, store):
        """Test getting all predictions for a node."""
        # Store 3 predictions for same node
        for i in range(3):
            pred = PredictionResult(
                node_id="TEST_NODE_1",
                timestamp=f"2026-04-17T{12+i:02d}:30:00Z",
                risk_probs={"call_drop_risk": 0.5},
                capacity_exhaustion_eta_min=10.0,
                severity="warning",
                shap_features={},
                retrieved_incidents=[],
                explanation="Test",
                eta_debug_status="ok",
                primary_metric_name="call_drop_risk",
                primary_metric_probability=0.5,
                eta_per_target={},
                top_3_drivers={},
                decision_thresholds_used={},
                margins_per_metric={},
            )
            store.store_prediction(pred)
        
        predictions = store.get_predictions_for_node("TEST_NODE_1", limit=10)
        assert len(predictions) == 3

    def test_get_predictions_by_severity(self, store):
        """Test filtering by severity."""
        # Store critical and warning predictions
        for severity in ["critical", "critical", "warning"]:
            pred = PredictionResult(
                node_id="TEST_NODE_1",
                timestamp=datetime.now().isoformat(),
                risk_probs={"call_drop_risk": 0.8 if severity == "critical" else 0.4},
                capacity_exhaustion_eta_min=10.0,
                severity=severity,
                shap_features={},
                retrieved_incidents=[],
                explanation="Test",
                eta_debug_status="ok",
                primary_metric_name="call_drop_risk",
                primary_metric_probability=0.8 if severity == "critical" else 0.4,
                eta_per_target={},
                top_3_drivers={},
                decision_thresholds_used={},
                margins_per_metric={},
            )
            store.store_prediction(pred)
        
        critical = store.get_predictions_by_severity("critical", limit=100)
        assert len(critical) == 2

    def test_get_statistics(self, store):
        """Test getting statistics."""
        # Store several predictions
        for i in range(5):
            pred = PredictionResult(
                node_id=f"NODE_{i}",
                timestamp=datetime.now().isoformat(),
                risk_probs={"call_drop_risk": 0.5 + i * 0.1},
                capacity_exhaustion_eta_min=10.0,
                severity="critical" if i < 2 else "warning",
                shap_features={},
                retrieved_incidents=[],
                explanation="Test",
                eta_debug_status="ok",
                primary_metric_name="call_drop_risk",
                primary_metric_probability=0.5 + i * 0.1,
                eta_per_target={},
                top_3_drivers={},
                decision_thresholds_used={},
                margins_per_metric={},
            )
            store.store_prediction(pred)
        
        stats = store.get_statistics(days_back=7)
        assert stats["total_predictions"] == 5
        assert "critical" in stats["severity_distribution"]
        assert "warning" in stats["severity_distribution"]

    def test_export_to_csv(self, store, sample_prediction, temp_db):
        """Test exporting to CSV."""
        store.store_prediction(sample_prediction)
        
        output_file = Path(temp_db).parent / "export.csv"
        count = store.export_to_csv(output_file)
        
        assert count == 1
        assert output_file.exists()
        
        output_file.unlink()

    def test_export_to_json(self, store, sample_prediction, temp_db):
        """Test exporting to JSON."""
        store.store_prediction(sample_prediction)
        
        output_file = Path(temp_db).parent / "export.json"
        count = store.export_to_json(output_file)
        
        assert count == 1
        assert output_file.exists()
        
        output_file.unlink()

    def test_cleanup_old_records(self, store):
        """Test cleaning up old records."""
        # Store an old prediction
        old_pred = PredictionResult(
            node_id="OLD_NODE",
            timestamp="2026-01-01T12:00:00Z",
            risk_probs={"call_drop_risk": 0.5},
            capacity_exhaustion_eta_min=10.0,
            severity="warning",
            shap_features={},
            retrieved_incidents=[],
            explanation="Old prediction",
            eta_debug_status="ok",
            primary_metric_name="call_drop_risk",
            primary_metric_probability=0.5,
            eta_per_target={},
            top_3_drivers={},
            decision_thresholds_used={},
            margins_per_metric={},
        )
        store.store_prediction(old_pred)
        
        # Manually set created_at to old date
        with sqlite3.connect(store.db_path) as conn:
            cursor = conn.cursor()
            old_date = (datetime.now() - timedelta(days=100)).isoformat()
            cursor.execute(
                "UPDATE predictions SET created_at = ? WHERE node_id = 'OLD_NODE'",
                (old_date,)
            )
            conn.commit()
        
        # Clean up records older than 90 days
        deleted = store.cleanup_old_records(days_old=90)
        assert deleted >= 1


class TestPredictionLogger:
    """Test PredictionLogger functionality."""

    def test_log_prediction(self, temp_db, sample_prediction):
        """Test logging a prediction."""
        logger = PredictionLogger(temp_db)
        pred_id = logger.log_prediction(sample_prediction)
        
        assert pred_id > 0

    def test_log_predictions_batch(self, temp_db):
        """Test logging multiple predictions."""
        logger = PredictionLogger(temp_db)
        
        predictions = []
        for i in range(3):
            pred = PredictionResult(
                node_id=f"NODE_{i}",
                timestamp="2026-04-17T12:30:00Z",
                risk_probs={"call_drop_risk": 0.5},
                capacity_exhaustion_eta_min=10.0,
                severity="warning",
                shap_features={},
                retrieved_incidents=[],
                explanation="Test",
                eta_debug_status="ok",
                primary_metric_name="call_drop_risk",
                primary_metric_probability=0.5,
                eta_per_target={},
                top_3_drivers={},
                decision_thresholds_used={},
                margins_per_metric={},
            )
            predictions.append(pred)
        
        pred_ids = logger.log_predictions(predictions)
        assert len(pred_ids) == 3

    def test_get_session_summary(self, temp_db, sample_prediction):
        """Test getting session summary."""
        logger = PredictionLogger(temp_db)
        logger.log_prediction(sample_prediction)
        
        summary = logger.get_session_summary()
        assert summary["count"] == 1
        assert len(summary["predictions"]) == 1

    def test_get_system_health(self, temp_db):
        """Test getting system health."""
        logger = PredictionLogger(temp_db)
        
        health = logger.get_system_health(days_back=7)
        assert "health_status" in health
        assert "total_predictions" in health
        assert "severity_distribution" in health
