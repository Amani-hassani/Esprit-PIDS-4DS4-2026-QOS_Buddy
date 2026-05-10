from __future__ import annotations

import warnings

import pytest
import pandas as pd

from deployment.core import settings as settings_mod
from deployment import data as data_mod
from deployment.store.db import reset_for_tests
from deployment.tools import ToolContext, run_tool
from deployment.tools.registry import TOOL_REGISTRY, describe_tools


@pytest.fixture(autouse=True)
def clean_store():
    reset_for_tests()
    yield
    reset_for_tests()


def _ctx(role: str = "engineer") -> ToolContext:
    return ToolContext(decision_id=None, principal_token=f"{role}-dev-token", principal_role=role)


def test_describe_lists_all_tools_with_schemas():
    descriptors = describe_tools()
    names = {d["name"] for d in descriptors}
    assert names >= {
        "read_kpis",
        "query_topology",
        "check_policy",
        "fetch_history",
        "fetch_incidents",
        "open_change_ticket",
    }
    for d in descriptors:
        assert d["input_schema"]["type"] == "object"
        assert d["minimum_role"] in {"viewer", "engineer", "lead"}


def test_read_kpis_returns_snapshot_and_root_cause():
    out = run_tool("read_kpis", {"cell_id": None}, _ctx("viewer"))
    assert "kpis" in out
    assert out["root_cause"].startswith("RC_")
    assert isinstance(out["evidence"], list)


def test_check_policy_returns_validators():
    out = run_tool("check_policy", {"action_code": "ACT_REDUCE_BUFFER_SIZE"}, _ctx())
    assert out["decision"] in {"APPROVED", "PENDING_APPROVAL", "REJECTED", "DEFERRED"}
    assert isinstance(out["validators"], list) and out["validators"]


def test_check_policy_uses_action_contract_not_root_cause_default():
    out = run_tool(
        "check_policy",
        {"action_code": "ACT_LOADBALANCE_FREQ_BAND", "root_cause": "RC_CAPACITY_OVERLOAD"},
        _ctx(),
    )
    assert out["risk_level"] == "medium"
    assert out["impact_radius"] == "sector"
    assert out["requires_human"] is False


def test_query_topology_emits_nodes_and_edges():
    out = run_tool("query_topology", {}, _ctx("viewer"))
    assert "nodes" in out and "edges" in out
    assert len(out["nodes"]) >= 1
    if len(out["nodes"]) > 1:
        assert len(out["edges"]) >= 1


def test_open_change_ticket_requires_engineer():
    from deployment.tools.base import ToolInvocationError

    viewer_ctx = _ctx("viewer")
    out = run_tool(
        "open_change_ticket",
        {
            "cell_id": "C1",
            "action_code": "ACT_LOADBALANCE_FREQ_BAND",
            "summary": "engineer requested band rebalance",
        },
        viewer_ctx,
    )
    assert "error" in out
    # run as engineer — must succeed
    eng_ctx = _ctx("engineer")
    out = run_tool(
        "open_change_ticket",
        {
            "cell_id": "C1",
            "action_code": "ACT_LOADBALANCE_FREQ_BAND",
            "summary": "engineer requested band rebalance",
            "evidence": {"latency_ms": 140},
        },
        eng_ctx,
    )
    assert out["status"] == "OPEN"
    assert out["ticket_id"].startswith("tkt_")


def test_run_tool_rejects_insufficient_role():
    viewer_ctx = _ctx("viewer")
    out = run_tool("open_change_ticket", {"cell_id": "C1", "action_code": "X", "summary": "nope"}, viewer_ctx)
    assert "error" in out and "requires role" in out["error"]


def test_prod_mode_disables_sample_fallback_for_data_tools(monkeypatch):
    monkeypatch.setenv("QOS_APP_MODE", "prod")
    monkeypatch.setenv("QOS_TOKENS_VIEWER", "viewer-dev-token")
    settings_mod.get_settings.cache_clear()

    data_mod.load_qos.cache_clear()

    kpis = run_tool("read_kpis", {"cell_id": None}, _ctx("viewer"))
    assert "error" in kpis
    assert "live telemetry is required in prod mode" in kpis["error"]

    topo = run_tool("query_topology", {}, _ctx("viewer"))
    assert "error" in topo
    assert "live telemetry is required in prod mode" in topo["error"]


def test_load_qos_skips_empty_or_all_na_frames_without_concat_warning(monkeypatch):
    data_mod.load_qos.cache_clear()

    class _FakePath:
        def __init__(self, name: str) -> None:
            self.name = name

        def __lt__(self, other: object) -> bool:
            if not isinstance(other, _FakePath):
                return NotImplemented
            return self.name < other.name

    class _FakeDir:
        def glob(self, pattern: str):
            return files if pattern == "qos_timeseries_*.csv" else []

    files = [_FakePath("qos_timeseries_empty.csv"), _FakePath("qos_timeseries_data.csv")]

    monkeypatch.setattr(data_mod, "DATA_DIR", _FakeDir())

    def fake_read_csv(file):
        if file.name.endswith("empty.csv"):
            return pd.DataFrame(columns=["timestamp", "cell_id", "latency_ms"])
        return pd.DataFrame(
            [
                {
                    "timestamp": "2026-04-25T10:00:00Z",
                    "cell_id": "CELL-W1",
                    "latency_ms": 120.0,
                }
            ]
        )

    monkeypatch.setattr(data_mod.pd, "read_csv", fake_read_csv)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        frame = data_mod.load_qos()

    concat_warnings = [w for w in caught if "DataFrame concatenation with empty or all-NA entries is deprecated" in str(w.message)]
    assert concat_warnings == []
    assert list(frame["cell_id"]) == ["CELL-W1"]
