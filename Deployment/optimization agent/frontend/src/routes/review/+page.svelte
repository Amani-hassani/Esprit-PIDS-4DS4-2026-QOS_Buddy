<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { apiGet, apiPost, auth, hasRole } from '../../lib/api';
  import { fmtDeltaPct, fmtNumber, fmtPct, fmtSigned, pillClass, riskPill } from '../../lib/format';
  import Topology from '../../lib/components/Topology.svelte';

  interface Snapshot {
    root_cause: string;
    confidence: number;
    recommended_action: string;
    evidence: string[];
    state: { cell_id: string; zone_id?: string; node_id?: string; timestamp?: string };
  }

  interface ApprovalItem {
    id: string;
    cell_id?: string;
    selected_action?: string;
    risk_level?: string;
    root_cause?: string;
    gate_reason?: string;
  }

  interface ApprovalDetail {
    approval: ApprovalItem & { decision_id: string; status: string };
    decision: {
      id: string;
      cell_id: string;
      selected_action: string;
      root_cause: string;
      rc_confidence: number;
      evidence: string[];
      kpi_before: Record<string, unknown>;
      risk_level: string;
    } | null;
  }

  interface CatalogItem {
    root_cause: string;
    action_code: string;
    tool_name: string;
    risk_level: string;
    autonomy: string;
    reason: string;
    estimated_impact: string;
    requires_human: boolean;
  }

  interface TopoNode {
    id: string;
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

  interface Preview {
    cell_id: string;
    zone_id?: string;
    node_id?: string;
    root_cause: string;
    proposed_action: string;
    tool_name: string;
    policy: {
      decision: string;
      reason: string;
      validators: Array<{ name: string; passed: boolean; reason: string; failure_decision: string }>;
    };
    forecast: {
      before_health_score: number;
      after_health_score: number;
      delta_health_score: number;
      changed_kpis: Record<string, { before: number; after: number }>;
    };
    llm: {
      available: boolean;
      model: string;
      reasoning: string;
      recommendation: string;
      risks: string[];
      reasoning_id?: string | null;
    };
    history: Array<{ action: string; gate: string; created_at: string }>;
  }

  interface ExecuteResult {
    decision_id: string;
    approval_id?: string | null;
    execution?: {
      mode: string;
      snapshot_id?: string | null;
      ticket?: { provider?: string; ticket_key?: string; ticket_url?: string | null } | null;
    } | null;
    policy: { decision: string; reason: string };
  }

  interface TicketProviderHealth {
    provider: string;
    configured: boolean;
    jira: { project_key?: string | null; can_create: boolean };
  }

  let snapshot = $state<Snapshot | null>(null);
  let topology = $state<Topo>({ nodes: [], edges: [], zones: [] });
  let catalog = $state<CatalogItem[]>([]);
  let ticketProvider = $state<TicketProviderHealth | null>(null);
  let approvals = $state<ApprovalItem[]>([]);
  let selectedApprovalId = $state<string>('');
  let selectedApproval = $state<ApprovalDetail | null>(null);
  let selectedCell = $state<string | null>(null);
  let selectedAction = $state<string>('');
  let preview = $state<Preview | null>(null);
  let execution = $state<ExecuteResult | null>(null);
  let loading = $state(false);
  let executing = $state(false);
  let error = $state<string | null>(null);
  let baseLoadToken = 0;
  let previewToken = 0;
  let usingLiveSnapshot = $state(false);

  const current = $derived($auth);
  const selectedContract = $derived(catalog.find((item) => item.action_code === selectedAction) ?? null);
  const recordedKpis = $derived((selectedApproval?.decision?.kpi_before ?? {}) as Record<string, unknown>);
  const previewEntries = $derived(Object.entries(preview?.forecast.changed_kpis ?? {}));

  function displayDigits(key: string): number {
    if (key.includes('pct')) return 2;
    if (key.includes('throughput') || key.includes('sinr') || key.includes('rssi') || key.includes('jitter')) return 1;
    return 0;
  }

  function formatKpiValue(key: string, value: unknown): string {
    return fmtNumber(value, displayDigits(key));
  }

  function deltaClass(delta: number): string {
    return delta >= 0 ? 'delta-up' : 'delta-down';
  }

  async function loadStatic() {
    const [items, provider] = await Promise.all([
      apiGet<{ items: CatalogItem[] }>('/api/review/catalog'),
      apiGet<TicketProviderHealth>('/api/tickets/provider-health')
    ]);
    catalog = items.items || [];
    ticketProvider = provider;
  }

  async function loadApprovals() {
    const data = await apiGet<{ items: ApprovalItem[] }>('/api/approvals/pending?limit=50');
    approvals = data.items || [];
    if (!selectedApprovalId && approvals[0]?.id) selectedApprovalId = approvals[0].id;
    if (selectedApprovalId && !approvals.find((item) => item.id === selectedApprovalId)) {
      selectedApprovalId = approvals[0]?.id ?? '';
    }
  }

  async function loadLiveSnapshot(cellId: string | null = selectedCell) {
    const live = await apiGet<Snapshot>(`/api/snapshot${cellId ? `?cell_id=${cellId}` : ''}`);
    snapshot = live;
    selectedCell = live.state?.cell_id ?? cellId ?? null;
    selectedAction = live.recommended_action ?? '';
    usingLiveSnapshot = true;
  }

  function snapshotFromDecision(detail: ApprovalDetail | null): Snapshot | null {
    if (!detail?.decision) return null;
    const kpis = detail.decision.kpi_before || {};
    return {
      root_cause: detail.decision.root_cause,
      confidence: detail.decision.rc_confidence,
      recommended_action: detail.decision.selected_action,
      evidence: detail.decision.evidence || [],
      state: {
        cell_id: detail.decision.cell_id,
        zone_id: typeof kpis.zone_id === 'string' ? kpis.zone_id : undefined,
        node_id: typeof kpis.node_id === 'string' ? kpis.node_id : undefined,
        timestamp: typeof kpis.timestamp === 'string' ? kpis.timestamp : undefined
      }
    };
  }

  async function loadApprovalDetail() {
    if (!selectedApprovalId) {
      selectedApproval = null;
      await loadLiveSnapshot(selectedCell);
      return;
    }
    selectedApproval = await apiGet<ApprovalDetail>(`/api/approvals/${selectedApprovalId}`);
    snapshot = snapshotFromDecision(selectedApproval);
    selectedCell = selectedApproval.decision?.cell_id ?? null;
    selectedAction = selectedApproval.decision?.selected_action ?? '';
    usingLiveSnapshot = false;
  }

  async function loadLive() {
    const token = ++baseLoadToken;
    const topo = await apiGet<Topo>(`/api/topology${selectedCell ? `?focus=${selectedCell}` : ''}`);
    if (token !== baseLoadToken) return;
    topology = topo;
  }

  async function previewAction() {
    if (!selectedAction || (!selectedApprovalId && !selectedCell)) return;
    loading = true;
    error = null;
    execution = null;
    const token = ++previewToken;
    await tick();
    try {
      const result = await apiPost<Preview>('/api/review/preview', {
        approval_id: selectedApprovalId || undefined,
        cell_id: selectedApprovalId ? undefined : selectedCell,
        action_code: selectedAction
      });
      if (token !== previewToken) return;
      preview = result;
    } catch (e: any) {
      error = e?.message || String(e);
    } finally {
      loading = false;
    }
  }

  async function executeAction() {
    if (!selectedAction || (!selectedApprovalId && !selectedCell)) return;
    executing = true;
    error = null;
    await tick();
    try {
      execution = await apiPost<ExecuteResult>('/api/review/execute', {
        approval_id: selectedApprovalId || undefined,
        cell_id: selectedApprovalId ? undefined : selectedCell,
        action_code: selectedAction
      });
      await loadApprovals();
      await loadApprovalDetail();
      await loadLive();
      preview = null;
    } catch (e: any) {
      error = e?.message || String(e);
    } finally {
      executing = false;
    }
  }

  function selectNode(nodeId: string) {
    const node = topology.nodes.find((item) => item.id === nodeId || item.cell_id === nodeId);
    selectedCell = node?.cell_id ?? nodeId;
    if (!selectedApprovalId) {
      void loadLiveSnapshot(selectedCell).then(() => void loadLive());
      return;
    }
    void loadLive();
  }

  $effect(() => {
    void selectedApprovalId;
    previewToken += 1;
    preview = null;
    execution = null;
    error = null;
    void loadApprovalDetail().then(() => void loadLive());
  });

  onMount(() => {
    void Promise.all([loadStatic(), loadApprovals()]).then(() => {
      void loadApprovalDetail().then(() => void loadLive());
    });
  });
</script>

<section class="review-shell">
  <div class="workspace card">
    <div class="workspace-head">
      <div>
        <div class="eyebrow">Review Workspace</div>
        <h2>{snapshot?.state?.zone_id ?? '?'} / {snapshot?.state?.node_id ?? '?'} / {snapshot?.state?.cell_id ?? '?'}</h2>
      </div>
      <div class="status-strip">
        <span class="pill {riskPill(selectedContract?.risk_level)}">{(selectedContract?.risk_level ?? 'risk').toUpperCase()}</span>
        <span class="pill {ticketProvider?.configured ? 'accent' : 'warn'}">
          {ticketProvider?.provider === 'jira' ? `Jira ${ticketProvider?.jira?.project_key ?? ''}` : 'Local Ticketing'}
        </span>
      </div>
    </div>

    <div class="workspace-grid">
      <div class="summary subtle-card">
        <div class="metric-grid">
          <div>
            <span class="label">pending approval</span>
            <select bind:value={selectedApprovalId}>
              {#if approvals.length === 0}
                <option value="">No pending approvals</option>
              {:else}
                {#each approvals as item (item.id)}
                  <option value={item.id}>{item.cell_id ?? '?'} - {item.selected_action ?? item.id}</option>
                {/each}
              {/if}
            </select>
          </div>
          <div><span class="label">root cause</span><span class="mono">{snapshot?.root_cause ?? '-'}</span></div>
          <div><span class="label">confidence</span><span class="mono">{fmtPct((snapshot?.confidence ?? 0) * 100)}</span></div>
          <div><span class="label">recommended</span><span class="mono">{snapshot?.recommended_action ?? '-'}</span></div>
          <div><span class="label">tool</span><span class="mono">{selectedContract?.tool_name ?? '-'}</span></div>
          <div><span class="label">autonomy</span><span class="mono">{selectedContract?.autonomy ?? '-'}</span></div>
          <div><span class="label">impact</span><span class="mono">{selectedContract?.estimated_impact ?? '-'}</span></div>
        </div>

        <label class="field">
          <span>Executable Action <span class="hint">scoped to pending approvals</span></span>
          <select
            class="mono"
            value={selectedApprovalId}
            onchange={(event) => {
              selectedApprovalId = (event.currentTarget as HTMLSelectElement).value;
            }}
            disabled={approvals.length === 0}
          >
            {#if approvals.length === 0}
              <option value="">No pending actions to preview</option>
            {:else}
              {#each approvals as item (item.id)}
                <option value={item.id}>
                  {item.cell_id ?? '?'} | {item.root_cause ?? 'RC?'} -> {item.selected_action ?? '?'}
                </option>
              {/each}
            {/if}
          </select>
          <span class="hint mono">resolved tool: {selectedContract?.tool_name ?? '-'}</span>
        </label>

        <div class="reason-card">
          <div class="label">contract rationale</div>
          <div>{selectedContract?.reason ?? (usingLiveSnapshot ? 'Live snapshot mode uses the latest ingested cell and its recommended action.' : 'Select a pending approval to inspect its contract.')}</div>
        </div>

        <div class="actions">
          <button
            class="primary"
            onclick={() => void previewAction()}
            disabled={loading || !selectedAction || (!selectedApprovalId && !selectedCell) || !hasRole(current.role, 'engineer')}
            title={!hasRole(current.role, 'engineer') ? 'Engineer role required' : ''}
          >{loading ? 'Previewing...' : 'Preview Policy'}</button>
          <button
            class="accent"
            onclick={() => void executeAction()}
            disabled={executing || !selectedAction || (!selectedApprovalId && !selectedCell) || !hasRole(current.role, 'engineer')}
            title={!hasRole(current.role, 'engineer') ? 'Engineer role required' : ''}
          >{executing ? 'Executing...' : 'Execute Action'}</button>
          <a href="/approvals">Open Approvals</a>
        </div>

        {#if snapshot?.evidence?.length}
          <div class="panel">
            <div class="panel-title">Recorded Evidence</div>
            <div class="evidence-list">
              {#each snapshot.evidence as item, i (i)}
                <div class="evidence-line mono">{item}</div>
              {/each}
            </div>
          </div>
        {/if}

        {#if Object.keys(recordedKpis).length}
          <div class="panel">
            <div class="panel-title">Recorded KPI Snapshot</div>
            <div class="meta-grid">
              {#each Object.entries(recordedKpis) as [key, value] (key)}
                {#if !['cell_id', 'zone_id', 'node_id', 'timestamp'].includes(key)}
                  <div class="metric-card">
                    <span class="label">{key}</span>
                    <span class="metric-value mono">{formatKpiValue(key, value)}</span>
                  </div>
                {/if}
              {/each}
            </div>
          </div>
        {/if}

        {#if execution}
          <div class="execution-banner">
            <span class="pill {pillClass(execution.policy.decision)}">{execution.policy.decision}</span>
            <span class="mono">decision {execution.decision_id}</span>
            {#if execution.approval_id}
              <span class="mono">approval {execution.approval_id}</span>
            {/if}
            {#if execution.execution?.mode}
              <span class="mono">mode {execution.execution.mode}</span>
            {/if}
            {#if execution.execution?.ticket?.ticket_key}
              {#if execution.execution.ticket.ticket_url}
                <a href={execution.execution.ticket.ticket_url} target="_blank" rel="noreferrer" class="mono">
                  {execution.execution.ticket.ticket_key}
                </a>
              {:else}
                <span class="mono">{execution.execution.ticket.ticket_key}</span>
              {/if}
            {/if}
          </div>
        {/if}

        {#if error}
          <div class="error mono">{error}</div>
        {/if}
      </div>

      <div class="graph">
        <Topology
          nodes={topology.nodes}
          edges={topology.edges}
          zones={topology.zones ?? []}
          focus={selectedCell}
          onSelect={selectNode}
        />
      </div>
    </div>
  </div>

  <div class="inspector card">
    <div class="inspector-head">
      <div>
        <div class="eyebrow">Decision Inspector</div>
        <h3>Preview Result</h3>
      </div>
      {#if preview}
        <span class="pill {pillClass(preview.policy.decision)}">{preview.policy.decision}</span>
      {/if}
    </div>

    {#if preview}
      <div class="preview-grid">
        <div class="metric-card">
          <span class="label">before health</span>
          <span class="metric-value mono">{fmtNumber(preview.forecast.before_health_score, 2)}</span>
          <span class="metric-note">Recorded approval snapshot baseline</span>
        </div>
        <div class="metric-card">
          <span class="label">after health</span>
          <span class="metric-value mono">{fmtNumber(preview.forecast.after_health_score, 2)}</span>
          <span class="metric-note">Forecast after executing the fixed action</span>
        </div>
        <div class="metric-card">
          <span class="label">health delta</span>
          <span class={`metric-value mono ${deltaClass(preview.forecast.delta_health_score)}`}>{fmtSigned(preview.forecast.delta_health_score, 2)}</span>
          <span class={`metric-note ${deltaClass(preview.forecast.delta_health_score)}`}>{fmtDeltaPct(preview.forecast.before_health_score, preview.forecast.after_health_score, 1)}</span>
        </div>
        <div class="metric-card">
          <span class="label">llm recommendation</span>
          <span class="pill accent">{preview.llm.recommendation}</span>
          <span class="metric-note mono">{preview.llm.reasoning_id ?? '-'}</span>
        </div>
      </div>

      <div class="panel">
        <div class="panel-title">Reasoning</div>
        <div class="reasoning mono text-block">{preview.llm.reasoning}</div>
      </div>

      <div class="panel">
        <div class="panel-title">Validators</div>
        <div class="validator-list">
          {#each preview.policy.validators as validator (validator.name)}
            <div class="validator subtle-card">
              <span class="pill {validator.passed ? 'ok' : 'danger'}">{validator.passed ? 'pass' : 'fail'}</span>
              <span class="mono">{validator.name}</span>
              <span>{validator.reason}</span>
            </div>
          {/each}
        </div>
      </div>

      <div class="panel">
        <div class="panel-title">Forecast KPI Changes</div>
        {#if previewEntries.length}
          <div class="data-table-wrap">
            <table class="data-table">
              <thead><tr><th>kpi</th><th>before</th><th>after</th><th>delta</th><th>change</th></tr></thead>
              <tbody>
                {#each previewEntries as [key, value] (key)}
                  <tr>
                    <td class="mono">{key}</td>
                    <td class="mono">{formatKpiValue(key, value.before)}</td>
                    <td class="mono">{formatKpiValue(key, value.after)}</td>
                    <td class={`mono ${deltaClass(value.after - value.before)}`}>{fmtSigned(value.after - value.before, displayDigits(key))}</td>
                    <td class={`mono ${deltaClass(value.after - value.before)}`}>{fmtDeltaPct(value.before, value.after, 1)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {:else}
          <div class="empty-note">No KPI deltas forecast for this action.</div>
        {/if}
      </div>

      <div class="panel">
        <div class="panel-title">Recent Decision History</div>
        {#if preview.history.length}
          <div class="history">
            {#each preview.history as item (item.created_at + item.action)}
              <div class="history-row subtle-card">
                <span class="mono">{item.action}</span>
                <span class="pill {pillClass(item.gate)}">{item.gate}</span>
                <span class="mono small">{item.created_at}</span>
              </div>
            {/each}
          </div>
        {:else}
          <div class="empty-note">No recent decisions for this cell.</div>
        {/if}
      </div>
    {:else}
      <div class="empty-note">{usingLiveSnapshot ? 'No pending approvals. Preview the policy and execute against the latest ingested live snapshot instead.' : 'Select a pending approval and preview its fixed action against the recorded KPI snapshot.'}</div>
    {/if}
  </div>
</section>

<style>
  .review-shell {
    display: grid;
    gap: 16px;
  }
  .workspace {
    display: grid;
    gap: 16px;
  }
  .workspace-head,
  .inspector-head {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    align-items: start;
    flex-wrap: wrap;
  }
  .eyebrow {
    color: var(--text-3);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-bottom: 6px;
  }
  .status-strip {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .workspace-grid {
    display: grid;
    grid-template-columns: minmax(320px, 440px) minmax(0, 1fr);
    gap: 16px;
    align-items: start;
  }
  .workspace-grid > * { min-width: 0; }
  .summary {
    display: grid;
    gap: 14px;
  }
  .metric-grid,
  .preview-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }
  .label {
    color: var(--text-3);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    display: block;
    margin-bottom: 4px;
  }
  .field {
    display: grid;
    gap: 6px;
  }
  .field span {
    font-size: 12px;
    color: var(--text-2);
  }
  .hint {
    color: var(--text-3);
    font-size: 10px;
    text-transform: none;
    letter-spacing: 0;
    margin-left: 6px;
  }
  .reason-card,
  .execution-banner {
    padding: 12px;
    border: 1px solid var(--stroke);
    border-radius: var(--radius-sm);
    background: var(--bg-2);
  }
  .execution-banner {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    align-items: center;
  }
  .actions {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
  }
  .actions a {
    color: var(--accent);
    font-size: 12px;
  }
  .panel {
    display: grid;
    gap: 8px;
    min-width: 0;
  }
  .evidence-list,
  .history,
  .validator-list {
    display: grid;
    gap: 8px;
  }
  .evidence-line {
    padding: 8px 10px;
    border-radius: var(--radius-sm);
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.04);
  }
  .graph {
    min-width: 0;
  }
  .inspector {
    display: grid;
    gap: 14px;
  }
  .panel-title {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-2);
  }
  .reasoning {
    background: var(--bg-2);
    border: 1px solid var(--stroke);
    border-radius: var(--radius-sm);
    padding: 12px;
    line-height: 1.6;
    font-size: 12px;
    max-height: 260px;
    overflow-y: auto;
  }
  .error {
    color: var(--danger);
    font-size: 12px;
  }
  .empty-note {
    color: var(--text-3);
    font-size: 13px;
  }
  .small {
    font-size: 10px;
    color: var(--text-3);
  }
  @media (max-width: 1080px) {
    .workspace-grid {
      grid-template-columns: 1fr;
    }
    .metric-grid,
    .preview-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
