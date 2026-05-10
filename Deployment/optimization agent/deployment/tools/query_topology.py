from __future__ import annotations

from threading import Lock
from typing import Any

import numpy as np
import pandas as pd

from ..data import infer_root_cause, latest_rows_frame
from ..simulation import health_score
from ..store.repos import MonitoringSnapshotsRepo
from .base import ToolContext, ToolDef


_cache: dict[str, Any] = {"signature": None, "value": None}
_cache_lock = Lock()


def _signature() -> tuple[int, str]:
    rows = MonitoringSnapshotsRepo.list_recent(limit=1)
    if rows:
        top = rows[0]
        return (len(MonitoringSnapshotsRepo.latest_per_cell(limit=500)), str(top.get("observed_at")))
    raw = latest_rows_frame()
    if raw.empty:
        return (0, "")
    return (int(raw["cell_id"].nunique()) if "cell_id" in raw else len(raw), str(raw["timestamp"].max()))


def _build_topology() -> dict[str, Any]:
    sig = _signature()
    with _cache_lock:
        if _cache["signature"] == sig and _cache["value"] is not None:
            return _cache["value"]
    value = _compute_topology()
    with _cache_lock:
        _cache["signature"] = sig
        _cache["value"] = value
    return value


def _latest_rows() -> pd.DataFrame:
    return latest_rows_frame().copy()


def _compute_topology() -> dict[str, Any]:
    df = _latest_rows()
    if df.empty:
        return {"nodes": [], "edges": [], "zones": []}

    if "zone_id" not in df.columns:
        df["zone_id"] = "ZONE-1"
    if "node_id" not in df.columns:
        df["node_id"] = "NODE-1"
    if "cell_id" not in df.columns:
        df["cell_id"] = "CELL-1"
    df = df.dropna(subset=["timestamp"]).sort_values(["zone_id", "node_id", "cell_id", "timestamp"])
    df["zone_id"] = df["zone_id"].fillna("ZONE-1").astype(str)
    df["node_id"] = df["node_id"].fillna("NODE-1").astype(str)
    df["cell_id"] = df["cell_id"].fillna("CELL-1").astype(str)

    nodes: list[dict[str, Any]] = []
    for _, latest in df.iterrows():
        rc, confidence, _ = infer_root_cause(latest)
        nodes.append(
            {
                "id": f"{latest['zone_id']}/{latest['node_id']}/{latest['cell_id']}",
                "label": str(latest["cell_id"]),
                "zone_id": str(latest["zone_id"]),
                "node_id": str(latest["node_id"]),
                "cell_id": str(latest["cell_id"]),
                "root_cause": rc,
                "confidence": float(confidence),
                "health": float(health_score(latest)),
                "latency_ms": float(latest.get("latency_ms") or 0.0),
                "throughput_mbps": float(latest.get("throughput_mbps") or 0.0),
                "sinr_db": float(latest.get("sinr_db") or 0.0),
                "rssi_dbm": float(latest.get("rssi_dbm") or 0.0),
                "anomaly_score": float(latest.get("anomaly_score") or 0.0),
            }
        )

    zones_index: dict[str, list[int]] = {}
    for i, node in enumerate(nodes):
        zones_index.setdefault(node["zone_id"], []).append(i)

    zones: list[dict[str, Any]] = []
    zone_keys = sorted(zones_index)
    for z_idx, zone_id in enumerate(zone_keys):
        center_angle = 2 * np.pi * z_idx / max(len(zone_keys), 1)
        cx = float(0.5 + 0.34 * np.cos(center_angle))
        cy = float(0.5 + 0.30 * np.sin(center_angle))
        zone_nodes = zones_index[zone_id]
        by_node: dict[str, list[int]] = {}
        for ni in zone_nodes:
            by_node.setdefault(nodes[ni]["node_id"], []).append(ni)
        node_keys = sorted(by_node)
        for n_idx, node_id in enumerate(node_keys):
            node_angle = center_angle + (n_idx - (len(node_keys) - 1) / 2) * 0.34
            node_radius = 0.12
            node_x = cx + float(node_radius * np.cos(node_angle))
            node_y = cy + float(node_radius * np.sin(node_angle))
            cell_indices = by_node[node_id]
            spread = max(len(cell_indices), 1)
            for c_idx, ni in enumerate(cell_indices):
                offset = (c_idx - (spread - 1) / 2) * 0.045
                tangent = node_angle + np.pi / 2
                nodes[ni]["x"] = node_x + float(offset * np.cos(tangent))
                nodes[ni]["y"] = node_y + float(offset * np.sin(tangent))

        avg_health = float(np.mean([nodes[i]["health"] for i in zone_nodes])) if zone_nodes else 0.0
        worst_rc = max(
            ((nodes[i]["root_cause"], nodes[i]["confidence"]) for i in zone_nodes),
            key=lambda item: item[1],
            default=("RC_NONE", 0.0),
        )[0]
        zones.append(
            {
                "id": str(zone_id),
                "x": cx,
                "y": cy,
                "node_count": len(by_node),
                "cell_count": len(zone_nodes),
                "avg_health": avg_health,
                "worst_root_cause": worst_rc,
            }
        )

    edges: list[dict[str, Any]] = []
    by_node_key: dict[tuple[str, str], list[int]] = {}
    for i, node in enumerate(nodes):
        by_node_key.setdefault((node["zone_id"], node["node_id"]), []).append(i)
    for indices in by_node_key.values():
        indices = sorted(indices, key=lambda idx: nodes[idx]["cell_id"])
        for a, b in zip(indices, indices[1:]):
            edges.append({"source": nodes[a]["id"], "target": nodes[b]["id"], "kind": "sibling"})

    by_zone: dict[str, list[int]] = {}
    for i, node in enumerate(nodes):
        by_zone.setdefault(node["zone_id"], []).append(i)
    for zone_nodes in by_zone.values():
        primaries: dict[str, int] = {}
        for ni in zone_nodes:
            primaries.setdefault(nodes[ni]["node_id"], ni)
        primary_indices = list(primaries.values())
        for a, b in zip(primary_indices, primary_indices[1:]):
            edges.append({"source": nodes[a]["id"], "target": nodes[b]["id"], "kind": "peer-node"})

    return {"nodes": nodes, "edges": edges, "zones": zones}


def clear_topology_cache() -> None:
    with _cache_lock:
        _cache["signature"] = None
        _cache["value"] = None


def _run(inputs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    topo = _build_topology()
    focus = inputs.get("focus_node_id")
    if focus:
        neighbors = {e["target"] for e in topo["edges"] if e["source"] == focus}
        neighbors |= {e["source"] for e in topo["edges"] if e["target"] == focus}
        focus_cell = focus.split("/")[-1] if isinstance(focus, str) else focus
        focused_nodes = [
            n
            for n in topo["nodes"]
            if n["id"] in neighbors or n["id"] == focus or n["cell_id"] == focus_cell
        ]
        focused_ids = {n["id"] for n in focused_nodes}
        focused_edges = [e for e in topo["edges"] if e["source"] in focused_ids and e["target"] in focused_ids]
        return {
            "nodes": focused_nodes,
            "edges": focused_edges,
            "zones": topo["zones"],
            "focus_node_id": focus,
        }
    return topo


QUERY_TOPOLOGY = ToolDef(
    name="query_topology",
    description="Return the live zone-node-cell topology graph for the operator dashboard.",
    input_schema={
        "type": "object",
        "properties": {"focus_node_id": {"type": ["string", "null"]}},
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "nodes": {"type": "array"},
            "edges": {"type": "array"},
            "zones": {"type": "array"},
            "focus_node_id": {"type": ["string", "null"]},
        },
    },
    minimum_role="viewer",
    handler=_run,
)
