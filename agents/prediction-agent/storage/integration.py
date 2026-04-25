"""Integration utilities for ResultsStore with PredictionAgent."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from storage import ResultsStore
from agent.result import PredictionResult

logger = logging.getLogger(__name__)


class PredictionLogger:
    """High-level interface for logging and querying predictions."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize prediction logger.
        
        Args:
            db_path: Optional custom database path
        """
        self.store = ResultsStore(db_path)
        self.session_predictions = []

    def log_prediction(self, result: PredictionResult) -> int:
        """Log a single prediction to database.
        
        Args:
            result: PredictionResult to store
            
        Returns:
            Prediction ID
        """
        pred_id = self.store.store_prediction(result)
        self.session_predictions.append(pred_id)
        logger.info(f"Logged prediction {pred_id}: {result.node_id} → {result.severity}")
        return pred_id

    def log_predictions(self, results: List[PredictionResult]) -> List[int]:
        """Log multiple predictions to database.
        
        Args:
            results: List of PredictionResult objects
            
        Returns:
            List of prediction IDs
        """
        pred_ids = []
        for result in results:
            pred_id = self.log_prediction(result)
            pred_ids.append(pred_id)
        logger.info(f"Logged {len(pred_ids)} predictions")
        return pred_ids

    def get_session_summary(self) -> Dict:
        """Get summary of predictions logged in this session.
        
        Returns:
            Dictionary with session statistics
        """
        if not self.session_predictions:
            return {"count": 0, "predictions": []}

        summary = {
            "count": len(self.session_predictions),
            "predictions": [],
            "severity_breakdown": {},
            "affected_nodes": set(),
        }

        for pred_id in self.session_predictions:
            pred = self.store.get_prediction(pred_id)
            if pred:
                summary["predictions"].append({
                    "id": pred_id,
                    "node": pred.node_id,
                    "severity": pred.severity,
                    "timestamp": pred.timestamp,
                })
                summary["severity_breakdown"][pred.severity] = (
                    summary["severity_breakdown"].get(pred.severity, 0) + 1
                )
                summary["affected_nodes"].add(pred.node_id)

        summary["affected_nodes"] = list(summary["affected_nodes"])
        return summary

    def query_node_history(
        self,
        node_id: str,
        limit: int = 100,
        days_back: Optional[int] = None
    ) -> pd.DataFrame:
        """Query prediction history for a node as DataFrame.
        
        Args:
            node_id: Node to query
            limit: Max results
            days_back: Optional time window
            
        Returns:
            DataFrame with columns: timestamp, severity, primary_metric, 
                                   primary_probability, capacity_eta_min
        """
        predictions = self.store.get_predictions_for_node(
            node_id,
            limit=limit,
            days_back=days_back
        )

        data = []
        for pred in predictions:
            data.append({
                "timestamp": pred.timestamp,
                "severity": pred.severity,
                "primary_metric": pred.primary_metric_name,
                "primary_probability": pred.primary_metric_probability,
                "capacity_eta_min": pred.capacity_exhaustion_eta_min,
            })

        return pd.DataFrame(data)

    def query_critical_events(
        self,
        days_back: int = 7,
        limit: int = 100
    ) -> pd.DataFrame:
        """Query critical severity events.
        
        Args:
            days_back: Time window in days
            limit: Max results
            
        Returns:
            DataFrame with critical predictions
        """
        critical_ids = self.store.get_predictions_by_severity(
            "critical",
            limit=limit,
            days_back=days_back
        )

        data = []
        for pred_id, node_id, timestamp, severity in critical_ids:
            pred = self.store.get_prediction(pred_id)
            if pred:
                data.append({
                    "node_id": node_id,
                    "timestamp": timestamp,
                    "primary_metric": pred.primary_metric_name,
                    "primary_probability": pred.primary_metric_probability,
                    "capacity_eta_min": pred.capacity_exhaustion_eta_min,
                    "explanation": pred.explanation[:100],  # Truncate
                })

        return pd.DataFrame(data)

    def get_risk_evolution(
        self,
        node_id: str,
        target: str,
        days_back: int = 7
    ) -> pd.DataFrame:
        """Get risk probability evolution for a target.
        
        Args:
            node_id: Node to analyze
            target: Risk target (e.g., latency_breach_risk)
            days_back: Time window
            
        Returns:
            DataFrame with: date, avg_prob, max_prob, min_prob
        """
        import sqlite3

        query = """
            SELECT 
                DATE(p.timestamp) as date,
                AVG(rp.probability) as avg_prob,
                MAX(rp.probability) as max_prob,
                MIN(rp.probability) as min_prob,
                COUNT(*) as prediction_count
            FROM predictions p
            JOIN risk_probabilities rp ON p.id = rp.prediction_id
            WHERE p.node_id = ? AND rp.target = ? 
                AND p.created_at >= datetime('now', ? || ' days')
            GROUP BY DATE(p.timestamp)
            ORDER BY date DESC
        """

        with sqlite3.connect(self.store.db_path) as conn:
            df = pd.read_sql_query(
                query,
                conn,
                params=[node_id, target, -days_back]
            )

        return df

    def get_top_drivers_frequency(
        self,
        node_id: str,
        target: str,
        days_back: int = 7
    ) -> pd.DataFrame:
        """Get most frequent top drivers for a node/target.
        
        Args:
            node_id: Node to analyze
            target: Risk target
            days_back: Time window
            
        Returns:
            DataFrame with: feature, frequency, avg_rank
        """
        import sqlite3

        query = """
            SELECT 
                td.feature,
                COUNT(*) as frequency,
                AVG(td.rank) as avg_rank,
                AVG(ABS(td.value)) as avg_impact
            FROM top_drivers td
            JOIN predictions p ON td.prediction_id = p.id
            WHERE p.node_id = ? AND td.target = ?
                AND p.created_at >= datetime('now', ? || ' days')
            GROUP BY td.feature
            ORDER BY frequency DESC, avg_impact DESC
        """

        with sqlite3.connect(self.store.db_path) as conn:
            df = pd.read_sql_query(
                query,
                conn,
                params=[node_id, target, -days_back]
            )

        return df

    def export_session_results(
        self,
        output_dir: str = "results",
        format: str = "both"
    ) -> Dict[str, str]:
        """Export session results to files.
        
        Args:
            output_dir: Directory to save files
            format: 'csv', 'json', or 'both'
            
        Returns:
            Dictionary with output file paths
        """
        from pathlib import Path
        output_path = Path(output_dir)

        outputs = {}

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if format in ("csv", "both"):
            csv_file = output_path / f"predictions_{timestamp}.csv"
            self.store.export_to_csv(csv_file)
            outputs["csv"] = str(csv_file)
            logger.info(f"Exported CSV: {csv_file}")

        if format in ("json", "both"):
            json_file = output_path / f"predictions_{timestamp}.json"
            self.store.export_to_json(json_file)
            outputs["json"] = str(json_file)
            logger.info(f"Exported JSON: {json_file}")

        return outputs

    def get_system_health(self, days_back: int = 7) -> Dict:
        """Get overall system health metrics.
        
        Args:
            days_back: Analysis window
            
        Returns:
            Dictionary with health metrics
        """
        stats = self.store.get_statistics(days_back)

        # Calculate derived metrics
        total = stats["total_predictions"]
        severity_dist = stats["severity_distribution"]

        critical_pct = (severity_dist.get("critical", 0) / total * 100) if total > 0 else 0
        high_pct = (severity_dist.get("high", 0) / total * 100) if total > 0 else 0
        alert_pct = critical_pct + high_pct

        health = {
            "analysis_period_days": days_back,
            "total_predictions": total,
            "severity_distribution": severity_dist,
            "critical_percentage": round(critical_pct, 2),
            "high_percentage": round(high_pct, 2),
            "alert_percentage": round(alert_pct, 2),
            "top_affected_nodes": stats["top_nodes"],
            "avg_risks": stats["average_risk_by_target"],
            "health_status": (
                "🔴 Critical" if alert_pct > 20
                else "🟠 Concerning" if alert_pct > 10
                else "🟡 Watch" if alert_pct > 5
                else "🟢 Healthy"
            ),
        }

        return health


class AgentWithLogging:
    """Wrapper to add logging to PredictionAgent."""

    def __init__(self, agent, logger: Optional[PredictionLogger] = None):
        """Initialize agent wrapper.
        
        Args:
            agent: PredictionAgent instance
            logger: Optional PredictionLogger (creates if None)
        """
        self.agent = agent
        self.logger = logger or PredictionLogger()

    def predict(self, node_id: str, df: pd.DataFrame, **kwargs):
        """Predict with automatic logging.
        
        Args:
            node_id: Node to predict
            df: Feature dataframe
            **kwargs: Additional arguments for agent.predict
            
        Returns:
            PredictionResult with logged ID
        """
        result = self.agent.predict(node_id, df, **kwargs)
        pred_id = self.logger.log_prediction(result)
        result.database_id = pred_id  # Attach ID to result
        return result

    def batch_predict(
        self,
        node_dfs: Dict[str, pd.DataFrame],
        **kwargs
    ) -> Dict[str, PredictionResult]:
        """Batch predict with logging.
        
        Args:
            node_dfs: Dict of {node_id: dataframe}
            **kwargs: Additional arguments
            
        Returns:
            Dict of {node_id: PredictionResult}
        """
        results = {}
        for node_id, df in node_dfs.items():
            results[node_id] = self.predict(node_id, df, **kwargs)
        return results

    def get_logger(self) -> PredictionLogger:
        """Get the prediction logger."""
        return self.logger
