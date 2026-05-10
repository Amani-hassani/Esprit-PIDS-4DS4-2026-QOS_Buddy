let state = {
  dashboard: null,
  incidents: [],
  selectedIncidentId: null,
};

const rootLabels = {
  RC_CAPACITY_OVERLOAD: "Capacity Overload",
  RC_TRANSPORT_DELAY: "Transport Delay",
  RC_JITTER_INSTABILITY: "Jitter Instability",
  RC_PACKET_LOSS: "Packet Loss",
  RC_RETRANSMISSION: "Retransmission",
  RC_RADIO_SIGNAL_WEAK: "Radio Signal Weak",
  RC_HANDOVER_INSTABILITY: "Handover Instability",
  RC_CQI_MISMATCH: "CQI Mismatch",
};

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    throw new Error(`${path} failed with ${response.status}`);
  }
  return response.json();
}

function fmtTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().replace("T", " ").slice(11, 19);
}

function riskClass(level) {
  return `risk-${String(level || "medium").toLowerCase()}`;
}

function switchView(view) {
  document.querySelectorAll(".view").forEach((item) => item.classList.remove("active"));
  document.querySelectorAll(".nav-link").forEach((item) => item.classList.remove("active"));
  document.getElementById(`${view}-view`).classList.add("active");
  const nav = document.querySelector(`.nav-link[data-view="${view}"]`);
  if (nav) nav.classList.add("active");
}

function renderKpis(summary) {
  const cards = [
    ["Current Anomaly Score", summary.current_anomaly_score, "Threshold 5.0 -- Elevated", "#ff5668"],
    ["Active Incidents", summary.active_incidents, "Live incidents from ingestion endpoint", "#f2b632"],
    ["Avg Confidence %", `${summary.avg_confidence_pct}%`, "Fused RF + GRU + FAISS evidence", "#12d6ff"],
    ["SLA Risk Index", summary.sla_risk_index, "Above threshold 0.5 -- at risk", "#f2b632"],
    ["Data Quality Trust Score", `${summary.data_quality_trust_score}%`, "Fresh samples across streams", "#19d17f"],
  ];

  document.getElementById("kpi-grid").innerHTML = cards
    .map(
      ([title, value, subtitle, color]) => `
        <article class="kpi-card" style="--accent:${color}">
          <small>${title}</small>
          <strong>${value}</strong>
          <span>${subtitle}</span>
        </article>
      `
    )
    .join("");
}

function renderMonitor(monitoring) {
  const titleMap = {
    qos_kpis: "QoS KPIs",
    radio_metrics: "Radio Metrics",
    handover_coverage: "Handover & Coverage",
    congestion_quality: "Congestion & Quality",
  };
  document.getElementById("monitor-grid").innerHTML = Object.entries(monitoring)
    .map(([key, metrics]) => {
      const lines = Object.entries(metrics)
        .map(([name, value]) => `<div class="metric-line"><span>${name}</span><b>${value}</b></div>`)
        .join("");
      return `<div class="monitor-box"><h3>${titleMap[key] || key}</h3>${lines}</div>`;
    })
    .join("");
}

function rootOptions(incidents) {
  const select = document.getElementById("cause-filter");
  const current = select.value;
  const causes = [...new Set(incidents.map((item) => item.root_cause))].sort();
  select.innerHTML = `<option value="all">All Root Causes</option>` +
    causes.map((cause) => `<option value="${cause}">${rootLabels[cause] || cause}</option>`).join("");
  select.value = causes.includes(current) ? current : "all";
}

function renderIncidentRows() {
  const query = document.getElementById("search").value.toLowerCase();
  const scope = document.getElementById("scope-filter").value;
  const cause = document.getElementById("cause-filter").value;

  const rows = state.incidents.filter((item) => {
    const haystack = `${item.id} ${item.anomaly_type} ${item.root_cause} ${item.scope}`.toLowerCase();
    return (
      haystack.includes(query) &&
      (scope === "all" || item.scope === scope) &&
      (cause === "all" || item.root_cause === cause)
    );
  });

  document.getElementById("incident-rows").innerHTML = rows
    .map(
      (item) => `
      <tr>
        <td><span class="id-link" data-incident="${item.id}">${item.id}</span></td>
        <td><b>${fmtTime(item.timestamp)}</b><br><small>${item.cell_id || ""}</small></td>
        <td>${item.anomaly_type}</td>
        <td><span class="badge ${item.root_tag.split(" ")[0]}">${item.root_tag}</span></td>
        <td><b>${item.confidence_pct}%</b><div class="bar"><span style="width:${item.confidence_pct}%"></span></div></td>
        <td><b>${item.score}</b></td>
        <td><span class="badge ${riskClass(item.risk_level)}">${String(item.risk_level).toUpperCase()}</span></td>
        <td><button class="view-details" data-incident="${item.id}">View Details &gt;</button></td>
      </tr>
    `
    )
    .join("");

  document.querySelectorAll("[data-incident]").forEach((node) => {
    node.addEventListener("click", () => showIncident(node.dataset.incident));
  });
}

function probabilityRows(top3) {
  return top3
    .map(
      (item, index) => `
      <div class="prob-row">
        <span>#${index + 1} ${rootLabels[item.root_cause] || item.root_cause}</span>
        <div class="bar"><span style="width:${item.probability * 100}%"></span></div>
        <b>${Math.round(item.probability * 100)}%</b>
      </div>
    `
    )
    .join("");
}

function protocolRows(item) {
  const dq = item.data_quality || {};
  const ae = item.autoencoder_evidence || {};
  const fusion = item.fusion || {};
  const discriminator = item.radio_transport_discriminator || {};
  const adjustments = fusion.confidence_adjustments || {};
  const scopeScores = discriminator.scope_scores || {};
  const rows = [
    ["Context Fusion", (item.protocol_pipeline?.context_fusion?.present_sources || []).join(", ") || "seed context"],
    ["Data Quality Gate", `trust ${dq.trust_score || 0}% / penalty ${adjustments.data_quality_penalty || 0}`],
    ["Sequence Builder", `${item.protocol_pipeline?.sequence_builder?.observed_samples || 0}/${item.protocol_pipeline?.sequence_builder?.window_size || 10} samples`],
    ["Memory Autoencoder", `MSE ${ae.reconstruction_mse || 0} / severity ${ae.reconstruction_severity || 0}`],
    ["FAISS Prototype", `${item.prototype_neighbors?.[0]?.root_cause || "n/a"} similarity ${item.prototype_neighbors?.[0]?.similarity || 0}`],
    ["Scope Discriminator", `${discriminator.macro_scope || item.scope} / R:${scopeScores.RADIO || 0} T:${scopeScores.TRANSPORT || 0}`],
    ["Fusion Confidence", `raw ${fusion.raw_confidence || 0} -> final ${fusion.adjusted_confidence || item.confidence}`],
  ];
  return rows
    .map(([title, value]) => `<div class="protocol-item"><b>${title}</b><span>${value}</span></div>`)
    .join("");
}

function renderDetail(item) {
  const ringPct = `${item.confidence_pct}%`;
  const evidence = item.evidence
    .map(
      (ev) => `
      <div class="evidence-item">
        <b>${ev.field}: ${ev.value}</b>
        <p>${ev.message}</p>
      </div>
    `
    )
    .join("");
  const chain = item.causal_chain
    .map(
      (step) => `
      <div class="chain-step">
        <b>${step.title}</b>
        <p>${step.description}</p>
        <small>${step.field}: ${step.value}</small>
      </div>
    `
    )
    .join("");
  const contributions = item.feature_contributions
    .map(
      (feature) => `
      <div class="contrib-row">
        <span>${feature.feature}<br><small>${feature.direction}; value=${feature.value}</small></span>
        <div class="bar"><span style="width:${Math.min(100, Math.abs(feature.contribution) * 2400)}%"></span></div>
        <b>${feature.contribution}</b>
      </div>
    `
    )
    .join("");
  const neighbors = item.prototype_neighbors
    .map(
      (neighbor) => `
      <div class="neighbor-item">
        <b>#${neighbor.rank} ${rootLabels[neighbor.root_cause] || neighbor.root_cause}</b>
        <div class="bar"><span style="width:${neighbor.similarity * 100}%"></span></div>
        <small>Similarity ${Math.round(neighbor.similarity * 100)}% - FAISS distance ${neighbor.distance}</small>
      </div>
    `
    )
    .join("");

  document.getElementById("incident-detail").innerHTML = `
    <section class="panel detail-card">
      <div class="detail-header">
        <div>
          <h1>${item.id} <span>${String(item.risk_level).toUpperCase()} ANOMALY</span></h1>
          <p>Timestamp: ${item.timestamp} - Cell: ${item.cell_id} - Region: ${item.region}</p>
          <p>Trust score: ${item.data_quality?.trust_score || "seed"}% -- Confidence: ${item.confidence_pct}% -- ${item.augmentation_origin}</p>
        </div>
        <div class="confidence-ring" style="--pct:${ringPct}"><div>${item.confidence_pct}%</div></div>
      </div>
    </section>
    <div class="detail-grid">
      <div>
        <section class="panel">
          <h2>Diagnosis</h2>
          <div class="diagnosis-box">
            <strong>${item.root_cause}</strong><br>
            <span class="badge ${item.scope.toLowerCase()}">${item.scope} SCOPE</span>
          </div>
          <h3>Top-3 Cause Probability Ranking</h3>
          ${probabilityRows(item.top3)}
        </section>
        <section class="panel">
          <h2>Protocol Branch Evidence</h2>
          <div class="protocol-grid">${protocolRows(item)}</div>
        </section>
        <section class="panel">
          <h2>Causal Chain Flow</h2>
          <div class="chain">${chain}</div>
        </section>
        <section class="panel">
          <h2>Feature Contribution Analysis -- Why This Diagnosis?</h2>
          <p class="muted-copy">${item.feature_contribution_narrative || item.llm_explanation?.feature_contribution_narrative || ""}</p>
          ${contributions}
        </section>
      </div>
      <div>
        <section class="panel">
          <h2>Evidence Summary</h2>
          <div class="evidence-list">${evidence}</div>
        </section>
        <section class="panel">
          <h2>FAISS Prototype Matches</h2>
          <div class="evidence-list">${neighbors}</div>
        </section>
        <section class="panel action-box">
          <h2>Recommended Action Context</h2>
          <b>${item.recommended_action.title}</b>
          <p>${item.recommended_action.message}</p>
          <button class="send-button" data-send-optimization="${item.id}">Send to Optimization Agent</button>
        </section>
      </div>
    </div>
  `;
  const sendButton = document.querySelector("[data-send-optimization]");
  if (sendButton) {
    sendButton.addEventListener("click", async () => {
      sendButton.textContent = "Sending...";
      const result = await api(`/api/incidents/${sendButton.dataset.sendOptimization}/send-to-optimization`, {
        method: "POST",
      });
      sendButton.textContent = `Optimization ${result.status}`;
    });
  }
}

async function showIncident(id) {
  const item = await api(`/api/incidents/${id}`);
  state.selectedIncidentId = id;
  renderDetail(item);
  switchView("incident");
}

async function renderHealth() {
  const health = await api("/api/model-health");
  const pipeline = (health.protocol_pipeline || []).map((stage) => `<li>${stage.replaceAll("_", " ")}</li>`).join("");
  document.getElementById("health-panel").innerHTML = `
    <h2>Model & Health</h2>
    <div class="monitor-grid">
      <div class="monitor-box"><h3>Status</h3><b>${health.status}</b><p>Uptime ${health.uptime_sec}s</p></div>
      <div class="monitor-box"><h3>Artifacts</h3><b>${health.artifacts.feature_columns}</b><p>Leak-safe features loaded</p></div>
      <div class="monitor-box"><h3>FAISS</h3><b>Loaded</b><p>Native IndexFlatL2 required</p></div>
      <div class="monitor-box"><h3>GRU</h3><b>Loaded</b><p>10-sample autoencoder, latent and reconstruction evidence</p></div>
      <div class="monitor-box"><h3>LLM</h3><b>${health.llm.provider}</b><p>${health.llm.enabled ? health.llm.model : "Configure QOS_LLM_API_KEY for remote LLM"}</p></div>
      <div class="monitor-box"><h3>Optimization</h3><b>${health.optimization.outbox_size}</b><p>Queued handoffs</p></div>
    </div>
    <h2>Runtime Protocol</h2>
    <ol class="pipeline-list">${pipeline}</ol>
  `;
}

function renderPipeline() {
  const stages = state.dashboard?.protocol?.pipeline || [];
  document.getElementById("protocol-pipeline").innerHTML = stages
    .map((stage, index) => `<div><b>${index + 1}. ${stage.replaceAll("_", " ")}</b><span>active in runtime response</span></div>`)
    .join("");
}

async function loadDashboard() {
  state.dashboard = await api("/api/dashboard");
  state.incidents = state.dashboard.incidents;
  document.getElementById("last-refresh").textContent = new Date().toISOString();
  document.getElementById("updated-seconds").textContent = state.dashboard.updated_seconds_ago;
  document.getElementById("nav-count").textContent = state.incidents.length;
  renderKpis(state.dashboard.summary);
  renderMonitor(state.dashboard.live_monitoring);
  renderPipeline();
  rootOptions(state.incidents);
  renderIncidentRows();
  await renderHealth();
}

document.querySelectorAll(".nav-link, .back-btn").forEach((node) => {
  node.addEventListener("click", () => switchView(node.dataset.view));
});
document.getElementById("refresh-btn").addEventListener("click", loadDashboard);
document.getElementById("demo-ingest-btn").addEventListener("click", async () => {
  await api("/api/demo/ingest-next", { method: "POST" });
  await loadDashboard();
});
document.getElementById("search").addEventListener("input", renderIncidentRows);
document.getElementById("scope-filter").addEventListener("change", renderIncidentRows);
document.getElementById("cause-filter").addEventListener("change", renderIncidentRows);

loadDashboard().catch((error) => {
  document.body.innerHTML = `<pre style="color:#ff8b95;padding:24px">${error.stack || error}</pre>`;
});

setInterval(() => {
  loadDashboard().catch((error) => console.error(error));
}, 5000);
