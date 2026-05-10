<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost, auth, hasRole } from '../../lib/api';
  import { fmtNumber, fmtPct } from '../../lib/format';

  interface HealthInfo {
    llm: { available: boolean; model: string; url: string; error: string | null };
    mlops: {
      available: boolean;
      tracking_uri: string;
      registry_uri: string | null;
      experiment_name: string;
      experiment_id: string | null;
      artifact_location: string | null;
      backend: string;
      warning: string | null;
      tracing_ready?: boolean;
      traces_present?: boolean | null;
    };
    store: string;
  }

  interface MlopsRun {
    run_id: string;
    status: string;
    start_time: number | null;
    end_time: number | null;
    artifact_uri: string;
    params: Record<string, string>;
    metrics: Record<string, number>;
    tags: Record<string, string>;
  }

  interface TokenUsage {
    input_tokens?: number;
    output_tokens?: number;
    total_tokens?: number;
  }

  interface MlopsTrace {
    trace_id: string | null;
    name: string | null;
    status: string;
    timestamp_ms: number | null;
    execution_time_ms: number | null;
    session_id: string | null;
    tags: Record<string, string>;
    token_usage: TokenUsage | null;
  }

  interface MlopsInfo {
    status: HealthInfo['mlops'] & { tracing_ready?: boolean; traces_present?: boolean | null };
    recent_runs: MlopsRun[];
    recent_traces: MlopsTrace[];
  }

  interface DriftColumn {
    column: string;
    live_mean: number;
    live_std: number;
    reference_mean: number | null;
    reference_std: number | null;
    z_score: number | null;
    drifted: boolean;
    elevated?: boolean;
    baseline_missing?: boolean;
  }

  interface DriftReport {
    columns: DriftColumn[];
    overall_drift: number;
    window_rows: number;
    baseline_missing?: boolean;
    baseline_unavailable?: boolean;
    scored_columns?: number;
    error?: string;
  }

  interface CacheStats {
    entries: number;
    total_hits: number;
  }

  interface PromptInfo {
    prompt_name: string;
    prompt_version: number;
    prompt_hash: string;
    created_at: string;
    size: number;
  }

  let health = $state<HealthInfo | null>(null);
  let drift = $state<DriftReport | null>(null);
  let cache = $state<CacheStats | null>(null);
  let prompts = $state<PromptInfo[]>([]);
  let mlops = $state<MlopsInfo | null>(null);
  let healthcheckResult = $state<any>(null);
  let probing = $state(false);
  let driftWindow = $state(300);
  let sectionErrors = $state<Record<string, string>>({});

  function setSectionError(section: string, value: string | null) {
    if (value) {
      sectionErrors = { ...sectionErrors, [section]: value };
      return;
    }
    const next = { ...sectionErrors };
    delete next[section];
    sectionErrors = next;
  }

  async function loadHealth() {
    try {
      health = await apiGet<HealthInfo>('/api/ops/health');
      setSectionError('health', null);
    } catch (e: any) {
      health = null;
      setSectionError('health', e?.message || String(e));
    }
  }

  async function loadDriftSection() {
    try {
      drift = await apiGet<DriftReport>(`/api/ops/drift?window=${driftWindow}`);
      setSectionError('drift', null);
    } catch (e: any) {
      drift = null;
      setSectionError('drift', e?.message || String(e));
    }
  }

  async function loadCacheStats() {
    try {
      cache = await apiGet<CacheStats>('/api/ops/llm-cache');
      setSectionError('cache', null);
    } catch (e: any) {
      cache = null;
      setSectionError('cache', e?.message || String(e));
    }
  }

  async function loadPromptRegistry() {
    try {
      const payload = await apiGet<{ items: PromptInfo[] }>('/api/ops/prompts');
      prompts = payload.items || [];
      setSectionError('prompts', null);
    } catch (e: any) {
      prompts = [];
      setSectionError('prompts', e?.message || String(e));
    }
  }

  async function loadMlops() {
    try {
      mlops = await apiGet<MlopsInfo>('/api/ops/mlops');
      setSectionError('mlops', null);
    } catch (e: any) {
      mlops = null;
      setSectionError('mlops', e?.message || String(e));
    }
  }

  const current = $derived($auth);

  async function loadAll() {
    await Promise.allSettled([
      loadHealth(),
      loadDriftSection(),
      loadCacheStats(),
      loadPromptRegistry(),
      loadMlops()
    ]);
  }

  async function reloadDrift() {
    await loadDriftSection();
  }

  async function probeLlm() {
    if (!hasRole(current.role, 'engineer')) return;
    probing = true;
    try {
      healthcheckResult = await apiPost<any>('/api/ops/llm-healthcheck', {});
    } catch (e: any) {
      setSectionError('healthcheck', e?.message || String(e));
    } finally {
      probing = false;
    }
  }

  onMount(() => {
    void loadAll();
  });
</script>

<section class="layout">
  {#if Object.keys(sectionErrors).length}
    <div class="card error-card">
      <div class="error-title">Some ops sections failed to load.</div>
      <div class="error-list">
        {#each Object.entries(sectionErrors) as [section, message] (section)}
          <div class="error mono">{section}: {message}</div>
        {/each}
      </div>
    </div>
  {/if}

  <div class="row">
    <div class="card grow">
      <h3>LLM Reasoner</h3>
      {#if health}
        <div class="health-grid">
          <div>
            <span class="label">status</span>
            <span class="pill {health.llm.available ? 'ok' : 'danger'}">
              {health.llm.available ? 'available' : 'offline'}
            </span>
          </div>
          <div><span class="label">model</span><span class="mono">{health.llm.model}</span></div>
          <div><span class="label">endpoint</span><span class="mono small">{health.llm.url}</span></div>
          <div><span class="label">store</span><span class="pill {health.store === 'ok' ? 'ok' : 'warn'}">{health.store}</span></div>
          {#if health.llm.error}
            <div class="full"><span class="label">last error</span><span class="error mono">{health.llm.error}</span></div>
          {/if}
        </div>
      {:else}
        <div class="skeleton" style="height:60px"></div>
      {/if}
      <div class="actions">
        <button
          disabled={probing || !hasRole(current.role, 'engineer')}
          onclick={probeLlm}
          title={!hasRole(current.role, 'engineer') ? 'Engineer role required' : ''}
        >{probing ? 'Probing...' : 'Run Healthcheck'}</button>
        <button onclick={loadAll}>Refresh All</button>
      </div>
      {#if healthcheckResult}
        <div class="hc-result mono">
          <div>available: <span class={healthcheckResult.available ? 'up' : 'down'}>{healthcheckResult.available}</span></div>
          <div>model: {healthcheckResult.model}</div>
          <div>latency: {healthcheckResult.latency_ms} ms</div>
          {#if healthcheckResult.error}
            <div class="error">error: {healthcheckResult.error}</div>
          {/if}
        </div>
      {/if}
    </div>

    <div class="card grow">
      <h3>MLOps Tracking</h3>
      {#if mlops}
        <div class="health-grid">
          <div>
            <span class="label">status</span>
            <span class="pill {mlops.status.available ? 'ok' : 'danger'}">
              {mlops.status.available ? 'available' : 'offline'}
            </span>
          </div>
          <div><span class="label">backend</span><span class="mono">{mlops.status.backend}</span></div>
          <div><span class="label">experiment</span><span class="mono">{mlops.status.experiment_name}</span></div>
          <div><span class="label">experiment id</span><span class="mono">{mlops.status.experiment_id ?? '-'}</span></div>
          <div class="full"><span class="label">tracking uri</span><span class="mono small">{mlops.status.tracking_uri}</span></div>
          <div class="full"><span class="label">artifact root</span><span class="mono small">{mlops.status.artifact_location ?? '-'}</span></div>
          {#if mlops.status.registry_uri}
            <div class="full"><span class="label">registry uri</span><span class="mono small">{mlops.status.registry_uri}</span></div>
          {/if}
          {#if mlops.status.warning}
            <div class="full"><span class="label">warning</span><span class="error mono">{mlops.status.warning}</span></div>
          {/if}
        </div>
      {:else}
        <div class="empty">MLflow status is unavailable right now.</div>
      {/if}
    </div>

    <div class="card grow">
      <h3>LLM Cache</h3>
      {#if cache}
        <div class="stats-grid">
          <div class="stat">
            <div class="stat-label">entries</div>
            <div class="stat-value">{cache.entries}</div>
          </div>
          <div class="stat">
            <div class="stat-label">total hits</div>
            <div class="stat-value">{cache.total_hits}</div>
          </div>
          <div class="stat">
            <div class="stat-label">hit ratio</div>
            <div class="stat-value">
              {cache.entries + cache.total_hits === 0
                ? '-'
                : fmtPct((cache.total_hits / Math.max(1, cache.total_hits + cache.entries)) * 100, 1)}
            </div>
          </div>
        </div>
      {:else}
        <div class="empty">Cache stats are unavailable right now.</div>
      {/if}
    </div>
  </div>

  <div class="card">
    <h3>Recent MLflow Runs</h3>
    {#if mlops && mlops.recent_runs.length}
      <div class="data-table-wrap">
        <table class="data-table prompts">
          <thead>
            <tr><th>run</th><th>status</th><th>action</th><th>decision</th><th>hybrid</th><th>llm</th></tr>
          </thead>
          <tbody>
            {#each mlops.recent_runs as run (run.run_id)}
              <tr>
                <td class="mono small">{run.run_id}</td>
                <td><span class="pill {run.status === 'FINISHED' ? 'ok' : 'warn'}">{run.status}</span></td>
                <td class="mono">{run.params.action_code ?? '-'}</td>
                <td class="mono">{run.params.decision ?? '-'}</td>
                <td class="mono">{run.metrics.hybrid_score ?? '-'}</td>
                <td class="mono">{run.metrics.llm_available ?? '-'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <div class="empty">No MLflow runs recorded yet.</div>
    {/if}
  </div>

  <div class="card">
    <div class="head">
      <h3>GenAI Traces</h3>
      <div class="head-controls">
        {#if mlops?.status?.tracing_ready}
          <span class="pill ok">tracing ready</span>
        {:else}
          <span class="pill danger">tracing offline</span>
        {/if}
        {#if mlops?.recent_traces?.length}
          <span class="mono small">{mlops.recent_traces.length} recent</span>
        {/if}
      </div>
    </div>
    {#if mlops && mlops.recent_traces.length}
      <div class="data-table-wrap">
        <table class="data-table traces">
          <thead>
            <tr><th>name</th><th>status</th><th>session</th><th>duration</th><th>tokens (in / out)</th><th>trace id</th></tr>
          </thead>
          <tbody>
            {#each mlops.recent_traces as trace (trace.trace_id)}
              <tr>
                <td class="mono">{trace.name ?? '-'}</td>
                <td><span class="pill {trace.status === 'OK' ? 'ok' : 'warn'}">{trace.status || '-'}</span></td>
                <td class="mono small">{trace.session_id ?? '-'}</td>
                <td class="mono">{trace.execution_time_ms != null ? `${fmtNumber(trace.execution_time_ms, 0)} ms` : '-'}</td>
                <td class="mono">
                  {#if trace.token_usage && (trace.token_usage.input_tokens != null || trace.token_usage.output_tokens != null)}
                    {trace.token_usage.input_tokens ?? '-'} / {trace.token_usage.output_tokens ?? '-'}
                  {:else}
                    -
                  {/if}
                </td>
                <td class="mono small">{trace.trace_id ?? '-'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <div class="empty">No traces emitted yet — they will appear here once the agent runs a decision.</div>
    {/if}
  </div>

  <div class="card">
    <div class="head">
      <h3>Drift</h3>
      <div class="head-controls">
        <select bind:value={driftWindow} onchange={reloadDrift}>
          <option value={50}>last 50 rows</option>
          <option value={150}>last 150 rows</option>
          <option value={300}>last 300 rows</option>
          <option value={1000}>last 1000 rows</option>
        </select>
        {#if drift}
          <span class="pill {drift.overall_drift >= 5 ? 'danger' : drift.overall_drift >= 3.5 ? 'warn' : 'ok'}">
            overall z = {drift.overall_drift}
          </span>
          {#if drift.baseline_unavailable || drift.baseline_missing}
            <span class="pill warn">baseline missing</span>
          {:else}
            <span class="pill ok">{drift.scored_columns ?? drift.columns.length} scored</span>
          {/if}
          <span class="mono small">window {drift.window_rows} rows</span>
        {/if}
      </div>
    </div>
    {#if drift?.error}
      <div class="error mono">drift: {drift.error}</div>
    {/if}
    {#if drift && drift.columns.length}
      <div class="data-table-wrap">
        <table class="data-table drift">
          <thead>
            <tr>
              <th>column</th>
              <th>live mean</th>
              <th>live std</th>
              <th>train mean</th>
              <th>train std</th>
              <th>|z|</th>
              <th>state</th>
            </tr>
          </thead>
          <tbody>
            {#each drift.columns as c (c.column)}
              <tr class:drifted={c.drifted}>
                <td class="mono">{c.column}</td>
                <td class="mono">{fmtNumber(c.live_mean, 3)}</td>
                <td class="mono">{fmtNumber(c.live_std, 3)}</td>
                <td class="mono">{fmtNumber(c.reference_mean, 3)}</td>
                <td class="mono">{fmtNumber(c.reference_std, 3)}</td>
                <td class="mono z" class:warn={c.elevated || ((c.z_score ?? 0) >= 3.5 && (c.z_score ?? 0) < 5)} class:danger={c.drifted || (c.z_score ?? 0) >= 5}>
                  {fmtNumber(c.z_score, 2)}
                </td>
                <td>
                  {#if c.baseline_missing}
                    <span class="pill warn">no baseline</span>
                  {:else if c.drifted}
                    <span class="pill danger">drifted</span>
                  {:else if c.elevated || (c.z_score ?? 0) >= 3.5}
                    <span class="pill warn">elevated</span>
                  {:else}
                    <span class="pill ok">stable</span>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <div class="empty">No drift signal yet.</div>
    {/if}
  </div>

  <div class="card">
    <h3>Prompt Registry</h3>
    {#if prompts.length === 0}
      <div class="empty">No prompts registered.</div>
    {:else}
      <div class="data-table-wrap">
        <table class="data-table prompts">
          <thead>
            <tr><th>name</th><th>version</th><th>hash</th><th>size</th></tr>
          </thead>
          <tbody>
            {#each prompts as p (p.prompt_name + p.prompt_version)}
              <tr>
                <td class="mono">{p.prompt_name}</td>
                <td class="mono">v{p.prompt_version}</td>
                <td class="mono small">{p.prompt_hash}</td>
                <td class="mono small">{p.size} B</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </div>
</section>

<style>
  .layout { display: grid; gap: 16px; }
  .row { display: flex; gap: 16px; flex-wrap: wrap; }
  .grow { flex: 1; min-width: 360px; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
  .head h3 { margin: 0; }
  .head-controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .head select { width: auto; }
  .empty { color: var(--text-3); font-size: 13px; padding: 12px 0; }
  .error-card { border-color: rgba(242, 108, 108, 0.5); }
  .error-title { color: var(--text-1); font-size: 13px; margin-bottom: 8px; }
  .error-list { display: grid; gap: 4px; }
  .error { color: var(--danger); font-size: 12px; }
  .label { color: var(--text-3); font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; display: block; margin-bottom: 2px; }
  .health-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; align-items: start; }
  .health-grid .full { grid-column: 1 / -1; }
  .health-grid .small { font-size: 11px; }
  .actions { display: flex; gap: 8px; margin-top: 12px; }
  .hc-result { margin-top: 10px; background: var(--bg-2); border: 1px solid var(--stroke); border-radius: var(--radius-sm); padding: 10px; font-size: 11px; display: grid; gap: 2px; }
  .up { color: var(--ok); }
  .down { color: var(--danger); }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
  .stat { background: var(--bg-2); border: 1px solid var(--stroke); border-radius: var(--radius-sm); padding: 10px; }
  .stat-label { color: var(--text-3); font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; }
  .stat-value { font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .small { font-size: 10px; }
  .drift tr.drifted { background: rgba(242, 108, 108, 0.04); }
  .z.warn { color: var(--warn); font-weight: 700; }
  .z.danger { color: var(--danger); font-weight: 700; }
</style>
