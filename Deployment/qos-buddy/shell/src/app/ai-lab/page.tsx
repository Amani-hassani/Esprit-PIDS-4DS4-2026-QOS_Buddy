"use client";

import { type ComponentType, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import {
  Activity,
  BookMarked,
  BookOpen,
  Brain,
  CheckCircle2,
  Cpu,
  Database,
  FlaskConical,
  Lightbulb,
  Loader2,
  PenLine,
  Search,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react";
import { withChartDefaults } from "@/lib/chart-defaults";
import { useLive } from "@/lib/store";
import { cn } from "@/lib/utils";
import { RoleGate, useAuth } from "@/components/providers/auth-provider";
import type { AlertEvent, DiagnosisEvent, InsightEvent, MetricEvent, ProposedActionEvent, ExecutedActionEvent } from "@/lib/types";

const ReactEChartsCore = dynamic(() => import("echarts-for-react"), { ssr: false });

const RAG_URL = process.env.NEXT_PUBLIC_RAG_URL ?? "http://localhost:8088";
const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8080";

type Tab = "pipeline" | "detection" | "insight" | "optimization" | "memory";

interface ServiceHealth {
  status: "ok" | "degraded" | "down";
}

type HealthAll = Record<string, ServiceHealth>;

interface DetectionModelInfo {
  model_type: string;
  last_trained: string | null;
  features_used: number;
  threshold: number;
  recent_accuracy: number;
  alerts_last_hour: number;
  false_positive_rate: number;
}

interface ArmStat {
  action_code: string;
  action_label: string;
  pull_count: number;
  win_rate: number;
  last_execution_time: string | null;
}

// ─── helpers ────────────────────────────────────────────────────────────

function rate(arr: { occurred_at: string }[], windowMs = 60_000): number {
  const cutoff = Date.now() - windowMs;
  return arr.filter((x) => new Date(x.occurred_at).getTime() > cutoff).length;
}

function avg(nums: number[]): number {
  return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : 0;
}

// ─── page ────────────────────────────────────────────────────────────────

export default function AiLabPage() {
  return (
    <RoleGate allow={["ai_engineer", "site_admin"]}>
      <AiLabPageContent />
    </RoleGate>
  );
}

function AiLabPageContent() {
  const metrics  = useLive((s) => s.metrics);
  const alerts   = useLive((s) => s.alerts);
  const diagnoses = useLive((s) => s.diagnoses);
  const insights  = useLive((s) => s.insights);
  const proposed  = useLive((s) => s.proposedActions);
  const executed  = useLive((s) => s.executedActions);

  const { token, demoMode, role } = useAuth();
  const effectiveToken = demoMode ? `demo:${role}` : token;
  const authHeaders = useMemo(
    () => (effectiveToken ? { authorization: `Bearer ${effectiveToken}` } : undefined),
    [effectiveToken],
  );

  const [tab, setTab] = useState<Tab>("pipeline");
  const [ragHealth, setRagHealth] = useState<{ ok: boolean; collections?: number; docs?: number } | null>(null);
  const [healthAll, setHealthAll] = useState<HealthAll | null>(null);
  const [modelInfo, setModelInfo] = useState<DetectionModelInfo | null>(null);
  const [armStats, setArmStats] = useState<ArmStat[]>([]);

  useEffect(() => {
    fetch(`${RAG_URL}/health`)
      .then((r) => r.ok ? r.json() : null)
      .then((j) => j && setRagHealth({ ok: true, collections: j.collections ?? 1, docs: j.document_count ?? j.count ?? null }))
      .catch(() => setRagHealth({ ok: false }));
  }, []);

  useEffect(() => {
    if (!authHeaders) return;
    let cancelled = false;
    const load = () => {
      fetch(`${GATEWAY_URL}/api/health/all`, { headers: authHeaders })
        .then((r) => (r.ok ? r.json() : null))
        .then((data: HealthAll | null) => {
          if (!cancelled && data) setHealthAll(data);
        })
        .catch(() => {
          if (!cancelled) setHealthAll(null);
        });
    };
    load();
    const id = window.setInterval(load, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [authHeaders]);

  useEffect(() => {
    if (!authHeaders) return;
    fetch(`${GATEWAY_URL}/api/detection/model-info`, { headers: authHeaders })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: DetectionModelInfo | null) => {
        if (data) setModelInfo(data);
      })
      .catch(() => {});
    fetch(`${GATEWAY_URL}/api/optimization/arm-stats`, { headers: authHeaders })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { arms?: ArmStat[] } | null) => {
        setArmStats(data?.arms ?? []);
      })
      .catch(() => setArmStats([]));
  }, [authHeaders]);

  const TABS: Array<{ key: Tab; label: string; icon: ComponentType<{ className?: string }> }> = [
    { key: "pipeline",    label: "Pipeline",    icon: Cpu        },
    { key: "detection",   label: "Detection",   icon: Activity   },
    { key: "insight",     label: "Insight",     icon: Brain      },
    { key: "optimization",label: "Optimization",icon: ShieldCheck},
    { key: "memory",      label: "Memory",      icon: BookMarked },
  ];

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">AI Lab</h1>
          <p className="text-sm text-ink-2">
            Live model performance, inference throughput, and knowledge-base
            health — all derived from the running pipeline.
          </p>
        </div>
        <span className="inline-flex items-center gap-2 rounded-lg border border-vio/40 bg-vio-soft/30 px-3 py-1.5 text-xs text-vio">
          <FlaskConical className="h-3.5 w-3.5" />
          ai_engineer view
        </span>
      </header>

      {/* ── throughput strip ── */}
      <ThroughputStrip metrics={metrics} alerts={alerts} diagnoses={Object.values(diagnoses)} insights={Object.values(insights)} executed={executed} />

      {/* ── tabs ── */}
      <nav className="flex gap-2 border-b border-line-subtle">
        {TABS.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={cn(
                "flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium transition",
                tab === t.key ? "border-cy text-cy" : "border-transparent text-ink-2 hover:text-ink-0",
              )}
            >
              <Icon className="h-4 w-4" />
              {t.label}
            </button>
          );
        })}
      </nav>

      {tab === "pipeline"     && <PipelineTab metrics={metrics} alerts={alerts} diagnoses={Object.values(diagnoses)} insights={Object.values(insights)} proposed={proposed} executed={executed} ragHealth={ragHealth} healthAll={healthAll} />}
      {tab === "detection"    && <DetectionTab metrics={metrics} alerts={alerts} modelInfo={modelInfo} />}
      {tab === "insight"      && <InsightTab alerts={alerts} diagnoses={Object.values(diagnoses)} insights={Object.values(insights)} ragHealth={ragHealth} />}
      {tab === "optimization" && <OptimizationTab proposed={proposed} executed={executed} armStats={armStats} />}
      {tab === "memory"       && <MemoryTab alerts={alerts} />}
    </div>
  );
}

// ─── throughput strip ─────────────────────────────────────────────────────

function ThroughputStrip({
  metrics, alerts, diagnoses, insights, executed,
}: {
  metrics: MetricEvent[];
  alerts: AlertEvent[];
  diagnoses: DiagnosisEvent[];
  insights: InsightEvent[];
  executed: ExecutedActionEvent[];
}) {
  const tiles = [
    { label: "Metrics/min",   value: rate(metrics),   icon: Cpu,         color: "text-cy"  },
    { label: "Alerts/min",    value: rate(alerts),    icon: Activity,    color: "text-warn" },
    { label: "Diagnoses/min", value: rate(diagnoses), icon: Brain,       color: "text-vio"  },
    { label: "Insights/min",  value: rate(insights),  icon: Lightbulb,   color: "text-info" },
    { label: "Actions/min",   value: rate(executed),  icon: ShieldCheck, color: "text-ok"   },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      {tiles.map((t) => {
        const Icon = t.icon;
        return (
          <div key={t.label} className="glass rounded-xl p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wide text-ink-2">{t.label}</span>
              <Icon className={cn("h-4 w-4", t.color)} />
            </div>
            <div className={cn("mt-2 font-mono text-2xl tabular-nums", t.color)}>{t.value}</div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Pipeline tab ─────────────────────────────────────────────────────────

function PipelineTab({
  metrics, alerts, diagnoses, insights, proposed, executed, ragHealth, healthAll,
}: {
  metrics: MetricEvent[];
  alerts: AlertEvent[];
  diagnoses: DiagnosisEvent[];
  insights: InsightEvent[];
  proposed: ProposedActionEvent[];
  executed: ExecutedActionEvent[];
  ragHealth: { ok: boolean; collections?: number; docs?: number } | null;
  healthAll: HealthAll | null;
}) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  // Throughput over time — bucket metrics into 30s bins
  const throughputSeries = useMemo(() => {
    if (metrics.length < 2) return [];
    const bins = new Map<number, number>();
    const BIN = 30_000;
    for (const m of metrics) {
      const t = Math.floor(new Date(m.occurred_at).getTime() / BIN) * BIN;
      bins.set(t, (bins.get(t) ?? 0) + 1);
    }
    return Array.from(bins.entries())
      .sort((a, b) => a[0] - b[0])
      .map(([t, c]) => [t, c]);
  }, [metrics]);

  const alertsByDetector = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const a of alerts) counts[a.detector] = (counts[a.detector] ?? 0) + 1;
    return Object.entries(counts).map(([name, value]) => ({ name, value }));
  }, [alerts]);

  const ax = {
    axisLabel: { color: dark ? "#7C8AAB" : "#475569", fontSize: 10 },
    axisLine:  { lineStyle: { color: dark ? "#2D3D5E" : "#CBD5E1" } },
    splitLine: { lineStyle: { color: dark ? "#1F2C44" : "#E2E8F0" } },
  };

  const throughputOption = {
    backgroundColor: "transparent",
    grid: { left: 40, right: 12, top: 20, bottom: 28 },
    tooltip: { trigger: "axis", backgroundColor: dark ? "#0D1825" : "#fff", borderColor: dark ? "#2D3D5E" : "#E2E8F0", textStyle: { color: dark ? "#ECF2FB" : "#0F172A", fontSize: 11 } },
    xAxis: { type: "time" as const, ...ax },
    yAxis: { type: "value" as const, name: "msg/30s", nameTextStyle: { color: dark ? "#7C8AAB" : "#475569", fontSize: 10 }, ...ax },
    series: [{
      name: "Metrics ingested",
      type: "bar",
      data: throughputSeries,
      itemStyle: { color: "#00D4FF", borderRadius: [3, 3, 0, 0] },
      barMaxWidth: 18,
    }],
  };

  const detectorOption = {
    backgroundColor: "transparent",
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0, textStyle: { color: dark ? "#B8C4DC" : "#475569", fontSize: 10 } },
    series: [{
      type: "pie",
      radius: ["50%", "72%"],
      center: ["50%", "45%"],
      avoidLabelOverlap: true,
      label: { show: false },
      data: alertsByDetector.map((d, i) => ({
        ...d,
        itemStyle: { color: ["#A87BFF", "#00D4FF", "#F59E0B", "#34D399"][i % 4] },
      })),
    }],
  };

  const agentRows = [
    { name: "Monitoring",   count: metrics.length,    label: "metrics ingested",   icon: Cpu,        color: "text-cy"   },
    { name: "Detection",    count: alerts.filter((a) => a.detector !== "forecast").length,  label: "behavioural alerts", icon: Activity,   color: "text-warn" },
    { name: "Prediction",   count: alerts.filter((a) => a.detector === "forecast").length,  label: "forecast alerts",    icon: TrendingUp, color: "text-info" },
    { name: "Diagnostic",   count: diagnoses.length,  label: "patterns matched",   icon: Brain,      color: "text-vio"  },
    { name: "Insight",      count: insights.length,   label: "lessons synthesised",icon: Lightbulb,  color: "text-cy"   },
    { name: "Optimization", count: proposed.length,   label: "actions proposed",   icon: Sparkles,   color: "text-ok"   },
  ];

  return (
    <div className="space-y-4">
      <ServiceHealthGrid healthAll={healthAll} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 glass rounded-xl p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-medium text-ink-1">Metric ingest throughput</h3>
            <span className="text-xs text-ink-2">30-second bins</span>
          </div>
          {throughputSeries.length > 0 ? (
            <ReactEChartsCore option={withChartDefaults(throughputOption)} notMerge lazyUpdate style={{ height: 180, width: "100%" }} opts={{ renderer: "canvas" }} />
          ) : (
            <div className="grid h-[180px] place-items-center text-sm text-ink-2">Waiting for samples…</div>
          )}
        </div>
        <div className="glass rounded-xl p-4">
          <div className="mb-2 text-sm font-medium text-ink-1">Alert detector mix</div>
          {alertsByDetector.length > 0 ? (
            <ReactEChartsCore option={withChartDefaults(detectorOption)} notMerge lazyUpdate style={{ height: 180, width: "100%" }} opts={{ renderer: "canvas" }} />
          ) : (
            <div className="grid h-[180px] place-items-center text-sm text-ink-2">No alerts yet</div>
          )}
        </div>
      </div>

      <div className="glass rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-line-subtle">
          <h3 className="text-sm font-medium text-ink-1">Agent activity summary</h3>
        </div>
        <table className="w-full text-sm">
          <tbody className="divide-y divide-line-subtle">
            {agentRows.map((r) => {
              const Icon = r.icon;
              const pct = metrics.length > 0 ? Math.min(100, Math.round((r.count / Math.max(1, metrics.length)) * 100)) : 0;
              return (
                <tr key={r.name}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Icon className={cn("h-4 w-4 shrink-0", r.color)} />
                      <span className="font-medium text-ink-0">{r.name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-ink-0 tabular-nums">{r.count}</td>
                  <td className="px-4 py-3 text-xs text-ink-2">{r.label}</td>
                  <td className="px-4 py-3 w-32 hidden md:table-cell">
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-2">
                      <div className={cn("h-full rounded-full bg-current", r.color)} style={{ width: `${Math.max(2, pct)}%` }} />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <RagCard ragHealth={ragHealth} />
    </div>
  );
}

function ServiceHealthGrid({ healthAll }: { healthAll: HealthAll | null }) {
  const services = ["monitoring", "detection", "prediction", "diagnostic", "optimization", "reporting", "rag"];
  return (
    <div className="glass rounded-xl p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-ink-1">Agent health</h3>
        <span className="text-xs text-ink-3">Gateway health aggregation</span>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
        {services.map((service) => {
          const status = healthAll?.[service]?.status ?? "degraded";
          return (
            <div key={service} className="rounded-lg border border-line-subtle bg-bg-2/40 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-xs font-medium capitalize text-ink-0">{service}</span>
                <span
                  className={cn(
                    "h-2.5 w-2.5 rounded-full",
                    status === "ok" ? "bg-ok" : status === "down" ? "bg-bad" : "bg-warn",
                  )}
                />
              </div>
              <div className="mt-1 text-[11px] uppercase tracking-wide text-ink-3">{status}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Detection tab ────────────────────────────────────────────────────────

function DetectionTab({ metrics, alerts, modelInfo }: { metrics: MetricEvent[]; alerts: AlertEvent[]; modelInfo: DetectionModelInfo | null }) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  const anomalyPoints = useMemo(() =>
    metrics
      .filter((m) => m.anomaly_score != null)
      .map((m) => [new Date(m.occurred_at).getTime(), m.anomaly_score as number]),
  [metrics]);

  // Score distribution buckets 0→1 in 0.1 steps
  const scoreDist = useMemo(() => {
    const bins = Array(10).fill(0);
    for (const m of metrics) {
      if (m.anomaly_score == null) continue;
      const b = Math.min(9, Math.floor(m.anomaly_score * 10));
      bins[b]++;
    }
    return bins;
  }, [metrics]);

  const confDist = useMemo(() => {
    const bins = Array(10).fill(0);
    for (const a of alerts) {
      const b = Math.min(9, Math.floor(a.confidence * 10));
      bins[b]++;
    }
    return bins;
  }, [alerts]);

  const detectRate = metrics.length > 0
    ? Math.round((alerts.filter((a) => a.detector !== "forecast").length / Math.max(1, metrics.filter((m) => m.anomaly_flag).length)) * 100)
    : 0;

  const avgConf = Math.min(96, Math.round(avg(alerts.map((a) => a.confidence)) * 100));
  const flagRate = metrics.length > 0 ? Math.round((metrics.filter((m) => m.anomaly_flag).length / metrics.length) * 100) : 0;

  const ax = {
    axisLabel: { color: dark ? "#7C8AAB" : "#475569", fontSize: 10 },
    axisLine:  { lineStyle: { color: dark ? "#2D3D5E" : "#CBD5E1" } },
    splitLine: { lineStyle: { color: dark ? "#1F2C44" : "#E2E8F0" } },
  };

  const scoreTimeOpt = {
    backgroundColor: "transparent",
    grid: { left: 44, right: 12, top: 20, bottom: 28 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "time" as const, ...ax },
    yAxis: { type: "value" as const, min: 0, max: 1, ...ax },
    series: [{
      name: "Anomaly score",
      type: "line",
      data: anomalyPoints,
      smooth: true,
      showSymbol: false,
      sampling: "lttb",
      lineStyle: { color: "#A87BFF", width: 1.8 },
      areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "#A87BFF40" }, { offset: 1, color: "#A87BFF00" }] } },
      markLine: {
        silent: true, symbol: ["none", "none"],
        data: [
          { yAxis: 0.4, lineStyle: { color: "#F59E0B", type: "dotted", width: 1 }, label: { formatter: "watch", color: "#F59E0B", fontSize: 9 } },
          { yAxis: 0.75, lineStyle: { color: "#F43F5E", type: "dotted", width: 1 }, label: { formatter: "act", color: "#F43F5E", fontSize: 9 } },
        ],
      },
    }],
  };

  const binLabels = ["0.0", "0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9"];

  const scoreDistOpt = {
    backgroundColor: "transparent",
    grid: { left: 36, right: 8, top: 16, bottom: 28 },
    xAxis: { type: "category" as const, data: binLabels, ...ax },
    yAxis: { type: "value" as const, ...ax },
    series: [{
      type: "bar",
      data: scoreDist.map((v, i) => ({ value: v, itemStyle: { color: i >= 7 ? "#F43F5E" : i >= 4 ? "#F59E0B" : "#34D399", borderRadius: [3, 3, 0, 0] } })),
      barMaxWidth: 24,
    }],
  };

  const confDistOpt = {
    backgroundColor: "transparent",
    grid: { left: 36, right: 8, top: 16, bottom: 28 },
    xAxis: { type: "category" as const, data: binLabels, ...ax },
    yAxis: { type: "value" as const, ...ax },
    series: [{
      type: "bar",
      data: confDist.map((v, i) => ({ value: v, itemStyle: { color: i >= 7 ? "#34D399" : i >= 4 ? "#00D4FF" : "#A87BFF", borderRadius: [3, 3, 0, 0] } })),
      barMaxWidth: 24,
    }],
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <LabStat
          label="Detector type"
          value={modelInfo?.model_type ?? "Loading"}
          sub={modelInfo?.last_trained ? `trained ${modelInfo.last_trained}` : "waiting for model metadata"}
          color="text-cy"
        />
        <LabStat
          label="Features used"
          value={modelInfo ? modelInfo.features_used.toString() : "--"}
          sub="live model artifact"
          color="text-vio"
        />
        <LabStat
          label="Alert threshold"
          value={modelInfo ? modelInfo.threshold.toFixed(3) : "--"}
          sub="active detector setting"
          color="text-warn"
        />
        <LabStat
          label="Recent quality"
          value={modelInfo ? `${Math.round(modelInfo.recent_accuracy * 100)}%` : "--"}
          sub={`${modelInfo?.alerts_last_hour ?? 0} alerts last hour`}
          color="text-ok"
        />
      </div>

      <div className="grid grid-cols-3 gap-3">
        <LabStat label="Anomaly flag rate" value={`${flagRate}%`} sub={`${metrics.filter((m) => m.anomaly_flag).length} / ${metrics.length} samples`} color="text-warn" />
        <LabStat label="Avg alert confidence" value={`${avgConf}%`} sub={`over ${alerts.length} alerts`} color={avgConf >= 70 ? "text-ok" : "text-warn"} />
        <LabStat label="Detector precision proxy" value={`${Math.min(100, detectRate)}%`} sub="flagged → alerted" color="text-cy" />
      </div>

      <div className="glass rounded-xl p-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-medium text-ink-1">Anomaly score · live stream</h3>
          <span className="text-xs text-ink-2">{anomalyPoints.length} samples</span>
        </div>
        {anomalyPoints.length > 0 ? (
          <ReactEChartsCore option={withChartDefaults(scoreTimeOpt)} notMerge lazyUpdate style={{ height: 200, width: "100%" }} opts={{ renderer: "canvas" }} />
        ) : (
          <div className="grid h-[200px] place-items-center text-sm text-ink-2">Waiting…</div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="glass rounded-xl p-4">
          <h3 className="mb-2 text-sm font-medium text-ink-1">Score distribution</h3>
          <ReactEChartsCore option={withChartDefaults(scoreDistOpt)} notMerge lazyUpdate style={{ height: 140, width: "100%" }} opts={{ renderer: "canvas" }} />
        </div>
        <div className="glass rounded-xl p-4">
          <h3 className="mb-2 text-sm font-medium text-ink-1">Alert confidence distribution</h3>
          <ReactEChartsCore option={withChartDefaults(confDistOpt)} notMerge lazyUpdate style={{ height: 140, width: "100%" }} opts={{ renderer: "canvas" }} />
        </div>
      </div>
    </div>
  );
}

// ─── Insight tab ──────────────────────────────────────────────────────────

function InsightTab({
  alerts, diagnoses, insights, ragHealth,
}: {
  alerts: AlertEvent[];
  diagnoses: DiagnosisEvent[];
  insights: InsightEvent[];
  ragHealth: { ok: boolean; collections?: number; docs?: number } | null;
}) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  // Pattern frequency
  const patternFreq = useMemo(() => {
    const counts = new Map<string, number>();
    for (const d of diagnoses) counts.set(d.pattern_label, (counts.get(d.pattern_label) ?? 0) + 1);
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8);
  }, [diagnoses]);

  // Insight confidence histogram
  const confBins = useMemo(() => {
    const bins = Array(10).fill(0);
    for (const i of insights) {
      const b = Math.min(9, Math.floor(i.confidence * 10));
      bins[b]++;
    }
    return bins;
  }, [insights]);

  // Citation rate
  const citationRate = insights.length
    ? Math.round((insights.filter((i) => i.citations.length > 0).length / insights.length) * 100)
    : 0;
  const avgCitations = insights.length
    ? (insights.reduce((s, i) => s + i.citations.length, 0) / insights.length).toFixed(1)
    : "—";
  const avgInsightConf = Math.min(96, Math.round(avg(insights.map((i) => i.confidence)) * 100));

  // Pattern match rate
  const patternMatchRate = alerts.length > 0
    ? Math.round((diagnoses.length / alerts.filter((a) => a.detector !== "forecast").length) * 100)
    : 0;

  const ax = {
    axisLabel: { color: dark ? "#7C8AAB" : "#475569", fontSize: 10 },
    axisLine:  { lineStyle: { color: dark ? "#2D3D5E" : "#CBD5E1" } },
    splitLine: { lineStyle: { color: dark ? "#1F2C44" : "#E2E8F0" } },
  };

  const patternOpt = {
    backgroundColor: "transparent",
    grid: { left: 140, right: 16, top: 8, bottom: 8 },
    xAxis: { type: "value" as const, ...ax },
    yAxis: { type: "category" as const, data: patternFreq.map((p) => p[0]).reverse(), axisLabel: { color: dark ? "#B8C4DC" : "#475569", fontSize: 10, width: 130, overflow: "truncate" as const } },
    series: [{
      type: "bar",
      data: patternFreq.map((p) => p[1]).reverse(),
      itemStyle: { color: "#A87BFF", borderRadius: [0, 3, 3, 0] },
      barMaxWidth: 20,
      label: { show: true, position: "right" as const, color: dark ? "#B8C4DC" : "#475569", fontSize: 10 },
    }],
  };

  const confOpt = {
    backgroundColor: "transparent",
    grid: { left: 36, right: 8, top: 16, bottom: 28 },
    xAxis: { type: "category" as const, data: ["0.0","0.1","0.2","0.3","0.4","0.5","0.6","0.7","0.8","0.9"], ...ax },
    yAxis: { type: "value" as const, ...ax },
    series: [{
      type: "bar",
      data: confBins.map((v, i) => ({ value: v, itemStyle: { color: i >= 7 ? "#34D399" : i >= 4 ? "#00D4FF" : "#A87BFF", borderRadius: [3, 3, 0, 0] } })),
      barMaxWidth: 24,
    }],
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <LabStat label="Diagnoses" value={diagnoses.length.toString()} sub="pattern matches" color="text-vio" />
        <LabStat label="Pattern match rate" value={`${Math.min(100, patternMatchRate)}%`} sub="alerts → diagnosis" color={patternMatchRate >= 60 ? "text-ok" : "text-warn"} />
        <LabStat label="Avg confidence" value={`${avgInsightConf}%`} sub={`Qwen2.5-3B · ${insights.length} lessons`} color={avgInsightConf >= 70 ? "text-ok" : "text-warn"} />
        <LabStat label="Citation rate" value={`${citationRate}%`} sub={`avg ${avgCitations} citations/lesson`} color="text-cy" />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="glass rounded-xl p-4">
          <h3 className="mb-3 text-sm font-medium text-ink-1">Top diagnostic patterns</h3>
          {patternFreq.length > 0 ? (
            <ReactEChartsCore option={withChartDefaults(patternOpt)} notMerge lazyUpdate style={{ height: 220, width: "100%" }} opts={{ renderer: "canvas" }} />
          ) : (
            <div className="grid h-[220px] place-items-center text-sm text-ink-2">No patterns yet</div>
          )}
        </div>
        <div className="glass rounded-xl p-4">
          <h3 className="mb-3 text-sm font-medium text-ink-1">Insight confidence histogram</h3>
          {insights.length > 0 ? (
            <ReactEChartsCore option={withChartDefaults(confOpt)} notMerge lazyUpdate style={{ height: 220, width: "100%" }} opts={{ renderer: "canvas" }} />
          ) : (
            <div className="grid h-[220px] place-items-center text-sm text-ink-2">No insights yet</div>
          )}
        </div>
      </div>

      <RagCard ragHealth={ragHealth} />
    </div>
  );
}

// ─── Optimization tab ─────────────────────────────────────────────────────

function OptimizationTab({
  proposed,
  executed,
  armStats,
}: {
  proposed: ProposedActionEvent[];
  executed: ExecutedActionEvent[];
  armStats: ArmStat[];
}) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  const verdictCounts = useMemo(() => {
    const c: Record<string, number> = { auto: 0, deferred: 0, rejected: 0 };
    for (const p of proposed) c[p.verdict] = (c[p.verdict] ?? 0) + 1;
    return c;
  }, [proposed]);

  const riskCounts = useMemo(() => {
    const c: Record<string, number> = { low: 0, medium: 0, high: 0 };
    for (const p of proposed) c[p.risk_level] = (c[p.risk_level] ?? 0) + 1;
    return c;
  }, [proposed]);

  const successRate = executed.length
    ? Math.round((executed.filter((e) => e.success).length / executed.length) * 100)
    : 0;

  const modeBreak = useMemo(() => {
    const c: Record<string, number> = {};
    for (const e of executed) c[e.mode] = (c[e.mode] ?? 0) + 1;
    return Object.entries(c);
  }, [executed]);

  // Execution latency distribution
  const latBins = useMemo(() => {
    const bins = [0, 0, 0, 0, 0]; // <100, 100-500, 500-1k, 1-5k, >5k
    for (const e of executed) {
      const ms = e.duration_ms ?? 0;
      if (ms < 100) bins[0]++;
      else if (ms < 500) bins[1]++;
      else if (ms < 1000) bins[2]++;
      else if (ms < 5000) bins[3]++;
      else bins[4]++;
    }
    return bins;
  }, [executed]);

  const ax = {
    axisLabel: { color: dark ? "#7C8AAB" : "#475569", fontSize: 10 },
    axisLine:  { lineStyle: { color: dark ? "#2D3D5E" : "#CBD5E1" } },
    splitLine: { lineStyle: { color: dark ? "#1F2C44" : "#E2E8F0" } },
  };

  const verdictOpt = {
    backgroundColor: "transparent",
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0, textStyle: { color: dark ? "#B8C4DC" : "#475569", fontSize: 10 } },
    series: [{
      type: "pie", radius: ["45%", "68%"], center: ["50%", "44%"],
      label: { show: false },
      data: [
        { name: "auto",     value: verdictCounts.auto,     itemStyle: { color: "#34D399" } },
        { name: "deferred", value: verdictCounts.deferred, itemStyle: { color: "#F59E0B" } },
        { name: "rejected", value: verdictCounts.rejected, itemStyle: { color: "#F43F5E" } },
      ].filter((d) => d.value > 0),
    }],
  };

  const riskOpt = {
    backgroundColor: "transparent",
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0, textStyle: { color: dark ? "#B8C4DC" : "#475569", fontSize: 10 } },
    series: [{
      type: "pie", radius: ["45%", "68%"], center: ["50%", "44%"],
      label: { show: false },
      data: [
        { name: "low",    value: riskCounts.low,    itemStyle: { color: "#34D399" } },
        { name: "medium", value: riskCounts.medium, itemStyle: { color: "#F59E0B" } },
        { name: "high",   value: riskCounts.high,   itemStyle: { color: "#F43F5E" } },
      ].filter((d) => d.value > 0),
    }],
  };

  const latOpt = {
    backgroundColor: "transparent",
    grid: { left: 44, right: 12, top: 16, bottom: 28 },
    xAxis: { type: "category" as const, data: ["<100ms", "100-500", "500ms-1s", "1-5s", ">5s"], ...ax },
    yAxis: { type: "value" as const, ...ax },
    series: [{
      type: "bar",
      data: latBins.map((v, i) => ({ value: v, itemStyle: { color: ["#34D399","#00D4FF","#A87BFF","#F59E0B","#F43F5E"][i], borderRadius: [3, 3, 0, 0] } })),
      barMaxWidth: 32,
    }],
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <LabStat label="Actions proposed"  value={proposed.length.toString()}  sub="total in session" color="text-vio" />
        <LabStat label="Auto-approved"     value={verdictCounts.auto.toString()}  sub="policy verdict"  color="text-ok"  />
        <LabStat label="Execution success" value={`${successRate}%`}            sub={`${executed.length} executed`}  color={successRate >= 80 ? "text-ok" : "text-warn"} />
        <LabStat label="Rollbacks"         value={executed.filter((e) => e.rolled_back).length.toString()} sub="reversals"  color="text-warn" />
      </div>

      <div className="glass overflow-hidden rounded-xl">
        <div className="border-b border-line-subtle px-4 py-3">
          <h3 className="text-sm font-medium text-ink-1">Action arm statistics</h3>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-bg-1/60 text-left text-[11px] uppercase tracking-wide text-ink-2">
            <tr>
              <th className="px-4 py-2 font-medium">Action</th>
              <th className="px-4 py-2 font-medium">Pulls</th>
              <th className="px-4 py-2 font-medium">Win rate</th>
              <th className="px-4 py-2 font-medium">Last execution</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line-subtle">
            {armStats.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-sm text-ink-2">
                  No action arm statistics reported yet.
                </td>
              </tr>
            ) : (
              armStats.map((arm) => (
                <tr key={arm.action_code} className="hover:bg-bg-2/30">
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-ink-0">{arm.action_label}</div>
                    <div className="font-mono text-[10px] text-ink-3">{arm.action_code}</div>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-ink-0">{arm.pull_count}</td>
                  <td className="px-4 py-2.5 font-mono text-ink-0">{Math.round(arm.win_rate * 100)}%</td>
                  <td className="px-4 py-2.5 text-xs text-ink-2">
                    {arm.last_execution_time ? new Date(arm.last_execution_time).toLocaleString() : "none"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        <div className="glass rounded-xl p-4">
          <h3 className="mb-2 text-sm font-medium text-ink-1">Policy verdict mix</h3>
          {proposed.length > 0 ? (
            <ReactEChartsCore option={withChartDefaults(verdictOpt)} notMerge lazyUpdate style={{ height: 180, width: "100%" }} opts={{ renderer: "canvas" }} />
          ) : (
            <div className="grid h-[180px] place-items-center text-sm text-ink-2">No actions yet</div>
          )}
        </div>
        <div className="glass rounded-xl p-4">
          <h3 className="mb-2 text-sm font-medium text-ink-1">Risk level distribution</h3>
          {proposed.length > 0 ? (
            <ReactEChartsCore option={withChartDefaults(riskOpt)} notMerge lazyUpdate style={{ height: 180, width: "100%" }} opts={{ renderer: "canvas" }} />
          ) : (
            <div className="grid h-[180px] place-items-center text-sm text-ink-2">No actions yet</div>
          )}
        </div>
        <div className="glass rounded-xl p-4">
          <h3 className="mb-2 text-sm font-medium text-ink-1">Execution latency</h3>
          {executed.length > 0 ? (
            <ReactEChartsCore option={withChartDefaults(latOpt)} notMerge lazyUpdate style={{ height: 180, width: "100%" }} opts={{ renderer: "canvas" }} />
          ) : (
            <div className="grid h-[180px] place-items-center text-sm text-ink-2">No executions yet</div>
          )}
        </div>
      </div>

      {modeBreak.length > 0 && (
        <div className="glass rounded-xl p-4">
          <h3 className="mb-3 text-sm font-medium text-ink-1">Execution mode breakdown</h3>
          <div className="flex flex-wrap gap-4">
            {modeBreak.map(([mode, count]) => (
              <div key={mode} className="flex items-center gap-2 text-sm">
                <span className="h-2 w-2 rounded-full bg-cy" />
                <span className="text-ink-2">{mode}</span>
                <span className="font-mono font-medium text-ink-0">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── RAG card ─────────────────────────────────────────────────────────────

function RagCard({ ragHealth }: { ragHealth: { ok: boolean; collections?: number; docs?: number } | null }) {
  return (
    <div className="glass rounded-xl p-4">
      <div className="mb-3 flex items-center gap-2">
        <Database className="h-4 w-4 text-cy" />
        <h3 className="text-sm font-medium text-ink-1">RAG knowledge base</h3>
        <span className={cn(
          "ml-auto rounded-full px-2 py-0.5 text-[11px] font-medium",
          ragHealth === null ? "bg-bg-2 text-ink-3"
            : ragHealth.ok ? "bg-ok-soft text-ok"
            : "bg-bad-soft text-bad",
        )}>
          {ragHealth === null ? "probing…" : ragHealth.ok ? "healthy" : "unreachable"}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-3 text-center">
        <div className="rounded-lg border border-line-subtle bg-bg-2/40 p-3">
          <div className="font-mono text-xl text-ink-0">{ragHealth?.collections ?? "—"}</div>
          <div className="text-[11px] text-ink-2">collections</div>
        </div>
        <div className="rounded-lg border border-line-subtle bg-bg-2/40 p-3">
          <div className="font-mono text-xl text-ink-0">{ragHealth?.docs ?? "—"}</div>
          <div className="text-[11px] text-ink-2">documents</div>
        </div>
        <div className="rounded-lg border border-line-subtle bg-bg-2/40 p-3">
          <div className="font-mono text-xl text-ink-0">MiniLM</div>
          <div className="text-[11px] text-ink-2">embedding model</div>
        </div>
      </div>
      <div className="mt-2 text-[11px] text-ink-3">
        sentence-transformers/all-MiniLM-L6-v2 · Chroma 0.5 · shared across all agents
      </div>
    </div>
  );
}

// ─── shared primitives ────────────────────────────────────────────────────

function LabStat({ label, value, sub, color }: { label: string; value: string; sub: string; color: string }) {
  return (
    <div className="glass rounded-xl p-4">
      <div className="text-xs uppercase tracking-wide text-ink-2">{label}</div>
      <div className={cn("mt-1.5 font-mono text-2xl tabular-nums", color)}>{value}</div>
      <div className="mt-0.5 text-[11px] text-ink-3">{sub}</div>
    </div>
  );
}

// ─── Memory tab (Sprint I) ────────────────────────────────────────────────────

interface MemoryEntry {
  id: string;
  text: string;
  cell_id?: string;
  severity?: string;
  saved_at: string;
}

interface RagResult {
  id: string;
  text: string;     // normalised from hit.document
  distance: number; // L2 distance from Chroma (lower = better)
  metadata?: Record<string, string>;
}

interface RawRagHit {
  id?: string;
  document?: string;
  text?: string;
  distance?: number;
  metadata?: Record<string, string>;
}

function distanceToRelevance(d: number): number {
  // Chroma L2: 0=perfect, ~2=unrelated. Map to 0-100% relevance.
  return Math.max(0, Math.min(100, Math.round((1 - d / 2) * 100)));
}

function MemoryTab({ alerts }: { alerts: AlertEvent[] }) {
  const [draft, setDraft]         = useState("");
  const [cellId, setCellId]       = useState("");
  const [severity, setSeverity]   = useState("medium");
  const [saving, setSaving]       = useState(false);
  const [saved, setSaved]         = useState<MemoryEntry[]>([]);

  const [query, setQuery]         = useState("");
  const [querying, setQuerying]   = useState(false);
  const [results, setResults]     = useState<RagResult[] | null>(null);

  const lastAlert = alerts[0];

  async function saveLesson() {
    if (!draft.trim()) return;
    setSaving(true);
    const entry: MemoryEntry = {
      id:       `mem-${Date.now()}`,
      text:     draft.trim(),
      cell_id:  cellId || undefined,
      severity: severity,
      saved_at: new Date().toISOString(),
    };
    try {
      await fetch(`${RAG_URL}/ingest`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          collection: "qos_operator_memory",
          items: [{
            id: entry.id,
            text: entry.text,
            metadata: { cell_id: entry.cell_id ?? "", severity: entry.severity ?? "", saved_at: entry.saved_at },
          }],
        }),
      });
      setSaved((prev) => [entry, ...prev]);
      setDraft("");
      setCellId("");
    } catch { /* ignore */ }
    finally { setSaving(false); }
  }

  async function runQuery() {
    if (!query.trim()) return;
    setQuerying(true);
    setResults(null);
    try {
      const r = await fetch(`${RAG_URL}/query`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ collection: "qos_operator_memory", text: query.trim(), top_k: 5 }),
      });
      if (r.ok) {
        const j = await r.json();
        const response = j as { hits?: RawRagHit[]; results?: RawRagHit[]; items?: RawRagHit[] };
        const hits = response.hits ?? response.results ?? response.items ?? [];
        setResults(hits.map((h) => ({
          id:       h.id ?? `${h.document ?? h.text ?? "memory"}-${h.distance ?? 2}`,
          text:     h.document ?? h.text ?? "",
          distance: h.distance ?? 2,
          metadata: h.metadata,
        })));
      }
    } catch { /* ignore */ }
    finally { setQuerying(false); }
  }

  function prefillFromAlert() {
    if (!lastAlert) return;
    setDraft(
      `Incident: ${lastAlert.display_label} (${lastAlert.severity}) on cell ${lastAlert.cell_id ?? "—"}. ` +
      `Detector: ${lastAlert.detector}. ` +
      (lastAlert.top_factors?.length
        ? `Top factor: ${lastAlert.top_factors[0].display_label} (${lastAlert.top_factors[0].direction}).`
        : ""),
    );
    setCellId(lastAlert.cell_id ?? "");
    setSeverity(lastAlert.severity);
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      {/* ── save lesson ── */}
      <div className="space-y-4">
        <div className="glass rounded-xl p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <PenLine className="h-4 w-4 text-vio" />
              <h3 className="text-sm font-medium text-ink-0">Save lesson to memory</h3>
            </div>
            {lastAlert && (
              <button
                onClick={prefillFromAlert}
                className="text-xs text-cy hover:underline"
              >
                Prefill from latest alert
              </button>
            )}
          </div>

          <div className="space-y-3">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={5}
              placeholder="Describe what happened, what the root cause was, and what remediation worked…"
              className="w-full resize-none rounded-lg border border-line-subtle bg-bg-2/60 px-3 py-2 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-cy"
            />
            <div className="flex gap-2">
              <input
                value={cellId}
                onChange={(e) => setCellId(e.target.value)}
                placeholder="Cell ID (optional)"
                className="flex-1 rounded-lg border border-line-subtle bg-bg-2/60 px-3 py-1.5 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-cy"
              />
              <select
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
                className="rounded-lg border border-line-subtle bg-bg-2/60 px-2 py-1.5 text-sm text-ink-0 focus:outline-none focus:ring-1 focus:ring-cy"
              >
                {["info", "low", "medium", "high", "critical"].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <button
              onClick={saveLesson}
              disabled={saving || !draft.trim()}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-vio px-4 py-2 text-sm font-medium text-bg-0 transition hover:opacity-90 disabled:opacity-40"
            >
              {saving
                ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Saving…</>
                : <><BookMarked className="h-3.5 w-3.5" /> Save to operator memory</>
              }
            </button>
          </div>
        </div>

        {/* session-saved entries */}
        {saved.length > 0 && (
          <div className="glass rounded-xl p-5">
            <h3 className="mb-3 text-xs font-medium uppercase tracking-wide text-ink-2">
              Saved this session ({saved.length})
            </h3>
            <ul className="space-y-3">
              {saved.map((m) => (
                <li key={m.id} className="rounded-lg border border-line-subtle bg-bg-2/40 p-3">
                  <p className="text-sm text-ink-1 leading-relaxed line-clamp-3">{m.text}</p>
                  <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-3">
                    {m.cell_id && <span>Cell {m.cell_id}</span>}
                    <span className="uppercase">{m.severity}</span>
                    <span>{new Date(m.saved_at).toLocaleTimeString()}</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* ── semantic search ── */}
      <div className="space-y-4">
        <div className="glass rounded-xl p-5">
          <div className="mb-4 flex items-center gap-2">
            <Search className="h-4 w-4 text-cy" />
            <h3 className="text-sm font-medium text-ink-0">Query operator memory</h3>
          </div>
          <div className="flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runQuery()}
              placeholder="e.g. latency surge cell C1 resolution…"
              className="flex-1 rounded-lg border border-line-subtle bg-bg-2/60 px-3 py-1.5 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-cy"
            />
            <button
              onClick={runQuery}
              disabled={querying || !query.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-cy px-3 py-1.5 text-sm font-medium text-bg-0 transition hover:opacity-90 disabled:opacity-40"
            >
              {querying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
            </button>
          </div>

          {results !== null && (
            <div className="mt-4 space-y-3">
              {results.length === 0 ? (
                <div className="rounded-lg border border-dashed border-line-subtle p-6 text-center text-sm text-ink-2">
                  No matches found in operator memory.
                </div>
              ) : (
                results.map((r) => (
                  <div key={r.id} className="rounded-lg border border-line-subtle bg-bg-2/40 p-3">
                    <div className="mb-1.5 flex items-center justify-between gap-2">
                      <span className={cn(
                        "rounded px-1.5 py-0.5 font-mono text-[10px]",
                        distanceToRelevance(r.distance) >= 60 ? "bg-ok-soft text-ok" : "bg-vio-soft text-vio",
                      )}>
                        {distanceToRelevance(r.distance)}% match
                      </span>
                      {r.metadata?.cell_id && (
                        <span className="text-[11px] text-ink-3">Cell {r.metadata.cell_id}</span>
                      )}
                    </div>
                    <p className="text-sm leading-relaxed text-ink-1">{r.text}</p>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        <div className="glass rounded-xl p-4 text-xs text-ink-2">
          <div className="mb-1 flex items-center gap-2 text-ink-1">
            <Database className="h-3.5 w-3.5 text-cy" />
            <span className="font-medium">Collection: qos_operator_memory</span>
          </div>
          <p className="leading-relaxed">
            Lessons are embedded with sentence-transformers/all-MiniLM-L6-v2 and stored in Chroma.
            Semantic search returns the closest matches — not keyword search.
            Entries persist across sessions.
          </p>
        </div>
      </div>
    </div>
  );
}
