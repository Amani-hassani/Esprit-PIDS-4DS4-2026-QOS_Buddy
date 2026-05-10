from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


ROOT = Path(__file__).resolve().parent
DEFAULT_SCENARIOS = ROOT / "scenarios.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_scenarios(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _post_json(url: str, token: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str, token: str, timeout_s: float) -> dict[str, Any]:
    req = request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _approve_pending(base_url: str, token: str, approval_id: str, timeout_s: float) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + f"/api/approvals/{approval_id}/decide"
    return _post_json(
        endpoint,
        token,
        {"status": "APPROVED", "reason": "near-live harness auto-approved ticket workflow"},
        timeout_s,
    )


def _ticket_summary(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    execution = payload.get("execution") or {}
    ticket = execution.get("ticket") or payload.get("deferred_ticket") or {}
    if not ticket:
        return ""
    key = ticket.get("ticket_key") or ticket.get("local_id") or "ticket"
    provider = ticket.get("provider") or "unknown"
    url = ticket.get("ticket_url")
    return f" ticket={provider}:{key}" + (f" url={url}" if url else "")


def _decision_summary(response: dict[str, Any]) -> str:
    decision = response.get("decision") or {}
    if not decision:
        return ""
    bits = [
        f"decision={decision.get('selected_action')}",
        f"gate={decision.get('gate_decision')}",
        f"risk={decision.get('risk_level')}",
    ]
    if decision.get("approval_id"):
        bits.append(f"approval={decision.get('approval_id')}")
    if decision.get("ticket_key"):
        bits.append(f"ticket={decision.get('ticket_provider')}:{decision.get('ticket_key')}")
    return " " + " ".join(bits)


def _ingest_payload(base_url: str, token: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    test_drive_endpoint = base_url.rstrip("/") + "/api/integrations/test-drive"
    try:
        return _post_json(test_drive_endpoint, token, payload, timeout_s)
    except error.HTTPError as exc:
        if exc.code not in {404, 405}:
            raise

    monitoring_endpoint = base_url.rstrip("/") + "/api/integrations/monitoring/snapshot"
    diagnostic_endpoint = base_url.rstrip("/") + "/api/integrations/diagnostic/contract"
    monitoring = _post_json(monitoring_endpoint, token, payload["monitoring"], timeout_s)
    diagnostic = _post_json(diagnostic_endpoint, token, payload["diagnostic"], timeout_s)
    return {
        "ok": monitoring.get("ok") and diagnostic.get("ok"),
        "monitoring": monitoring,
        "diagnostic": diagnostic,
        "cell_id": payload["monitoring"]["cell_id"],
    }


def _build_payload(
    *,
    scenarios: dict[str, Any],
    scenario_name: str,
    zone_id: str,
    node_id: str,
    cell_id: str,
    case_index: int = 0,
    vary_kpis: bool = False,
) -> dict[str, Any]:
    scenario = scenarios[scenario_name]
    observed_at = _now_iso()
    monitoring = dict(scenario["monitoring"])
    if vary_kpis:
        # Deterministic, bounded perturbations so 50-case runs are varied but reproducible.
        wave = (case_index % 7) - 3
        scale = 1.0 + (wave * 0.035)
        for key in ("latency_ms", "jitter_ms", "packet_loss_pct", "throughput_mbps", "bandwidth_util_pct", "queue_length"):
            if key in monitoring and isinstance(monitoring[key], (int, float)):
                monitoring[key] = round(max(0.0, float(monitoring[key]) * scale), 3)
        if "rssi_dbm" in monitoring and isinstance(monitoring["rssi_dbm"], (int, float)):
            monitoring["rssi_dbm"] = round(float(monitoring["rssi_dbm"]) + wave, 3)
        if "sinr_db" in monitoring and isinstance(monitoring["sinr_db"], (int, float)):
            monitoring["sinr_db"] = round(float(monitoring["sinr_db"]) - (wave * 0.25), 3)
        if "active_connections" in monitoring and isinstance(monitoring["active_connections"], (int, float)):
            monitoring["active_connections"] = round(max(0.0, float(monitoring["active_connections"]) + (case_index % 5) * 8), 3)
    diagnostic = dict(scenario["diagnostic"])
    evidence = list(diagnostic.get("evidence") or [])
    evidence.append(f"case_index={case_index + 1}")
    diagnostic["evidence"] = evidence
    return {
        "monitoring": {
            "source_system": "near-live-harness",
            "observed_at": observed_at,
            "zone_id": zone_id,
            "node_id": node_id,
            "cell_id": cell_id,
            **monitoring,
        },
        "diagnostic": {
            "source_system": "near-live-harness",
            "observed_at": observed_at,
            "zone_id": zone_id,
            "node_id": node_id,
            "cell_id": cell_id,
            **diagnostic,
        },
    }


def _scenario_for_index(scenarios: dict[str, Any], requested_scenario: str | None, idx: int) -> str:
    if requested_scenario:
        return requested_scenario
    names = list(scenarios.keys())
    if not names:
        raise ValueError("scenario file is empty")
    return names[idx % len(names)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Standalone near-live harness for QoS Buddy.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--token", default="engineer-dev-token")
    parser.add_argument("--scenario-file", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--scenario", default=None)
    parser.add_argument("--cell-id", default="CELL-H1")
    parser.add_argument("--zone-id", default="ZONE-1")
    parser.add_argument("--node-id", default="NODE-1")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--interval-s", type=float, default=2.0)
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-delay-s", type=float, default=1.5)
    parser.add_argument(
        "--approve-pending",
        action="store_true",
        help="Approve PENDING_APPROVAL decisions with --lead-token so ticket-backed actions create tickets.",
    )
    parser.add_argument("--lead-token", default="lead-dev-token")
    parser.add_argument(
        "--ticket-pack",
        action="store_true",
        help="Shortcut for ticket-producing scenarios: weak_signal_ticket, congestion_ticket, coverage_planning_ticket.",
    )
    parser.add_argument(
        "--human-pack",
        action="store_true",
        help="Shortcut for human-intervention scenarios including pending approvals and policy-rejected tickets.",
    )
    parser.add_argument(
        "--case-pack",
        action="store_true",
        help="Run a 50-case KPI + root-cause contract suite across all available scenarios.",
    )
    parser.add_argument(
        "--fixed-cell",
        action="store_true",
        help="Keep --cell-id for every case. By default case packs use CELL-H001, CELL-H002, ...",
    )
    parser.add_argument("--list-tickets", action="store_true", help="Print recent tickets after the run.")
    args = parser.parse_args(argv)

    scenarios = _load_scenarios(args.scenario_file)
    if args.scenario is not None and args.scenario not in scenarios:
        print(f"unknown scenario: {args.scenario}", file=sys.stderr)
        return 1

    ticket_pack = ["weak_signal_ticket", "weak_signal_indoor_ticket", "weak_signal_edge_ticket"]
    human_pack = [
        "weak_signal_ticket",
        "weak_signal_indoor_ticket",
        "weak_signal_edge_ticket",
        "congestion_ticket",
        "coverage_planning_ticket",
        "capacity_overload",
    ]
    if args.ticket_pack:
        missing = [name for name in ticket_pack if name not in scenarios]
        if missing:
            print(f"scenario file is missing ticket-pack scenarios: {', '.join(missing)}", file=sys.stderr)
            return 1
    if args.human_pack:
        missing = [name for name in human_pack if name not in scenarios]
        if missing:
            print(f"scenario file is missing human-pack scenarios: {', '.join(missing)}", file=sys.stderr)
            return 1
    case_pack = list(scenarios.keys())
    if args.case_pack and not case_pack:
        print("scenario file is empty", file=sys.stderr)
        return 1

    for idx in range(args.count):
        if args.case_pack:
            scenario_name = case_pack[idx % len(case_pack)]
        elif args.human_pack:
            scenario_name = human_pack[idx % len(human_pack)]
        elif args.ticket_pack:
            scenario_name = ticket_pack[idx % len(ticket_pack)]
        else:
            scenario_name = _scenario_for_index(scenarios, args.scenario, idx)
        case_cell_id = args.cell_id if args.fixed_cell else f"CELL-H{idx + 1:03d}"
        case_zone_id = args.zone_id if args.fixed_cell else f"ZONE-{(idx % 5) + 1}"
        case_node_id = args.node_id if args.fixed_cell else f"NODE-{(idx % 10) + 1}"
        payload = _build_payload(
            scenarios=scenarios,
            scenario_name=scenario_name,
            zone_id=case_zone_id,
            node_id=case_node_id,
            cell_id=case_cell_id,
            case_index=idx,
            vary_kpis=args.case_pack or args.human_pack or args.ticket_pack,
        )
        response = None
        last_exc: Exception | None = None
        for attempt in range(args.retries + 1):
            try:
                response = _ingest_payload(args.base_url, args.token, payload, args.timeout_s)
                last_exc = None
                break
            except error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                print(f"[{idx + 1}/{args.count}] HTTP {exc.code}: {body}", file=sys.stderr)
                return 1
            except Exception as exc:
                last_exc = exc
                if attempt >= args.retries:
                    break
                print(
                    f"[{idx + 1}/{args.count}] attempt {attempt + 1} failed: {exc}; retrying...",
                    file=sys.stderr,
                )
                time.sleep(max(args.retry_delay_s, 0.0))

        if response is None:
            print(f"[{idx + 1}/{args.count}] request failed: {last_exc}", file=sys.stderr)
            return 1

        print(
            f"[{idx + 1}/{args.count}] {scenario_name} cell={case_cell_id} "
            f"snapshot={response.get('monitoring', {}).get('snapshot_id')} "
            f"contract={response.get('diagnostic', {}).get('contract_id')}"
            f"{_decision_summary(response)}"
        )
        decision = response.get("decision") or {}
        approval_id = decision.get("approval_id")
        if args.approve_pending and approval_id:
            try:
                approval = _approve_pending(args.base_url, args.lead_token, str(approval_id), args.timeout_s)
                print(f"      approved={approval_id}{_ticket_summary(approval)}")
            except error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                print(f"      approval failed HTTP {exc.code}: {body}", file=sys.stderr)
                return 1
        if idx + 1 < args.count:
            time.sleep(max(args.interval_s, 0.0))
    if args.list_tickets:
        try:
            tickets = _get_json(args.base_url.rstrip("/") + "/api/tickets?limit=20", args.token, args.timeout_s)
            for ticket in tickets.get("items", []):
                evidence = ticket.get("evidence") or {}
                print(
                    "ticket "
                    f"id={ticket.get('id')} status={ticket.get('status')} provider={evidence.get('provider')} "
                    f"key={evidence.get('ticket_key')} cell={ticket.get('cell_id')} action={ticket.get('action_code')}"
                )
        except Exception as exc:
            print(f"ticket listing failed: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
