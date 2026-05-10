from __future__ import annotations
import json

from workflow_engine_gnn_v2 import WorkflowEngineGNNV2

engine = WorkflowEngineGNNV2(graph_window_size=4)

events = [
    {
        "event_id": "evt_1",
        "timestamp": "2026-04-05T10:00:00",
        "node_id": "N1",
        "severity": "warning",
        "reason": "high latency + low throughput",
        "payload": {
            "zone_id": "Z1",
            "cell_id": "C1",
            "latency_ms": 145,
            "jitter_ms": 36,
            "packet_loss_pct": 2,
            "throughput_mbps": 3.2,
            "mos_estimate": 3.4,
            "sinr_db": 13,
            "rsrp_dbm": -98,
            "rsrq_db": -11,
            "ho_success_rate_pct": 94,
            "anomaly_type": "latency_degradation",
            "anomaly_score": 0.62,
            "health_score": 68,
            "confidence": 0.89,
            "anomaly_rate_recent": 14,
            "signal_health_score": 61,
            "tcp_retransmit_rate": 2.2,
            "channel_util_pct": 76,
        },
    },
    {
        "event_id": "evt_2",
        "timestamp": "2026-04-05T10:01:00",
        "node_id": "N1",
        "severity": "warning",
        "reason": "high latency + high jitter + low throughput",
        "payload": {
            "zone_id": "Z1",
            "cell_id": "C1",
            "latency_ms": 170,
            "jitter_ms": 49,
            "packet_loss_pct": 3,
            "throughput_mbps": 2.6,
            "mos_estimate": 3.0,
            "sinr_db": 11,
            "rsrp_dbm": -101,
            "rsrq_db": -12,
            "ho_success_rate_pct": 93,
            "anomaly_type": "high_latency",
            "anomaly_score": 0.71,
            "health_score": 61,
            "confidence": 0.88,
            "anomaly_rate_recent": 21,
            "signal_health_score": 57,
            "tcp_retransmit_rate": 3.8,
            "channel_util_pct": 82,
        },
    },
    {
        "event_id": "evt_3",
        "timestamp": "2026-04-05T10:02:00",
        "node_id": "N1",
        "severity": "critical",
        "reason": "very high latency + very high jitter + very low throughput + low SINR",
        "payload": {
            "zone_id": "Z1",
            "cell_id": "C1",
            "latency_ms": 305,
            "jitter_ms": 116,
            "packet_loss_pct": 12,
            "throughput_mbps": 0.4,
            "mos_estimate": 2.3,
            "sinr_db": 6,
            "rsrp_dbm": -110,
            "rsrq_db": -15,
            "ho_success_rate_pct": 82,
            "anomaly_type": "severe_packet_loss",
            "anomaly_score": 0.93,
            "health_score": 28,
            "confidence": 0.85,
            "anomaly_rate_recent": 39,
            "signal_health_score": 34,
            "tcp_retransmit_rate": 8.0,
            "channel_util_pct": 91,
        },
    },
]

for e in events:
    action = engine.route_event(e)
    print("\n=== ACTION V2 ===")
    print(json.dumps(action, indent=2, ensure_ascii=False))
