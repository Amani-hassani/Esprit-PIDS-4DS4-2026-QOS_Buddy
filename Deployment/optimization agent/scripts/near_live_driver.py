from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


SCENARIOS: dict[str, dict[str, Any]] = {
    "transport_delay": {
        "monitoring": {
            "latency_ms": 162.0,
            "jitter_ms": 46.0,
            "packet_loss_pct": 2.1,
            "throughput_mbps": 15.0,
            "bandwidth_util_pct": 71.0,
            "queue_length": 96.0,
            "rssi_dbm": -78.0,
            "sinr_db": 9.0,
        },
        "diagnostic": {
            "root_cause": "RC_TRANSPORT_DELAY",
            "confidence": 0.92,
            "recommended_action": "ACT_REDUCE_BUFFER_SIZE",
            "summary": "Queue pressure is driving transport delay.",
            "evidence": ["queue_length>90", "latency>150", "jitter>40"],
        },
    },
    "sinr_degraded": {
        "monitoring": {
            "latency_ms": 84.0,
            "jitter_ms": 18.0,
            "packet_loss_pct": 1.2,
            "throughput_mbps": 22.0,
            "bandwidth_util_pct": 79.0,
            "queue_length": 40.0,
            "rssi_dbm": -83.0,
            "sinr_db": 3.5,
        },
        "diagnostic": {
            "root_cause": "RC_SINR_DEGRADED",
            "confidence": 0.87,
            "recommended_action": "ACT_LOADBALANCE_FREQ_BAND",
            "summary": "Interference is suppressing SINR.",
            "evidence": ["sinr<4", "throughput collapsing under moderate load"],
        },
    },
    "handover_failure": {
        "monitoring": {
            "latency_ms": 92.0,
            "jitter_ms": 15.0,
            "packet_loss_pct": 0.9,
            "throughput_mbps": 24.0,
            "bandwidth_util_pct": 67.0,
            "queue_length": 28.0,
            "rssi_dbm": -81.0,
            "sinr_db": 8.0,
            "ho_success_rate_pct": 82.0,
        },
        "diagnostic": {
            "root_cause": "RC_HO_FAILURE",
            "confidence": 0.89,
            "recommended_action": "ACT_OPTIMIZE_HO_PARAMS",
            "summary": "Handover retries and late A3 triggers are degrading mobility.",
            "evidence": ["ho_success_rate_pct<85", "drop spikes during mobility"],
        },
    },
    "congestion_burst": {
        "monitoring": {
            "latency_ms": 138.0,
            "jitter_ms": 31.0,
            "packet_loss_pct": 1.7,
            "throughput_mbps": 18.5,
            "bandwidth_util_pct": 94.0,
            "queue_length": 124.0,
            "rssi_dbm": -74.0,
            "sinr_db": 11.5,
        },
        "diagnostic": {
            "root_cause": "RC_PRB_CONGESTION",
            "confidence": 0.9,
            "recommended_action": "ACT_TRIGGER_CA",
            "summary": "Peak-hour congestion is saturating the cell scheduler.",
            "evidence": ["bandwidth_util_pct>90", "queue_length>120", "packet_loss_pct>1.5"],
        },
    },
    "capacity_overload": {
        "monitoring": {
            "latency_ms": 126.0,
            "jitter_ms": 27.0,
            "packet_loss_pct": 1.4,
            "throughput_mbps": 17.0,
            "bandwidth_util_pct": 91.0,
            "queue_length": 109.0,
            "rssi_dbm": -79.0,
            "sinr_db": 7.0,
            "active_connections": 286.0,
        },
        "diagnostic": {
            "root_cause": "RC_CAPACITY_OVERLOAD",
            "confidence": 0.88,
            "recommended_action": "ACT_LOADBALANCE_FREQ_BAND",
            "summary": "Traffic volume is exceeding the site capacity envelope.",
            "evidence": ["active_connections>250", "bandwidth_util_pct>90"],
        },
    },
    "cqi_mismatch": {
        "monitoring": {
            "latency_ms": 58.0,
            "jitter_ms": 9.0,
            "packet_loss_pct": 0.6,
            "throughput_mbps": 29.0,
            "bandwidth_util_pct": 63.0,
            "queue_length": 24.0,
            "rssi_dbm": -76.0,
            "sinr_db": 13.0,
            "cqi": 5.0,
        },
        "diagnostic": {
            "root_cause": "RC_CQI_MISMATCH",
            "confidence": 0.83,
            "recommended_action": "ACT_PRIORITY_VOLTE_SCHEDULING",
            "summary": "CQI variance is hurting scheduler efficiency for premium traffic.",
            "evidence": ["cqi low for observed sinr", "voice queue intermittently elevated"],
        },
    },
    "weak_signal": {
        "monitoring": {
            "latency_ms": 98.0,
            "jitter_ms": 20.0,
            "packet_loss_pct": 1.5,
            "throughput_mbps": 16.0,
            "bandwidth_util_pct": 52.0,
            "queue_length": 29.0,
            "rssi_dbm": -96.0,
            "sinr_db": 4.4,
        },
        "diagnostic": {
            "root_cause": "RC_WEAK_SIGNAL",
            "confidence": 0.91,
            "recommended_action": "ACT_ALERT_COVERAGE_HOLE",
            "summary": "Persistent weak signal is degrading user experience at the sector edge.",
            "evidence": ["rssi<-95", "sinr<5", "throughput depressed despite moderate load"],
        },
    },
    "coverage_hole": {
        "monitoring": {
            "latency_ms": 109.0,
            "jitter_ms": 22.0,
            "packet_loss_pct": 1.9,
            "throughput_mbps": 14.0,
            "bandwidth_util_pct": 49.0,
            "queue_length": 32.0,
            "rssi_dbm": -101.0,
            "sinr_db": 1.8,
        },
        "diagnostic": {
            "root_cause": "RC_COVERAGE_HOLE",
            "confidence": 0.93,
            "recommended_action": "ACT_RECOMMEND_SITE_ADDITION",
            "summary": "Weak signal and poor SINR suggest a localized coverage hole.",
            "evidence": ["rssi<-100", "sinr<2", "throughput_mbps<15"],
        },
    },
    "healthy_baseline": {
        "monitoring": {
            "latency_ms": 34.0,
            "jitter_ms": 4.5,
            "packet_loss_pct": 0.08,
            "throughput_mbps": 92.0,
            "bandwidth_util_pct": 46.0,
            "queue_length": 11.0,
            "rssi_dbm": -67.0,
            "sinr_db": 21.0,
        },
        "diagnostic": {
            "root_cause": "RC_NONE",
            "confidence": 0.79,
            "recommended_action": "ACT_NO_OP",
            "summary": "Baseline healthy cell for steady-state validation.",
            "evidence": ["latency<40", "packet_loss_pct<0.1", "sinr>20"],
        },
    },
}

SCENARIO_ORDER = [
    "transport_delay",
    "sinr_degraded",
    "handover_failure",
    "congestion_burst",
    "capacity_overload",
    "cqi_mismatch",
    "weak_signal",
    "coverage_hole",
    "healthy_baseline",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _post_json(url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _jitter(value: float, request_index: int, metric_index: int) -> float:
    wave = math.sin((request_index + 1) * (metric_index + 2) * 0.73) * 0.035
    scaled = value * (1.0 + wave)
    return round(scaled, 3)


def _mutated_monitoring(base: dict[str, Any], request_index: int) -> dict[str, Any]:
    mutated: dict[str, Any] = {}
    for metric_index, (key, value) in enumerate(base.items()):
        if isinstance(value, (int, float)):
            mutated[key] = _jitter(float(value), request_index, metric_index)
        else:
            mutated[key] = value
    return mutated


def _request_cell_id(base_cell_id: str, request_index: int, scenario_name: str) -> str:
    suffix = scenario_name.split("_")[0][:3].upper()
    return f"{base_cell_id}-{suffix}-{request_index + 1:02d}"


def _build_payload(
    *,
    scenario_name: str,
    zone_id: str,
    node_id: str,
    cell_id: str,
    request_index: int = 0,
) -> dict[str, Any]:
    scenario = SCENARIOS[scenario_name]
    observed_at = _now_iso()
    monitoring = {
        "source_system": "near-live-driver",
        "observed_at": observed_at,
        "zone_id": zone_id,
        "node_id": node_id,
        "cell_id": cell_id,
        **_mutated_monitoring(scenario["monitoring"], request_index),
    }
    diagnostic = {
        "source_system": "near-live-driver",
        "observed_at": observed_at,
        "zone_id": zone_id,
        "node_id": node_id,
        "cell_id": cell_id,
        **scenario["diagnostic"],
    }
    return {"monitoring": monitoring, "diagnostic": diagnostic}


def _scenario_sequence(name: str, count: int) -> list[str]:
    if count <= 0:
        return []
    if name == "mixed":
        return [SCENARIO_ORDER[index % len(SCENARIO_ORDER)] for index in range(count)]
    if name == "all":
        all_names = list(SCENARIOS.keys())
        return [all_names[index % len(all_names)] for index in range(count)]
    return [name for _ in range(count)]


def _decision_summary(response: dict[str, Any]) -> str:
    decision = response.get("decision")
    if not isinstance(decision, dict) or not decision:
        return "decision=not-run"

    selected_action = decision.get("selected_action") or "-"
    gate = decision.get("gate_decision") or "-"
    risk = decision.get("risk_level") or "-"
    mode = "auto" if decision.get("auto_executed") else "review"
    approval = decision.get("approval_id")
    approval_text = f" approval={approval}" if approval else ""
    return f"decision={selected_action} gate={gate} risk={risk} mode={mode}{approval_text}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Drive QoS Buddy with near-live KPI and diagnostic payloads.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001", help="Backend base URL.")
    parser.add_argument("--token", default="engineer-dev-token", help="Bearer token with engineer role.")
    parser.add_argument(
        "--scenario",
        choices=sorted([*SCENARIOS.keys(), "all", "mixed"]),
        default="mixed",
        help="Single scenario, all scenarios in rotation, or mixed rotation tuned to exercise the policy gate.",
    )
    parser.add_argument("--cell-id", default="CELL-NL", help="Base cell ID prefix.")
    parser.add_argument("--zone-id", default="ZONE-1")
    parser.add_argument("--node-id", default="NODE-1")
    parser.add_argument("--count", type=int, default=50, help="Total number of requests to send.")
    parser.add_argument("--interval-s", type=float, default=0.2, help="Delay between payloads.")
    parser.add_argument("--save-last", type=Path, default=None, help="Optional path to write the last response JSON.")
    args = parser.parse_args(argv)

    endpoint = args.base_url.rstrip("/") + "/api/integrations/test-drive"
    last_response: dict[str, Any] | None = None
    scenario_names = _scenario_sequence(args.scenario, args.count)

    total = len(scenario_names)
    for request_index, scenario_name in enumerate(scenario_names):
        payload = _build_payload(
            scenario_name=scenario_name,
            zone_id=args.zone_id,
            node_id=args.node_id,
            cell_id=_request_cell_id(args.cell_id, request_index, scenario_name),
            request_index=request_index,
        )
        try:
            last_response = _post_json(endpoint, args.token, payload)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            print(f"[{request_index + 1}/{total}] HTTP {exc.code}: {body}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"[{request_index + 1}/{total}] request failed: {exc}", file=sys.stderr)
            return 1
        print(
            f"[{request_index + 1}/{total}] cell={payload['monitoring']['cell_id']} scenario={scenario_name} "
            f"snapshot={last_response.get('monitoring', {}).get('snapshot_id')} "
            f"contract={last_response.get('diagnostic', {}).get('contract_id')} "
            f"{_decision_summary(last_response)}"
        )
        if request_index + 1 < total:
            time.sleep(max(args.interval_s, 0.0))

    if args.save_last and last_response is not None:
        args.save_last.write_text(json.dumps(last_response, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
