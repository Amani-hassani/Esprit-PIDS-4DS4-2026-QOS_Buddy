<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { apiGet, apiPost, auth, hasRole } from '../../lib/api';
  import { fmtRelative, pillClass, riskPill } from '../../lib/format';

  interface Approval {
    id: string;
    decision_id: string;
    created_at: string;
    sla_deadline: string;
    status: string;
    cell_id?: string;
    selected_action?: string;
    risk_level?: string;
    root_cause?: string;
    gate_reason?: string;
  }

  interface ApprovalDetail {
    approval: Approval & { actor?: string | null; reason?: string | null };
    decision: any;
    tool_calls: Array<{ id: string; seq: number; tool_name: string; duration_ms: number; error?: string | null; output: any }>;
    reasonings: Array<{ id: string; kind: string; available: boolean; model: string; created_at: string; reasoning_text: string; chosen_action?: string | null }>;
    tickets: Array<{ id: string; status: string; summary: string; created_at: string; evidence?: any }>;
  }

  let items = $state<Approval[]>([]);
  let selected = $state<ApprovalDetail | null>(null);
  let loading = $state(true);
  let busyId = $state<string | null>(null);
  let error = $state<string | null>(null);
  let reason = $state<string>('');

  const current = $derived($auth);
  const canApprove = $derived(hasRole(current.role, 'engineer'));

  async function load() {
    loading = true;
    try {
      const data = await apiGet<{ items: Approval[] }>('/api/approvals/pending?limit=50');
      items = data.items || [];
      if (!selected && items[0]) {
        await selectApproval(items[0].id);
      } else if (selected) {
        const stillThere = items.find((item) => item.id === selected?.approval.id);
        if (stillThere) await selectApproval(stillThere.id);
        else selected = null;
      }
      error = null;
    } catch (e: any) {
      error = e?.message || String(e);
    } finally {
      loading = false;
    }
  }

  async function selectApproval(id: string) {
    selected = await apiGet<ApprovalDetail>(`/api/approvals/${id}`);
    reason = '';
  }

  async function act(status: 'APPROVED' | 'REJECTED' | 'DEFERRED') {
    if (!selected) return;
    const trimmed = reason.trim();
    if ((status === 'REJECTED' || status === 'DEFERRED') && !trimmed) {
      error = `Provide a reason before ${status === 'REJECTED' ? 'rejecting' : 'deferring'}.`;
      return;
    }
    busyId = selected.approval.id;
    await tick();
    try {
      await apiPost(`/api/approvals/${selected.approval.id}/decide`, {
        status,
        reason: trimmed || undefined
      });
      reason = '';
      await load();
    } catch (e: any) {
      error = e?.message || String(e);
    } finally {
      busyId = null;
    }
  }

  onMount(() => {
    void load();
  });
</script>

<section class="layout">
  <div class="card list-card">
    <div class="head">
      <h3>Approval Queue</h3>
      <button class="ghost small" onclick={() => void load()} disabled={loading}>{loading ? '...' : 'Refresh'}</button>
    </div>
    {#if error}
      <div class="error mono">{error}</div>
    {/if}
    {#if items.length === 0}
      <div class="empty">No pending approvals.</div>
    {:else}
      <div class="queue scroll">
        {#each items as item (item.id)}
          <button class="queue-item" class:active={selected?.approval.id === item.id} onclick={() => void selectApproval(item.id)}>
            <div class="row1">
              <span class="pill {riskPill(item.risk_level)}">{(item.risk_level || '').toUpperCase() || '?'}</span>
              <span class="mono">{item.selected_action}</span>
            </div>
            <div class="row2 mono">
              <span>{item.cell_id}</span>
              <span>{item.root_cause}</span>
            </div>
            <div class="row3">{item.gate_reason}</div>
          </button>
        {/each}
      </div>
    {/if}
  </div>

  <div class="detail">
    {#if selected}
      <div class="card">
        <div class="head">
          <div>
            <h3>Approval Detail</h3>
            <div class="mono small">{selected.approval.id} / {selected.approval.decision_id}</div>
          </div>
          <span class="pill {pillClass(selected.decision?.gate_decision)}">{selected.decision?.gate_decision}</span>
        </div>

        <div class="meta">
          <div><span class="label">cell</span><span class="mono">{selected.decision?.cell_id}</span></div>
          <div><span class="label">action</span><span class="mono">{selected.decision?.selected_action}</span></div>
          <div><span class="label">source</span><span class="mono">{selected.decision?.selected_source}</span></div>
          <div><span class="label">risk</span><span class="pill {riskPill(selected.decision?.risk_level)}">{selected.decision?.risk_level}</span></div>
          <div><span class="label">root cause</span><span class="mono">{selected.decision?.root_cause}</span></div>
          <div><span class="label">created</span><span class="mono">{fmtRelative(selected.approval.created_at)}</span></div>
        </div>

        <label class="reason-field">
          <span class="label">Decision rationale<span class="hint"> - required for reject or defer</span></span>
          <textarea
            bind:value={reason}
            rows="2"
            maxlength="500"
            placeholder="Explain why you're approving, deferring, or rejecting this action..."
          ></textarea>
        </label>

        <div class="actions">
          <button onclick={() => void act('DEFERRED')} disabled={busyId === selected.approval.id}>Defer</button>
          <button class="danger" onclick={() => void act('REJECTED')} disabled={busyId === selected.approval.id}>Reject</button>
          <button
            class="accent"
            onclick={() => void act('APPROVED')}
            disabled={busyId === selected.approval.id || !canApprove}
            title={!canApprove ? 'Engineer role required' : ''}
          >Approve and Execute</button>
        </div>
      </div>

      <div class="card">
        <h3>LLM Reasoning</h3>
        {#if selected.reasonings.length}
          {#each selected.reasonings as item (item.id)}
            <div class="reason-block">
              <div class="reason-head">
                <span class="pill {item.available ? 'ok' : 'warn'}">{item.kind}</span>
                {#if item.chosen_action}<span class="mono">{item.chosen_action}</span>{/if}
                <span class="mono small">{item.model}</span>
                <span class="mono small">{fmtRelative(item.created_at)}</span>
              </div>
              <div class="reason-text mono">{item.reasoning_text}</div>
            </div>
          {/each}
        {:else}
          <div class="empty">No reasoning entries attached.</div>
        {/if}
      </div>

      <div class="card">
        <h3>Tool Trace</h3>
        {#if selected.tool_calls.length}
          <div class="data-table-wrap">
            <table class="data-table">
              <thead><tr><th>#</th><th>tool</th><th>ms</th><th>result</th></tr></thead>
              <tbody>
                {#each selected.tool_calls as item (item.id)}
                  <tr>
                    <td class="mono">{item.seq}</td>
                    <td class="mono">{item.tool_name}</td>
                    <td class="mono">{item.duration_ms}</td>
                    <td class="mono">{item.error ?? 'ok'}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {:else}
          <div class="empty">No tool calls recorded.</div>
        {/if}
      </div>

      <div class="card">
        <h3>Tickets</h3>
        {#if selected.tickets.length}
          <div class="tickets">
            {#each selected.tickets as item (item.id)}
              <div class="ticket">
                <div class="ticket-head">
                  <span class="pill {item.status === 'OPEN' ? 'warn' : 'ok'}">{item.status}</span>
                  <span class="mono">{item.evidence?.ticket_key ?? item.id}</span>
                  <span class="mono small">{fmtRelative(item.created_at)}</span>
                </div>
                <div>{item.summary}</div>
                {#if item.evidence?.reasoning}
                  <div class="mono small">{item.evidence.reasoning}</div>
                {/if}
              </div>
            {/each}
          </div>
        {:else}
          <div class="empty">No tickets attached.</div>
        {/if}
      </div>
    {:else}
      <div class="card empty">Select an approval to inspect reasoning, tool trace, and tickets.</div>
    {/if}
  </div>
</section>

<style>
  .layout { display: grid; grid-template-columns: 380px 1fr; gap: 16px; align-items: start; }
  .detail { display: grid; gap: 16px; }
  .head { display: flex; justify-content: space-between; align-items: start; gap: 12px; }
  .small { font-size: 10px; color: var(--text-3); }
  .list-card { display: grid; gap: 12px; }
  .queue { display: grid; gap: 8px; max-height: 760px; }
  .queue-item { background: var(--bg-2); border: 1px solid var(--stroke); border-radius: var(--radius-sm); padding: 10px; display: grid; gap: 6px; text-align: left; }
  .queue-item.active { border-color: var(--accent); box-shadow: inset 0 0 0 1px rgba(122, 166, 255, 0.18); }
  .row1, .row2, .reason-head, .ticket-head, .actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .row3 { color: var(--text-2); font-size: 12px; }
  .meta { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
  .label { color: var(--text-3); font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; display: block; margin-bottom: 4px; }
  .reason-block, .ticket { display: grid; gap: 8px; padding: 10px; border: 1px solid var(--stroke); border-radius: var(--radius-sm); background: var(--bg-2); min-width: 0; overflow: hidden; }
  .reason-text {
    white-space: pre-wrap;
    word-break: break-word;
    overflow-wrap: anywhere;
    line-height: 1.6;
    font-size: 12px;
    max-height: 220px;
    overflow-y: auto;
  }
  .reason-field { display: grid; gap: 6px; margin-top: 4px; }
  .reason-field .hint { color: var(--text-3); font-size: 10px; text-transform: none; letter-spacing: 0; margin-left: 6px; }
  .reason-field textarea { resize: vertical; min-height: 56px; font-family: var(--font-sans); }
  .tickets { display: grid; gap: 8px; }
  .empty { color: var(--text-3); }
  .error { color: var(--danger); font-size: 12px; }
  @media (max-width: 1100px) {
    .layout { grid-template-columns: 1fr; }
    .meta { grid-template-columns: 1fr 1fr; }
  }
</style>
