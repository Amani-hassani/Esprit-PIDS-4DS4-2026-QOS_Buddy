"""SQLite-based results storage and retrieval system for predictions."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from agent.result import PredictionResult
from config import PROJECT_ROOT

logger = logging.getLogger(__name__)

# Default storage location (lazy evaluation)
def _get_default_db_path():
    """Get default database path."""
    return PROJECT_ROOT / "storage" / "predictions.db"

DEFAULT_DB_PATH = None  # Set lazily in __init__


class ResultsStore:
    """Manage prediction results storage and retrieval in SQLite."""

    def __init__(self, db_path: Path | str | None = None):
        """Initialize the results store with database path.
        
        Args:
            db_path: Path to SQLite database file (default: storage/predictions.db)
        """
        if db_path is None:
            db_path = _get_default_db_path()
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema if not exists."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Main predictions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    primary_metric TEXT,
                    primary_probability REAL,
                    capacity_eta_min REAL,
                    eta_debug_status TEXT,
                    explanation TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(node_id, timestamp)
                )
            """)

            # Risk probabilities (per-target)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS risk_probabilities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_id INTEGER NOT NULL,
                    target TEXT NOT NULL,
                    probability REAL NOT NULL,
                    FOREIGN KEY(prediction_id) REFERENCES predictions(id)
                        ON DELETE CASCADE
                )
            """)

            # ETA per target
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS eta_per_target (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_id INTEGER NOT NULL,
                    target TEXT NOT NULL,
                    eta_minutes REAL NOT NULL,
                    FOREIGN KEY(prediction_id) REFERENCES predictions(id)
                        ON DELETE CASCADE
                )
            """)

            # Top 3 drivers (feature importance)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS top_drivers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_id INTEGER NOT NULL,
                    target TEXT NOT NULL,
                    feature TEXT NOT NULL,
                    value REAL NOT NULL,
                    direction TEXT NOT NULL,
                    rank INTEGER,
                    FOREIGN KEY(prediction_id) REFERENCES predictions(id)
                        ON DELETE CASCADE
                )
            """)

            # Retrieved incidents (for audit trail)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS retrieved_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_id INTEGER NOT NULL,
                    incident_type TEXT,
                    severity TEXT,
                    document TEXT,
                    distance REAL,
                    FOREIGN KEY(prediction_id) REFERENCES predictions(id)
                        ON DELETE CASCADE
                )
            """)

            # Decision thresholds used (audit trail)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS decision_thresholds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_id INTEGER NOT NULL,
                    target TEXT NOT NULL,
                    threshold REAL NOT NULL,
                    FOREIGN KEY(prediction_id) REFERENCES predictions(id)
                        ON DELETE CASCADE
                )
            """)

            # Margins per metric (for severity calculation audit)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS margins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_id INTEGER NOT NULL,
                    metric TEXT NOT NULL,
                    margin REAL NOT NULL,
                    FOREIGN KEY(prediction_id) REFERENCES predictions(id)
                        ON DELETE CASCADE
                )
            """)

            # Create indices for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_node_timestamp 
                ON predictions(node_id, timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_severity 
                ON predictions(severity)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at 
                ON predictions(created_at)
            """)

            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")

    def store_prediction(self, result: PredictionResult) -> int:
        """Store a prediction result and all associated data.
        
        Args:
            result: PredictionResult object
            
        Returns:
            Prediction ID in database
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Insert main prediction
            cursor.execute("""
                INSERT OR REPLACE INTO predictions
                (node_id, timestamp, severity, primary_metric, primary_probability,
                 capacity_eta_min, eta_debug_status, explanation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result.node_id,
                result.timestamp,
                result.severity,
                result.primary_metric_name,
                result.primary_metric_probability,
                result.capacity_exhaustion_eta_min,
                result.eta_debug_status,
                result.explanation,
            ))

            # Get the prediction ID
            cursor.execute(
                "SELECT id FROM predictions WHERE node_id = ? AND timestamp = ?",
                (result.node_id, result.timestamp)
            )
            prediction_id = cursor.fetchone()[0]

            # Insert risk probabilities
            for target, prob in result.risk_probs.items():
                cursor.execute("""
                    INSERT INTO risk_probabilities (prediction_id, target, probability)
                    VALUES (?, ?, ?)
                """, (prediction_id, target, prob))

            # Insert ETA per target
            for target, eta in result.eta_per_target.items():
                cursor.execute("""
                    INSERT INTO eta_per_target (prediction_id, target, eta_minutes)
                    VALUES (?, ?, ?)
                """, (prediction_id, target, eta))

            # Insert top drivers
            if result.top_3_drivers:
                for target, drivers in result.top_3_drivers.items():
                    for rank, driver in enumerate(drivers, 1):
                        cursor.execute("""
                            INSERT INTO top_drivers 
                            (prediction_id, target, feature, value, direction, rank)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            prediction_id,
                            target,
                            driver.get("feature", "unknown"),
                            driver.get("value", 0.0),
                            driver.get("direction", "unknown"),
                            rank
                        ))

            # Insert retrieved incidents
            for incident in result.retrieved_incidents:
                cursor.execute("""
                    INSERT INTO retrieved_incidents
                    (prediction_id, incident_type, severity, document, distance)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    prediction_id,
                    incident.get("incident_type"),
                    incident.get("severity"),
                    incident.get("document"),
                    incident.get("distance"),
                ))

            # Insert decision thresholds
            for target, threshold in result.decision_thresholds_used.items():
                cursor.execute("""
                    INSERT INTO decision_thresholds (prediction_id, target, threshold)
                    VALUES (?, ?, ?)
                """, (prediction_id, target, threshold))

            # Insert margins
            for metric, margin in result.margins_per_metric.items():
                cursor.execute("""
                    INSERT INTO margins (prediction_id, metric, margin)
                    VALUES (?, ?, ?)
                """, (prediction_id, metric, margin))

            conn.commit()
            logger.info(
                f"Stored prediction for {result.node_id} at {result.timestamp} "
                f"with severity {result.severity}"
            )
            return prediction_id

    def get_prediction(self, prediction_id: int) -> Optional[PredictionResult]:
        """Retrieve a prediction result by ID.
        
        Args:
            prediction_id: ID of prediction to retrieve
            
        Returns:
            PredictionResult object or None if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Get main prediction
            cursor.execute("SELECT * FROM predictions WHERE id = ?", (prediction_id,))
            row = cursor.fetchone()
            if not row:
                return None

            # Get risk probabilities
            cursor.execute(
                "SELECT target, probability FROM risk_probabilities WHERE prediction_id = ?",
                (prediction_id,)
            )
            risk_probs = {r[0]: r[1] for r in cursor.fetchall()}

            # Get ETA per target
            cursor.execute(
                "SELECT target, eta_minutes FROM eta_per_target WHERE prediction_id = ?",
                (prediction_id,)
            )
            eta_per_target = {r[0]: r[1] for r in cursor.fetchall()}

            # Get top drivers
            cursor.execute(
                """SELECT target, feature, value, direction FROM top_drivers 
                   WHERE prediction_id = ? ORDER BY target, rank""",
                (prediction_id,)
            )
            top_3_drivers = {}
            for r in cursor.fetchall():
                target = r[0]
                if target not in top_3_drivers:
                    top_3_drivers[target] = []
                top_3_drivers[target].append({
                    "feature": r[1],
                    "value": r[2],
                    "direction": r[3],
                })

            # Get retrieved incidents
            cursor.execute(
                "SELECT * FROM retrieved_incidents WHERE prediction_id = ?",
                (prediction_id,)
            )
            retrieved_incidents = [
                {
                    "incident_type": r[1],
                    "severity": r[2],
                    "document": r[3],
                    "distance": r[4],
                }
                for r in cursor.fetchall()
            ]

            # Get decision thresholds
            cursor.execute(
                "SELECT target, threshold FROM decision_thresholds WHERE prediction_id = ?",
                (prediction_id,)
            )
            decision_thresholds_used = {r[0]: r[1] for r in cursor.fetchall()}

            # Get margins
            cursor.execute(
                "SELECT metric, margin FROM margins WHERE prediction_id = ?",
                (prediction_id,)
            )
            margins_per_metric = {r[0]: r[1] for r in cursor.fetchall()}

            return PredictionResult(
                node_id=row["node_id"],
                timestamp=row["timestamp"],
                risk_probs=risk_probs,
                capacity_exhaustion_eta_min=row["capacity_eta_min"],
                severity=row["severity"],
                shap_features={},  # Not stored currently
                retrieved_incidents=retrieved_incidents,
                explanation=row["explanation"],
                eta_debug_status=row["eta_debug_status"],
                primary_metric_name=row["primary_metric"],
                primary_metric_probability=row["primary_probability"],
                eta_per_target=eta_per_target,
                top_3_drivers=top_3_drivers,
                decision_thresholds_used=decision_thresholds_used,
                margins_per_metric=margins_per_metric,
            )

    def get_latest_for_node(self, node_id: str) -> Optional[PredictionResult]:
        """Get the most recent prediction for a node.
        
        Args:
            node_id: Node ID to search for
            
        Returns:
            Most recent PredictionResult or None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM predictions WHERE node_id = ? ORDER BY timestamp DESC LIMIT 1",
                (node_id,)
            )
            row = cursor.fetchone()
            if row:
                return self.get_prediction(row[0])
        return None

    def get_predictions_for_node(
        self,
        node_id: str,
        limit: int = 100,
        days_back: Optional[int] = None
    ) -> List[PredictionResult]:
        """Get predictions for a specific node.
        
        Args:
            node_id: Node ID to search for
            limit: Maximum number of results
            days_back: Optional - only get predictions from last N days
            
        Returns:
            List of PredictionResult objects
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if days_back:
                cutoff = datetime.now() - timedelta(days=days_back)
                cursor.execute("""
                    SELECT id FROM predictions 
                    WHERE node_id = ? AND created_at >= ?
                    ORDER BY timestamp DESC LIMIT ?
                """, (node_id, cutoff.isoformat(), limit))
            else:
                cursor.execute("""
                    SELECT id FROM predictions 
                    WHERE node_id = ?
                    ORDER BY timestamp DESC LIMIT ?
                """, (node_id, limit))

            results = []
            for row in cursor.fetchall():
                pred = self.get_prediction(row[0])
                if pred:
                    results.append(pred)
            return results

    def get_predictions_by_severity(
        self,
        severity: str,
        limit: int = 100,
        days_back: Optional[int] = None
    ) -> List[Tuple[int, str, str, str]]:
        """Get predictions filtered by severity.
        
        Args:
            severity: Severity level (critical, high, warning, etc.)
            limit: Maximum number of results
            days_back: Optional - only get predictions from last N days
            
        Returns:
            List of (prediction_id, node_id, timestamp, severity) tuples
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if days_back:
                cutoff = datetime.now() - timedelta(days=days_back)
                cursor.execute("""
                    SELECT id, node_id, timestamp, severity FROM predictions 
                    WHERE severity = ? AND created_at >= ?
                    ORDER BY created_at DESC LIMIT ?
                """, (severity, cutoff.isoformat(), limit))
            else:
                cursor.execute("""
                    SELECT id, node_id, timestamp, severity FROM predictions 
                    WHERE severity = ?
                    ORDER BY created_at DESC LIMIT ?
                """, (severity, limit))

            return cursor.fetchall()

    def get_statistics(self, days_back: int = 7) -> Dict[str, Any]:
        """Get summary statistics for predictions.
        
        Args:
            days_back: Number of days to analyze
            
        Returns:
            Dictionary with statistics
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days_back)

            # Total predictions
            cursor.execute(
                "SELECT COUNT(*) FROM predictions WHERE created_at >= ?",
                (cutoff.isoformat(),)
            )
            total_predictions = cursor.fetchone()[0]

            # By severity
            cursor.execute("""
                SELECT severity, COUNT(*) FROM predictions 
                WHERE created_at >= ?
                GROUP BY severity
            """, (cutoff.isoformat(),))
            severity_dist = {r[0]: r[1] for r in cursor.fetchall()}

            # By node
            cursor.execute("""
                SELECT node_id, COUNT(*) FROM predictions 
                WHERE created_at >= ?
                GROUP BY node_id ORDER BY COUNT(*) DESC LIMIT 10
            """, (cutoff.isoformat(),))
            top_nodes = dict(cursor.fetchall())

            # Average risk probabilities
            cursor.execute("""
                SELECT target, AVG(probability) FROM risk_probabilities rp
                JOIN predictions p ON rp.prediction_id = p.id
                WHERE p.created_at >= ?
                GROUP BY target
            """, (cutoff.isoformat(),))
            avg_risks = {r[0]: round(r[1], 4) for r in cursor.fetchall()}

            return {
                "period_days": days_back,
                "total_predictions": total_predictions,
                "severity_distribution": severity_dist,
                "top_nodes": top_nodes,
                "average_risk_by_target": avg_risks,
            }

    def export_to_csv(
        self,
        output_path: Path | str,
        node_id: Optional[str] = None,
        days_back: Optional[int] = None
    ) -> int:
        """Export predictions to CSV.
        
        Args:
            output_path: Path to save CSV file
            node_id: Optional - filter by node
            days_back: Optional - filter by time period
            
        Returns:
            Number of rows exported
        """
        with sqlite3.connect(self.db_path) as conn:
            query = "SELECT * FROM predictions WHERE 1=1"
            params = []
            
            if node_id:
                query += " AND node_id = ?"
                params.append(node_id)
            
            if days_back:
                cutoff = datetime.now() - timedelta(days=days_back)
                query += " AND created_at >= ?"
                params.append(cutoff.isoformat())
            
            query += " ORDER BY created_at DESC"
            
            df = pd.read_sql_query(query, conn, params=params)
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(output_path, index=False)
            logger.info(f"Exported {len(df)} predictions to {output_path}")
            return len(df)

    def export_to_json(
        self,
        output_path: Path | str,
        node_id: Optional[str] = None,
        days_back: Optional[int] = None
    ) -> int:
        """Export predictions to JSON.
        
        Args:
            output_path: Path to save JSON file
            node_id: Optional - filter by node
            days_back: Optional - filter by time period
            
        Returns:
            Number of records exported
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            query = "SELECT id FROM predictions WHERE 1=1"
            params = []
            
            if node_id:
                query += " AND node_id = ?"
                params.append(node_id)
            
            if days_back:
                cutoff = datetime.now() - timedelta(days=days_back)
                query += " AND created_at >= ?"
                params.append(cutoff.isoformat())
            
            query += " ORDER BY created_at DESC"
            
            cursor.execute(query, params)
            prediction_ids = [r[0] for r in cursor.fetchall()]
            
            predictions = []
            for pred_id in prediction_ids:
                pred = self.get_prediction(pred_id)
                if pred:
                    predictions.append(pred.to_dict())
            
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(predictions, f, indent=2, default=str)
            
            logger.info(f"Exported {len(predictions)} predictions to {output_path}")
            return len(predictions)

    def cleanup_old_records(self, days_old: int = 90) -> int:
        """Delete predictions older than specified days.
        
        Args:
            days_old: Delete records older than this many days
            
        Returns:
            Number of records deleted
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() - timedelta(days=days_old)
            
            cursor.execute(
                "DELETE FROM predictions WHERE created_at < ?",
                (cutoff.isoformat(),)
            )
            deleted = cursor.rowcount
            conn.commit()
            logger.info(f"Deleted {deleted} predictions older than {days_old} days")
            return deleted
