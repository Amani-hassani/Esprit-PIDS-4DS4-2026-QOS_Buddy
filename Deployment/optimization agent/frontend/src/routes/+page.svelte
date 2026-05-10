<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { apiGet, apiPost, auth, hasRole } from '../lib/api';
  import { fmtPct, fmtRelative, riskPill } from '../lib/format';
  import AlertsFeed from '../lib/components/AlertsFeed.svelte';
  import HealthGauge from '../lib/components/HealthGauge.svelte';
  import KpiCard from '../lib/components/KpiCard.svelte';
  import TelemetryChart from '../lib/components/TelemetryChart.svelte';
  import Topology from '../lib/components/Topology.svelte';

  interface CellState {
    timestamp: string;
    cell_id: string;
    zone_id?: string;
    node_id?: string;
    latency_ms: number;
    jitter_ms: number;
    packet_loss_pct: number;
    throughput_mbps: number;
    bandwidth_util_pct: number;
    queue_length: number;
    rssi_dbm: number;
    sinr_db: number;
    anomaly_score?: number;
  }

  interface ActionSpec {
    action_code: string;
    risk_level: string;
    estimated_impact: string;
    requires_human: boolean;
    is_reversible: boolean;
    autonomy: string;
    reason: string;
  }

  interface Snapshot {
    root_cause: string;
    confidence: number;
    evidence: string[];
    recommended_action: string;
    state: CellState;
    action_spec: ActionSpec;
  }

  interface TimePoint extends CellState {}

  interface TopoNode {
    id: string;
    label: string;
    cell_id: string;
    zone_id?: string;
    node_id?: string;
    root_cause: string;
    confidence: number;
    health: number;
    x: number;
    y: number;
  }

  interface TopoZone {
    id: string;
    x: number;
    y: number;
    node_count: number;
    cell_count: number;
    avg_health: number;
    worst_root_cause: string;
  }

  interface Topo {
    nodes: TopoNode[];
    edges: Array<{ source: string; target: string; kind: string }>;
    zones?: TopoZone[];
  }

  interface DecisionResult {
    decision_id: string;
    cell_id: string;
    selected_action: string;
    root_cause?: string;
    gate_decision: string;
    risk_level: string;
    health_before: number;
    health_after: number;
    auto_executed: boolean;
    llm_available: boolean;
    llm_reasoning: string | null;
    ticket_provider?: string | null;
    ticket_key?: string | null;
    ticket_url?: string | null;
    created_at?: string;
  }

  interface ApprovalQueueItem {
    id: string;
    cell_id?: string;
    selected_action?: string;
    root_cause?: string;
    risk_level?: string;
  }

  interface IntegrationStatus {
    monitoring: {
      observed_at?: string;
      source_system?: string;
      zone_id?: string;
      node_id?: string;
      cell_id?: string;
    } | null;
    diagnostic: {
      observed_at?: string;
      source_system?: string;
      root_cause?: string;
      confidence?: number;
      cell_id?: string;
    } | null;
    monitoring_cells: number;
  }

  interface TicketProviderHealth {
    provider: string;
    configured: boolean;
    jira: {
      url: string | null;
      project_key: string | null;
      issue_type: string;
      email: string | null;
      can_create: boolean;
      done_transitions: string[];
      timeout_s: number;
    };
  }

  interface ProbeResult {
    provider: string;
    configured: boolean;
    ok?: boolean;
    reason?: string;
    error?: string;
    account_id?: string | null;
    display_name?: string | null;
  }

  let snapshot: Snapshot | null = null;
  let series: TimePoint[] = [];
  let topology: Topo = { nodes: [], edges: [], zones: [] };
  let integrationStatus: IntegrationStatus | null = null;
  let ticketProvider: TicketProviderHealth | null = null;
  let selectedCell: string | null = null;
  let runError: string | null = null;
  let lastDecision: DecisionResult | null = null;
  let refreshTimer: number | undefined;
  let current = { token: null as string | null, role: null as 'viewer' | 'engineer' | 'lead' | null };
  let probeBusy = false;
  let probeResult: ProbeResult | null = null;
  let probeError: string | null = null;
  let cellState: CellState | null = null;
  let focusHealth: number | null = null;
  let sparkRssi: number[] = [];
  let sparkSinr: number[] = [];
  let sparkTput: number[] = [];
  let sparkLat: number[] = [];
  let sparkLoss: number[] = [];
  let sparkJitter: number[] = [];

  $: current = $auth;
  $: cellState = snapshot?.state ?? null;
  $: focusHealth = selectedCell
    ? topology.nodes.find((item) => item.cell_id === selectedCell || item.id === selectedCell)?.health ?? null
    : null;
  $: sparkRssi = series.map((point) => point.rssi_dbm ?? 0);
  $: sparkSinr = series.map((point) => point.sinr_db ?? 0);
  $: sparkTput = series.map((point) => point.throughput_mbps ?? 0);
  $: sparkLat = series.map((point) => point.latency_ms ?? 0);
  $: sparkLoss = series.map((point) => point.packet_loss_pct ?? 0);
  $: sparkJitter = series.map((point) => point.jitter_ms ?? 0);
  $: canProbeJira = hasRole(current.role, 'engineer');

  async function loadSnapshot() {
    const snap = await apiGet<Snapshot>(`/api/snapshot${selectedCell ? `?cell_id=${selectedCell}` : ''}`);
    snapshot = snap;
    if (!selectedCell && snap?.state?.cell_id) selectedCell = snap.state.cell_id;
  }

  async function loadSeries() {
    const data = await apiGet<{ points: TimePoint[] }>(
      `/api/timeseries?limit=120${selectedCell ? `&cell_id=${selectedCell}` : ''}`
    );
    series = data.points ?? [];
  }

  async function loadTopology() {
    topology = await apiGet<Topo>(`/api/topology${selectedCell ? `?focus=${selectedCell}` : ''}`);
  }

  async function loadIntegrationStatus() {
    integrationStatus = await apiGet<IntegrationStatus>('/api/integrations/status');
  }

  async function loadTicketProvider() {
    ticketProvider = await apiGet<TicketProviderHealth>('/api/tickets/provider-health');
  }

  async function loadLatestDecision() {
    const data = await apiGet<{ items: DecisionResult[] }>(
      `/api/decisions?limit=1${selectedCell ? `&cell_id=${selectedCell}` : ''}`
    );
    lastDecision = (data.items ?? [])[0] ?? null;
  }

  async function probeJira() {
    if (!canProbeJira) return;
    probeBusy = true;
    probeError = null;
    probeResult = null;
    try {
      probeResult = await apiPost<ProbeResult>('/api/tickets/probe', {});
      await loadTicketProvider();
    } catch (e) {
      probeError = e instanceof Error ? e.message : String(e);
    } finally {
      probeBusy = false;
    }
  }

  async function refreshAll() {
    try {
      await Promise.all([
        loadSnapshot(),
        loadSeries(),
        loadTopology(),
        loadIntegrationStatus(),
        loadTicketProvider(),
        loadLatestDecision()
      ]);
      runError = null;
    } catch (e) {
      runError = e instanceof Error ? e.message : String(e);
    }
  }

  function selectNode(nodeId: string) {
    const node = topology.nodes.find((item) => item.id === nodeId || item.cell_id === nodeId);
    selectedCell = node?.cell_id ?? nodeId.split('/').at(-1) ?? nodeId;
    void refreshAll();
  }

  onMount(() => {
    void refreshAll();
    refreshTimer = window.setInterval(() => {
      if (current.token) void refreshAll();
    }, 5000);
  });

  onDestroy(() => {
    if (refreshTimer !== undefined) clearInterval(refreshTimer);
  });
</script>

<section class="hero">
  <div class="card hero-card">
    <div class="hero-head">
      <div>
        <h3>Command Cell</h3>
        <div class="hero-title mono">{cellState?.zone_id ?? 'ZONE ?'} / {cellState?.node_id ?? 'NODE ?'} / {cellState?.cell_id ?? 'CELL ?'}</div>
      </div>
      <div class="integration-strip">
        <span class="pill {integrationStatus?.monitoring ? 'ok' : 'warn'}">
          Monitoring {integrationStatus?.monitoring ? fmtRelative(integrationStatus.monitoring.observed_at) : 'offline'}
        </span>
        <span class="pill {integrationStatus?.diagnostic ? 'accent' : 'warn'}">
          Diagnostic {integrationStatus?.diagnostic ? fmtRelative(integrationStatus.diagnostic.observed_at) : 'offline'}
        </span>
        <span class="pill info">{integrationStatus?.monitoring_cells ?? 0} live cells</span>
      </div>
    </div>

    <div class="hero-grid">
      <HealthGauge score={focusHealth ?? (snapshot?.confidence ?? 0) * 100} />
      <div class="hero-info">
        <div class="info-line">
          <span class="label">root cause</span>
          <span class="mono accent">{snapshot?.root_cause ?? '-'}</span>
        </div>
        <div class="info-line">
          <span class="label">confidence</span>
          <span class="mono">{fmtPct((snapshot?.confidence ?? 0) * 100)}</span>
        </div>
        <div class="info-line">
          <span class="label">recommended</span>
          <span class="mono">{snapshot?.recommended_action ?? '-'}</span>
        </div>
        <div class="info-line">
          <span class="label">risk</span>
          <span class="pill {riskPill(snapshot?.action_spec?.risk_level)}">
            {(snapshot?.action_spec?.risk_level ?? '').toUpperCase() || '-'}
          </span>
        </div>
        <div class="info-line">
          <span class="label">autonomy</span>
          <span class="mono">{snapshot?.action_spec?.autonomy ?? '-'}</span>
        </div>
        <div class="info-line">
          <span class="label">last seen</span>
          <span class="mono">{fmtRelative(cellState?.timestamp)}</span>
        </div>
        <div class="actions auto">
          <span class="pill info">Decision Audit</span>
          <span class="mono small">decisions appear here after test-drive runs or manual agent execution</span>
          <a href="/audit">Open Audit Trail</a>
        </div>
        {#if runError}
          <span class="error">{runError}</span>
        {/if}
        {#if lastDecision}
          <div class="last">
            <div class="last-line">
              <span class="pill {lastDecision.gate_decision === 'APPROVED' ? 'ok' : lastDecision.gate_decision === 'REJECTED' ? 'danger' : 'warn'}">
                {lastDecision.gate_decision}
              </span>
              <span class="mono">{lastDecision.selected_action}</span>
              <span class="delta {lastDecision.health_after >= lastDecision.health_before ? 'up' : 'down'}">
                delta health {((lastDecision.health_after ?? 0) - (lastDecision.health_before ?? 0)).toFixed(2)}
              </span>
              <span class="pill {lastDecision.llm_available ? 'accent' : 'warn'}">
                {lastDecision.llm_available ? 'LLM' : 'heuristic'}
              </span>
              {#if lastDecision.ticket_key}
                {#if lastDecision.ticket_url}
                  <a href={lastDecision.ticket_url} class="ticket mono" target="_blank" rel="noopener">
                    {lastDecision.ticket_key}
                  </a>
                {:else}
                  <span class="ticket mono">{lastDecision.ticket_key}</span>
                {/if}
              {/if}
            </div>
            {#if lastDecision.llm_reasoning}
              <div class="reasoning mono">{lastDecision.llm_reasoning}</div>
            {/if}
          </div>
        {/if}

        <div class="jira-card">
          <div class="head-row">
            <h3>Jira</h3>
            <span class="pill {ticketProvider?.configured ? 'accent' : 'warn'}">
              {ticketProvider?.provider === 'jira' ? `Jira ${ticketProvider?.jira?.project_key ?? ''}` : 'Local Ticketing'}
            </span>
          </div>
          <div class="info-line">
            <span class="label">configured</span>
            <span class="mono">{ticketProvider?.configured ? 'yes' : 'no'}</span>
          </div>
          <div class="info-line">
            <span class="label">project</span>
            <span class="mono">{ticketProvider?.jira?.project_key ?? '-'}</span>
          </div>
          <div class="info-line">
            <span class="label">issue type</span>
            <span class="mono">{ticketProvider?.jira?.issue_type ?? '-'}</span>
          </div>
          <div class="info-line">
            <span class="label">provider</span>
            <span class="mono small">{ticketProvider?.jira?.url ?? 'local-only'}</span>
          </div>
          <div class="actions">
            <a href="/tickets">Open Tickets</a>
            {#if canProbeJira}
              <button class="action-btn" on:click={probeJira} disabled={probeBusy || !ticketProvider?.configured}>
                {probeBusy ? 'Testing...' : 'Test Jira'}
              </button>
            {/if}
          </div>
          {#if probeResult}
            <div class="probe-note">
              <span class="pill ok">connected</span>
              <span class="mono small">{probeResult.display_name ?? probeResult.account_id ?? 'jira account ok'}</span>
            </div>
          {/if}
          {#if probeError}
            <div class="probe-note">
              <span class="pill danger">probe failed</span>
              <span class="mono small">{probeError}</span>
            </div>
          {/if}
        </div>
      </div>
    </div>
  </div>

  <div class="topology-wrap">
    <Topology
      nodes={topology.nodes}
      edges={topology.edges}
      zones={topology.zones ?? []}
      focus={selectedCell}
      onSelect={selectNode}
    />
  </div>
</section>

<section class="kpi-row">
  <KpiCard label="RSSI" value={cellState?.rssi_dbm} unit=" dBm" digits={1} series={sparkRssi} threshold={{ warn: -90, danger: -100, invert: true }} />
  <KpiCard label="SINR" value={cellState?.sinr_db} unit=" dB" digits={1} series={sparkSinr} threshold={{ warn: 5, danger: 0, invert: true }} />
  <KpiCard label="Throughput" value={cellState?.throughput_mbps} unit=" Mbps" digits={1} series={sparkTput} threshold={{ warn: 25, danger: 10, invert: true }} />
  <KpiCard label="Latency" value={cellState?.latency_ms} unit=" ms" digits={0} series={sparkLat} threshold={{ warn: 80, danger: 120 }} />
  <KpiCard label="Packet Loss" value={cellState?.packet_loss_pct} unit=" %" digits={2} series={sparkLoss} threshold={{ warn: 1, danger: 3 }} />
  <KpiCard label="Jitter" value={cellState?.jitter_ms} unit=" ms" digits={1} series={sparkJitter} threshold={{ warn: 10, danger: 20 }} />
</section>

<section class="row content-row">
  <div class="grow stack">
    <TelemetryChart
      title="Live Telemetry"
      series={[
        { label: 'Throughput', color: 'var(--accent)', values: sparkTput, unit: ' Mbps', digits: 1 },
        { label: 'Latency', color: 'var(--accent-2)', values: sparkLat, unit: ' ms', digits: 0 },
        { label: 'Loss', color: 'var(--warn)', values: sparkLoss, unit: ' %', digits: 2 }
      ]}
    />
    <div class="card evidence-card">
      <div class="head-row">
        <h3>
          Why
          <span class="mono accent">{cellState?.cell_id ?? '?'}</span>
          ->
          <span class="mono">{snapshot?.root_cause ?? '?'}</span>
        </h3>
        <span class="pill info">{snapshot?.recommended_action ?? '-'}</span>
      </div>
      {#if snapshot?.evidence?.length}
        <ul class="evidence-list">
          {#each snapshot.evidence as item, i (i)}
            <li class="mono">{item}</li>
          {/each}
        </ul>
      {:else}
        <div class="empty-note">No evidence attached to the current snapshot.</div>
      {/if}
      <div class="next-links">
        <a href="/review">Open Review Workspace</a>
        <a href="/approvals">Open Approval Console</a>
        <a href="/audit">Open Audit Trail</a>
      </div>
    </div>
  </div>
</section>

<section class="row">
  <AlertsFeed />
</section>

<style>
  .hero {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(360px, 520px);
    gap: 16px;
    align-items: stretch;
  }
  .hero-card { min-width: 0; display: flex; flex-direction: column; }
  .topology-wrap { min-width: 0; display: flex; }
  .hero-head {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 14px;
    flex-wrap: wrap;
  }
  .hero-title { color: var(--text-1); font-size: 14px; }
  .integration-strip { display: flex; gap: 8px; flex-wrap: wrap; }
  .hero-grid { display: grid; grid-template-columns: 152px minmax(0, 1fr); gap: 18px; align-items: center; }
  .hero-info { display: grid; gap: 8px; min-width: 0; }
  .info-line { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 4px 0; }
  .label { color: var(--text-3); font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; }
  .accent { color: var(--accent); }
  .actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 4px; }
  .error { color: var(--danger); font-size: 12px; }
  .last {
    background: var(--bg-2);
    border: 1px solid var(--stroke);
    border-radius: var(--radius-sm);
    padding: 10px;
    display: grid;
    gap: 6px;
    min-width: 0;
    overflow: hidden;
  }
  .last-line { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .delta { font-family: var(--font-mono); font-size: 11px; color: var(--text-2); }
  .delta.up { color: var(--ok); }
  .delta.down { color: var(--danger); }
  .reasoning {
    font-size: 11px;
    color: var(--text-2);
    white-space: pre-wrap;
    word-break: break-word;
    overflow-wrap: anywhere;
    line-height: 1.55;
    max-height: 140px;
    overflow-y: auto;
  }
  .ticket { color: var(--accent); font-size: 11px; }
  a.ticket:hover { text-decoration: underline; }
  .kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-top: 16px; }
  .row { margin-top: 16px; }
  .content-row { align-items: start; }
  .stack { display: grid; gap: 16px; min-width: 0; }
  .evidence-card { display: grid; gap: 10px; }
  .head-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .jira-card {
    background: var(--bg-2);
    border: 1px solid var(--stroke);
    border-radius: var(--radius-sm);
    padding: 10px;
    display: grid;
    gap: 6px;
  }
  .action-btn {
    border: 1px solid var(--stroke);
    background: var(--bg-3);
    color: var(--text-1);
    border-radius: 999px;
    padding: 6px 10px;
    font: inherit;
    cursor: pointer;
  }
  .action-btn:disabled {
    opacity: 0.55;
    cursor: default;
  }
  .probe-note {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }
  .stat-chip {
    border: 1px solid var(--stroke);
    border-radius: var(--radius-sm);
    background: rgba(255,255,255,0.02);
    padding: 8px;
    display: grid;
    gap: 2px;
  }
  .queue-preview {
    display: grid;
    gap: 6px;
  }
  .queue-row {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  .evidence-list { margin: 0; padding-left: 18px; display: grid; gap: 6px; }
  .empty-note { color: var(--text-3); font-size: 12px; }
  .next-links { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; }
  .next-links a { color: var(--accent); }
  .next-links a:hover { text-decoration: underline; }
  @media (max-width: 1180px) {
    .hero { grid-template-columns: 1fr; }
  }
  @media (max-width: 1000px) {
    .hero-grid { grid-template-columns: 1fr; }
  }
</style>
