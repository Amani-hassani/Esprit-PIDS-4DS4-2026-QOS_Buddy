from __future__ import annotations


class WorkflowEngine:
    def __init__(self):
        self.logs = []

        self.qos_types = {
            "high_latency",
            "latency_degradation",
            "high_jitter",
            "jitter_degradation",
            "low_throughput",
            "poor_voice_quality",
            "congestion",
            "high_retransmission",
            "severe_packet_loss",
            "packet_loss",
        }

        self.radio_types = {
            "weak_signal",
            "weak_rsrp",
            "low_sinr",
            "handover_event",
        }

    def detect_domain(self, event: dict) -> str:
        payload = event.get("payload", {})
        anomaly_type = str(payload.get("anomaly_type", "")).strip().lower()
        reason = str(event.get("reason", "")).lower()

        qos_keywords = ["latency", "jitter", "throughput", "mos", "packet loss", "retransmission", "congestion"]
        radio_keywords = ["sinr", "rsrp", "rsrq", "handover", "ho success", "signal"]

        has_qos = anomaly_type in self.qos_types or any(k in reason for k in qos_keywords)
        has_radio = anomaly_type in self.radio_types or any(k in reason for k in radio_keywords)

        if has_qos and has_radio:
            return "mixed"
        if has_qos:
            return "qos"
        if has_radio:
            return "radio"
        return "unknown"

    def decide_targets(self, severity: str, event: dict) -> list:
        severity = str(severity).lower()
        domain = self.detect_domain(event)

        if severity == "normal":
            return []

        if domain == "qos":
            return ["Detection"]
        if domain == "radio":
            return ["Diagnostic"]
        if domain == "mixed":
            return ["Detection", "Diagnostic"]

        return ["Detection"] if severity == "warning" else ["Detection", "Diagnostic"]

    def route_event(self, event: dict) -> dict:
        severity = str(event.get("severity", "")).lower()
        targets = self.decide_targets(severity, event)
        payload = event.get("payload", {})
        health_score = payload.get("health_score", 100)
        anomaly_rate_recent = payload.get("anomaly_rate_recent")
        domain = self.detect_domain(event)

        priority = "normal"
        if severity == "critical":
            priority = "high"
        elif isinstance(health_score, (int, float)) and health_score < 60:
            priority = "high"
        elif isinstance(anomaly_rate_recent, (int, float)) and anomaly_rate_recent > 30:
            priority = "high"

        if severity == "normal":
            action = {
                "event_id": event.get("event_id"),
                "status": "logged_only",
                "targets": [],
                "domain": domain,
                "priority": "normal",
                "message": "Event logged only",
            }
        elif severity in {"warning", "critical"}:
            target_text = ", ".join(targets) if targets else "nobody"
            action = {
                "event_id": event.get("event_id"),
                "status": "routed",
                "targets": targets,
                "domain": domain,
                "priority": priority,
                "message": f"Event sent to {target_text}",
            }
        else:
            action = {
                "event_id": event.get("event_id"),
                "status": "unknown_severity",
                "targets": [],
                "domain": domain,
                "priority": "normal",
                "message": "Unknown severity, event not routed",
            }

        self.logs.append({"event": event, "action": action})
        return action

    def get_logs(self):
        return self.logs
