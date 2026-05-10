-- QoS Buddy event store. Append-only apart from approval state transitions.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS decisions (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    cell_id         TEXT NOT NULL,
    root_cause      TEXT NOT NULL,
    rc_confidence   REAL NOT NULL,
    selected_action TEXT NOT NULL,
    selected_source TEXT NOT NULL,
    hybrid_score    REAL NOT NULL,
    gate_decision   TEXT NOT NULL,
    gate_reason     TEXT NOT NULL,
    risk_level      TEXT NOT NULL,
    impact_radius   TEXT NOT NULL,
    auto_executed   INTEGER NOT NULL DEFAULT 0,
    principal       TEXT,
    evidence_json   TEXT NOT NULL,
    candidates_json TEXT NOT NULL,
    validators_json TEXT NOT NULL,
    kpi_before_json TEXT NOT NULL,
    kpi_after_json  TEXT,
    health_before   REAL,
    health_after    REAL,
    mlflow_run_id   TEXT
);
CREATE INDEX IF NOT EXISTS idx_decisions_created_at ON decisions (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_cell_id    ON decisions (cell_id);
CREATE INDEX IF NOT EXISTS idx_decisions_rc         ON decisions (root_cause);
CREATE INDEX IF NOT EXISTS idx_decisions_gate       ON decisions (gate_decision);

CREATE TABLE IF NOT EXISTS tool_calls (
    id             TEXT PRIMARY KEY,
    decision_id    TEXT NOT NULL REFERENCES decisions (id) ON DELETE CASCADE,
    seq            INTEGER NOT NULL,
    created_at     TEXT NOT NULL,
    tool_name      TEXT NOT NULL,
    input_json     TEXT NOT NULL,
    output_json    TEXT NOT NULL,
    duration_ms    REAL NOT NULL,
    error          TEXT
);
CREATE INDEX IF NOT EXISTS idx_toolcalls_decision ON tool_calls (decision_id, seq);
CREATE INDEX IF NOT EXISTS idx_toolcalls_tool     ON tool_calls (tool_name);

CREATE TABLE IF NOT EXISTS reasonings (
    id             TEXT PRIMARY KEY,
    decision_id    TEXT REFERENCES decisions (id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL,
    kind           TEXT NOT NULL,            -- agent | review | healthcheck
    prompt_hash    TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model          TEXT NOT NULL,
    available      INTEGER NOT NULL,
    chosen_action  TEXT,
    confidence     REAL,
    reasoning_text TEXT NOT NULL,
    raw_json       TEXT NOT NULL,
    latency_ms     REAL,
    error          TEXT
);
CREATE INDEX IF NOT EXISTS idx_reasonings_created_at ON reasonings (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reasonings_decision   ON reasonings (decision_id);
CREATE INDEX IF NOT EXISTS idx_reasonings_kind       ON reasonings (kind);

CREATE TABLE IF NOT EXISTS approvals (
    id              TEXT PRIMARY KEY,
    decision_id     TEXT NOT NULL REFERENCES decisions (id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    sla_deadline    TEXT NOT NULL,
    status          TEXT NOT NULL,           -- PENDING_APPROVAL | APPROVED | REJECTED | DEFERRED | EXPIRED
    decided_at      TEXT,
    actor           TEXT,
    reason          TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_status   ON approvals (status);
CREATE INDEX IF NOT EXISTS idx_approvals_deadline ON approvals (sla_deadline);

CREATE TABLE IF NOT EXISTS alerts (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    severity      TEXT NOT NULL,             -- info | warning | critical
    kind          TEXT NOT NULL,             -- sla_breach | drift | llm_offline | ...
    subject       TEXT NOT NULL,
    body          TEXT NOT NULL,
    approval_id   TEXT REFERENCES approvals (id) ON DELETE SET NULL,
    decision_id   TEXT REFERENCES decisions (id) ON DELETE SET NULL,
    acknowledged  INTEGER NOT NULL DEFAULT 0,
    acknowledged_at TEXT,
    acknowledged_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_created  ON alerts (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts (severity);

CREATE TABLE IF NOT EXISTS prompt_registry (
    prompt_hash    TEXT PRIMARY KEY,
    prompt_name    TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    template       TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_tickets (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    decision_id   TEXT REFERENCES decisions (id) ON DELETE SET NULL,
    cell_id       TEXT NOT NULL,
    action_code   TEXT NOT NULL,
    summary       TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    opened_by     TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'OPEN'
);
CREATE INDEX IF NOT EXISTS idx_tickets_cell   ON change_tickets (cell_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON change_tickets (status);

CREATE TABLE IF NOT EXISTS llm_cache (
    key          TEXT PRIMARY KEY,            -- sha256(prompt_hash + payload)
    prompt_hash  TEXT NOT NULL,
    model        TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    hits         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_llm_cache_prompt ON llm_cache (prompt_hash);

CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    revoked_at      TEXT,
    revoked_by      TEXT,
    principal_token TEXT NOT NULL,
    principal_role  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions (expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_revoked ON sessions (revoked_at);

CREATE TABLE IF NOT EXISTS monitoring_snapshots (
    id             TEXT PRIMARY KEY,
    received_at    TEXT NOT NULL,
    observed_at    TEXT NOT NULL,
    source_system  TEXT NOT NULL,
    zone_id        TEXT NOT NULL,
    node_id        TEXT NOT NULL,
    cell_id        TEXT NOT NULL,
    payload_json   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_monitoring_cell     ON monitoring_snapshots (cell_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_monitoring_zone     ON monitoring_snapshots (zone_id, node_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_monitoring_received ON monitoring_snapshots (received_at DESC);

CREATE TABLE IF NOT EXISTS diagnostic_contracts (
    id               TEXT PRIMARY KEY,
    received_at      TEXT NOT NULL,
    observed_at      TEXT NOT NULL,
    source_system    TEXT NOT NULL,
    zone_id          TEXT,
    node_id          TEXT,
    cell_id          TEXT NOT NULL,
    root_cause       TEXT NOT NULL,
    confidence       REAL NOT NULL,
    recommended_action TEXT,
    summary          TEXT,
    evidence_json    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diagnostic_cell     ON diagnostic_contracts (cell_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_diagnostic_received ON diagnostic_contracts (received_at DESC);

-- Per-cell live execution state. Each tool overlay (buffer profile, scheduler
-- profile, handover profile) is keyed by `(cell_id, profile_kind)`. The agent
-- can read this back to decide whether a profile is already applied, and roll
-- back by setting `state = 'rolled_back'` plus restoring `before_kpis`.
CREATE TABLE IF NOT EXISTS execution_state (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    cell_id         TEXT NOT NULL,
    profile_kind    TEXT NOT NULL,
    action_code     TEXT NOT NULL,
    state           TEXT NOT NULL,            -- staged | active | rolled_back
    decision_id     TEXT REFERENCES decisions (id) ON DELETE SET NULL,
    snapshot_id     TEXT REFERENCES monitoring_snapshots (id) ON DELETE SET NULL,
    parameters_json TEXT NOT NULL,
    before_kpis_json TEXT NOT NULL,
    after_kpis_json TEXT NOT NULL,
    validation_json TEXT NOT NULL,
    rollback_token  TEXT,
    actor           TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_execstate_active
    ON execution_state (cell_id, profile_kind)
    WHERE state IN ('staged', 'active');
CREATE INDEX IF NOT EXISTS idx_execstate_cell ON execution_state (cell_id, created_at DESC);
