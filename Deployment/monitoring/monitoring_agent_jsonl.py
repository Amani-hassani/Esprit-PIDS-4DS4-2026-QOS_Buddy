from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set
import math


class MonitoringAgent:
    """
    Monitoring Agent relié à un collecteur temps réel.

    Idée:
    - utiliser un noyau réduit de KPI pour décider l'état du réseau
    - conserver aussi les KPI radio / Wi-Fi utiles au diagnostic dans le payload
    """

    CORE_METRICS = [
        "latency_ms", "jitter_ms", "packet_loss_pct", "throughput_mbps",
        "mos_estimate", "rsrp_dbm", "rsrq_db", "sinr_db",
        "channel_util_pct", "ho_success_rate_pct", "anomaly_score"
    ]

    OPTIONAL_METRICS = [
        "latency_rolling_mean", "latency_rolling_std", "latency_trend", "latency_volatility",
        "jitter_rolling_mean", "jitter_rolling_std", "jitter_increasing",
        "throughput_rolling_mean", "throughput_rolling_std", "throughput_volatility",
        "signal_health_score", "signal_health_overall",
        "data_completeness_pct", "required_metrics_pct", "router_metrics_pct",
        "data_quality_rating", "data_quality_issues",
        "collection_completion_pct", "anomaly_rate_recent",
        "signal_degradation_rate", "incident_recovery_time",
        "teams_in_meeting", "tcp_retransmit_rate", "cssr_proxy_pct"
    ]

    DIAGNOSTIC_METRICS = [
        "zone_id", "cell_id", "device_type",
        "cpu_pct", "memory_pct", "active_connections",
        "traffic_type", "traffic_confidence", "detection_method",
        "rssi_dbm", "signal_quality_pct", "rx_link_mbps",
        "channel", "bssid", "connected_stations",
        "pci", "cqi", "earfcn", "mcs",
        "network_type_router", "cell_id_router", "timing_advance",
        "bler_proxy_pct", "bler_delta", "bler_trend", "bler_severity",
        "wifi_signal_category", "wifi_signal_score",
        "cellular_signal_category", "cellular_signal_score",
        "data_source", "day_of_week", "hour_of_day"
    ]

    REQUIRED_INPUT_KEYS = ["timestamp", "node_id"]

    QOS_TYPES = {
        "high_latency", "latency_degradation", "high_jitter", "jitter_degradation",
        "low_throughput", "poor_voice_quality", "congestion", "high_retransmission",
        "severe_packet_loss", "packet_loss"
    }
    RADIO_TYPES = {"weak_signal", "weak_rsrp", "low_sinr", "handover_event"}

    def __init__(self, window_size: int = 5, warning_escalation_count: int = 3) -> None:
        self.window_size = window_size
        self.warning_escalation_count = warning_escalation_count
        self.history = defaultdict(lambda: deque(maxlen=self.window_size))
        self.warning_streak = defaultdict(int)
        self.event_counter = 0

    def _to_dict(self, row: Any) -> Dict[str, Any]:
        if isinstance(row, dict):
            return dict(row)
        if hasattr(row, "to_dict"):
            return row.to_dict()
        raise TypeError("row must be dict-like")

    def _num(self, value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            if isinstance(value, str) and not value.strip():
                return None
            v = float(value)
            if math.isnan(v):
                return None
            return v
        except Exception:
            return None

    def _bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "y"}

    def _has_text_value(self, value: Any) -> bool:
        if value is None:
            return False
        text = str(value).strip().lower()
        return text not in {"", "none", "null", "n/a", "na", "unknown", "unavailable"}

    def _context_signals(self, row: Dict[str, Any]) -> Dict[str, bool]:
        source = str(row.get("data_source", "")).strip().lower()
        network_type = str(row.get("network_type_router", "")).strip().lower()
        wifi_hits = 0
        cellular_hits = 0

        if self._num(row.get("rssi_dbm")) is not None:
            wifi_hits += 2
        if self._has_text_value(row.get("channel")):
            wifi_hits += 1
        if self._has_text_value(row.get("bssid")):
            wifi_hits += 1
        if self._num(row.get("connected_stations")) is not None:
            wifi_hits += 1
        if self._num(row.get("rx_link_mbps")) is not None:
            wifi_hits += 1
        if self._has_text_value(row.get("wifi_signal_category")):
            wifi_hits += 1
        wifi_signal_score = self._num(row.get("wifi_signal_score"))
        if wifi_signal_score is not None and wifi_signal_score > 0:
            wifi_hits += 1
        if source == "wifi":
            wifi_hits += 2

        if self._num(row.get("sinr_db")) is not None:
            cellular_hits += 2
        if self._num(row.get("rsrp_dbm")) is not None:
            cellular_hits += 2
        if self._num(row.get("rsrq_db")) is not None:
            cellular_hits += 2
        for key in ("cqi", "mcs", "pci", "earfcn", "timing_advance"):
            if self._num(row.get(key)) is not None:
                cellular_hits += 1
        if self._has_text_value(row.get("cell_id_router")):
            cellular_hits += 1
        if self._has_text_value(row.get("cellular_signal_category")):
            cellular_hits += 1
        cellular_signal_score = self._num(row.get("cellular_signal_score"))
        if cellular_signal_score is not None and cellular_signal_score > 0:
            cellular_hits += 1
        if any(tag in network_type for tag in ("5g", "4g", "lte", "nr", "3g", "umts")):
            cellular_hits += 2
        if source in {"cellular", "router", "modem"}:
            cellular_hits += 2

        has_wifi = wifi_hits > 0
        has_cellular = cellular_hits > 0
        has_ho_context = has_cellular and (
            self._num(row.get("sinr_db")) is not None
            or self._num(row.get("rsrp_dbm")) is not None
            or self._num(row.get("rsrq_db")) is not None
            or self._num(row.get("cqi")) is not None
            or self._num(row.get("mcs")) is not None
            or self._has_text_value(row.get("network_type_router"))
            or self._has_text_value(row.get("cell_id_router"))
        )

        return {
            "wifi": has_wifi,
            "cellular": has_cellular,
            "mixed": has_wifi and has_cellular,
            "none": not has_wifi and not has_cellular,
            "ho_context": has_ho_context,
        }

    def validate_row(self, row: Dict[str, Any]) -> None:
        for key in self.REQUIRED_INPUT_KEYS:
            if row.get(key) in (None, ""):
                raise ValueError(f"Champ obligatoire manquant: {key}")

    def smooth_with_window(self, node_id: str) -> Dict[str, Optional[float]]:
        rows = list(self.history[node_id])
        if not rows:
            return {}
        keys = [
            "latency_ms", "jitter_ms", "packet_loss_pct", "throughput_mbps",
            "mos_estimate", "sinr_db", "ho_success_rate_pct", "rssi_dbm", "rsrp_dbm", "rsrq_db"
        ]
        out = {}
        for key in keys:
            vals = [self._num(r.get(key)) for r in rows]
            vals = [v for v in vals if v is not None]
            out[key] = round(sum(vals) / len(vals), 2) if vals else None
        return out

    def compute_health_score(self, row: Dict[str, Any]) -> int:
        score = 100
        context = self._context_signals(row)
        has_wifi = context["wifi"]
        has_cellular = context["cellular"]
        has_ho_context = context["ho_context"]
        has_signal_context = has_wifi or has_cellular

        latency = self._num(row.get("latency_ms"))
        jitter = self._num(row.get("jitter_ms"))
        packet_loss = self._num(row.get("packet_loss_pct"))
        throughput = self._num(row.get("throughput_mbps"))
        mos = self._num(row.get("mos_estimate"))
        sinr = self._num(row.get("sinr_db"))
        rsrp = self._num(row.get("rsrp_dbm"))
        rsrq = self._num(row.get("rsrq_db"))
        ho = self._num(row.get("ho_success_rate_pct"))
        signal_health = self._num(row.get("signal_health_score"))
        anomaly_rate_recent = self._num(row.get("anomaly_rate_recent"))
        retransmit = self._num(row.get("tcp_retransmit_rate"))
        rssi = self._num(row.get("rssi_dbm"))
        channel_util = self._num(row.get("channel_util_pct"))
        connected_stations = self._num(row.get("connected_stations"))
        cqi = self._num(row.get("cqi"))

        if latency is not None:
            score -= 20 if latency > 250 else 10 if latency > 120 else 0
        if jitter is not None:
            score -= 18 if jitter > 100 else 9 if jitter > 40 else 0
        if packet_loss is not None:
            score -= 25 if packet_loss > 10 else 12 if packet_loss > 5 else 0
        if throughput is not None:
            score -= 20 if throughput < 1 else 10 if throughput < 5 else 0
        if mos is not None:
            score -= 15 if mos < 2.5 else 8 if mos < 3.5 else 0

        if has_cellular and sinr is not None:
            score -= 15 if sinr < 8 else 8 if sinr < 15 else 0
        if has_cellular and rsrp is not None:
            score -= 8 if rsrp < -110 else 4 if rsrp < -95 else 0
        if has_cellular and rsrq is not None:
            score -= 8 if rsrq < -15 else 4 if rsrq < -10 else 0
        if has_ho_context and ho is not None:
            score -= 12 if ho < 80 else 6 if ho < 95 else 0
        if has_cellular and cqi is not None:
            score -= 6 if cqi < 5 else 3 if cqi < 9 else 0

        if has_signal_context and signal_health is not None:
            score -= 10 if signal_health < 40 else 5 if signal_health < 60 else 0

        if anomaly_rate_recent is not None:
            score -= 10 if anomaly_rate_recent > 40 else 5 if anomaly_rate_recent > 20 else 0
        if retransmit is not None:
            score -= 10 if retransmit > 5 else 5 if retransmit > 2 else 0

        if has_wifi and rssi is not None:
            score -= 8 if rssi < -80 else 4 if rssi < -67 else 0
        if has_wifi and channel_util is not None:
            score -= 8 if channel_util > 85 else 4 if channel_util > 70 else 0
        if has_wifi and connected_stations is not None:
            score -= 5 if connected_stations > 35 else 2 if connected_stations > 20 else 0

        return max(int(score), 0)

    def compute_confidence(self, row: Dict[str, Any]) -> float:
        completeness = self._num(row.get("data_completeness_pct"))
        required = self._num(row.get("required_metrics_pct"))
        collection = self._num(row.get("collection_completion_pct"))
        quality = str(row.get("data_quality_rating", "")).strip().lower()
        router_metrics_pct = self._num(row.get("router_metrics_pct"))

        conf = 0.85
        if completeness is not None:
            conf *= completeness / 100.0
        if required is not None:
            conf *= required / 100.0
        if collection is not None:
            conf *= max(0.5, collection / 100.0)
        if router_metrics_pct is not None:
            conf *= max(0.75, router_metrics_pct / 100.0)

        if quality in {"poor", "bad", "low"}:
            conf *= 0.65
        elif quality in {"fair", "medium"}:
            conf *= 0.85
        elif quality in {"good", "high", "excellent"}:
            conf *= 1.0

        return round(min(max(conf, 0.05), 0.99), 2)

    def classify_severity(self, health_score: int, row: Dict[str, Any]) -> str:
        severity = "normal"
        if health_score < 50:
            severity = "critical"
        elif health_score < 80:
            severity = "warning"

        packet_loss = self._num(row.get("packet_loss_pct"))
        anomaly_type = str(row.get("anomaly_type", "")).strip().lower()
        sinr = self._num(row.get("sinr_db"))
        throughput = self._num(row.get("throughput_mbps"))

        if packet_loss is not None and packet_loss > 10:
            severity = "critical"
        if anomaly_type == "severe_packet_loss":
            severity = "critical"
        if sinr is not None and sinr < 5 and throughput is not None and throughput < 1:
            severity = "critical"

        return severity

    def build_reason_list(self, row: Dict[str, Any]) -> List[str]:
        reasons: List[str] = []
        context = self._context_signals(row)
        has_wifi = context["wifi"]
        has_cellular = context["cellular"]
        has_ho_context = context["ho_context"]
        has_signal_context = has_wifi or has_cellular

        latency = self._num(row.get("latency_ms"))
        jitter = self._num(row.get("jitter_ms"))
        packet_loss = self._num(row.get("packet_loss_pct"))
        throughput = self._num(row.get("throughput_mbps"))
        mos = self._num(row.get("mos_estimate"))
        sinr = self._num(row.get("sinr_db"))
        rsrp = self._num(row.get("rsrp_dbm"))
        rsrq = self._num(row.get("rsrq_db"))
        ho = self._num(row.get("ho_success_rate_pct"))
        latency_trend = self._num(row.get("latency_trend"))
        anomaly_rate_recent = self._num(row.get("anomaly_rate_recent"))
        signal_degradation_rate = self._num(row.get("signal_degradation_rate"))
        retransmit = self._num(row.get("tcp_retransmit_rate"))
        rssi = self._num(row.get("rssi_dbm"))
        channel_util = self._num(row.get("channel_util_pct"))
        connected_stations = self._num(row.get("connected_stations"))
        cqi = self._num(row.get("cqi"))
        mcs = self._num(row.get("mcs"))

        if packet_loss is not None:
            reasons.append("severe packet loss" if packet_loss > 10 else "packet loss" if packet_loss > 5 else "")
        if latency is not None:
            reasons.append("very high latency" if latency > 250 else "high latency" if latency > 120 else "")
        if jitter is not None:
            reasons.append("very high jitter" if jitter > 100 else "high jitter" if jitter > 40 else "")
        if throughput is not None:
            reasons.append("very low throughput" if throughput < 1 else "low throughput" if throughput < 5 else "")
        if mos is not None:
            reasons.append("very low MOS" if mos < 2.5 else "low MOS" if mos < 3.5 else "")
        if latency_trend is not None and latency_trend > 40:
            reasons.append("latency rising")
        if self._bool(row.get("jitter_increasing")):
            reasons.append("jitter worsening")
        if anomaly_rate_recent is not None and anomaly_rate_recent > 30:
            reasons.append("repeated anomalies")
        if retransmit is not None:
            reasons.append("high retransmission" if retransmit > 5 else "retransmission" if retransmit > 2 else "")

        if has_cellular and sinr is not None:
            reasons.append("very low SINR" if sinr < 8 else "low SINR" if sinr < 15 else "")
        if has_cellular and rsrp is not None:
            reasons.append("weak RSRP" if rsrp < -95 else "")
        if has_cellular and rsrq is not None:
            reasons.append("weak RSRQ" if rsrq < -10 else "")
        if has_ho_context and ho is not None:
            reasons.append("very low HO success" if ho < 80 else "low HO success" if ho < 95 else "")
        if has_signal_context and signal_degradation_rate is not None and signal_degradation_rate > 20:
            reasons.append("signal degrading")
        if has_cellular and cqi is not None:
            reasons.append("low CQI" if cqi < 7 else "")
        if has_cellular and mcs is not None:
            reasons.append("low MCS" if mcs < 4 else "")

        if has_wifi and rssi is not None:
            reasons.append("weak Wi-Fi RSSI" if rssi < -75 else "")
        if has_wifi and channel_util is not None:
            reasons.append("channel congestion" if channel_util > 80 else "")
        if has_wifi and connected_stations is not None:
            reasons.append("many connected stations" if connected_stations > 25 else "")

        quality = str(row.get("data_quality_rating", "")).strip().lower()
        if quality in {"poor", "bad", "low"}:
            reasons.append("low data quality")
        if self._bool(row.get("teams_in_meeting")):
            reasons.append("active meeting context")

        anomaly_type = str(row.get("anomaly_type", "")).strip().lower()
        qos_reason_map = {
            "severe_packet_loss": "detected severe packet loss",
            "packet_loss": "detected packet loss",
            "high_retransmission": "high retransmission",
            "congestion": "channel congestion",
            "latency_degradation": "latency degradation",
            "jitter_degradation": "jitter degradation",
            "high_latency": "detected high latency",
            "high_jitter": "detected high jitter",
            "low_throughput": "detected low throughput",
        }
        radio_reason_map = {
            "weak_rsrp": "weak RSRP",
            "low_sinr": "low SINR",
            "handover_event": "handover event",
            "weak_signal": "weak cellular signal",
        }

        if anomaly_type in qos_reason_map:
            reasons.append(qos_reason_map[anomaly_type])
        elif has_cellular and anomaly_type in radio_reason_map:
            reasons.append(radio_reason_map[anomaly_type])

        dedup: List[str] = []
        for reason in reasons:
            item = reason.strip()
            if item and item not in dedup:
                dedup.append(item)

        return dedup or ["healthy state"]

    def detect_domain(self, row: Dict[str, Any], reasons: List[str]) -> str:
        anomaly_type = str(row.get("anomaly_type", "")).strip().lower()
        text = " ".join(reasons).lower()
        context = self._context_signals(row)
        has_wifi_context = context["wifi"]
        has_cellular_context = context["cellular"]
        has_ho_context = context["ho_context"]

        qos_keywords = {"latency", "jitter", "throughput", "mos", "packet loss", "retransmission", "congestion"}
        radio_keywords = {"sinr", "rsrp", "rsrq", "handover", "ho success", "cqi", "mcs", "pci", "earfcn", "cellular signal"}
        wifi_keywords = {"wifi", "wi-fi", "rssi", "channel congestion", "bssid", "stations"}

        has_qos = anomaly_type in self.QOS_TYPES or any(k in text for k in qos_keywords)

        sinr = self._num(row.get("sinr_db"))
        rsrp = self._num(row.get("rsrp_dbm"))
        rsrq = self._num(row.get("rsrq_db"))
        ho = self._num(row.get("ho_success_rate_pct"))
        cqi = self._num(row.get("cqi"))
        rssi = self._num(row.get("rssi_dbm"))
        channel_util = self._num(row.get("channel_util_pct"))
        connected_stations = self._num(row.get("connected_stations"))

        cellular_issue = False
        if has_cellular_context:
            cellular_issue = (
                anomaly_type in self.RADIO_TYPES
                or any(k in text for k in radio_keywords)
                or (sinr is not None and sinr < 15)
                or (rsrp is not None and rsrp < -95)
                or (rsrq is not None and rsrq < -10)
                or (cqi is not None and cqi < 7)
                or (has_ho_context and ho is not None and ho < 95)
            )

        wifi_issue = False
        if has_wifi_context:
            wifi_issue = (
                any(k in text for k in wifi_keywords)
                or (rssi is not None and rssi < -75)
                or (channel_util is not None and channel_util > 80)
                or (connected_stations is not None and connected_stations > 25)
            )

        if has_qos and (cellular_issue or wifi_issue):
            return "mixed"
        if has_qos:
            return "qos"
        if cellular_issue or wifi_issue:
            return "radio"
        return "unknown"

    def build_event(self, row: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_row(row)
        node_id = str(row.get("node_id", "unknown"))
        self.history[node_id].append(row)

        reasons = self.build_reason_list(row)
        health_score = self.compute_health_score(row)
        confidence = self.compute_confidence(row)
        severity = self.classify_severity(health_score, row)

        if severity == "warning":
            self.warning_streak[node_id] += 1
            if self.warning_streak[node_id] >= self.warning_escalation_count:
                severity = "critical"
                if "warning escalation" not in reasons:
                    reasons.append("warning escalation")
        elif severity == "critical":
            self.warning_streak[node_id] = 0
        else:
            self.warning_streak[node_id] = 0

        domain = self.detect_domain(row, reasons)
        smoothed = self.smooth_with_window(node_id)

        self.event_counter += 1
        payload: Dict[str, Any] = {}
        for key in self.CORE_METRICS + self.OPTIONAL_METRICS + self.DIAGNOSTIC_METRICS + ["anomaly_type", "anomaly_flag"]:
            if key in row:
                payload[key] = row.get(key)

        payload.update({
            "health_score": health_score,
            "confidence": confidence,
            "domain": domain,
            "warning_streak": self.warning_streak[node_id],
            "window_avg_latency_ms": smoothed.get("latency_ms"),
            "window_avg_jitter_ms": smoothed.get("jitter_ms"),
            "window_avg_packet_loss_pct": smoothed.get("packet_loss_pct"),
            "window_avg_throughput_mbps": smoothed.get("throughput_mbps"),
            "window_avg_mos_estimate": smoothed.get("mos_estimate"),
            "window_avg_sinr_db": smoothed.get("sinr_db"),
            "window_avg_rsrp_dbm": smoothed.get("rsrp_dbm"),
            "window_avg_rsrq_db": smoothed.get("rsrq_db"),
            "window_avg_ho_success_rate_pct": smoothed.get("ho_success_rate_pct"),
            "window_avg_rssi_dbm": smoothed.get("rssi_dbm"),
        })

        return {
            "event_id": f"evt_{self.event_counter}",
            "event_type": "MonitoringAlertRaised",
            "timestamp": str(row.get("timestamp")),
            "node_id": node_id,
            "severity": severity,
            "reason": " + ".join(reasons),
            "domain": domain,
            "payload": payload,
        }

    def process_row(self, row: Any) -> Dict[str, Any]:
        row_dict = self._to_dict(row)
        return self.build_event(row_dict)