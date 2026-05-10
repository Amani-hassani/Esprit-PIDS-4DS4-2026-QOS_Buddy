from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

from shared_jsonl_bus import JSONLBus


class SafeTextStream:
    """Proxy de flux texte tolérant aux consoles Windows en cp1252."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def write(self, data: str) -> int:
        text = str(data)
        try:
            return self._stream.write(text)
        except UnicodeEncodeError:
            encoding = getattr(self._stream, "encoding", None) or "utf-8"
            safe_text = text.encode(encoding, errors="backslashreplace").decode(encoding, errors="ignore")
            return self._stream.write(safe_text)

    def flush(self) -> None:
        try:
            self._stream.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        try:
            return bool(self._stream.isatty())
        except Exception:
            return False

    def fileno(self) -> int:
        return self._stream.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self._stream, "encoding", None) or "utf-8"

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def _reconfigure_stream(stream: Any) -> Any:
    try:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
    return SafeTextStream(stream)


sys.stdout = _reconfigure_stream(sys.stdout)
sys.stderr = _reconfigure_stream(sys.stderr)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

if os.name == "nt":
    try:
        subprocess.run(
            ["chcp", "65001"],
            capture_output=True,
            check=False,
            shell=True,
        )
    except Exception:
        pass


# Permet d'importer le projet extrait ghassen/qos_buddy
CURRENT_DIR = Path(__file__).resolve().parent
GHASSEN_ROOT = CURRENT_DIR / "ghassen"
if str(GHASSEN_ROOT) not in sys.path and GHASSEN_ROOT.exists():
    sys.path.insert(0, str(GHASSEN_ROOT))

from qos_buddy.collector import QoSBuddyCollector  # type: ignore
from qos_buddy.config import TunisianNetworkConfig, setup_logging  # type: ignore

logger = logging.getLogger("ScraperProducer")

# KPI publiés vers le monitoring: essentiels + diagnostic avancé
ALLOWED_KPI = {
    "timestamp", "zone_id", "cell_id", "node_id", "device_type",
    "latency_ms", "jitter_ms", "packet_loss_pct", "throughput_mbps",
    "mos_estimate", "rsrp_dbm", "rsrq_db", "sinr_db", "channel_util_pct",
    "ho_success_rate_pct", "anomaly_score", "latency_rolling_mean",
    "latency_rolling_std", "latency_trend", "latency_volatility",
    "jitter_rolling_mean", "jitter_rolling_std", "jitter_increasing",
    "throughput_rolling_mean", "throughput_rolling_std", "throughput_volatility",
    "signal_health_score", "signal_health_overall", "data_completeness_pct",
    "required_metrics_pct", "router_metrics_pct", "data_quality_rating",
    "data_quality_issues", "collection_completion_pct", "anomaly_rate_recent",
    "signal_degradation_rate", "incident_recovery_time", "teams_in_meeting",
    "tcp_retransmit_rate", "cssr_proxy_pct", "anomaly_type", "anomaly_flag",
    "cpu_pct", "memory_pct", "active_connections", "traffic_type",
    "traffic_confidence", "detection_method", "rssi_dbm", "signal_quality_pct",
    "rx_link_mbps", "channel", "bssid", "connected_stations", "pci", "cqi",
    "earfcn", "mcs", "network_type_router", "cell_id_router", "timing_advance",
    "bler_proxy_pct", "bler_delta", "bler_trend", "bler_severity",
    "wifi_signal_category", "wifi_signal_score", "cellular_signal_category",
    "cellular_signal_score", "data_source", "day_of_week", "hour_of_day",
}


def harden_logging_streams() -> None:
    """Force les handlers texte à accepter l'Unicode sur Windows."""
    root_logger = logging.getLogger()
    all_loggers = [root_logger, logger]

    manager = logging.root.manager
    for obj in manager.loggerDict.values():
        if isinstance(obj, logging.Logger):
            all_loggers.append(obj)

    seen_handlers = set()
    for current_logger in all_loggers:
        for handler in current_logger.handlers:
            if id(handler) in seen_handlers:
                continue
            seen_handlers.add(id(handler))
            if isinstance(handler, logging.StreamHandler):
                stream = getattr(handler, "stream", None)
                if stream is not None and not isinstance(stream, SafeTextStream):
                    try:
                        handler.setStream(SafeTextStream(stream))
                    except Exception:
                        pass


def safe_print_json(record: Dict[str, Any]) -> None:
    text = json.dumps(record, ensure_ascii=False, default=str)
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="backslashreplace").decode("ascii"), flush=True)


def sanitize_sample(raw: Dict[str, Any]) -> Dict[str, Any]:
    record: Dict[str, Any] = {}
    for key in ALLOWED_KPI:
        if key in raw:
            record[key] = raw.get(key)

    # defaults utiles
    record.setdefault("node_id", raw.get("node_id") or raw.get("router_id") or "unknown")
    record.setdefault("timestamp", raw.get("timestamp"))
    record.setdefault("anomaly_flag", raw.get("anomaly_flag", False))
    record.setdefault("anomaly_type", raw.get("anomaly_type", ""))

    # fallback KPI dérivés
    if record.get("cssr_proxy_pct") is None and raw.get("cssr_pct") is not None:
        record["cssr_proxy_pct"] = raw.get("cssr_pct")
    if record.get("tcp_retransmit_rate") is None and raw.get("bler_proxy_pct") is not None:
        record["tcp_retransmit_rate"] = raw.get("bler_proxy_pct")

    return record


def build_collector(args: argparse.Namespace) -> QoSBuddyCollector:
    config = TunisianNetworkConfig()
    if args.router_gateway:
        setattr(config, "ROUTER_GATEWAY", args.router_gateway)
    if args.router_type:
        setattr(config, "ROUTER_TYPE", args.router_type)

    collector = QoSBuddyCollector(
        zone_id=args.zone,
        cell_id=args.cell,
        node_id=args.node,
        device_type=args.device_type,
        config=config,
        choice=args.choice,
    )

    if args.router_gateway:
        try:
            collector._initialize_router()
        except Exception as exc:
            logger.warning("Initialisation routeur échouée: %s", exc)
    return collector


def main() -> None:
    parser = argparse.ArgumentParser(description="Producteur temps réel -> JSONL bus")
    parser.add_argument("--bus-file", default="network_stream.jsonl")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument(
        "--scenario",
        default="normal",
        choices=["baseline", "congestion", "packet_loss", "throughput", "normal"],
    )
    parser.add_argument("--zone", default="Z2")
    parser.add_argument("--cell", default="C1")
    parser.add_argument("--node", default="N1")
    parser.add_argument("--device-type", default="workstation")
    parser.add_argument("--choice", type=int, default=None)
    parser.add_argument("--router-gateway", default=None)
    parser.add_argument("--router-type", default=None)
    parser.add_argument("--max-samples", type=int, default=0, help="0 = infini")
    args = parser.parse_args()

    setup_logging()
    harden_logging_streams()

    bus = JSONLBus(args.bus_file)
    collector = build_collector(args)

    logger.info("Démarrage du producteur. Bus=%s", args.bus_file)
    sent = 0
    while True:
        try:
            raw = collector.collect_single_sample(scenario_type=args.scenario)
            record = sanitize_sample(raw)
            bus.publish(record)
            sent += 1
            safe_print_json(record)

            if args.max_samples > 0 and sent >= args.max_samples:
                break
            time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("Arrêt manuel du producteur.")
            break
        except Exception as exc:
            logger.exception("Erreur producteur: %s", exc)
            time.sleep(max(2, args.interval))


if __name__ == "__main__":
    main()