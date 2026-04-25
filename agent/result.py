"""Structured prediction output."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class PredictionResult:
    node_id: str
    timestamp: str
    risk_probs: Dict[str, float]
    capacity_exhaustion_eta_min: float
    severity: str
    shap_features: Dict[str, List[Dict[str, Any]]]  # Changed: {target: [features]}
    retrieved_incidents: List[Dict[str, Any]]
    explanation: str
    eta_debug_status: str = ""
    eta_debug_reason: str = ""
    eta_debug_max_forecast: float | None = None
    eta_debug_threshold: float | None = None
    eta_debug_horizon_min: float | None = None
    primary_metric_name: str = ""
    primary_metric_eta_min: float = float("inf")
    primary_metric_probability: float = 0.0
    eta_per_target: Dict[str, float] = field(default_factory=dict)
    top_3_drivers: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)  # Changed: {target: [drivers]}
    
    def __post_init__(self):
        """Filter top_3_drivers to only include primary_metric."""
        if self.primary_metric_name and self.top_3_drivers:
            # Keep only drivers from the primary metric
            self.top_3_drivers = {
                self.primary_metric_name: self.top_3_drivers.get(
                    self.primary_metric_name, []
                )
            }
    recommended_action: str = ""
    # === TRANSPARENCY: Margin calculation breakdown ===
    margins_per_metric: Dict[str, float] = field(default_factory=dict)  # {metric: margin}
    highest_margin_metric: str = ""  # Which metric triggered severity
    highest_margin_value: float = 0.0  # The actual max margin
    decision_thresholds_used: Dict[str, float] = field(default_factory=dict)  # Audit trail

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)
    
    @staticmethod
    def reformat_features_to_target_grouped(
        flat_features: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Convert flat feature list to target-grouped dictionary.
        
        Args:
            flat_features: List of {target, feature, value, direction}
            
        Returns:
            {target: [{feature, value, direction}, ...]}
        """
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for item in flat_features:
            target = item.get("target", "unknown")
            if target not in grouped:
                grouped[target] = []
            grouped[target].append({
                "feature": item.get("feature"),
                "value": item.get("value"),
                "direction": item.get("direction"),
            })
        return grouped


def severity_from_max_risk(max_prob: float) -> str:
    """Map max probability to a band. Non-finite values → ``unknown`` (never ``critical``)."""
    if not math.isfinite(max_prob):
        return "unknown"
    if max_prob < 0.30:
        return "normal"
    if max_prob < 0.50:
        return "watch"
    if max_prob < 0.70:
        return "warning"
    if max_prob < 0.85:
        return "high"
    return "critical"
