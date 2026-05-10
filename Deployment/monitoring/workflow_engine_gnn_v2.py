from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from math import isnan
from typing import Any, Deque, Dict, List, Optional, Tuple


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        x = float(v)
        if isnan(x):
            return None
        return x
    except Exception:
        return None


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _risk_high(value: Optional[float], warn: float, critical: float) -> float:
    if value is None:
        return 0.0
    if critical <= warn:
        return 1.0 if value >= critical else 0.0
    if value <= warn:
        return 0.0
    if value >= critical:
        return 1.0
    return _clamp((value - warn) / (critical - warn))


def _risk_low(value: Optional[float], warn: float, critical: float) -> float:
    if value is None:
        return 0.0
    if critical >= warn:
        return 1.0 if value <= critical else 0.0
    if value >= warn:
        return 0.0
    if value <= critical:
        return 1.0
    return _clamp((warn - value) / (warn - critical))


@dataclass
class GraphNode:
    node_key: str
    node_type: str
    features: Dict[str, Any]
    timestamp: str


@dataclass
class GraphEdge:
    source: str
    target: str
    relation: str
    weight: float


class LightweightGraphEncoder:
    """
    Encodeur graphe léger sans dépendances externes.
    - embedding = vecteur de risques bornés
    - 1 passe de message passing pondérée
    - sortie: graph_score et embeddings
    """

    FEATURE_KEYS = [
        "latency_ms",
        "jitter_ms",
        "packet_loss_pct",
        "throughput_mbps",
        "mos_estimate",
        "sinr_db",
        "rsrp_dbm",
        "rsrq_db",
        "ho_success_rate_pct",
        "anomaly_score",
        "health_score",
        "confidence",
        "anomaly_rate_recent",
        "signal_health_score",
        "tcp_retransmit_rate",
        "channel_util_pct",
    ]

    def _node_vector(self, features: Dict[str, Any]) -> List[float]:
        return [
            _risk_high(_safe_float(features.get("latency_ms")), 120.0, 250.0),
            _risk_high(_safe_float(features.get("jitter_ms")), 40.0, 100.0),
            _risk_high(_safe_float(features.get("packet_loss_pct")), 5.0, 10.0),
            _risk_low(_safe_float(features.get("throughput_mbps")), 5.0, 1.0),
            _risk_low(_safe_float(features.get("mos_estimate")), 3.5, 2.5),
            _risk_low(_safe_float(features.get("sinr_db")), 15.0, 8.0),
            _risk_low(_safe_float(features.get("rsrp_dbm")), -95.0, -110.0),
            _risk_low(_safe_float(features.get("rsrq_db")), -10.0, -15.0),
            _risk_low(_safe_float(features.get("ho_success_rate_pct")), 95.0, 80.0),
            _clamp(_safe_float(features.get("anomaly_score")) or 0.0),
            _risk_low(_safe_float(features.get("health_score")), 80.0, 50.0),
            _risk_low(_safe_float(features.get("confidence")), 0.75, 0.45),
            _risk_high(_safe_float(features.get("anomaly_rate_recent")), 20.0, 40.0),
            _risk_low(_safe_float(features.get("signal_health_score")), 60.0, 40.0),
            _risk_high(_safe_float(features.get("tcp_retransmit_rate")), 2.0, 5.0),
            _risk_high(_safe_float(features.get("channel_util_pct")), 70.0, 85.0),
        ]

    def encode(self, nodes: List[GraphNode], edges: List[GraphEdge]) -> Dict[str, Any]:
        embeddings: Dict[str, List[float]] = {}
        for node in nodes:
            embeddings[node.node_key] = self._node_vector(node.features)

        neighbors: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        for edge in edges:
            neighbors[edge.source].append((edge.target, edge.weight))
            neighbors[edge.target].append((edge.source, edge.weight))

        new_embeddings: Dict[str, List[float]] = {}
        for node in nodes:
            base = embeddings[node.node_key]
            neigh = neighbors.get(node.node_key, [])
            if not neigh:
                new_embeddings[node.node_key] = base
                continue

            agg = [0.0] * len(base)
            total_w = 0.0
            for other_key, weight in neigh:
                other = embeddings.get(other_key, [0.0] * len(base))
                for index, value in enumerate(other):
                    agg[index] += value * weight
                total_w += weight

            if total_w > 0:
                agg = [value / total_w for value in agg]

            mixed = [(0.82 * base_value) + (0.18 * agg_value) for base_value, agg_value in zip(base, agg)]
            new_embeddings[node.node_key] = mixed

        node_scores: Dict[str, float] = {}
        for node_key, vec in new_embeddings.items():
            score = 0.0
            score += 0.16 * vec[0]   # latency
            score += 0.10 * vec[1]   # jitter
            score += 0.16 * vec[2]   # packet loss
            score += 0.18 * vec[3]   # low throughput
            score += 0.08 * vec[4]   # low MOS
            score += 0.06 * vec[5]   # low SINR
            score += 0.05 * vec[6]   # low RSRP
            score += 0.04 * vec[7]   # low RSRQ
            score += 0.04 * vec[8]   # low HO success
            score += 0.08 * vec[9]   # anomaly score
            score += 0.12 * vec[10]  # low health
            score += 0.04 * vec[11]  # low confidence
            score += 0.09 * vec[12]  # anomaly rate recent
            score += 0.06 * vec[13]  # low signal health
            score += 0.10 * vec[14]  # retransmit
            score += 0.08 * vec[15]  # channel util
            node_scores[node_key] = round(score, 4)

        graph_score = round(sum(node_scores.values()) / max(len(node_scores), 1), 4)

        return {
            "graph_score": graph_score,
            "node_scores": node_scores,
            "node_embeddings": new_embeddings,
        }


class WorkflowEngineGNNV2:
    """
    V2 du Workflow Engine:
    - garde une fenêtre récente d'événements
    - transforme la fenêtre en graphe
    - encode le graphe
    - route non seulement un event mais un graph_packet
    """

    def __init__(self, graph_window_size: int = 6):
        self.logs: List[Dict[str, Any]] = []
        self.graph_window_size = graph_window_size
        self.node_history: Dict[str, Deque[Dict[str, Any]]] = defaultdict(lambda: deque(maxlen=self.graph_window_size))
        self.encoder = LightweightGraphEncoder()

        self.qos_types = {
            "high_latency", "latency_degradation", "high_jitter", "jitter_degradation",
            "low_throughput", "poor_voice_quality", "congestion", "high_retransmission",
            "severe_packet_loss", "packet_loss",
        }
        self.radio_types = {
            "weak_signal", "weak_rsrp", "low_sinr", "handover_event",
        }

    def detect_domain(self, event: Dict[str, Any]) -> str:
        payload = event.get("payload", {})
        declared_domain = str(event.get("domain") or payload.get("domain") or "").strip().lower()
        if declared_domain in {"qos", "radio", "mixed", "unknown"}:
            return declared_domain

        anomaly_type = str(payload.get("anomaly_type", "")).strip().lower()
        reason = str(event.get("reason", "")).lower()

        qos_keywords = ["latency", "jitter", "throughput", "mos", "packet loss", "retransmission", "congestion"]
        radio_keywords = ["sinr", "rsrp", "rsrq", "handover", "ho success", "signal", "wifi", "rssi", "cqi"]

        has_qos = anomaly_type in self.qos_types or any(keyword in reason for keyword in qos_keywords)
        has_radio = anomaly_type in self.radio_types or any(keyword in reason for keyword in radio_keywords)

        if has_qos and has_radio:
            return "mixed"
        if has_qos:
            return "qos"
        if has_radio:
            return "radio"
        return "unknown"

    def decide_targets(self, event: Dict[str, Any], graph_score: float, domain: str) -> List[str]:
        severity = str(event.get("severity", "")).lower()

        if severity == "normal" and graph_score < 0.45:
            return []

        if domain == "qos":
            return ["Detection"] if severity in {"warning", "critical"} or graph_score >= 0.55 else []
        if domain == "radio":
            return ["Diagnostic"] if severity in {"warning", "critical"} or graph_score >= 0.55 else []
        if domain == "mixed":
            return ["Detection", "Diagnostic"] if severity != "normal" or graph_score >= 0.60 else []

        if severity == "critical" or graph_score >= 1.10:
            return ["Detection", "Diagnostic"]
        if severity == "warning" or graph_score >= 0.70:
            return ["Detection"]
        return []

    def _event_node(self, event: Dict[str, Any]) -> GraphNode:
        payload = event.get("payload", {})
        node_id = str(event.get("node_id", "unknown"))
        ts = str(event.get("timestamp", ""))

        features = {
            "severity": event.get("severity"),
            "domain": event.get("domain"),
            "reason": event.get("reason"),
            "zone_id": payload.get("zone_id"),
            "cell_id": payload.get("cell_id"),
            "device_type": payload.get("device_type"),
            "latency_ms": payload.get("latency_ms"),
            "jitter_ms": payload.get("jitter_ms"),
            "packet_loss_pct": payload.get("packet_loss_pct"),
            "throughput_mbps": payload.get("throughput_mbps"),
            "mos_estimate": payload.get("mos_estimate"),
            "sinr_db": payload.get("sinr_db"),
            "rsrp_dbm": payload.get("rsrp_dbm"),
            "rsrq_db": payload.get("rsrq_db"),
            "ho_success_rate_pct": payload.get("ho_success_rate_pct"),
            "anomaly_score": payload.get("anomaly_score"),
            "health_score": payload.get("health_score"),
            "confidence": payload.get("confidence"),
            "anomaly_rate_recent": payload.get("anomaly_rate_recent"),
            "signal_health_score": payload.get("signal_health_score"),
            "tcp_retransmit_rate": payload.get("tcp_retransmit_rate"),
            "channel_util_pct": payload.get("channel_util_pct"),
        }
        return GraphNode(
            node_key=f"{node_id}@{ts}",
            node_type="event_snapshot",
            features=features,
            timestamp=ts,
        )

    def _build_graph(self, event: Dict[str, Any]) -> Tuple[List[GraphNode], List[GraphEdge]]:
        node_id = str(event.get("node_id", "unknown"))
        history = list(self.node_history[node_id])

        nodes: List[GraphNode] = []
        edges: List[GraphEdge] = []

        current_node = self._event_node(event)
        nodes.append(current_node)

        prev_key = current_node.node_key
        zone_cur = event.get("payload", {}).get("zone_id")
        cell_cur = event.get("payload", {}).get("cell_id")

        for old_event in reversed(history):
            old_node = self._event_node(old_event)
            nodes.append(old_node)

            edges.append(GraphEdge(
                source=prev_key,
                target=old_node.node_key,
                relation="temporal_same_node",
                weight=0.45,
            ))
            prev_key = old_node.node_key

            zone_old = old_event.get("payload", {}).get("zone_id")
            cell_old = old_event.get("payload", {}).get("cell_id")
            if zone_cur and zone_old and zone_cur == zone_old:
                edges.append(GraphEdge(
                    source=current_node.node_key,
                    target=old_node.node_key,
                    relation="same_zone",
                    weight=0.15,
                ))
            if cell_cur and cell_old and cell_cur == cell_old:
                edges.append(GraphEdge(
                    source=current_node.node_key,
                    target=old_node.node_key,
                    relation="same_cell",
                    weight=0.20,
                ))

        return nodes, edges

    def _priority_from(self, event: Dict[str, Any], graph_score: float) -> str:
        severity = str(event.get("severity", "")).lower()
        payload = event.get("payload", {})
        health_score = payload.get("health_score", 100)
        anomaly_rate_recent = payload.get("anomaly_rate_recent", 0)

        if severity == "critical" or graph_score >= 1.10:
            return "high"
        if isinstance(health_score, (int, float)) and health_score < 45:
            return "high"
        if isinstance(anomaly_rate_recent, (int, float)) and anomaly_rate_recent > 60:
            return "high"
        if severity == "warning" or graph_score >= 0.70:
            return "medium"
        if isinstance(health_score, (int, float)) and health_score < 70:
            return "medium"
        if isinstance(anomaly_rate_recent, (int, float)) and anomaly_rate_recent > 25:
            return "medium"
        return "normal"

    def route_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        node_id = str(event.get("node_id", "unknown"))
        domain = self.detect_domain(event)

        nodes, edges = self._build_graph(event)
        encoded = self.encoder.encode(nodes, edges)
        graph_score = encoded["graph_score"]
        targets = self.decide_targets(event, graph_score, domain)
        priority = self._priority_from(event, graph_score)

        graph_packet = {
            "packet_type": "GraphWorkflowPacket",
            "event_id": event.get("event_id"),
            "node_id": node_id,
            "timestamp": event.get("timestamp"),
            "severity": event.get("severity"),
            "domain": domain,
            "priority": priority,
            "graph": {
                "nodes": [asdict(node) for node in nodes],
                "edges": [asdict(edge) for edge in edges],
                "graph_score": graph_score,
                "node_scores": encoded["node_scores"],
            },
            "targets": targets,
            "message": "Graph packet ready for downstream agents" if targets else "No routing target for this graph packet",
        }

        action = {
            "event_id": event.get("event_id"),
            "status": "logged_only" if not targets else "graph_routed",
            "targets": targets,
            "domain": domain,
            "priority": priority,
            "graph_score": graph_score,
            "message": graph_packet["message"],
            "graph_packet": graph_packet,
        }

        self.logs.append({"event": event, "action": action})
        self.node_history[node_id].append(event)
        return action

    def get_logs(self) -> List[Dict[str, Any]]:
        return self.logs