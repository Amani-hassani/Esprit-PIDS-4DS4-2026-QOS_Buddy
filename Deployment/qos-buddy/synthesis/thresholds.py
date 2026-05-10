"""
Threshold profile mirroring `monitoring/config.yaml` so the synthesis agent
reasons about the SAME limits the collector uses. Values are in real units
(ms, %, Mbps) and are tuned for the Tunisian mobile network baseline.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    # Round-trip delay
    latency_baseline_ms: float = 50.0
    latency_warning_ms: float = 150.0
    latency_critical_ms: float = 250.0
    # Delay variation
    jitter_acceptable_ms: float = 50.0
    jitter_warning_ms: float = 75.0
    jitter_critical_ms: float = 150.0
    # Packet loss
    loss_warning_pct: float = 5.0
    loss_critical_pct: float = 10.0
    # Throughput
    throughput_min_mbps: float = 0.5
    throughput_baseline_mbps: float = 3.0
    # Behavioral
    anomaly_score_warning: float = 0.4
    anomaly_score_critical: float = 0.75


THRESHOLDS = Thresholds()
