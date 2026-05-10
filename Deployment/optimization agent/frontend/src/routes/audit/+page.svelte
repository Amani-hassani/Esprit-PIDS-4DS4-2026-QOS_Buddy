<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { apiGet, subscribeChannel } from '../../lib/api';
  import { fmtRelative, fmtTime, riskPill, pillClass } from '../../lib/format';

  interface Decision {
    id: string;
    cell_id: string;
    created_at: string;
    selected_action: string;
    selected_source: string;
    risk_level: string;
    gate_decision: string;
    gate_reason: string;
    health_before: number;
    health_after: number;
    auto_executed: number | boolean;
    root_cause: string;
    rc_confidence: number;
    candidates: Array<{ action_code: string; source?: string; score?: number; rationale?: string }>;
    hybrid_score: number;
    impact_radius: number;
    evidence: string[];
    validators: Array<{ name: string; passed: boolean; reason: string; severity: string }>;
  }

  interface Reasoning {
    id: string;
    created_at: string;
    kind: string;
    decision_id: string | null;
    available: number | boolean;
    chosen_action: string | null;
    confidence: number | null;
    error: string | null;
    latency_ms: number;
    model: string;
    prompt_hash: string;
    prompt_version: number;
    reasoning_text: string;
  }

  interface ToolCall {
    id: string;
    decision_id: string;
    seq: number;
    tool_name: string;
    input: any;
    output: any;
    error: string | null;
    duration_ms: number;
    created_at: string;
  }

  interface DecisionDetail {
    decision: Decision;
    tool_calls: ToolCall[];
    reasonings: Reasoning[];
  }

  let decisions = $state<Decision[]>([]);
  let reasonings = $state<Reasoning[]>([]);
  let selected = $state<DecisionDetail | null>(null);
  let kindFilter = $state<string>('');
  let gateFilter = $state<string>('');
  let unsubscribers: Array<() => void> = [];

  async function loadDecisions() {
    try {
      const params = new URLSearchParams();
      params.set('limit', '50');
      if (gateFilter) params.set('gate', gateFilter);
      const data = await apiGet<{ items: Decision[] }>(`/api/decisions?${params.toString()}`);
      decisions = data.items || [];
    } catch (e) {
      console.warn(e);
    }
  }

  async function loadReasonings() {
    try {
      const params = new URLSearchParams();
      params.set('limit', '60');
      if (kindFilter) params.set('kind', kindFilter);
      const data = await apiGet<{ items: Reasoning[] }>(`/api/reasonings?${params.toString()}`);
      reasonings = data.items || [];
    } catch (e) {
      console.warn(e);
    }
  }

  async function selectDecision(id: string) {
    try {
      selected = await apiGet<DecisionDetail>(`/api/decisions/${id}`);
    } catch (e) {
      console.warn(e);
    }
  }

  onMount(() => {
    loadDecisions();
    loadReasonings();
    unsubscribers.push(subscribeChannel('decisions', () => loadDecisions()));
    unsubscribers.push(subscribeChannel('reasoning', () => loadReasonings()));
  });

  onDestroy(() => {
    for (const u of unsubscribers) u();
  });

  $effect(() => {
    void gateFilter;
    loadDecisions();
  });

  $effect(() => {
    void kindFilter;
    loadReasonings();
  });

  function summarize(value: any, max = 80): string {
    if (value === null || value === undefined) return '-';
    if (typeof value === 'string') return value.length > max ? value.slice(0, max) + '...' : value;
    try {
      const s = JSON.stringify(value);
      return s.length > max ? s.slice(0, max) + '...' : s;
    } catch {
      return String(value);
    }
  }
</script>

<section class="layout">
  <div class="card decisions-card">
    <div class="head">
      <h3>Decisions</h3>
      <select bind:value={gateFilter}>
        <option value="">all gates</option>
        <option value="AUTO_EXECUTED">auto-executed</option>
        <option value="PENDING_APPROVAL">pending approval</option>
        <option value="APPROVED">approved</option>
        <option value="REJECTED">rejected</option>
      </select>
    </div>
    {#if decisions.length === 0}
      <div class="empty">No decisions yet. Run the agent from the Command Cell.</div>
    {:else}
      <div class="list scroll">
        {#each decisions as d (d.id)}
          <button class="row-btn" class:active={selected?.decision.id === d.id} onclick={() => selectDecision(d.id)}>
            <div class="row-top">
              <span class="pill {pillClass(d.gate_decision)}">{d.gate_decision}</span>
              <span class="mono action">{d.selected_action}</span>
              <span class="time">{fmtRelative(d.created_at)}</span>
            </div>
            <div class="row-mid mono">
              <span class="cell">{d.cell_id}</span>
              <span class="rc">{d.root_cause}</span>
              <span class="pill {riskPill(d.risk_level)}">{d.risk_level}</span>
              <span class="delta {d.health_after >= d.health_before ? 'up' : 'down'}">
                delta {(d.health_after - d.health_before).toFixed(2)}
              </span>
              <span class="src">{d.selected_source}</span>
            </div>
          </button>
        {/each}
      </div>
    {/if}
  </div>

  <div class="detail-card">
    {#if selected}
      <div class="card">
        <h3>Decision - {selected.decision.id}</h3>
        <div class="meta-grid">
          <div><span class="label">cell</span><span class="mono">{selected.decision.cell_id}</span></div>
          <div><span class="label">gate</span><span class="pill {pillClass(selected.decision.gate_decision)}">{selected.decision.gate_decision}</span></div>
          <div><span class="label">action</span><span class="mono">{selected.decision.selected_action}</span></div>
          <div><span class="label">risk</span><span class="pill {riskPill(selected.decision.risk_level)}">{selected.decision.risk_level}</span></div>
          <div><span class="label">root cause</span><span class="mono">{selected.decision.root_cause}</span></div>
          <div><span class="label">source</span><span class="mono">{selected.decision.selected_source}</span></div>
          <div><span class="label">rc conf</span><span class="mono">{(selected.decision.rc_confidence * 100).toFixed(1)}%</span></div>
          <div><span class="label">hybrid</span><span class="mono">{selected.decision.hybrid_score?.toFixed(2)}</span></div>
          <div><span class="label">health delta</span>
            <span class="mono delta {selected.decision.health_after >= selected.decision.health_before ? 'up' : 'down'}">
              {selected.decision.health_before.toFixed(2)} -> {selected.decision.health_after.toFixed(2)}
            </span>
          </div>
        </div>
        {#if selected.decision.gate_reason}
          <div class="reason-line">
            <span class="label">gate reason</span>
            <span class="mono">{selected.decision.gate_reason}</span>
          </div>
        {/if}
        {#if selected.decision.candidates?.length}
          <div class="shortlist">
            <div class="label">Candidate shortlist</div>
            <div class="chips">
              {#each selected.decision.candidates as candidate (candidate.action_code + (candidate.source ?? ''))}
                <span class="chip mono" class:chosen={candidate.action_code === selected.decision.selected_action}>
                  {candidate.action_code}
                  {#if candidate.source} - {candidate.source}{/if}
                  {#if typeof candidate.score === 'number'} - {candidate.score.toFixed(2)}{/if}
                </span>
              {/each}
            </div>
          </div>
        {/if}
        {#if selected.reasonings?.length}
          <div class="shortlist">
            <div class="label">LLM / reasoning trace</div>
            <div class="reasonings">
              {#each selected.reasonings as item (item.id)}
                <div class="reasoning-item">
                  <div class="reasoning-head">
                    <span class="pill {item.available ? 'ok' : 'warn'}">{item.kind}</span>
                    {#if item.chosen_action}<span class="mono chosen">{item.chosen_action}</span>{/if}
                    <span class="mono prompt">v{item.prompt_version} - {item.model}</span>
                  </div>
                  <div class="reasoning-text mono">{item.reasoning_text}</div>
                </div>
              {/each}
            </div>
          </div>
        {/if}
        {#if selected.decision.evidence?.length}
          <div class="shortlist">
            <div class="label">Evidence</div>
            <ul class="evidence">
              {#each selected.decision.evidence as ev, i (i)}<li class="mono">{ev}</li>{/each}
            </ul>
          </div>
        {/if}
        {#if selected.decision.validators?.length}
          <div class="shortlist">
            <div class="label">Policy gate validators</div>
            <div class="validators">
              {#each selected.decision.validators as v (v.name)}
                <div class="validator">
                  <span class="pill {v.passed ? 'ok' : v.severity === 'CRITICAL' ? 'danger' : 'warn'}">
                    {v.passed ? 'pass' : v.severity}
                  </span>
                  <span class="mono name">{v.name}</span>
                  <span class="reason">{v.reason}</span>
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </div>
      <div class="card">
        <h3>Tool calls</h3>
        {#if selected.tool_calls.length === 0}
          <div class="empty">No tool calls recorded.</div>
        {:else}
          <div class="data-table-wrap">
            <table class="data-table tools">
              <thead>
                <tr><th>#</th><th>tool</th><th>status</th><th>duration</th><th>at</th><th>output</th></tr>
              </thead>
              <tbody>
                {#each selected.tool_calls as tc (tc.id)}
                  <tr>
                    <td class="mono small">{tc.seq}</td>
                    <td class="mono">{tc.tool_name}</td>
                    <td><span class="pill {tc.error ? 'danger' : 'ok'}">{tc.error ? 'fail' : 'ok'}</span></td>
                    <td class="mono">{tc.duration_ms} ms</td>
                    <td class="mono">{fmtTime(tc.created_at)}</td>
                    <td class="summary mono">{tc.error ?? summarize(tc.output, 70)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>
    {:else}
      <div class="card empty-card">
        <div class="empty">Select a decision to inspect its policy gate, candidate shortlist, and tool-call trace.</div>
      </div>
    {/if}

    <div class="card">
      <div class="head">
        <h3>Reasoning Stream</h3>
        <select bind:value={kindFilter}>
          <option value="">all kinds</option>
          <option value="agent">agent</option>
          <option value="healthcheck">healthcheck</option>
        </select>
      </div>
      {#if reasonings.length === 0}
        <div class="empty">No reasoning entries yet.</div>
      {:else}
        <div class="reasonings scroll">
          {#each reasonings as r (r.id)}
            <div class="reasoning-item" class:fallback={!r.available}>
              <div class="reasoning-head">
                <span class="pill {r.available ? 'ok' : 'warn'}">{r.kind}</span>
                {#if !r.available}<span class="pill danger">heuristic</span>{/if}
                {#if r.chosen_action}<span class="mono chosen">{r.chosen_action}</span>{/if}
                <span class="mono prompt">v{r.prompt_version} - {r.model}</span>
                <span class="mono small">{r.latency_ms}ms</span>
                <span class="time">{fmtRelative(r.created_at)}</span>
              </div>
              {#if r.reasoning_text}
                <p class="reasoning-text mono">{r.reasoning_text}</p>
              {/if}
              {#if r.error}
                <p class="reasoning-error mono">{r.error}</p>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </div>
  </div>
</section>

<style>
  .layout { display: grid; grid-template-columns: 420px minmax(0, 1fr); gap: 16px; align-items: start; }
  @media (max-width: 1100px) {
    .layout { grid-template-columns: 1fr; }
  }
  .detail-card > .card { min-width: 0; overflow: hidden; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
  .head h3 { margin: 0; }
  .head select { width: auto; }
  .empty { color: var(--text-3); font-size: 13px; padding: 12px 0; }
  .empty-card { min-height: 160px; display: grid; place-items: center; }
  .decisions-card .list { display: grid; gap: 8px; max-height: 78vh; }
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
  .row-top { display: flex; align-items: center; gap: 8px; }
  .row-mid { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 11px; color: var(--text-2); }
  .row-mid .cell { color: var(--text-1); }
  .row-mid .rc { color: var(--accent); }
  .row-mid .src { color: var(--text-3); font-size: 10px; }
  .row-mid .delta.up { color: var(--ok); }
  .row-mid .delta.down { color: var(--danger); }
  .action { color: var(--text-0); font-weight: 600; }
  .time { margin-left: auto; color: var(--text-3); font-size: 11px; }
  .detail-card { display: grid; gap: 16px; }
  .label { color: var(--text-3); font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; }
  .delta.up { color: var(--ok); }
  .delta.down { color: var(--danger); }
  .reason-line { margin-top: 10px; display: grid; gap: 4px; }
  .reason-line .mono { color: var(--text-1); font-size: 11px; }
  .shortlist { margin-top: 12px; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px; }
  .chip {
    padding: 3px 8px;
    border-radius: 4px;
    background: var(--bg-3);
    border: 1px solid var(--stroke);
    font-size: 11px;
  }
  .chip.chosen { background: rgba(90, 215, 181, 0.12); border-color: rgba(90, 215, 181, 0.4); color: var(--accent); }
  .evidence { margin: 4px 0 0 18px; padding: 0; color: var(--text-2); font-size: 11px; }
  .evidence li { margin-bottom: 2px; }
  .validators { display: grid; gap: 6px; margin-top: 4px; }
  .reasonings { display: grid; gap: 10px; max-height: 600px; min-width: 0; overflow-y: auto; }
  .reasoning-item {
    background: var(--bg-2);
    border: 1px solid var(--stroke);
    border-radius: var(--radius-sm);
    padding: 8px 10px;
    display: grid;
    gap: 4px;
    min-width: 0;
    overflow: hidden;
  }
  .reasoning-item.fallback { border-color: rgba(242, 192, 87, 0.35); }
  .reasoning-head { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .reasoning-head .prompt { color: var(--text-3); font-size: 11px; }
  .reasoning-head .small { color: var(--text-3); font-size: 10px; }
  .reasoning-head .chosen { color: var(--accent); font-size: 11px; }
  .reasoning-text {
    color: var(--text-1);
    font-size: 11px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
    overflow-wrap: anywhere;
    margin: 0;
  }
  .validator { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--text-2); flex-wrap: wrap; }
  .validator .name { color: var(--text-1); }
  .validator .reason { color: var(--text-2); font-size: 11px; }
  .tools .summary { color: var(--text-2); max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tools .small { font-size: 10px; }
  .reasoning-error {
    color: var(--danger);
    font-size: 11px;
    margin: 0;
    word-break: break-word;
    overflow-wrap: anywhere;
  }
</style>
