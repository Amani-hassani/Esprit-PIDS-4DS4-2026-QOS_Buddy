<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { buildLinePath, domainPalette, severityPalette } from '$lib/charts';

  type TabId = 'overview' | 'fleet' | 'node' | 'live' | 'memory' | 'models';
  type DomainHint = { domain: string; score: number };
  type Driver = { feature: string; value: number; direction: string };
  type Incident = {
    incident_id?: string;
    document?: string;
    distance?: number | null;
    metadata?: { incident_type?: string; severity?: string; node_id?: string };
  };
  type SystemHealth = {
    status: string;
    llm: { available: boolean; configured_model?: string; error?: string };
    rag: { incident_count?: number };
    models: { ready: boolean; artifact_count: number; required_artifact_count: number };
    storage: {
      total_predictions_7d: number;
      status?: string;
      using_fallback?: boolean;
      active_db_path?: string;
      fallback_reason?: string;
    };
    mlflow?: {
      available?: boolean;
      status?: string;
      ui_url?: string;
      tracking_uri?: string;
      using_fallback?: boolean;
      db_path?: string;
      artifact_root?: string;
      fallback_reason?: string | null;
      last_error?: string;
    };
    monitoring?: {
      status?: string;
      row_count?: number;
      node_count?: number;
      latest_timestamp?: string;
      cadence_seconds?: number;
      history_retained?: boolean;
    };
  };
  type Prediction = {
    database_id?: number | null;
    node_id: string;
    timestamp: string;
    severity: string;
    primary_metric_name: string;
    primary_metric_probability: number;
    primary_metric_eta_min?: number | null;
    capacity_exhaustion_eta_min?: number | null;
    confidence_score: number;
    llm_summary?: string;
    operator_brief?: string;
    explanation?: string;
    risk_probs: Record<string, number>;
    trust_signals: Record<string, number | string | null>;
    temporal_signals: Record<string, number | string | null>;
    domain_hints: DomainHint[];
    evidence_summary: Record<string, string | number>;
    top_3_drivers: Record<string, Driver[]>;
    shap_features?: Record<string, Driver[]>;
    fleet_context: {
      fleet_rank?: number;
      nodes_in_batch?: number;
      pattern_scope?: string;
      peer_nodes?: string[];
      dominant_domains?: Record<string, number>;
    };
    retrieved_incidents: Incident[];
    feedback_summary?: { count?: number };
    eta_per_target?: Record<string, number>;
    decision_thresholds_used?: Record<string, number>;
    recommended_action?: string;
    capacity_exhaustion_eta_min?: number | null;
    eta_debug_status?: string;
    eta_debug_reason?: string;
    eta_debug_max_forecast?: number | null;
    eta_debug_threshold?: number | null;
    eta_debug_horizon_min?: number | null;
    llm_used?: boolean;
    model_metadata?: Record<string, number | string | null>;
  };
  type SummaryPayload = {
    system_health: SystemHealth;
    stats: {
      total_predictions: number;
      severity_distribution: Record<string, number>;
      average_risk_by_target: Record<string, number>;
      average_confidence?: number;
      domain_distribution?: Record<string, number>;
      top_nodes?: Record<string, number>;
    };
    recent_predictions: Prediction[];
    priority_predictions: Prediction[];
    latest_by_node: Prediction[];
    targets: string[];
  };
  type FleetPayload = {
    nodes: Array<{
      node_id: string;
      severity: string;
      primary_metric: string;
      primary_probability: number;
      confidence_score: number;
      primary_eta_min: number | null;
      timestamp: string;
      top_domain: string;
      trend: string;
      fleet_rank: number | null;
      risk_probs: Record<string, number>;
    }>;
    severity_distribution: Record<string, number>;
    domain_distribution: Record<string, number>;
    average_risk_by_target: Record<string, number>;
    average_confidence: number;
    node_count: number;
  };
  type TimeseriesPayload = {
    node_id: string;
    target: string;
    points: number;
    timestamps: string[];
    primary_probability: number[];
    confidence: number[];
    severity: string[];
    target_probability: number[];
    per_target: Record<string, number[]>;
    eta_minutes: Array<number | null>;
  };
  type DriverFreqPayload = {
    node_id: string;
    target: string;
    history_size: number;
    drivers: Array<{ feature: string; frequency: number; avg_impact: number }>;
  };
  type ModelOverview = {
    model_status: { ready: boolean; artifact_count: number; required_artifact_count: number; missing_artifacts: string[] };
    ensemble_weights: { xgboost: number; lstm: number };
    lstm: { window: number; hyperparameters: Record<string, unknown> };
    xgboost: { targets: string[]; hyperparameters: Record<string, unknown> };
    prophet: Record<string, unknown>;
    shap: Record<string, unknown>;
    rag: Record<string, unknown>;
    llm: Record<string, unknown>;
    mlflow?: Record<string, unknown>;
    monitoring?: Record<string, unknown>;
    artifacts: Array<{ name: string; size_kb: number; modified_epoch: number }>;
  };
  type IncidentSamplePayload = { count: number; incidents: Array<Record<string, string | number | null>> };
  type AutonomousRunPayload = {
    prediction_count: number;
    processed_nodes: string[];
    skipped_nodes: Array<{ node_id: string; reason: string }>;
    monitoring_seed?: { row_count?: number; node_count?: number; latest_timestamp?: string; status?: string };
  };
  type QosFeedRow = Record<string, number | string>;

  let summary: SummaryPayload | null = null;
  let fleet: FleetPayload | null = null;
  let timeseries: TimeseriesPayload | null = null;
  let drivers: DriverFreqPayload | null = null;
  let modelOverview: ModelOverview | null = null;
  let incidentSample: IncidentSamplePayload | null = null;
  let qosFeed: QosFeedRow[] = [];
  let lifecycleResult: AutonomousRunPayload | null = null;
  let loading = true;
  let busy = false;
  let feedbackBusy = false;
  let error = '';
  let lastRefresh = '';
  let autoRefresh = true;
  let refreshTimer: ReturnType<typeof setInterval> | null = null;
  let auxiliaryRefreshTimer: ReturnType<typeof setInterval> | null = null;
  let workspaceLoadInFlight = false;
  let auxiliaryLoadInFlight = false;
  let selectedNodeId = '';
  let activeTarget = '';
  let activeTab: TabId = 'overview';
  let selectedNodeTouched = false;
  let activeTargetTouched = false;

  const tabs: Array<{ id: TabId; label: string }> = [
    { id: 'overview', label: 'Command' },
    { id: 'fleet', label: 'Incidents' },
    { id: 'node', label: 'Triage' },
    { id: 'live', label: 'Telemetry' },
    { id: 'memory', label: 'Knowledge' },
    { id: 'models', label: 'Runtime' },
  ];

  const AUTO_REFRESH_MS = 5000;
  const AUXILIARY_REFRESH_MS = 30000;

  function withNoCache(path: string) {
    const separator = path.includes('?') ? '&' : '?';
    return `${path}${separator}_ts=${Date.now()}`;
  }

  async function fetchJson<T>(path: string, init?: RequestInit, timeoutMs = 12000): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let response: Response;
    try {
      response = await fetch(withNoCache(path), {
        cache: 'no-store',
        ...init,
        signal: controller.signal,
        headers: {
          ...(init?.headers ?? {}),
          'Cache-Control': 'no-cache',
          Pragma: 'no-cache',
        },
      });
    } finally {
      clearTimeout(timer);
    }
    if (!response.ok) throw new Error(`${path} -> ${response.status}`);
    return response.json();
  }

  function predictionForNode(nodeId: string): Prediction | null {
    if (!summary) return null;
    return (
      summary.latest_by_node.find((item) => item.node_id === nodeId) ??
      summary.priority_predictions.find((item) => item.node_id === nodeId) ??
      null
    );
  }

  async function loadAuxiliaryWorkspace() {
    if (auxiliaryLoadInFlight) return;
    auxiliaryLoadInFlight = true;
    try {
      const [nextModels, nextIncidents] = await Promise.all([
        fetchJson<ModelOverview>('/api/dashboard/models', undefined, 30000),
        fetchJson<IncidentSamplePayload>('/api/dashboard/incidents/sample?limit=8', undefined, 15000),
      ]);
      modelOverview = nextModels;
      incidentSample = nextIncidents;
    } catch (err) {
      console.warn('auxiliary workspace load failed', err);
    } finally {
      auxiliaryLoadInFlight = false;
    }
  }

  async function loadWorkspace(showSpinner = true, loadAuxiliary = false) {
    if (workspaceLoadInFlight) return;
    workspaceLoadInFlight = true;
    if (showSpinner) loading = true;
    error = '';
    try {
      const [nextSummary, nextFleet] = await Promise.all([
        fetchJson<SummaryPayload>('/api/dashboard/summary', undefined, 30000),
        fetchJson<FleetPayload>('/api/dashboard/fleet', undefined, 15000),
      ]);
      summary = nextSummary;
      fleet = nextFleet;
      lastRefresh = new Date().toLocaleTimeString();

      if (!selectedNodeId || !selectedNodeTouched) {
        selectedNodeId = nextSummary.priority_predictions[0]?.node_id ?? nextSummary.latest_by_node[0]?.node_id ?? '';
      }
      if (!activeTarget || !activeTargetTouched) {
        activeTarget = predictionForNode(selectedNodeId)?.primary_metric_name ?? nextSummary.targets[0] ?? '';
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load dashboard';
    } finally {
      workspaceLoadInFlight = false;
      loading = false;
    }

    if (!error) {
      if (selectedNodeId) {
        void loadNodeDetail();
      }
      if (loadAuxiliary) {
        void loadAuxiliaryWorkspace();
      }
    }
  }

  async function loadNodeDetail() {
    if (!selectedNodeId) return;
    const target = currentTarget;
    try {
      const timelineParams = new URLSearchParams({ node_id: selectedNodeId, target, limit: '120' });
      const driverParams = new URLSearchParams({ node_id: selectedNodeId, target, days_back: '14' });
      const qosParams = new URLSearchParams({ node_id: selectedNodeId, limit: '120' });
      const [nextTimeseries, nextDrivers, nextFeed] = await Promise.all([
        fetchJson<TimeseriesPayload>(`/api/dashboard/timeseries?${timelineParams}`),
        fetchJson<DriverFreqPayload>(`/api/dashboard/drivers?${driverParams}`),
        fetchJson<{ rows: QosFeedRow[] }>(`/api/dashboard/qos-feed?${qosParams}`),
      ]);
      timeseries = nextTimeseries;
      drivers = nextDrivers;
      qosFeed = nextFeed.rows ?? [];
    } catch (err) {
      console.warn('node detail load failed', err);
    }
  }

  async function runAutonomousCycle() {
    busy = true;
    error = '';
    try {
      lifecycleResult = await fetchJson<AutonomousRunPayload>('/api/ops/autonomous/run-once', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          window_rows: 60,
          generate_llm: true,
          persist: true,
          inject_monitoring: true,
          monitoring_rows: 120,
        }),
      });
      if (!selectedNodeId) {
        selectedNodeId = lifecycleResult.processed_nodes[0] ?? selectedNodeId;
      }
      await loadWorkspace(false, true);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Live cycle failed';
    } finally {
      busy = false;
    }
  }

  async function syncIncidents() {
    busy = true;
    error = '';
    try {
      await fetchJson('/api/monitoring/incidents/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ replace: false }),
      });
      await loadWorkspace(false, true);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Incident sync failed';
    } finally {
      busy = false;
    }
  }

  async function submitFeedback(predictionId: number | null | undefined, type: string) {
    if (!predictionId) return;
    feedbackBusy = true;
    try {
      await fetchJson(`/api/predictions/${predictionId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback_type: type, outcome_status: type, notes: '' }),
      });
      await loadWorkspace(false, true);
    } catch (err) {
      console.warn('feedback failed', err);
    } finally {
      feedbackBusy = false;
    }
  }

  function setAutoRefresh(enabled: boolean) {
    autoRefresh = enabled;
    if (refreshTimer) clearInterval(refreshTimer);
    if (auxiliaryRefreshTimer) clearInterval(auxiliaryRefreshTimer);
    refreshTimer = null;
    auxiliaryRefreshTimer = null;
    if (autoRefresh) {
      refreshTimer = setInterval(() => {
        if (!busy && !feedbackBusy) {
          void loadWorkspace(false, false);
        }
      }, AUTO_REFRESH_MS);
      auxiliaryRefreshTimer = setInterval(() => {
        if (!busy && !feedbackBusy) {
          void loadAuxiliaryWorkspace();
        }
      }, AUXILIARY_REFRESH_MS);
    }
  }

  function toggleAutoRefresh() {
    setAutoRefresh(!autoRefresh);
  }

  function formatPct(value?: number | null) {
    return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 100)}%` : 'n/a';
  }

  function formatEta(value?: number | null) {
    return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)} min` : 'n/a';
  }

  function formatNumber(value?: number | string | null, digits = 2) {
    if (value === null || value === undefined) return 'n/a';
    const number = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) : String(value);
  }

  function formatLabel(value: string) {
    return value.replace(/_risk$/, '').replace(/_/g, ' ');
  }

  function formatSigned(value: number, digits = 3) {
    if (!Number.isFinite(value)) return 'n/a';
    const sign = value > 0 ? '+' : '';
    return `${sign}${value.toFixed(digits)}`;
  }

  function trendClass(label: string) {
    if (label === 'rising') return 'high';
    if (label === 'cooling') return 'normal';
    return 'watch';
  }

  function prophetStatusClass(status: string) {
    if (status === 'ok') return 'normal';
    if (status === 'no_crossing') return 'watch';
    return 'warning';
  }

  function prophetStatusLabel(status: string) {
    if (status === 'ok') return 'crossing projected';
    if (status === 'no_crossing') return 'no crossing';
    if (status === 'unavailable') return 'unavailable';
    return status || 'pending';
  }

  function shortTime(value?: string) {
    if (!value) return 'n/a';
    try {
      return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return value;
    }
  }

  function severityClass(value = 'unknown') {
    return value.toLowerCase();
  }

  function incidentLabel(incident: Incident) {
    return incident.metadata?.incident_type ?? incident.incident_id ?? 'historical incident';
  }

  function sortObjectByValue(obj?: Record<string, number>) {
    return Object.entries(obj ?? {})
      .filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
      .sort((left, right) => Number(right[1]) - Number(left[1]));
  }

  function selectNode(nodeId: string) {
    selectedNodeTouched = true;
    selectedNodeId = nodeId;
    activeTarget = predictionForNode(nodeId)?.primary_metric_name ?? activeTarget;
    activeTargetTouched = false;
    activeTab = 'node';
    void loadNodeDetail();
  }

  function setTarget(target: string) {
    activeTargetTouched = true;
    activeTarget = target;
    void loadNodeDetail();
  }

  $: priorityPredictions = summary?.priority_predictions ?? [];
  $: topQueuePredictions = priorityPredictions.slice(0, 3);
  $: latestNodes = summary?.latest_by_node ?? [];
  $: selectedPrediction = predictionForNode(selectedNodeId) ?? priorityPredictions[0] ?? latestNodes[0] ?? null;
  $: currentTarget = activeTarget || selectedPrediction?.primary_metric_name || summary?.targets?.[0] || '';
  $: criticalNodeCount = latestNodes.filter((item) => ['critical', 'high'].includes(item.severity)).length;
  $: criticalOnlyCount = latestNodes.filter((item) => item.severity === 'critical').length;
  $: highOnlyCount = latestNodes.filter((item) => item.severity === 'high').length;
  $: overviewPrediction = selectedPrediction ?? priorityPredictions[0] ?? null;
  $: overviewNarrative =
    overviewPrediction?.operator_brief || overviewPrediction?.llm_summary || overviewPrediction?.explanation || 'Run a live cycle to populate LLM reasoning.';
  $: overviewDrivers =
    overviewPrediction?.shap_features?.[overviewPrediction.primary_metric_name] ??
    overviewPrediction?.top_3_drivers?.[overviewPrediction.primary_metric_name] ??
    [];
  $: overviewRiskMatrix = sortObjectByValue(overviewPrediction?.risk_probs);
  $: overviewEtaMatrix = Object.entries(overviewPrediction?.eta_per_target ?? {})
    .map(([target, value]) => [target, Number(value)] as [string, number])
    .sort((left, right) => {
      const lFinite = Number.isFinite(left[1]);
      const rFinite = Number.isFinite(right[1]);
      if (lFinite && !rFinite) return -1;
      if (!lFinite && rFinite) return 1;
      return left[1] - right[1];
    });
  $: overviewTemporal = overviewPrediction?.temporal_signals ?? {};
  $: overviewTrust = overviewPrediction?.trust_signals ?? {};
  $: overviewTrend = String(overviewTemporal.trend_label ?? 'stable');
  $: overviewVelocity = Number(overviewTemporal.risk_velocity ?? 0);
  $: overviewAcceleration = Number(overviewTemporal.risk_acceleration ?? 0);
  $: overviewPersistence = Number(overviewTemporal.risk_persistence ?? 0);
  $: overviewAgreement = Number(overviewTrust.model_agreement_score ?? 0);
  $: overviewStability = Number(overviewTrust.prediction_stability ?? 0);
  $: overviewDrift = Number(overviewTrust.drift_score ?? 0);
  $: overviewQuality = Number(overviewTrust.data_quality_score ?? 0);
  $: overviewCapacityEta = Number(overviewPrediction?.capacity_exhaustion_eta_min ?? Number.POSITIVE_INFINITY);
  $: overviewProphetStatus = String(overviewPrediction?.eta_debug_status ?? '');
  $: overviewProphetThreshold = overviewPrediction?.eta_debug_threshold ?? null;
  $: overviewProphetMaxForecast = overviewPrediction?.eta_debug_max_forecast ?? null;
  $: overviewProphetHorizon = overviewPrediction?.eta_debug_horizon_min ?? null;
  $: overviewDomains = overviewPrediction?.domain_hints ?? [];
  $: overviewMemoryCount = Number(overviewPrediction?.evidence_summary?.incident_count ?? (overviewPrediction?.retrieved_incidents?.length ?? 0));
  $: overviewSimilarity = Number(overviewPrediction?.evidence_summary?.closest_incident_similarity_pct ?? 0);
  $: overviewClosestIncident = String(overviewPrediction?.evidence_summary?.closest_incident_type ?? '');
  $: overviewFeatureCount = Number(overviewPrediction?.model_metadata?.feature_count ?? 0);
  $: overviewWindowRows = Number(overviewPrediction?.model_metadata?.input_window_rows ?? 0);
  $: etaStatusLabel =
    overviewPrediction?.eta_debug_status === 'ok'
      ? 'Forecast ready'
      : overviewPrediction?.eta_debug_status === 'no_crossing'
        ? 'No threshold crossing'
        : overviewEtaMatrix.length
          ? 'Forecast ready'
          : 'Forecast unavailable';
  $: llmNarrativeMode = selectedPrediction?.operator_brief || selectedPrediction?.llm_summary ? 'llm narrative' : 'rule fallback';
  $: artifactStatusLabel = `${summary?.system_health?.models?.artifact_count ?? 0}/${summary?.system_health?.models?.required_artifact_count ?? 0} artifacts`;
  $: storageMode = summary?.system_health?.storage?.using_fallback ? 'temp fallback db' : 'workspace db';
  $: storageIssue = summary?.system_health?.storage?.fallback_reason ?? '';
  $: timelinePath = buildLinePath(timeseries?.target_probability ?? [], 680, 220, 8);
  $: confidencePath = buildLinePath(timeseries?.confidence ?? [], 680, 76, 8);
  $: timelineCurrentProbability = timeseries?.target_probability?.length ? Number(timeseries.target_probability[timeseries.target_probability.length - 1] ?? 0) : 0;
  $: timelineCurrentConfidence = timeseries?.confidence?.length ? Number(timeseries.confidence[timeseries.confidence.length - 1] ?? 0) : 0;
  $: timelineCurrentEta = timeseries?.eta_minutes?.length ? timeseries.eta_minutes[timeseries.eta_minutes.length - 1] : null;
  $: timelineThreshold = Number(selectedPrediction?.decision_thresholds_used?.[currentTarget] ?? 0.5);
  $: timelineThresholdY = 8 + (1 - Math.max(0, Math.min(1, timelineThreshold))) * 204;
  $: timelineLatestPoint = timelinePath.points.length ? timelinePath.points[timelinePath.points.length - 1] : null;
  $: confidenceLatestPoint = confidencePath.points.length ? confidencePath.points[confidencePath.points.length - 1] : null;
  $: liveMetricKeys = ['latency_ms', 'jitter_ms', 'throughput_mbps', 'packet_loss_pct', 'mos_estimate', 'queue_length'];
  $: latestQosRow = qosFeed[qosFeed.length - 1] ?? null;
  $: liveNodeCount = new Set(qosFeed.map((row) => String(row.node_id ?? ''))).size;

  onMount(() => {
    void loadWorkspace(true, true);
    setAutoRefresh(true);
  });

  onDestroy(() => {
    if (refreshTimer) clearInterval(refreshTimer);
    if (auxiliaryRefreshTimer) clearInterval(auxiliaryRefreshTimer);
  });
</script>

<svelte:head>
  <title>QoS Buddy | Prediction NOC</title>
</svelte:head>

<div class="app-shell">
  <aside class="sidebar">
    <div class="brand">
      <div class="logo">QB</div>
      <div>
        <div class="brand-name">QoS Buddy</div>
        <div class="brand-sub">Prediction NOC Console</div>
      </div>
    </div>

    <nav class="nav">
      {#each tabs as tab}
        <button class:active={activeTab === tab.id} on:click={() => (activeTab = tab.id)}>
          <span class="dot"></span>
          <span>{tab.label}</span>
        </button>
      {/each}
    </nav>

    <section class="status-panel">
      <div class="status-top">
        <span class={`pill ${summary?.system_health?.status ?? 'unknown'}`}>{summary?.system_health?.status ?? 'unknown'}</span>
        <span class="muted">sync {lastRefresh || '--'}</span>
      </div>
      <div class="status-metric">
        <span>MLflow</span>
        <strong>{summary?.system_health?.mlflow?.status ?? 'pending'}</strong>
      </div>
      <div class="status-metric">
        <span>Monitoring rows</span>
        <strong>{summary?.system_health?.monitoring?.row_count ?? 0}</strong>
      </div>
      <div class="status-metric">
        <span>Predictions 7d</span>
        <strong>{summary?.system_health?.storage?.total_predictions_7d ?? 0}</strong>
      </div>
      <div class="status-metric">
        <span>Storage</span>
        <strong>{storageMode}</strong>
      </div>
      <div class="status-row">
        <span class="muted">Auto refresh</span>
        <button class="link-button" on:click={toggleAutoRefresh}>{autoRefresh ? 'on / 5s' : 'off'}</button>
      </div>
    </section>
  </aside>

  <main class="workspace">
    <header class="topbar">
      <div>
        <div class="eyebrow">QoS prediction agent</div>
        <h1>NOC risk command center</h1>
        <p class="lede">
          Dispatch the active queue, triage a node, inspect live telemetry, and verify the result against saved artifacts and
          incident-aligned replay data.
        </p>
      </div>
      <div class="toolbar">
        <button class="ghost" on:click={syncIncidents} disabled={busy}>Sync incidents</button>
        <button class="ghost" on:click={() => loadWorkspace(false, true)} disabled={busy}>Refresh</button>
        <button class="primary" on:click={runAutonomousCycle} disabled={busy}>
          {busy ? 'Running...' : 'Run live cycle + seed monitoring'}
        </button>
      </div>
    </header>

    {#if error}
      <div class="error-banner">
        <strong>Backend issue</strong>
        <span>{error}</span>
      </div>
    {/if}

    {#if lifecycleResult}
      <div class="info-banner">
        <span>
          Live cycle stored {lifecycleResult.monitoring_seed?.row_count ?? 0} replay rows at 30-second cadence and produced {lifecycleResult.prediction_count} predictions.
        </span>
      </div>
    {/if}

    {#if loading}
      <div class="loading-state">
        <div class="spinner"></div>
        <p>Loading operational workspace...</p>
      </div>
    {:else}
      {#if activeTab === 'overview'}
        {#if !overviewPrediction}
          <section class="page-grid">
            <article class="card span-3">
              <div class="empty-state">Run a live cycle to produce a prediction packet.</div>
            </article>
          </section>
        {:else}
          <section class="page-grid hero-layout">
            <article class="card hero-card span-2">
              <div class="section-tag">Prediction packet</div>
              <div class="hero-head">
                <div class="hero-id">
                  <span class="muted">node</span>
                  <h2>{overviewPrediction.node_id}</h2>
                  <span class={`pill ${severityClass(overviewPrediction.severity)}`}>{overviewPrediction.severity}</span>
                  <span class="pill neutral">{formatLabel(overviewPrediction.primary_metric_name)}</span>
                </div>
                <div class="hero-meta muted">
                  <span>{shortTime(overviewPrediction.timestamp)}</span>
                  <span>·</span>
                  <span>{overviewFeatureCount} features</span>
                  <span>·</span>
                  <span>{overviewWindowRows}-row window</span>
                </div>
              </div>

              <div class="hero-stats">
                <div class="hero-stat">
                  <span>Primary risk</span>
                  <strong>{formatPct(overviewPrediction.primary_metric_probability)}</strong>
                </div>
                <div class="hero-stat">
                  <span>Confidence</span>
                  <strong>{formatPct(overviewPrediction.confidence_score)}</strong>
                </div>
                <div class="hero-stat">
                  <span>ETA</span>
                  <strong>{formatEta(overviewPrediction.primary_metric_eta_min ?? overviewPrediction.capacity_exhaustion_eta_min)}</strong>
                </div>
                <div class="hero-stat">
                  <span>Trend</span>
                  <strong class={`trend trend-${trendClass(overviewTrend)}`}>{overviewTrend}</strong>
                </div>
              </div>

              <div class="hero-action">
                <div class="mini-title">Recommended action</div>
                <p class="panel-copy">{overviewPrediction.recommended_action || 'No action has been proposed yet.'}</p>
              </div>

              <div class="hero-narrative">
                <div class="mini-title">{overviewPrediction.llm_used ? 'LLM brief' : 'Rule-based brief'}</div>
                <p class="panel-copy">{overviewNarrative}</p>
              </div>
            </article>

            <article class="card">
              <div class="section-tag">Queue</div>
              <div class="card-head">
                <h2>Priority queue</h2>
                <span class="hint">{criticalOnlyCount} critical · {highOnlyCount} high</span>
              </div>
              <div class="queue-list">
                {#each topQueuePredictions as item, index}
                  <button class="queue-card" class:selected={selectedNodeId === item.node_id} on:click={() => selectNode(item.node_id)}>
                    <div class="queue-row">
                      <strong>#{index + 1} {item.node_id}</strong>
                      <span class={`pill ${severityClass(item.severity)}`}>{item.severity}</span>
                    </div>
                    <div class="queue-row">
                      <span>{formatLabel(item.primary_metric_name)}</span>
                      <strong>{formatPct(item.primary_metric_probability)}</strong>
                    </div>
                    <div class="bar-track">
                      <div class="bar-fill" style="width:{Math.max(4, item.primary_metric_probability * 100)}%; background:{severityPalette(item.severity)}"></div>
                    </div>
                  </button>
                {:else}
                  <div class="empty-state">No predictions available yet.</div>
                {/each}
              </div>
            </article>
          </section>

          <section class="model-grid">
            <article class="card model-card">
              <div class="model-head">
                <div>
                  <div class="section-tag">XGBoost</div>
                  <h2>Per-target risk</h2>
                </div>
                <span class="hint">gradient-boost, ensemble-blended</span>
              </div>
              <div class="bar-list">
                {#each overviewRiskMatrix as [target, value]}
                  <div class="bar-item" class:bar-primary={target === overviewPrediction.primary_metric_name}>
                    <div class="bar-meta">
                      <span>{formatLabel(target)}</span>
                      <strong>{formatPct(Number(value))}</strong>
                    </div>
                    <div class="bar-track">
                      <div class="bar-fill" style="width:{Math.min(100, Number(value) * 100)}%; background:{severityPalette(Number(value) >= 0.8 ? 'critical' : Number(value) >= 0.6 ? 'high' : Number(value) >= 0.4 ? 'warning' : 'watch')}"></div>
                    </div>
                  </div>
                {/each}
              </div>
              <div class="model-foot muted">primary · {formatLabel(overviewPrediction.primary_metric_name)}</div>
            </article>

            <article class="card model-card">
              <div class="model-head">
                <div>
                  <div class="section-tag">LSTM</div>
                  <h2>Sequence dynamics</h2>
                </div>
                <span class={`pill ${trendClass(overviewTrend)}`}>{overviewTrend}</span>
              </div>
              <div class="metric-stack">
                <div class="metric-row">
                  <span>Velocity</span>
                  <strong>{formatSigned(overviewVelocity)}</strong>
                </div>
                <div class="metric-row">
                  <span>Acceleration</span>
                  <strong>{formatSigned(overviewAcceleration)}</strong>
                </div>
                <div class="metric-row">
                  <span>Persistence</span>
                  <strong>{formatPct(overviewPersistence)}</strong>
                </div>
                <div class="metric-row">
                  <span>Stability</span>
                  <strong>{formatPct(overviewStability)}</strong>
                </div>
              </div>
              <div class="model-foot muted">recent-window risk vs. threshold</div>
            </article>

            <article class="card model-card">
              <div class="model-head">
                <div>
                  <div class="section-tag">Prophet</div>
                  <h2>Capacity forecast</h2>
                </div>
                <span class={`pill ${prophetStatusClass(overviewProphetStatus)}`}>{prophetStatusLabel(overviewProphetStatus)}</span>
              </div>
              <div class="metric-stack">
                <div class="metric-row">
                  <span>Capacity ETA</span>
                  <strong>{formatEta(overviewCapacityEta)}</strong>
                </div>
                <div class="metric-row">
                  <span>Threshold</span>
                  <strong>{overviewProphetThreshold === null ? 'n/a' : formatNumber(overviewProphetThreshold)}</strong>
                </div>
                <div class="metric-row">
                  <span>Max forecast</span>
                  <strong>{overviewProphetMaxForecast === null ? 'n/a' : formatNumber(overviewProphetMaxForecast)}</strong>
                </div>
                <div class="metric-row">
                  <span>Horizon</span>
                  <strong>{overviewProphetHorizon === null ? 'n/a' : `${formatNumber(overviewProphetHorizon, 0)} min`}</strong>
                </div>
              </div>
              <div class="model-foot muted">queue-length time-series projection</div>
            </article>

            <article class="card model-card">
              <div class="model-head">
                <div>
                  <div class="section-tag">TTE</div>
                  <h2>Time-to-event</h2>
                </div>
                <span class="hint">per-target survival</span>
              </div>
              <div class="metric-stack">
                {#each overviewEtaMatrix as [target, eta]}
                  <div class="metric-row" class:metric-primary={target === overviewPrediction.primary_metric_name}>
                    <span>{formatLabel(target)}</span>
                    <strong>{Number.isFinite(eta) ? formatEta(eta) : '—'}</strong>
                  </div>
                {:else}
                  <div class="metric-row">
                    <span>No TTE outputs</span>
                    <strong>n/a</strong>
                  </div>
                {/each}
              </div>
              <div class="model-foot muted">minutes until each threshold breach</div>
            </article>
          </section>

          <section class="page-grid">
            <article class="card">
              <div class="section-tag">SHAP</div>
              <div class="card-head">
                <h2>Top drivers</h2>
                <span class="hint">{formatLabel(overviewPrediction.primary_metric_name)}</span>
              </div>
              <div class="driver-inline">
                {#each overviewDrivers.slice(0, 5) as driver}
                  <span class="driver-chip">{driver.feature}</span>
                {:else}
                  <span class="muted">No SHAP drivers available.</span>
                {/each}
              </div>
              <div class="metric-stack top-gap">
                {#each overviewDomains.slice(0, 3) as domain}
                  <div class="metric-row">
                    <span>{domain.domain}</span>
                    <strong>{formatPct(domain.score)}</strong>
                  </div>
                {:else}
                  <div class="metric-row">
                    <span>Domain</span>
                    <strong>unavailable</strong>
                  </div>
                {/each}
              </div>
            </article>

            <article class="card">
              <div class="section-tag">RAG</div>
              <div class="card-head">
                <h2>Incident memory</h2>
                <span class="hint">{overviewMemoryCount} match{overviewMemoryCount === 1 ? '' : 'es'}</span>
              </div>
              <div class="metric-stack">
                <div class="metric-row">
                  <span>Closest incident</span>
                  <strong>{overviewClosestIncident || 'none'}</strong>
                </div>
                <div class="metric-row">
                  <span>Similarity</span>
                  <strong>{overviewSimilarity > 0 ? `${Math.round(overviewSimilarity)}%` : 'n/a'}</strong>
                </div>
                <div class="metric-row">
                  <span>LLM</span>
                  <strong>{overviewPrediction.llm_used ? 'narrative' : 'fallback'}</strong>
                </div>
                <div class="metric-row">
                  <span>Monitoring feed</span>
                  <strong>{summary?.system_health?.monitoring?.row_count ?? 0} rows</strong>
                </div>
              </div>
            </article>

            <article class="card">
              <div class="section-tag">Trust</div>
              <div class="card-head">
                <h2>Ensemble trust</h2>
                <span class="hint">XGB ↔ LSTM agreement</span>
              </div>
              <div class="metric-stack">
                <div class="metric-row">
                  <span>Confidence</span>
                  <strong>{formatPct(overviewPrediction.confidence_score)}</strong>
                </div>
                <div class="metric-row">
                  <span>Model agreement</span>
                  <strong>{formatPct(overviewAgreement)}</strong>
                </div>
                <div class="metric-row">
                  <span>Data quality</span>
                  <strong>{formatPct(overviewQuality)}</strong>
                </div>
                <div class="metric-row">
                  <span>Drift</span>
                  <strong>{formatPct(overviewDrift)}</strong>
                </div>
                <div class="metric-row">
                  <span>Artifacts</span>
                  <strong>{artifactStatusLabel}</strong>
                </div>
              </div>
            </article>
          </section>
        {/if}
      {/if}

      {#if activeTab === 'fleet'}
        <section class="page-grid">
          <article class="card span-3">
            <div class="section-tag">Incidents</div>
            <div class="card-head">
              <h2>Incident board</h2>
              <span class="hint">per-node, per-target risk so an operator can pick the next escalation target fast</span>
            </div>
            {#if fleet && fleet.nodes.length}
              <div class="table-wrap">
                <table class="data-table heatmap-table">
                  <thead>
                    <tr>
                      <th>Node</th>
                      {#each summary?.targets ?? [] as target}
                        <th>{formatLabel(target)}</th>
                      {/each}
                      <th>Severity</th>
                      <th>Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each fleet.nodes as node}
                      <tr on:click={() => selectNode(node.node_id)}>
                        <td><strong>{node.node_id}</strong></td>
                        {#each summary?.targets ?? [] as target}
                          {@const value = Number(node.risk_probs?.[target] ?? 0)}
                          <td>
                            <div class="heat-cell" style="background:rgba(176,42,55,{Math.max(0.08, Math.min(0.92, value)).toFixed(2)})">
                              {Math.round(value * 100)}
                            </div>
                          </td>
                        {/each}
                        <td><span class={`pill ${severityClass(node.severity)}`}>{node.severity}</span></td>
                        <td>{formatPct(node.confidence_score)}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {:else}
              <div class="empty-state">No fleet data available.</div>
            {/if}
          </article>

          <article class="card">
            <div class="card-head">
              <h2>Node severity</h2>
              <span class="hint">latest fleet state only</span>
            </div>
            <div class="bar-list">
              {#each Object.entries(fleet?.severity_distribution ?? {}) as [severity, count]}
                <div class="bar-item">
                  <div class="bar-meta">
                    <span class={`pill ${severityClass(severity)}`}>{severity}</span>
                    <strong>{count}</strong>
                  </div>
                  <div class="bar-track">
                    <div class="bar-fill" style="width:{Math.min(100, (Number(count) / Math.max(1, fleet?.node_count ?? 1)) * 100)}%; background:{severityPalette(severity)}"></div>
                  </div>
                </div>
              {/each}
            </div>
          </article>

          <article class="card">
            <div class="card-head">
              <h2>Domain concentration</h2>
              <span class="hint">dominant domains across nodes</span>
            </div>
            <div class="bar-list">
              {#each Object.entries(fleet?.domain_distribution ?? {}) as [domain, count]}
                <div class="bar-item">
                  <div class="bar-meta">
                    <span class="chip" style="background:{domainPalette(domain)}22; color:{domainPalette(domain)}">{domain}</span>
                    <strong>{count}</strong>
                  </div>
                  <div class="bar-track">
                    <div class="bar-fill" style="width:{Math.min(100, (Number(count) / Math.max(1, fleet?.node_count ?? 1)) * 100)}%; background:{domainPalette(domain)}"></div>
                  </div>
                </div>
              {/each}
            </div>
          </article>

          <article class="card">
            <div class="card-head">
              <h2>Fleet average risk</h2>
              <span class="hint">aggregated by model target</span>
            </div>
            <div class="bar-list">
              {#each sortObjectByValue(fleet?.average_risk_by_target) as [target, value]}
                <div class="bar-item">
                  <div class="bar-meta">
                    <span>{formatLabel(target)}</span>
                    <strong>{formatPct(Number(value))}</strong>
                  </div>
                  <div class="bar-track">
                    <div class="bar-fill" style="width:{Math.min(100, Number(value) * 100)}%; background:linear-gradient(90deg,#11468f,#2a9d8f)"></div>
                  </div>
                </div>
              {/each}
            </div>
          </article>
        </section>
      {/if}

      {#if activeTab === 'node'}
        <section class="node-toolbar">
          <label class="picker">
            <span>Node</span>
            <select bind:value={selectedNodeId} on:change={loadNodeDetail}>
              {#each fleet?.nodes ?? [] as node}
                <option value={node.node_id}>{node.node_id} | {node.severity}</option>
              {/each}
            </select>
          </label>
          <div class="target-tabs">
            {#each summary?.targets ?? [] as target}
              <button class:active={currentTarget === target} on:click={() => setTarget(target)}>{formatLabel(target)}</button>
            {/each}
          </div>
        </section>

        {#if selectedPrediction}
          <section class="page-grid">
            <article class="card span-2">
              <div class="section-tag">Triage</div>
              <div class="hero-head">
                <div>
                  <h2>{selectedPrediction.node_id}</h2>
                  <p class="muted">{selectedPrediction.timestamp}</p>
                </div>
                <div class="hero-badges">
                  <span class={`pill ${severityClass(selectedPrediction.severity)}`}>{selectedPrediction.severity}</span>
                  <span class="pill neutral">{formatLabel(selectedPrediction.primary_metric_name)}</span>
                </div>
              </div>
              <div class="stat-grid">
                <article class="stat-card">
                  <span>Primary risk</span>
                  <strong>{formatPct(selectedPrediction.primary_metric_probability)}</strong>
                  <small>targeted metric</small>
                </article>
                <article class="stat-card">
                  <span>Confidence</span>
                  <strong>{formatPct(selectedPrediction.confidence_score)}</strong>
                  <small>trust score</small>
                </article>
                <article class="stat-card">
                  <span>ETA</span>
                  <strong>{formatEta(selectedPrediction.primary_metric_eta_min ?? selectedPrediction.capacity_exhaustion_eta_min)}</strong>
                  <small>time to threshold</small>
                </article>
                <article class="stat-card">
                  <span>Fleet rank</span>
                  <strong>#{selectedPrediction.fleet_context?.fleet_rank ?? '--'}</strong>
                  <small>{selectedPrediction.fleet_context?.pattern_scope ?? 'pattern unknown'}</small>
                </article>
              </div>
              <div class="split-grid">
                <div class="card-panel">
                  <div class="mini-title">Recommended action</div>
                  <p class="panel-copy">{selectedPrediction.recommended_action || 'No action recommendation available.'}</p>
                </div>
                <div class="card-panel">
                  <div class="mini-title">Feedback loop</div>
                  <div class="feedback-actions">
                    <button class="ghost" on:click={() => submitFeedback(selectedPrediction.database_id, 'confirmed_true_positive')} disabled={feedbackBusy}>
                      Confirm
                    </button>
                    <button class="ghost" on:click={() => submitFeedback(selectedPrediction.database_id, 'false_positive')} disabled={feedbackBusy}>
                      False positive
                    </button>
                  </div>
                </div>
              </div>
            </article>

            <article class="card">
              <div class="card-head">
                <h2>Reasoning context</h2>
                <span class="hint">narrative for the selected node</span>
              </div>
              <p class="panel-copy">
                {selectedPrediction.operator_brief || selectedPrediction.llm_summary || selectedPrediction.explanation || 'No reasoning available.'}
              </p>
            </article>

            <article class="card span-3">
              <div class="card-head">
                <h2>Risk timeline</h2>
                <span class="hint">{timeseries?.points ?? 0} historical predictions for {formatLabel(currentTarget)}</span>
              </div>
              {#if timeseries && timeseries.points > 1}
                <div class="timeline-summary">
                  <div class="timeline-stat">
                    <span>Current risk</span>
                    <strong>{formatPct(timelineCurrentProbability)}</strong>
                  </div>
                  <div class="timeline-stat">
                    <span>Threshold</span>
                    <strong>{formatPct(timelineThreshold)}</strong>
                  </div>
                  <div class="timeline-stat">
                    <span>Confidence</span>
                    <strong>{formatPct(timelineCurrentConfidence)}</strong>
                  </div>
                  <div class="timeline-stat">
                    <span>TTE</span>
                    <strong>{formatEta(timelineCurrentEta)}</strong>
                  </div>
                </div>
                <svg viewBox="0 0 680 320" class="timeline">
                  <defs>
                    <linearGradient id="riskFill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stop-color="#b02a37" stop-opacity="0.45" />
                      <stop offset="100%" stop-color="#b02a37" stop-opacity="0.06" />
                    </linearGradient>
                    <linearGradient id="confidenceFill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stop-color="#0f9d8a" stop-opacity="0.36" />
                      <stop offset="100%" stop-color="#0f9d8a" stop-opacity="0.06" />
                    </linearGradient>
                  </defs>
                  {#each [0.25, 0.5, 0.75] as y}
                    <line x1="8" x2="672" y1={8 + y * 204} y2={8 + y * 204} stroke="rgba(255,255,255,0.08)" stroke-dasharray="4 6" />
                  {/each}
                  <line x1="8" x2="672" y1={timelineThresholdY} y2={timelineThresholdY} stroke="rgba(240,196,15,0.9)" stroke-dasharray="8 6" />
                  <path d={timelinePath.area} fill="url(#riskFill)" />
                  <path d={timelinePath.path} stroke="#b02a37" stroke-width="2" fill="none" />
                  {#if timelineLatestPoint}
                    <circle cx={timelineLatestPoint.x} cy={timelineLatestPoint.y} r="5" fill="#f4f7fb" stroke="#b02a37" stroke-width="2" />
                  {/if}
                  <g transform="translate(0,228)">
                    <path d={confidencePath.area} fill="url(#confidenceFill)" />
                    <path d={confidencePath.path} stroke="#0f9d8a" stroke-width="1.6" fill="none" />
                    {#if confidenceLatestPoint}
                      <circle cx={confidenceLatestPoint.x} cy={confidenceLatestPoint.y} r="4" fill="#f4f7fb" stroke="#0f9d8a" stroke-width="1.6" />
                    {/if}
                  </g>
                  <text x="16" y={Math.max(18, timelineThresholdY - 8)} fill="rgba(241,196,15,0.95)" font-size="12">threshold</text>
                </svg>
                <div class="timeline-meta">
                  <span class="muted">first {shortTime(timeseries.timestamps[0])}</span>
                  <span class="muted">latest {shortTime(timeseries.timestamps[timeseries.timestamps.length - 1])}</span>
                  <span class="muted">target {formatLabel(currentTarget)}</span>
                </div>
              {:else}
                <div class="empty-state">Not enough node history yet. Run more live cycles.</div>
              {/if}
            </article>

            <article class="card">
              <div class="card-head">
                <h2>Target matrix</h2>
                <span class="hint">probability vs threshold</span>
              </div>
              <div class="bar-list">
                {#each summary?.targets ?? [] as target}
                  {@const probability = selectedPrediction.risk_probs?.[target] ?? 0}
                  {@const threshold = selectedPrediction.decision_thresholds_used?.[target] ?? 0.5}
                  <div class="bar-item">
                    <div class="bar-meta">
                      <span>{formatLabel(target)}</span>
                      <strong>{formatPct(probability)}</strong>
                    </div>
                    <div class="bar-track threshold">
                      <div class="threshold-line" style="left:{Math.min(99, threshold * 100)}%"></div>
                      <div class="bar-fill" style="width:{Math.min(100, probability * 100)}%; background:{probability >= threshold ? '#b02a37' : '#0f9d8a'}"></div>
                    </div>
                    <small class="muted">eta {formatEta(selectedPrediction.eta_per_target?.[target])}</small>
                  </div>
                {/each}
              </div>
            </article>

            <article class="card">
              <div class="card-head">
                <h2>Top drivers</h2>
                <span class="hint">SHAP or fallback drivers for {formatLabel(currentTarget)}</span>
              </div>
              <div class="bar-list">
                {#each selectedPrediction.shap_features?.[currentTarget] ?? selectedPrediction.top_3_drivers?.[currentTarget] ?? [] as driver}
                  {@const magnitude = Math.min(100, Math.abs(Number(driver.value ?? 0)) * 100)}
                  <div class="bar-item">
                    <div class="bar-meta">
                      <span>{driver.feature}</span>
                      <strong class={driver.direction === 'increases_risk' ? 'critical-text' : 'ok-text'}>
                        {driver.direction === 'increases_risk' ? 'up' : 'down'} {formatNumber(driver.value, 4)}
                      </strong>
                    </div>
                    <div class="bar-track">
                      <div class="bar-fill" style="width:{Math.max(4, magnitude)}%; background:{driver.direction === 'increases_risk' ? '#b02a37' : '#0f9d8a'}"></div>
                    </div>
                  </div>
                {:else}
                  <div class="empty-state">No feature drivers available.</div>
                {/each}
              </div>
            </article>

            <article class="card">
              <div class="card-head">
                <h2>Driver frequency</h2>
                <span class="hint">historical recurrence over 14 days</span>
              </div>
              <div class="bar-list">
                {#each drivers?.drivers?.slice(0, 8) ?? [] as item}
                  <div class="bar-item">
                    <div class="bar-meta">
                      <span>{item.feature}</span>
                      <strong>x{item.frequency}</strong>
                    </div>
                    <div class="bar-track">
                      <div class="bar-fill" style="width:{Math.min(100, item.frequency * 8)}%; background:linear-gradient(90deg,#11468f,#0f9d8a)"></div>
                    </div>
                    <small class="muted">avg impact {formatNumber(item.avg_impact, 4)}</small>
                  </div>
                {:else}
                  <div class="empty-state">No driver history yet.</div>
                {/each}
              </div>
            </article>

            <article class="card">
              <div class="card-head">
                <h2>Trust signals</h2>
                <span class="hint">confidence breakdown</span>
              </div>
              <div class="bar-list">
                {#each Object.entries(selectedPrediction.trust_signals ?? {}) as [key, value]}
                  {@const numeric = typeof value === 'number' ? value : Number(value)}
                  <div class="bar-item">
                    <div class="bar-meta">
                      <span>{key}</span>
                      <strong>{Number.isFinite(numeric) ? formatNumber(numeric, 3) : String(value)}</strong>
                    </div>
                    {#if Number.isFinite(numeric)}
                      <div class="bar-track">
                        <div class="bar-fill" style="width:{Math.min(100, Math.max(0, numeric * 100))}%; background:linear-gradient(90deg,#5a6ac6,#0f9d8a)"></div>
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            </article>

            <article class="card span-2">
              <div class="card-head">
                <h2>Incident memory matches</h2>
                <span class="hint">retrieved context for operator comparison before actioning the alert</span>
              </div>
              <div class="incident-stack">
                {#each selectedPrediction.retrieved_incidents ?? [] as incident}
                  {@const similarity = incident.distance != null ? Math.max(0, Math.min(100, (1 - incident.distance) * 100)) : 0}
                  <div class="incident-card">
                    <div class="incident-head">
                      <strong>{incidentLabel(incident)}</strong>
                      <span class={`pill ${severityClass(incident.metadata?.severity ?? 'unknown')}`}>{incident.metadata?.severity ?? 'n/a'}</span>
                    </div>
                    <div class="incident-meta">
                      <span class="muted">node {incident.metadata?.node_id ?? '--'}</span>
                      <strong>{Math.round(similarity)}% sim</strong>
                    </div>
                    <p>{incident.document}</p>
                  </div>
                {:else}
                  <div class="empty-state">No related incidents retrieved.</div>
                {/each}
              </div>
            </article>
          </section>
        {:else}
          <div class="empty-state">Select a node from fleet or overview to open the drilldown.</div>
        {/if}
      {/if}

      {#if activeTab === 'live'}
        <section class="page-grid">
          <article class="card span-3">
            <div class="section-tag">Telemetry</div>
            <div class="card-head">
              <h2>Live monitoring feed</h2>
              <span class="hint">seeded by the autonomous lifecycle and used as the short-horizon input for active inference</span>
            </div>
            <div class="stat-grid">
              <article class="stat-card">
                <span>Monitoring rows</span>
                <strong>{summary?.system_health?.monitoring?.row_count ?? 0}</strong>
                <small>stored in the monitoring KPI dataset</small>
              </article>
              <article class="stat-card">
                <span>Nodes in feed</span>
                <strong>{liveNodeCount || summary?.system_health?.monitoring?.node_count || 0}</strong>
                <small>currently visible in the live view</small>
              </article>
              <article class="stat-card">
                <span>Last feed sample</span>
                <strong>{shortTime(String(latestQosRow?.timestamp ?? summary?.system_health?.monitoring?.latest_timestamp ?? ''))}</strong>
                <small>latest monitoring timestamp</small>
              </article>
              <article class="stat-card">
                <span>Cycle output</span>
                <strong>{lifecycleResult?.prediction_count ?? 0}</strong>
                <small>predictions from the last live cycle</small>
              </article>
            </div>
          </article>

          <article class="card span-3">
            <div class="card-head">
              <h2>Live QoS mini-trends</h2>
              <span class="hint">{selectedNodeId || 'monitoring nodes'} | last {qosFeed.length} samples</span>
            </div>
            {#if qosFeed.length}
              <div class="mini-grid">
                {#each liveMetricKeys as metric}
                  {@const series = qosFeed.map((row) => Number(row[metric] ?? 0))}
                  {@const path = buildLinePath(series, 220, 92, 6)}
                  <div class="mini-card">
                    <div class="mini-head">
                      <span>{metric}</span>
                      <strong>{formatNumber(series[series.length - 1], 2)}</strong>
                    </div>
                    <svg viewBox="0 0 220 92" class="mini-chart">
                      <path d={path.area} fill="rgba(17,70,143,0.18)" />
                      <path d={path.path} stroke="#11468f" stroke-width="1.6" fill="none" />
                    </svg>
                  </div>
                {/each}
              </div>
            {:else}
              <div class="empty-state">No live feed available yet. Run the lifecycle to seed monitoring rows.</div>
            {/if}
          </article>

          <article class="card span-3">
            <div class="card-head">
              <h2>Live QoS table</h2>
              <span class="hint">most recent 12 monitoring samples</span>
            </div>
            {#if qosFeed.length}
              <div class="table-wrap">
                <table class="data-table compact">
                  <thead>
                    <tr>
                      {#each Object.keys(qosFeed[0] ?? {}) as column}
                        <th>{column}</th>
                      {/each}
                    </tr>
                  </thead>
                  <tbody>
                    {#each qosFeed.slice(-12) as row}
                      <tr>
                        {#each Object.entries(row) as [, value]}
                          <td>{typeof value === 'number' ? formatNumber(value, 3) : String(value)}</td>
                        {/each}
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {:else}
              <div class="empty-state">The live feed is empty.</div>
            {/if}
          </article>
        </section>
      {/if}

      {#if activeTab === 'memory'}
        <section class="page-grid">
          <article class="card span-2">
            <div class="section-tag">Knowledge</div>
            <div class="card-head">
              <h2>Prediction knowledge log</h2>
              <span class="hint">persisted outputs, operator-facing reasoning, and historical incident context</span>
            </div>
            <div class="table-wrap">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Node</th>
                    <th>Severity</th>
                    <th>Metric</th>
                    <th>Risk</th>
                    <th>Confidence</th>
                    <th>Reasoning</th>
                  </tr>
                </thead>
                <tbody>
                  {#each summary?.recent_predictions ?? [] as item}
                    <tr on:click={() => selectNode(item.node_id)}>
                      <td>{shortTime(item.timestamp)}</td>
                      <td>{item.node_id}</td>
                      <td><span class={`pill ${severityClass(item.severity)}`}>{item.severity}</span></td>
                      <td>{formatLabel(item.primary_metric_name)}</td>
                      <td>{formatPct(item.primary_metric_probability)}</td>
                      <td>{formatPct(item.confidence_score)}</td>
                      <td class="truncate">{(item.operator_brief || item.llm_summary || item.explanation || '').slice(0, 88)}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </article>

          <article class="card">
            <div class="card-head">
              <h2>Incident memory sample</h2>
              <span class="hint">{incidentSample?.count ?? 0} indexed incidents</span>
            </div>
            <div class="incident-stack">
              {#each incidentSample?.incidents ?? [] as incident}
                <div class="incident-card">
                  <div class="incident-head">
                    <strong>{String(incident.incident_type ?? incident.incident_id ?? 'incident')}</strong>
                    <span class="muted">{String(incident.severity ?? 'n/a')}</span>
                  </div>
                  <p>{String(incident.summary ?? incident.description ?? incident.root_cause ?? 'No summary available.')}</p>
                </div>
              {:else}
                <div class="empty-state">No incident sample available.</div>
              {/each}
            </div>
          </article>

          <article class="card">
            <div class="card-head">
              <h2>Top affected nodes</h2>
              <span class="hint">count across recent persisted predictions</span>
            </div>
            <div class="bar-list">
              {#each Object.entries(summary?.stats?.top_nodes ?? {}) as [node, count]}
                <div class="bar-item">
                  <div class="bar-meta">
                    <span><button class="link-button inline" on:click={() => selectNode(node)}>{node}</button></span>
                    <strong>x{count}</strong>
                  </div>
                  <div class="bar-track">
                    <div class="bar-fill" style="width:{Math.min(100, Number(count) * 5)}%; background:linear-gradient(90deg,#f0b429,#b02a37)"></div>
                  </div>
                </div>
              {/each}
            </div>
          </article>
        </section>
      {/if}

      {#if activeTab === 'models'}
        <section class="page-grid">
          <article class="card span-2">
            <div class="section-tag">Runtime</div>
            <div class="card-head">
              <h2>Runtime and artifact readiness</h2>
              <span class="hint">kept last so operators stay focused on dispatch first, but precise enough for debugging</span>
            </div>
            <div class="stat-grid">
              <article class="stat-card">
                <span>Artifacts loaded</span>
                <strong>{modelOverview?.model_status?.artifact_count ?? 0} / {modelOverview?.model_status?.required_artifact_count ?? 0}</strong>
                <small>{modelOverview?.model_status?.ready ? 'model stack ready' : 'artifacts missing'}</small>
              </article>
              <article class="stat-card">
                <span>MLflow</span>
                <strong>{String((modelOverview?.mlflow as Record<string, unknown> | undefined)?.status ?? 'pending')}</strong>
                <small>{String((modelOverview?.mlflow as Record<string, unknown> | undefined)?.ui_url ?? 'n/a')}</small>
              </article>
              <article class="stat-card">
                <span>LLM</span>
                <strong>{summary?.system_health?.llm?.available ? 'online' : 'offline'}</strong>
                <small>{summary?.system_health?.llm?.configured_model ?? 'no configured model'}</small>
              </article>
              <article class="stat-card">
                <span>Prediction storage</span>
                <strong>{storageMode}</strong>
                <small>{summary?.system_health?.storage?.active_db_path ?? 'n/a'}</small>
              </article>
            </div>

            {#if (modelOverview?.model_status?.missing_artifacts?.length ?? 0) > 0}
              <div class="notice">
                Missing artifacts: {modelOverview?.model_status?.missing_artifacts.join(', ')}
              </div>
            {/if}
            {#if summary?.system_health?.mlflow?.fallback_reason}
              <div class="notice">
                MLflow fallback reason: {summary.system_health.mlflow.fallback_reason}
              </div>
            {/if}
            {#if storageIssue}
              <div class="notice">
                Prediction DB fallback reason: {storageIssue}
              </div>
            {/if}
          </article>

          <article class="card">
            <div class="card-head">
              <h2>Decision profile</h2>
              <span class="hint">how the packet uses snapshot and sequence evidence</span>
            </div>
            <div class="metric-stack">
              <div class="metric-row">
                <span>Snapshot evidence</span>
                <strong>{formatPct((modelOverview?.decision_paths as Record<string, unknown> | undefined)?.snapshot_weight ?? modelOverview?.ensemble_weights?.xgboost ?? 0)}</strong>
              </div>
              <div class="metric-row">
                <span>Sequence evidence</span>
                <strong>{formatPct((modelOverview?.decision_paths as Record<string, unknown> | undefined)?.sequence_weight ?? modelOverview?.ensemble_weights?.lstm ?? 0)}</strong>
              </div>
              <div class="metric-row">
                <span>History window</span>
                <strong>{(modelOverview?.decision_paths as Record<string, unknown> | undefined)?.history_window_rows ?? modelOverview?.lstm?.window ?? '--'} rows</strong>
              </div>
              <div class="metric-row">
                <span>Stored cadence</span>
                <strong>{summary?.system_health?.monitoring?.cadence_seconds ?? 30}s</strong>
              </div>
            </div>
          </article>

          <article class="card span-3">
            <div class="card-head">
              <h2>Saved artifacts</h2>
              <span class="hint">deployment footprint</span>
            </div>
            <div class="table-wrap">
              <table class="data-table compact">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Size KB</th>
                    <th>Modified</th>
                  </tr>
                </thead>
                <tbody>
                  {#each modelOverview?.artifacts ?? [] as artifact}
                    <tr>
                      <td>{artifact.name}</td>
                      <td>{artifact.size_kb}</td>
                      <td>{new Date(artifact.modified_epoch * 1000).toLocaleString()}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </article>
        </section>
      {/if}
    {/if}
  </main>
</div>

<style>
  :global(body) {
    margin: 0;
    background:
      radial-gradient(circle at 0% 0%, rgba(17, 70, 143, 0.28), transparent 28%),
      radial-gradient(circle at 100% 0%, rgba(240, 180, 41, 0.12), transparent 24%),
      linear-gradient(180deg, #07111d 0%, #0b1727 100%);
    color: #e6ebf2;
    font-family: Aptos, 'Segoe UI', 'IBM Plex Sans', sans-serif;
  }

  :global(*) {
    box-sizing: border-box;
  }

  .app-shell {
    display: grid;
    grid-template-columns: 260px 1fr;
    min-height: 100vh;
  }

  .sidebar {
    position: sticky;
    top: 0;
    height: 100vh;
    padding: 24px 18px;
    display: flex;
    flex-direction: column;
    gap: 22px;
    background: rgba(6, 14, 24, 0.88);
    border-right: 1px solid rgba(255, 255, 255, 0.08);
    backdrop-filter: blur(16px);
  }

  .brand {
    display: flex;
    gap: 12px;
    align-items: center;
  }

  .logo {
    width: 44px;
    height: 44px;
    border-radius: 14px;
    display: grid;
    place-items: center;
    background: linear-gradient(135deg, #f0b429, #0f9d8a);
    color: #0b1727;
    font-weight: 800;
  }

  .brand-name {
    font-weight: 700;
    letter-spacing: 0.02em;
  }

  .brand-sub {
    color: #96a2b4;
    font-size: 0.8rem;
  }

  .nav {
    display: grid;
    gap: 6px;
  }

  .nav button {
    border: none;
    background: transparent;
    color: #b8c2cf;
    text-align: left;
    display: flex;
    align-items: center;
    gap: 10px;
    border-radius: 12px;
    padding: 11px 12px;
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease;
  }

  .nav button:hover {
    background: rgba(255, 255, 255, 0.04);
    color: #fff;
  }

  .nav button.active {
    background: linear-gradient(90deg, rgba(17, 70, 143, 0.32), rgba(15, 157, 138, 0.18));
    color: #fff;
  }

  .dot {
    width: 7px;
    height: 7px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.25);
  }

  .nav button.active .dot {
    background: #f0b429;
    box-shadow: 0 0 0 4px rgba(240, 180, 41, 0.18);
  }

  .status-panel {
    margin-top: auto;
    padding: 14px;
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.07);
    display: grid;
    gap: 10px;
  }

  .status-top,
  .status-row,
  .status-metric,
  .metric-row,
  .queue-row,
  .bar-meta,
  .hero-head,
  .card-head,
  .timeline-meta,
  .incident-head,
  .incident-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
  }

  .status-metric,
  .metric-row {
    font-size: 0.86rem;
  }

  .timeline-summary {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
    margin-bottom: 12px;
  }

  .timeline-stat {
    padding: 10px 12px;
    border-radius: 12px;
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.035), rgba(255, 255, 255, 0.015));
    border: 1px solid rgba(255, 255, 255, 0.06);
    display: grid;
    gap: 4px;
  }

  .timeline-stat span {
    color: #96a2b4;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .timeline-stat strong {
    font-size: 1rem;
  }

  .status-metric span,
  .metric-row span {
    color: #96a2b4;
  }

  .workspace {
    padding: 28px 32px 56px;
    display: flex;
    flex-direction: column;
    gap: 18px;
    min-width: 0;
  }

  .topbar {
    display: flex;
    justify-content: space-between;
    gap: 18px;
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .eyebrow {
    color: #f0b429;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    font-size: 0.72rem;
    margin-bottom: 8px;
  }

  h1,
  h2,
  p {
    margin: 0;
  }

  h1 {
    font-size: clamp(1.8rem, 3vw, 2.6rem);
    line-height: 1.02;
  }

  h2 {
    font-size: 1.08rem;
  }

  .lede,
  .muted,
  .hint,
  small {
    color: #96a2b4;
  }

  .lede {
    max-width: 760px;
    margin-top: 8px;
    line-height: 1.55;
  }

  .toolbar,
  .feedback-actions,
  .target-tabs,
  .hero-badges,
  .driver-inline {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
  }

  button {
    font: inherit;
  }

  .ghost,
  .primary {
    border-radius: 999px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    padding: 0.6rem 1rem;
    cursor: pointer;
    transition: transform 0.15s ease, background 0.15s ease;
  }

  .ghost {
    background: rgba(255, 255, 255, 0.04);
    color: #e6ebf2;
  }

  .primary {
    background: linear-gradient(135deg, #f0b429, #0f9d8a);
    color: #08111d;
    font-weight: 700;
    border-color: transparent;
  }

  .ghost:hover,
  .primary:hover {
    transform: translateY(-1px);
  }

  .error-banner,
  .info-banner,
  .notice {
    border-radius: 14px;
    padding: 14px 16px;
  }

  .error-banner {
    background: rgba(176, 42, 55, 0.16);
    border: 1px solid rgba(176, 42, 55, 0.45);
  }

  .info-banner {
    background: rgba(15, 157, 138, 0.12);
    border: 1px solid rgba(15, 157, 138, 0.28);
  }

  .notice {
    background: rgba(240, 180, 41, 0.12);
    border: 1px solid rgba(240, 180, 41, 0.28);
    margin-top: 14px;
  }

  .notice.compact {
    padding: 10px 12px;
    font-size: 0.84rem;
  }

  .loading-state,
  .empty-state {
    display: grid;
    place-items: center;
    text-align: center;
  }

  .loading-state {
    padding: 88px 0;
    gap: 16px;
  }

  .empty-state {
    padding: 28px;
    color: #96a2b4;
  }

  .spinner {
    width: 38px;
    height: 38px;
    border-radius: 999px;
    border: 3px solid rgba(240, 180, 41, 0.18);
    border-top-color: #f0b429;
    animation: spin 0.9s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .page-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 16px;
  }

  .hero-layout {
    align-items: start;
  }

  .model-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 16px;
  }

  @media (max-width: 1180px) {
    .model-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  .model-card {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .model-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 10px;
  }

  .model-head h2 {
    margin-top: 4px;
  }

  .model-foot {
    margin-top: auto;
    font-size: 0.78rem;
    padding-top: 4px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }

  .hero-id {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  .hero-id h2 {
    font-size: 1.5rem;
    letter-spacing: 0.02em;
  }

  .hero-meta {
    display: flex;
    gap: 6px;
    align-items: center;
    font-size: 0.8rem;
  }

  .hero-stats {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
    margin-top: 18px;
    padding: 14px;
    background: rgba(0, 0, 0, 0.18);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 14px;
  }

  .hero-stat {
    display: grid;
    gap: 4px;
  }

  .hero-stat span {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #96a2b4;
  }

  .hero-stat strong {
    font-size: 1.4rem;
  }

  .hero-action,
  .hero-narrative {
    margin-top: 14px;
    display: grid;
    gap: 6px;
  }

  .trend.trend-high {
    color: #f59f45;
  }

  .trend.trend-normal {
    color: #3cc995;
  }

  .trend.trend-watch {
    color: #5ca8ff;
  }

  .bar-item.bar-primary {
    background: rgba(240, 180, 41, 0.06);
    border-radius: 10px;
    padding: 6px 8px;
    margin: 0 -8px;
  }

  .metric-row.metric-primary {
    background: rgba(240, 180, 41, 0.06);
    border-radius: 10px;
    padding: 4px 8px;
    margin: 0 -8px;
  }

  .span-2 {
    grid-column: span 2;
  }

  .span-3 {
    grid-column: span 3;
  }

  .card {
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.025));
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 20px;
    padding: 20px;
    box-shadow: 0 20px 48px rgba(0, 0, 0, 0.22);
    backdrop-filter: blur(18px);
    overflow: hidden;
  }

  .hero-card {
    background:
      linear-gradient(135deg, rgba(17, 70, 143, 0.22), rgba(15, 157, 138, 0.14)),
      linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.02));
  }

  .section-tag,
  .mini-title,
  .kicker {
    text-transform: uppercase;
    letter-spacing: 0.14em;
    font-size: 0.72rem;
    color: #f0b429;
  }

  .hero-summary {
    margin-top: 16px;
    display: grid;
    gap: 12px;
  }

  .headline {
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }

  .headline strong {
    font-size: 1.3rem;
  }

  .stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin-top: 16px;
  }

  .stat-card,
  .card-panel,
  .mini-card,
  .queue-card,
  .incident-card {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 14px;
  }

  .stat-card {
    padding: 14px;
    display: grid;
    gap: 4px;
  }

  .stat-card span {
    font-size: 0.74rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #96a2b4;
  }

  .stat-card strong {
    font-size: 1.35rem;
  }

  .split-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px;
    margin-top: 16px;
  }

  .card-panel {
    padding: 14px;
    display: grid;
    gap: 8px;
  }

  .panel-copy {
    line-height: 1.55;
  }

  .queue-list,
  .bar-list,
  .metric-stack,
  .legend,
  .incident-stack {
    display: grid;
    gap: 10px;
  }

  .queue-card {
    width: 100%;
    padding: 14px;
    color: inherit;
    text-align: left;
    cursor: pointer;
    border-radius: 14px;
  }

  .queue-card strong {
    letter-spacing: 0.01em;
  }

  .queue-card.selected {
    border-color: rgba(240, 180, 41, 0.5);
    box-shadow: inset 0 0 0 1px rgba(240, 180, 41, 0.35);
  }

  .bar-item {
    display: grid;
    gap: 6px;
  }

  .bar-track {
    height: 7px;
    background: rgba(255, 255, 255, 0.07);
    border-radius: 999px;
    overflow: hidden;
    position: relative;
  }

  .bar-track.threshold {
    overflow: visible;
  }

  .bar-fill {
    height: 100%;
    border-radius: 999px;
  }

  .threshold-line {
    position: absolute;
    top: -3px;
    bottom: -3px;
    width: 2px;
    background: rgba(255, 255, 255, 0.82);
  }

  .pill,
  .chip,
  .driver-chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
  }

  .pill {
    padding: 0.34rem 0.76rem;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    background: rgba(255, 255, 255, 0.06);
  }

  .pill.normal,
  .pill.ok {
    color: #3cc995;
    background: rgba(60, 201, 149, 0.15);
  }

  .pill.watch {
    color: #5ca8ff;
    background: rgba(92, 168, 255, 0.15);
  }

  .pill.warning {
    color: #f0b429;
    background: rgba(240, 180, 41, 0.15);
  }

  .pill.high {
    color: #f59f45;
    background: rgba(245, 159, 69, 0.16);
  }

  .pill.critical,
  .pill.degraded {
    color: #ff7b87;
    background: rgba(176, 42, 55, 0.22);
  }

  .pill.neutral {
    color: #c9d4e5;
    background: rgba(255, 255, 255, 0.08);
  }

  .pill.unknown {
    color: #96a2b4;
  }

  .chip,
  .driver-chip {
    padding: 0.28rem 0.68rem;
    font-size: 0.76rem;
    background: rgba(255, 255, 255, 0.06);
  }

  .driver-chip {
    color: #f0b429;
  }

  .donut-layout,
  .domain-layout {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 16px;
    align-items: center;
  }

  .donut {
    width: 150px;
    height: 150px;
  }

  .donut.small {
    width: 132px;
    height: 132px;
  }

  .donut-num {
    fill: #fff;
    font-size: 22px;
    font-weight: 700;
  }

  .donut-cap {
    fill: #96a2b4;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
  }

  .legend-row {
    display: grid;
    grid-template-columns: 10px 1fr auto;
    align-items: center;
    gap: 8px;
  }

  .swatch {
    width: 10px;
    height: 10px;
    border-radius: 3px;
  }

  .legend-label {
    text-transform: capitalize;
    color: #c0cad7;
  }

  .node-toolbar {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }

  .picker {
    display: flex;
    gap: 8px;
    align-items: center;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 8px 12px;
  }

  .picker select {
    background: transparent;
    color: inherit;
    border: none;
    outline: none;
    min-width: 150px;
  }

  .picker option {
    color: #08111d;
  }

  .target-tabs button {
    border: 1px solid rgba(255, 255, 255, 0.09);
    background: rgba(255, 255, 255, 0.04);
    color: #b8c2cf;
    border-radius: 999px;
    padding: 0.45rem 0.8rem;
    cursor: pointer;
  }

  .target-tabs button.active {
    color: #fff;
    background: rgba(17, 70, 143, 0.28);
    border-color: rgba(17, 70, 143, 0.5);
  }

  .timeline {
    width: 100%;
    height: auto;
  }

  .table-wrap {
    overflow-x: auto;
  }

  .data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.86rem;
  }

  .data-table th,
  .data-table td {
    padding: 8px 10px;
    text-align: left;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    vertical-align: top;
  }

  .data-table th {
    color: #96a2b4;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 600;
  }

  .data-table tbody tr:hover {
    background: rgba(255, 255, 255, 0.03);
    cursor: pointer;
  }

  .data-table.compact th,
  .data-table.compact td {
    padding: 6px 8px;
    font-size: 0.78rem;
  }

  .heat-cell {
    min-width: 44px;
    min-height: 26px;
    display: grid;
    place-items: center;
    border-radius: 6px;
    color: #fff;
    font-size: 0.75rem;
    font-weight: 600;
  }

  .mini-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px;
  }

  .mini-card {
    padding: 12px;
  }

  .mini-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    font-size: 0.84rem;
    margin-bottom: 6px;
  }

  .mini-chart {
    width: 100%;
    height: 72px;
  }

  .incident-stack {
    max-height: 440px;
    overflow: auto;
    padding-right: 4px;
  }

  .incident-card {
    padding: 12px;
    display: grid;
    gap: 8px;
  }

  .incident-card p,
  .truncate {
    color: #c0cad7;
  }

  .truncate {
    max-width: 440px;
  }

  .link-button {
    border: none;
    background: none;
    color: #f0b429;
    cursor: pointer;
    padding: 0;
  }

  .link-button.inline {
    text-align: left;
  }

  .critical-text {
    color: #ff7b87;
  }

  .ok-text {
    color: #3cc995;
  }

  @media (max-width: 1180px) {
    .page-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .span-3 {
      grid-column: span 2;
    }
  }

  @media (max-width: 960px) {
    .app-shell {
      grid-template-columns: 1fr;
    }

    .sidebar {
      position: relative;
      height: auto;
    }

    .workspace {
      padding: 22px 18px 42px;
    }

    .page-grid,
    .span-2,
    .span-3 {
      grid-column: span 1;
      grid-template-columns: 1fr;
    }

    .page-grid {
      grid-template-columns: 1fr;
    }

    .timeline-summary {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .donut-layout,
    .domain-layout {
      grid-template-columns: 1fr;
      justify-items: center;
    }
  }
</style>
  const AUTO_REFRESH_MS = 5000;
