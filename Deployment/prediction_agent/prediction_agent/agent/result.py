"""Structured standalone prediction output for the QoS Buddy platform."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


@dataclass
class PredictionResult:
    node_id: str
    timestamp: str
    risk_probs: Dict[str, float]
    capacity_exhaustion_eta_min: float
    severity: str
    shap_features: Dict[str, List[Dict[str, Any]]]
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
    top_3_drivers: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    recommended_action: str = ""
    margins_per_metric: Dict[str, float] = field(default_factory=dict)
    highest_margin_metric: str = ""
    highest_margin_value: float = 0.0
    decision_thresholds_used: Dict[str, float] = field(default_factory=dict)

    # Standalone production fields
    llm_summary: str = ""
    operator_brief: str = ""
    confidence_score: float = 0.0
    trust_signals: Dict[str, Any] = field(default_factory=dict)
    temporal_signals: Dict[str, Any] = field(default_factory=dict)
    domain_hints: List[Dict[str, Any]] = field(default_factory=list)
    evidence_summary: Dict[str, Any] = field(default_factory=dict)
    fleet_context: Dict[str, Any] = field(default_factory=dict)
    model_metadata: Dict[str, Any] = field(default_factory=dict)
    data_quality: Dict[str, Any] = field(default_factory=dict)
    llm_used: bool = False
    database_id: int | None = None
    feedback_summary: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.primary_metric_name and self.top_3_drivers:
            self.top_3_drivers = {
                self.primary_metric_name: self.top_3_drivers.get(self.primary_metric_name, [])
            }
        self.confidence_score = float(max(0.0, min(1.0, self.confidence_score)))

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    @staticmethod
    def reformat_features_to_target_grouped(
        flat_features: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for item in flat_features:
            target = item.get("target", "unknown")
            grouped.setdefault(target, []).append(
                {
                    "feature": item.get("feature"),
                    "value": item.get("value"),
                    "direction": item.get("direction"),
                }
            )
        return grouped


def severity_from_max_risk(max_prob: float) -> str:
    """Map max probability to a band. Non-finite values -> ``unknown``."""
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
