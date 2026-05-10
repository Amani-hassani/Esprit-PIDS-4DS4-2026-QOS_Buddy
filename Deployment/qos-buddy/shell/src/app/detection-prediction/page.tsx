"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState, type ComponentType } from "react";
import { useTheme } from "next-themes";
import { Activity, Gauge, Radar } from "lucide-react";
import { IncidentStream } from "@/components/cards/incident-stream";
import { useAuth } from "@/components/providers/auth-provider";
import { EmptyState } from "@/components/ui/empty-state";
import { withChartDefaults } from "@/lib/chart-defaults";
import { useLive } from "@/lib/store";
import { cn } from "@/lib/utils";
import type { AlertEvent, MetricEvent, Severity, TopFactor } from "@/lib/types";

const GATEWAY_URL =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8080";
const SEVERITY_RANK: Record<Severity, number> = {
  info: 0,
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
};
const SEVERITY_OPTIONS: Severity[] = ["info", "low", "medium", "high", "critical"];

const ReactEChartsCore = dynamic(() => import("echarts-for-react"), {
  ssr: false,
  loading: () => (
    <div className="grid h-[260px] place-items-center rounded-xl border border-dashed border-line-subtle bg-bg-2/40 text-sm text-ink-2">
      Preparing chart…
    </div>
  ),
});

/**
 * Detection page — focuses on what the system has *already* flagged in the
 * live stream. Forecasting (time-to-breach projections) lives on its own
 * page so the operator can switch context without clutter.
 */
export default function DetectionPage() {
  const metrics = useLive((s) => s.metrics);
  const alerts = useLive((s) => s.alerts);
  const { token, demoMode, role, preferences } = useAuth();
  const effectiveToken = demoMode ? `demo:${role}` : token;
  const [severityFilter, setSeverityFilter] = useState<Severity>(
    preferences.alert_filter ?? "info",
  );
  useEffect(() => {
    if (preferences.alert_filter) setSeverityFilter(preferences.alert_filter);
  }, [preferences.alert_filter]);

  useEffect(() => {
    if (!effectiveToken) return;
    fetch(`${GATEWAY_URL}/api/memory/preference`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${effectiveToken}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ preference_type: "alert_filter", value: severityFilter }),
    }).catch(() => {});
  }, [effectiveToken, severityFilter]);

  const currentAlerts = useMemo(
    () =>
      alerts.filter(
        (a) =>
          a.detector !== "forecast" &&
          SEVERITY_RANK[a.severity] >= SEVERITY_RANK[severityFilter],
      ),
    [alerts, severityFilter],
  );

  // Throttled "headline" alert — flips at most once per 60s bucket so the Top
  // Factors card stops thrashing as new alerts stream in.
  const headlineAlert = useMemo(() => {
    if (currentAlerts.length === 0) return null;
    const BUCKET_MS = 60_000;
    const byBucket = new Map<number, AlertEvent>();
    for (const a of currentAlerts) {
      const bucket = Math.floor(new Date(a.occurred_at).getTime() / BUCKET_MS);
      const ex = byBucket.get(bucket);
      if (!ex || (SEVERITY_RANK[a.severity] ?? 0) > (SEVERITY_RANK[ex.severity] ?? 0)) {
        byBucket.set(bucket, a);
      }
    }
    return Array.from(byBucket.values()).sort(
      (x, y) => new Date(y.occurred_at).getTime() - new Date(x.occurred_at).getTime(),
    )[0] ?? null;
  }, [currentAlerts]);
  const latestAlert = headlineAlert;
  const latestMetric = metrics[metrics.length - 1] ?? null;

  // Sampled metrics for the chart — pull from `metrics` only every 5s so the
  // line doesn't flicker on every push.
  const [sampledMetrics, setSampledMetrics] = useState<MetricEvent[]>(metrics);
  useEffect(() => {
    setSampledMetrics(metrics);
    const id = window.setInterval(() => setSampledMetrics(useLive.getState().metrics), 5000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Detection</h1>
        <p className="text-sm text-ink-2">
          Live behavioural and threshold-based detection on the streaming
          metrics. Forecasts and time-to-breach projections live on the{" "}
          <a href="/forecast" className="text-cy hover:underline">
            Forecast
          </a>{" "}
          page.
        </p>
        <label className="mt-3 inline-flex items-center gap-2 text-xs text-ink-2">
          Minimum severity
          <select
            value={severityFilter}
            onChange={(event) => setSeverityFilter(event.target.value as Severity)}
            className="rounded-md border border-line-subtle bg-bg-2 px-2 py-1 text-ink-0"
          >
            {SEVERITY_OPTIONS.map((sev) => (
              <option key={sev} value={sev}>
                {sev}
              </option>
            ))}
          </select>
        </label>
      </header>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Tile
          label="Behavioural score"
          icon={Activity}
          value={latestMetric?.anomaly_score ?? null}
          format={(v) => v.toFixed(2)}
          tone={
            latestMetric?.anomaly_score != null && latestMetric.anomaly_score >= 0.75
              ? "bad"
              : latestMetric?.anomaly_score != null && latestMetric.anomaly_score >= 0.4
                ? "warn"
                : "ok"
          }
        />
        <Tile
          label="Active alerts"
          icon={Gauge}
          value={currentAlerts.length}
          format={(v) => v.toString()}
          tone={currentAlerts.length > 0 ? "warn" : "ok"}
        />
        <Tile
          label="Detector confidence"
          icon={Radar}
          value={latestAlert?.confidence ?? null}
          format={(v) => `${Math.min(96, Math.round(v * 100))}%`}
          tone={
            latestAlert
              ? latestAlert.confidence >= 0.75
                ? "ok"
                : "warn"
              : "muted"
          }
        />
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <AnomalyTimeline metrics={sampledMetrics} alerts={currentAlerts} />
        </div>
        <div className="lg:col-span-1">
          <TopFactorsCard alert={latestAlert} />
        </div>
      </section>

      <section>
        <IncidentStream />
      </section>
    </div>
  );
}

// ─── tile ────────────────────────────────────────────────────────────────

function Tile({
  label,
  icon: Icon,
  value,
  format,
  tone,
}: {
  label: string;
  icon: ComponentType<{ className?: string }>;
  value: number | null;
  format: (v: number) => string;
  tone: "ok" | "warn" | "bad" | "muted";
}) {
  const toneCls =
    tone === "bad"
      ? "text-bad"
      : tone === "warn"
        ? "text-warn"
        : tone === "ok"
          ? "text-ok"
          : "text-ink-0";
  return (
    <div className="glass rounded-xl p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-ink-2">{label}</span>
        <Icon className="h-4 w-4 text-ink-3" />
      </div>
      <div className={cn("mt-2 font-mono text-2xl tabular-nums", toneCls)}>
        {value == null ? "—" : format(value)}
      </div>
    </div>
  );
}

// ─── timeline ────────────────────────────────────────────────────────────

function AnomalyTimeline({
  metrics,
  alerts,
}: {
  metrics: MetricEvent[];
  alerts: AlertEvent[];
}) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  const option = useMemo(() => {
    const points = metrics
      .filter((m) => m.anomaly_score != null)
      .map((m) => [new Date(m.occurred_at).getTime(), m.anomaly_score as number]);

    const alertMarks = alerts.map((a) => ({
      xAxis: new Date(a.occurred_at).getTime(),
      label: { show: false },
      lineStyle: {
        color:
          a.severity === "critical" || a.severity === "high"
            ? "#F43F5E"
            : a.severity === "medium"
              ? "#F59E0B"
              : "#00D4FF",
        width: 1,
        type: "dashed",
      },
    }));

    const ax = {
      axisLabel: { color: dark ? "#7C8AAB" : "#475569" },
      axisLine: { lineStyle: { color: dark ? "#2D3D5E" : "#CBD5E1" } },
      splitLine: { lineStyle: { color: dark ? "#1F2C44" : "#E2E8F0" } },
    };

    return {
      backgroundColor: "transparent",
      grid: { left: 48, right: 16, top: 28, bottom: 28 },
      tooltip: {
        trigger: "axis",
        backgroundColor: dark ? "#0D1825" : "#FFFFFF",
        borderColor: dark ? "#2D3D5E" : "#E2E8F0",
        textStyle: { color: dark ? "#ECF2FB" : "#0F172A" },
      },
      xAxis: { type: "time", ...ax },
      yAxis: { type: "value", min: 0, max: 1, ...ax },
      series: [
        {
          name: "Behavioural score",
          type: "line",
          data: points,
          smooth: true,
          showSymbol: false,
          sampling: "lttb",
          lineStyle: { width: 1.8, color: "#A87BFF" },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "#A87BFF50" },
                { offset: 1, color: "#A87BFF00" },
              ],
            },
          },
          markLine: {
            silent: true,
            symbol: ["none", "none"],
            data: [
              {
                yAxis: 0.4,
                lineStyle: { color: "#F59E0B", type: "dotted", width: 1 },
                label: { formatter: "watch", color: "#F59E0B", fontSize: 10 },
              },
              {
                yAxis: 0.75,
                lineStyle: { color: "#F43F5E", type: "dotted", width: 1 },
                label: { formatter: "act", color: "#F43F5E", fontSize: 10 },
              },
              ...alertMarks,
            ],
          },
        },
      ],
    };
  }, [metrics, alerts, dark]);

  if (metrics.length === 0) {
    return (
      <div className="glass flex h-[300px] flex-col rounded-xl p-4">
        <h3 className="mb-3 text-sm font-medium text-ink-1">
          Behavioural score · last 10 minutes
        </h3>
        <div className="flex-1 grid place-items-center text-sm text-ink-2">
          Waiting for live samples…
        </div>
      </div>
    );
  }

  return (
    <div className="glass rounded-xl p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-ink-1">
          Behavioural score · last 10 minutes
        </h3>
        <span className="text-xs text-ink-2">watch ≥ 0.40 · act ≥ 0.75</span>
      </div>
      <ReactEChartsCore
        option={withChartDefaults(option)}
        notMerge={false}
        lazyUpdate
        style={{ height: 280, width: "100%" }}
        opts={{ renderer: "canvas" }}
      />
    </div>
  );
}

// ─── top contributing factors ────────────────────────────────────────────

function TopFactorsCard({ alert }: { alert: AlertEvent | null }) {
  const factors: TopFactor[] = alert?.top_factors ?? [];
  return (
    <div className="glass rounded-xl p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-ink-1">Top contributing factors</h3>
        {alert?.cell_id && (
          <span className="text-xs text-ink-2">Cell {alert.cell_id}</span>
        )}
      </div>
      {!alert ? (
        <div className="rounded-lg border border-dashed border-line-subtle p-6 text-center text-sm text-ink-2">
          No active incident.
        </div>
      ) : factors.length === 0 ? (
        <div className="rounded-lg border border-dashed border-line-subtle p-6 text-center text-sm text-ink-2">
          {alert.display_label} — no individual factor stood out.
        </div>
      ) : (
        <ul className="space-y-2">
          {factors.slice(0, 6).map((f) => {
            const w = Math.min(100, Math.max(2, Math.round(f.impact_pct)));
            return (
              <li key={f.display_label} className="text-sm">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-ink-0">{f.display_label}</span>
                  <span className="font-mono text-xs text-ink-2">
                    {f.direction === "down" ? "↓" : "↑"} {Math.round(f.impact_pct)}%
                  </span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-2">
                  <div
                    className={cn(
                      "h-full rounded-full",
                      f.direction === "down" ? "bg-warn" : "bg-bad",
                    )}
                    style={{ width: `${w}%` }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
