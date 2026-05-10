<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { apiGet, apiPost, auth, hasRole } from '../../lib/api';
  import { fmtRelative, fmtTime, pillClass, riskPill } from '../../lib/format';

  interface JiraStatus {
    name: string | null;
    category_key: string | null;
    category_name: string | null;
    resolution: string | null;
    updated: string | null;
    local_status: string;
  }

  interface TicketEvidence {
    provider?: string;
    ticket_key?: string | null;
    ticket_url?: string | null;
    labels?: string[];
    kpi_lines?: string[];
    evidence?: string[];
    reasoning?: string;
    risk_level?: string;
    opened_at?: string;
    upstream_error?: string | null;
    closed_by?: string | null;
    closed_at?: string | null;
    jira_status?: JiraStatus;
    jira_refreshed_at?: string;
  }

  interface Ticket {
    id: string;
    created_at: string;
    decision_id: string | null;
    cell_id: string;
    action_code: string;
    summary: string;
    opened_by: string;
    status: string;
    evidence: TicketEvidence;
  }

  interface ProviderHealth {
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

  let tickets = $state<Ticket[]>([]);
  let selected = $state<Ticket | null>(null);
  let provider = $state<ProviderHealth | null>(null);
  let statusFilter = $state<string>('');
  let cellFilter = $state<string>('');
  let probeResult = $state<ProbeResult | null>(null);
  let probing = $state(false);
  let busy = $state(false);
  let actionError = $state<string | null>(null);
  let actionNote = $state<string | null>(null);

  const role = $derived($auth.role);
  const canAct = $derived(hasRole(role, 'engineer'));

  async function loadProvider() {
    try {
      provider = await apiGet<ProviderHealth>('/api/tickets/provider-health');
    } catch (e) {
      console.warn(e);
    }
  }

  async function loadTickets() {
    try {
      const params = new URLSearchParams();
      params.set('limit', '100');
      if (statusFilter) params.set('status', statusFilter);
      if (cellFilter.trim()) params.set('cell_id', cellFilter.trim());
      const data = await apiGet<{ provider: string; items: Ticket[] }>(`/api/tickets?${params.toString()}`);
      tickets = data.items || [];
      if (selected) {
        const fresh = tickets.find((t) => t.id === selected!.id);
        selected = fresh ?? null;
      }
    } catch (e) {
      console.warn(e);
    }
  }

  async function probeJira() {
    probing = true;
    actionError = null;
    await tick();
    try {
      probeResult = await apiPost<ProbeResult>('/api/tickets/probe', {});
      await loadProvider();
    } catch (e: any) {
      actionError = e?.message ?? String(e);
      probeResult = null;
    } finally {
      probing = false;
    }
  }

  async function refresh(ticket: Ticket) {
    if (!canAct) return;
    busy = true;
    actionError = null;
    actionNote = null;
    await tick();
    try {
      const res = await apiPost<{
        ticket: Ticket;
        refreshed: boolean;
        reason?: string;
        error?: string;
        jira_status?: JiraStatus;
      }>(`/api/tickets/${ticket.id}/refresh`, {});
      selected = res.ticket;
      await loadTickets();
      if (!res.refreshed) {
        actionNote = `Refresh skipped: ${res.reason ?? 'unknown'}${res.error ? ` (${res.error})` : ''}`;
      } else {
        actionNote = `Synced from Jira (${res.jira_status?.name ?? 'unknown status'}).`;
      }
    } catch (e: any) {
      actionError = e?.message ?? String(e);
    } finally {
      busy = false;
    }
  }

  async function close(ticket: Ticket) {
    if (!canAct) return;
    busy = true;
    actionError = null;
    actionNote = null;
    await tick();
    try {
      const res = await apiPost<{
        ticket: Ticket;
        transitioned: boolean;
        upstream_error?: string | null;
      }>(`/api/tickets/${ticket.id}/close`, {});
      selected = res.ticket;
      await loadTickets();
      if (res.upstream_error) {
        actionNote = `Local closed; Jira transition failed: ${res.upstream_error}`;
      } else if (res.transitioned) {
        actionNote = 'Closed locally and transitioned in Jira.';
      } else {
        actionNote = 'Closed locally (no Jira link or already done).';
      }
    } catch (e: any) {
      actionError = e?.message ?? String(e);
    } finally {
      busy = false;
    }
  }

  function jiraBadge(t: Ticket): 'ok' | 'warn' | 'info' {
    const providerName = t.evidence?.provider ?? 'local';
    if (providerName === 'jira') return t.evidence?.upstream_error ? 'warn' : 'ok';
    return 'info';
  }

  function ticketKey(t: Ticket): string {
    return t.evidence?.ticket_key || t.id;
  }

  onMount(() => {
    loadProvider();
    loadTickets();
  });

  $effect(() => {
    void statusFilter;
    loadTickets();
  });

  $effect(() => {
    void cellFilter;
    loadTickets();
  });
</script>

<section class="layout">
  <div class="card list-card">
    <div class="head">
      <h3>Change Tickets</h3>
      <div class="filters">
        <input type="text" placeholder="filter cell" bind:value={cellFilter} class="mono" />
        <select bind:value={statusFilter}>
          <option value="">all</option>
          <option value="OPEN">open</option>
          <option value="CLOSED">closed</option>
        </select>
      </div>
    </div>

    {#if tickets.length === 0}
      <div class="empty">No change tickets yet. Tickets are opened when an approved action needs external handling or cannot be automated.</div>
    {:else}
      <div class="list scroll">
        {#each tickets as t (t.id)}
          <button class="row-btn" class:active={selected?.id === t.id} onclick={() => (selected = t)}>
            <div class="row-top">
              <span class="pill {pillClass(t.status)}">{t.status}</span>
              <span class="pill {jiraBadge(t)}">{t.evidence?.provider ?? 'local'}</span>
              <span class="mono key">{ticketKey(t)}</span>
              <span class="time">{fmtRelative(t.created_at)}</span>
            </div>
            <div class="row-mid mono">
              <span class="cell">{t.cell_id}</span>
              <span class="action">{t.action_code}</span>
              {#if t.evidence?.risk_level}
                <span class="pill {riskPill(t.evidence.risk_level)}">{t.evidence.risk_level}</span>
              {/if}
              {#if t.evidence?.jira_status?.name}
                <span class="jira-status">{t.evidence.jira_status.name}</span>
              {/if}
            </div>
            <div class="summary">{t.summary}</div>
          </button>
        {/each}
      </div>
    {/if}
  </div>

  <div class="detail-card">
    <div class="card provider-card">
      <div class="head">
        <h3>Jira Provider</h3>
        <button onclick={probeJira} disabled={probing || !canAct}>
          {probing ? 'probing...' : 'probe'}
        </button>
      </div>
      {#if provider}
        <div class="meta-grid">
          <div><span class="label">provider</span><span class="pill {provider.configured ? 'ok' : 'info'}">{provider.provider}</span></div>
          <div><span class="label">configured</span><span class="mono">{provider.configured ? 'yes' : 'no'}</span></div>
          <div><span class="label">url</span><span class="mono small">{provider.jira.url ?? '-'}</span></div>
          <div><span class="label">project</span><span class="mono">{provider.jira.project_key ?? '-'}</span></div>
          <div><span class="label">issue type</span><span class="mono">{provider.jira.issue_type}</span></div>
          <div><span class="label">email</span><span class="mono small">{provider.jira.email ?? '-'}</span></div>
          <div><span class="label">timeout</span><span class="mono">{provider.jira.timeout_s}s</span></div>
          <div><span class="label">done transitions</span><span class="mono small">{provider.jira.done_transitions.join(', ')}</span></div>
        </div>
        {#if !provider.configured}
          <div class="hint">
            Set <code>JIRA_URL</code>, <code>JIRA_EMAIL</code>, <code>JIRA_TOKEN</code>, <code>JIRA_PROJECT_KEY</code>
            in your environment. Jira status refreshes automatically here; tickets stay local-only until all four are present.
          </div>
        {/if}
      {:else}
        <div class="empty">Loading provider health...</div>
      {/if}
      {#if probeResult}
        <div class="probe-result" class:ok={probeResult.ok} class:err={!probeResult.ok}>
          {#if probeResult.ok}
            Authenticated as <span class="mono">{probeResult.display_name ?? probeResult.account_id ?? 'unknown'}</span>
          {:else}
            {probeResult.reason ?? 'failed'}{probeResult.error ? ` - ${probeResult.error}` : ''}
          {/if}
        </div>
      {/if}
    </div>

    {#if selected}
      <div class="card">
        <div class="head">
          <h3>Ticket - <span class="mono">{ticketKey(selected)}</span></h3>
          <div class="actions">
            {#if selected.evidence?.ticket_url}
              <a class="btn" href={selected.evidence.ticket_url} target="_blank" rel="noopener">open in Jira</a>
            {/if}
            <button onclick={() => refresh(selected!)} disabled={busy || !canAct}>refresh</button>
            <button onclick={() => close(selected!)} disabled={busy || !canAct || selected.status === 'CLOSED'} class="danger">
              close
            </button>
          </div>
        </div>

        {#if actionError}<div class="error">{actionError}</div>{/if}
        {#if actionNote}<div class="note">{actionNote}</div>{/if}

        <div class="meta-grid">
          <div><span class="label">status</span><span class="pill {pillClass(selected.status)}">{selected.status}</span></div>
          <div><span class="label">provider</span><span class="pill {jiraBadge(selected)}">{selected.evidence?.provider ?? 'local'}</span></div>
          <div><span class="label">cell</span><span class="mono">{selected.cell_id}</span></div>
          <div><span class="label">action</span><span class="mono">{selected.action_code}</span></div>
          {#if selected.evidence?.risk_level}
            <div><span class="label">risk</span><span class="pill {riskPill(selected.evidence.risk_level)}">{selected.evidence.risk_level}</span></div>
          {/if}
          <div><span class="label">opened</span><span class="mono small">{fmtTime(selected.created_at)}</span></div>
          <div><span class="label">opened by</span><span class="mono small">{selected.opened_by}</span></div>
          {#if selected.decision_id}
            <div><span class="label">decision</span><span class="mono small">{selected.decision_id}</span></div>
          {/if}
          {#if selected.evidence?.jira_status}
            <div>
              <span class="label">jira status</span>
              <span class="mono">{selected.evidence.jira_status.name ?? '-'}</span>
            </div>
            <div>
              <span class="label">jira category</span>
              <span class="mono">{selected.evidence.jira_status.category_name ?? '-'}</span>
            </div>
            {#if selected.evidence.jira_status.resolution}
              <div>
                <span class="label">resolution</span>
                <span class="mono">{selected.evidence.jira_status.resolution}</span>
              </div>
            {/if}
            {#if selected.evidence.jira_refreshed_at}
              <div>
                <span class="label">last sync</span>
                <span class="mono small">{fmtRelative(selected.evidence.jira_refreshed_at)}</span>
              </div>
            {/if}
          {/if}
        </div>

        {#if selected.evidence?.upstream_error}
          <div class="upstream-error">
            <div class="label">upstream error</div>
            <div class="mono small">{selected.evidence.upstream_error}</div>
          </div>
        {/if}

        <div class="block">
          <div class="label">summary</div>
          <p class="summary-text">{selected.summary}</p>
        </div>

        {#if selected.evidence?.reasoning}
          <div class="block">
            <div class="label">reasoning</div>
            <p class="reasoning-text mono">{selected.evidence.reasoning}</p>
          </div>
        {/if}

        {#if selected.evidence?.kpi_lines?.length}
          <div class="block">
            <div class="label">kpi snapshot</div>
            <div class="subtle-card">
              <ul class="bullets">
                {#each selected.evidence.kpi_lines as line, i (i)}<li class="mono small">{line}</li>{/each}
              </ul>
            </div>
          </div>
        {/if}

        {#if selected.evidence?.evidence?.length}
          <div class="block">
            <div class="label">evidence</div>
            <div class="subtle-card">
              <ul class="bullets">
                {#each selected.evidence.evidence as line, i (i)}<li class="mono small">{line}</li>{/each}
              </ul>
            </div>
          </div>
        {/if}

        {#if selected.evidence?.labels?.length}
          <div class="block">
            <div class="label">labels</div>
            <div class="chips">
              {#each selected.evidence.labels as label (label)}
                <span class="chip mono">{label}</span>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    {:else}
      <div class="card empty-card">
        <div class="empty">Select a ticket to view its detail, refresh from Jira, or close it.</div>
      </div>
    {/if}
  </div>
</section>

<style>
  .layout { display: grid; grid-template-columns: 460px 1fr; gap: 16px; align-items: start; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
  .head h3 { margin: 0; }
  .filters { display: flex; gap: 6px; }
  .filters input { width: 120px; }
  .filters select { width: auto; }
  .empty { color: var(--text-3); font-size: 13px; padding: 12px 0; }
  .empty-card { min-height: 160px; display: grid; place-items: center; }
  .list-card .list { display: grid; gap: 8px; max-height: 78vh; }
  .row-btn {
    text-align: left;
    background: var(--bg-2);
    border: 1px solid var(--stroke);
    border-radius: var(--radius-sm);
    padding: 10px 12px;
    color: var(--text-1);
    display: grid;
    gap: 4px;
    cursor: pointer;
    width: 100%;
  }
  .row-btn:hover { border-color: var(--stroke-strong); }
  .row-btn.active { border-color: var(--accent-2); box-shadow: inset 0 0 0 1px var(--accent-2); }
  .row-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .row-mid { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 11px; color: var(--text-2); }
  .row-mid .cell { color: var(--text-1); }
  .row-mid .action { color: var(--accent); }
  .row-mid .jira-status { color: var(--text-3); font-size: 10px; }
  .key { color: var(--text-0); font-weight: 600; }
  .summary { color: var(--text-2); font-size: 12px; line-height: 1.4; }
  .time { margin-left: auto; color: var(--text-3); font-size: 11px; }
  .detail-card { display: grid; gap: 16px; }
  .label { color: var(--text-3); font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; }
  .small { font-size: 11px; }
  .actions { display: flex; gap: 6px; flex-wrap: wrap; }
  .actions .btn,
  .actions button {
    padding: 5px 10px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--stroke);
    background: var(--bg-2);
    color: var(--text-1);
    font-size: 12px;
    cursor: pointer;
    text-decoration: none;
  }
  .actions button:hover { border-color: var(--stroke-strong); }
  .actions button:disabled { opacity: 0.5; cursor: not-allowed; }
  .actions .danger { color: var(--danger); border-color: rgba(255, 110, 110, 0.4); }
  .actions .danger:hover { border-color: var(--danger); }
  .block { margin-top: 12px; display: grid; gap: 4px; }
  .summary-text { margin: 0; font-size: 13px; color: var(--text-1); }
  .reasoning-text { margin: 0; color: var(--text-1); font-size: 11px; line-height: 1.5; white-space: pre-wrap; }
  .bullets { margin: 0 0 0 18px; padding: 0; color: var(--text-2); }
  .bullets li { margin-bottom: 2px; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; }
  .chip {
    padding: 3px 8px;
    border-radius: 4px;
    background: var(--bg-3);
    border: 1px solid var(--stroke);
    font-size: 11px;
  }
  .upstream-error {
    margin-top: 10px;
    padding: 8px 10px;
    border: 1px solid rgba(255, 110, 110, 0.3);
    background: rgba(255, 110, 110, 0.06);
    border-radius: var(--radius-sm);
  }
  .hint {
    margin-top: 10px;
    padding: 8px 10px;
    border: 1px dashed var(--stroke);
    border-radius: var(--radius-sm);
    color: var(--text-2);
    font-size: 12px;
  }
  .hint code {
    background: var(--bg-3);
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 11px;
  }
  .probe-result {
    margin-top: 10px;
    padding: 8px 10px;
    border-radius: var(--radius-sm);
    font-size: 12px;
  }
  .probe-result.ok { border: 1px solid rgba(90, 215, 181, 0.3); background: rgba(90, 215, 181, 0.06); color: var(--ok); }
  .probe-result.err { border: 1px solid rgba(255, 110, 110, 0.3); background: rgba(255, 110, 110, 0.06); color: var(--danger); }
  .error {
    margin-top: 8px;
    padding: 8px 10px;
    border: 1px solid rgba(255, 110, 110, 0.3);
    background: rgba(255, 110, 110, 0.06);
    color: var(--danger);
    border-radius: var(--radius-sm);
    font-size: 12px;
  }
  .note {
    margin-top: 8px;
    padding: 8px 10px;
    border: 1px solid var(--stroke);
    background: var(--bg-2);
    color: var(--text-1);
    border-radius: var(--radius-sm);
    font-size: 12px;
  }
</style>
