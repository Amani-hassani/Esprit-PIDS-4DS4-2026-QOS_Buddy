"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { useTheme } from "next-themes";
import { Layers, Radar, TrendingDown, TrendingUp } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { withChartDefaults } from "@/lib/chart-defaults";
import { useLive } from "@/lib/store";
import { cn } from "@/lib/utils";
import type { AlertEvent, MetricEvent } from "@/lib/types";

const ReactEChartsCore = dynamic(() => import("echarts-for-react"), {
  ssr: false,
  loading: () => (
    <div className="grid h-[280px] place-items-center rounded-xl border border-dashed border-line-subtle bg-bg-2/40 text-sm text-ink-2">
      Preparing chart…
    </div>
  ),
});

type TimeRange = "15m" | "60m" | "3h" | "24h";
const RANGE_MS: Record<TimeRange, number> = { "15m": 15 * 60_000, "60m": 60 * 60_000, "3h": 3 * 3600_000, "24h": 24 * 3600_000 };
const BREACH_LABEL: Record<string, string> = {
  latency_ms:      "Latency breach",
  jitter_ms:       "Jitter breach",
  packet_loss_pct: "Packet loss breach",
  throughput_mbps: "Throughput drop",
  mos_estimate:    "Voice quality drop",
  bler_proxy_pct:  "Error rate spike",
};

export default function ForecastPage() {
  const metrics = useLive((s) => s.metrics);
  const alerts  = useLive((s) => s.alerts);
  const proposed = useLive((s) => s.proposedActions);
  const [range, setRange] = useState<TimeRange>("60m");

  const forecastAlerts = useMemo(() => {
    const seen = new Map<string, AlertEvent>();
    for (const a of alerts) {
      if (a.detector !== "forecast" || a.time_to_breach_seconds == null) continue;
      const key = `${a.cell_id ?? ""}:${a.breach_metric ?? a.event_id}`;
      const ex = seen.get(key);
      if (!ex || new Date(a.occurred_at) > new Date(ex.occurred_at)) seen.set(key, a);
    }
    return Array.from(seen.values()).sort(
      (a, b) => (a.time_to_breach_seconds ?? Infinity) - (b.time_to_breach_seconds ?? Infinity),
    );
  }, [alerts]);

  // Fleet table: one row per unique cell, with the worst forecast for that cell
  const fleetRows = useMemo(() => {
    const byCell = new Map<string, AlertEvent[]>();
    for (const a of forecastAlerts) {
      const cell = a.cell_id ?? "default";
      const existing = byCell.get(cell) ?? [];
      existing.push(a);
      byCell.set(cell, existing);
    }
    return Array.from(byCell.entries()).map(([cell, cellAlerts]) => {
      const worst = cellAlerts[0]; // already sorted by TTS ascending
      const likelihood = Math.min(96, Math.round(worst.confidence * 100));
      const tts = worst.time_to_breach_seconds ?? 0;
      const etaLabel = tts < 60 ? `${Math.round(tts)}s` : tts < 3600 ? `${Math.round(tts / 60)} min` : `${Math.round(tts / 3600)} h`;
      const isRising = (worst.top_factors?.[0]?.direction ?? "up") === "up";
      return { cell, worst, likelihood, etaLabel, isRising };
    }).sort((a, b) => b.likelihood - a.likelihood);
  }, [forecastAlerts]);

  // Selected cell for the detail chart
  const [selectedCell, setSelectedCell] = useState<string | null>(null);
  const displayCell = selectedCell ?? fleetRows[0]?.cell ?? null;
  const cellForecast = forecastAlerts.find((a) => (a.cell_id ?? "default") === displayCell) ?? null;
  const cellProposed = proposed.find((a) => a.cell_id === displayCell) ?? proposed[0] ?? null;

  const headline = forecastAlerts[0] ?? null;
  const peersAtRisk = fleetRows.filter((r) => r.likelihood >= 50).length;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Forecast Outlook</h1>
          <p className="text-sm text-ink-2">Time-to-breach projections · what&apos;s likely to happen per cell</p>
        </div>
        {/* time range selector */}
        <div className="flex items-center gap-1 rounded-lg border border-line-subtle bg-bg-2 p-1">
          {(["15m", "60m", "3h", "24h"] as TimeRange[]).map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setRange(r)}
              className={cn(
                "rounded-md px-3 py-1 text-xs font-medium transition",
                range === r ? "bg-cy text-bg-0" : "text-ink-2 hover:text-ink-0",
              )}
            >
              {r}
            </button>
          ))}
        </div>
      </header>

      {forecastAlerts.length === 0 ? (
        <EmptyState
          icon={<Radar className="h-8 w-8 text-ink-3" />}
          title="No active forecasts"
          body="All KPIs are tracking healthy. Projected breaches appear here when a trend approaches threshold."
        />
      ) : (
        <>
          {/* ── Detail: chart + briefing ── */}
          {displayCell && (
            <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <FocusChart
                  cell={displayCell}
                  metrics={metrics}
                  alerts={forecastAlerts.filter((a) => (a.cell_id ?? "default") === displayCell)}
                  range={range}
                />
              </div>
              <div className="lg:col-span-1">
                <BriefingPanel
                  cell={displayCell}
                  forecast={cellForecast}
                  peersAtRisk={peersAtRisk}
                  action={cellProposed}
                />
              </div>
            </section>
          )}

          {/* ── Concurrent breaches timeline ── */}
          {forecastAlerts.length > 1 && (
            <ConcurrentBreachesTimeline
              alerts={forecastAlerts}
              onSelect={(cell) => setSelectedCell(cell)}
              selectedCell={displayCell}
            />
          )}

          {/* ── Fleet outlook table ── */}
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-medium text-ink-1">Fleet outlook · cells ranked by risk</h2>
              <span className="text-xs text-ink-2">{fleetRows.length} cells · refreshed live</span>
            </div>
            <div className="glass overflow-hidden rounded-xl">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line-subtle text-[10px] font-medium uppercase tracking-widest text-ink-3">
                    <th className="px-4 py-3 text-left">Cell</th>
                    <th className="px-4 py-3 text-left hidden md:table-cell">Zone</th>
                    <th className="px-4 py-3 text-left">Dominant risk</th>
                    <th className="px-4 py-3 text-center">Likelihood</th>
                    <th className="px-4 py-3 text-right">ETA</th>
                    <th className="px-4 py-3 text-center hidden sm:table-cell">Trend</th>
                    <th className="px-4 py-3 text-right">Advice</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line-subtle">
                  {fleetRows.map((row) => {
                    const isSelected = row.cell === displayCell;
                    const likeClass =
                      row.likelihood >= 80 ? "bg-bad-soft text-bad" :
                      row.likelihood >= 50 ? "bg-warn-soft text-warn" : "bg-info-soft text-info";
                    const domRisk = BREACH_LABEL[row.worst.breach_metric ?? ""] ?? row.worst.display_label;
                    return (
                      <tr
                        key={row.cell}
                        className={cn("cursor-pointer transition hover:bg-bg-2/40", isSelected && "bg-cy-soft/10")}
                        onClick={() => setSelectedCell(row.cell)}
                      >
                        <td className="px-4 py-3 font-mono font-medium text-ink-0">{row.cell}</td>
                        <td className="px-4 py-3 text-ink-2 hidden md:table-cell">—</td>
                        <td className="px-4 py-3 text-ink-1">{domRisk}</td>
                        <td className="px-4 py-3 text-center">
                          <span className={cn("inline-block rounded-full px-2 py-0.5 text-xs font-bold", likeClass)}>
                            {row.likelihood}%
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-ink-0">{row.etaLabel}</td>
                        <td className="px-4 py-3 text-center hidden sm:table-cell">
                          {row.isRising ? (
                            <span className="inline-flex items-center gap-1 text-bad text-xs font-medium">
                              <TrendingUp className="h-3.5 w-3.5" /> rising
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-ok text-xs font-medium">
                              <TrendingDown className="h-3.5 w-3.5" /> easing
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); setSelectedCell(row.cell); }}
                            className={cn(
                              "text-xs font-medium transition hover:underline",
                              row.likelihood >= 50 ? "text-cy" : "text-ink-2",
                            )}
                          >
                            {row.likelihood >= 50 ? "Open recommendation →" : "Watch →"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

// ─── Concurrent breaches timeline ─────────────────────────────────────────────

function ConcurrentBreachesTimeline({
  alerts,
  selectedCell,
  onSelect,
}: {
  alerts: AlertEvent[];
  selectedCell: string | null;
  onSelect: (cell: string) => void;
}) {
  // Use a shared horizon = max time-to-breach across forecasts (capped to 60 min for readability)
  const horizon = useMemo(() => {
    const maxTts = alerts.reduce((m, a) => Math.max(m, a.time_to_breach_seconds ?? 0), 0);
    return Math.min(3600, Math.max(60, maxTts));
  }, [alerts]);

  // Group by cell so overlapping breaches stack on the same row
  const rows = useMemo(() => {
    const byCell = new Map<string, AlertEvent[]>();
    for (const a of alerts) {
      const c = a.cell_id ?? "default";
      const arr = byCell.get(c) ?? [];
      arr.push(a);
      byCell.set(c, arr);
    }
    return Array.from(byCell.entries())
      .map(([cell, list]) => ({
        cell,
        list: list.slice().sort((x, y) => (x.time_to_breach_seconds ?? 0) - (y.time_to_breach_seconds ?? 0)),
      }))
      .sort((a, b) => (a.list[0]?.time_to_breach_seconds ?? 0) - (b.list[0]?.time_to_breach_seconds ?? 0));
  }, [alerts]);

  if (rows.length === 0) return null;

  const ticks = [0, 0.25, 0.5, 0.75, 1.0];

  return (
    <section className="glass rounded-xl p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-vio" />
          <h2 className="text-sm font-medium text-ink-1">Concurrent breaches · timeline</h2>
        </div>
        <span className="text-xs text-ink-2">
          {rows.length} cell{rows.length === 1 ? "" : "s"} · horizon {Math.round(horizon / 60)} min
        </span>
      </div>

      {/* axis */}
      <div className="relative mb-1 ml-24 h-4 border-b border-line-subtle">
        {ticks.map((t) => (
          <span
            key={t}
            className="absolute top-0 -translate-x-1/2 text-[9px] text-ink-3"
            style={{ left: `${t * 100}%` }}
          >
            {t === 0 ? "now" : `+${Math.round((t * horizon) / 60)} min`}
          </span>
        ))}
      </div>

      <ul className="space-y-1.5">
        {rows.map(({ cell, list }) => {
          const isSelected = cell === selectedCell;
          return (
            <li key={cell}>
              <button
                type="button"
                onClick={() => onSelect(cell)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-1 py-1 text-left transition hover:bg-bg-2/40",
                  isSelected && "bg-cy-soft/10",
                )}
              >
                <span className="w-22 shrink-0 truncate font-mono text-[11px] font-medium text-ink-0" style={{ width: 88 }}>
                  {cell}
                </span>
                <div className="relative h-5 flex-1 overflow-hidden rounded-md bg-bg-2/60">
                  {ticks.map((t) => (
                    <span
                      key={t}
                      className="pointer-events-none absolute top-0 h-full w-px bg-line-subtle/40"
                      style={{ left: `${t * 100}%` }}
                    />
                  ))}
                  {list.slice(0, 4).map((a, i) => {
                    const tts = a.time_to_breach_seconds ?? 0;
                    const startPct = Math.max(0, (tts / horizon) * 100 - 1.5);
                    const widthPct = Math.max(2, 3); // small breach marker
                    const tone =
                      tts < 300 ? "bg-bad text-bad" :
                      tts < 900 ? "bg-warn text-warn" : "bg-info text-info";
                    return (
                      <span
                        key={a.event_id}
                        title={`${a.display_label} · ETA ${Math.round(tts / 60)} min`}
                        className={cn("absolute top-0.5 bottom-0.5 rounded-sm", tone.split(" ")[0])}
                        style={{
                          left: `${startPct}%`,
                          width: `${widthPct}%`,
                          opacity: 0.85 - i * 0.1,
                        }}
                      />
                    );
                  })}
                </div>
                <span className="w-16 shrink-0 text-right font-mono text-[11px] text-ink-2">
                  {list.length} risk{list.length === 1 ? "" : "s"}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-[10px] text-ink-3">
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-3 rounded-sm bg-bad" /> &lt; 5 min
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-3 rounded-sm bg-warn" /> &lt; 15 min
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-3 rounded-sm bg-info" /> later
        </span>
      </div>
    </section>
  );
}

// ─── Focus chart ──────────────────────────────────────────────────────────────

function FocusChart({
  cell,
  metrics,
  alerts,
  range,
}: {
  cell: string;
  metrics: MetricEvent[];
  alerts: AlertEvent[];
  range: TimeRange;
}) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  const option = useMemo(() => {
    const cutoff = Date.now() - RANGE_MS[range];
    const cellMetrics = metrics.filter((m) => (m.cell_id ?? "default") === cell && new Date(m.occurred_at).getTime() >= cutoff);

    if (cellMetrics.length === 0) return null;

    const ax = {
      axisLabel: { color: dark ? "#7C8AAB" : "#475569", fontSize: 10 },
      axisLine:  { lineStyle: { color: dark ? "#2D3D5E" : "#CBD5E1" } },
      splitLine: { lineStyle: { color: dark ? "#1F2C44" : "#E2E8F0" } },
    };

    // Build normalized risk series (0 = safe, 1 = breached)
    const kpis: Array<{ key: keyof MetricEvent; name: string; color: string; invert: boolean; threshold: number }> = [
      { key: "latency_ms",      name: "Latency",    color: "#F43F5E", invert: false, threshold: 200 },
      { key: "throughput_mbps", name: "Throughput", color: "#00D4FF", invert: true,  threshold: 5   },
      { key: "packet_loss_pct", name: "Loss",       color: "#F59E0B", invert: false, threshold: 5   },
      { key: "mos_estimate",    name: "Voice",      color: "#A87BFF", invert: true,  threshold: 4   },
      { key: "jitter_ms",       name: "Jitter",     color: "#34D399", invert: false, threshold: 50  },
    ];

    const series = kpis.map((kpi) => {
      const observed: Array<[number, number]> = [];
      const projection: Array<[number, number]> = [];

      for (const m of cellMetrics) {
        const v = m[kpi.key] as number | null | undefined;
        if (v == null) continue;
        const risk = kpi.invert
          ? Math.max(0, 1 - v / kpi.threshold)
          : Math.min(1, v / kpi.threshold);
        observed.push([new Date(m.occurred_at).getTime(), Math.round(risk * 100) / 100]);
      }

      // Extend projection to the earliest matching alert's breach time
      const matchAlert = alerts.find((a) => a.breach_metric === kpi.key);
      if (observed.length > 1 && matchAlert?.time_to_breach_seconds) {
        const [lastT, lastV] = observed[observed.length - 1];
        projection.push([lastT, lastV]);
        projection.push([lastT + matchAlert.time_to_breach_seconds * 1000, 1.0]);
      }

      return [
        {
          name: kpi.name,
          type: "line",
          data: observed,
          smooth: true,
          showSymbol: false,
          sampling: "lttb",
          lineStyle: { color: kpi.color, width: 1.8 },
          itemStyle: { color: kpi.color },
        },
        ...(projection.length > 0 ? [{
          name: `${kpi.name} (proj)`,
          type: "line",
          data: projection,
          smooth: false,
          showSymbol: false,
          lineStyle: { color: kpi.color, width: 1.4, type: "dashed" },
          itemStyle: { color: kpi.color },
          legend: { show: false },
        }] : []),
      ];
    }).flat();

    return {
      backgroundColor: "transparent",
      grid: { left: 44, right: 16, top: 24, bottom: 60 },
      tooltip: { trigger: "axis" },
      legend: {
        bottom: 8,
        textStyle: { color: dark ? "#7C8AAB" : "#475569", fontSize: 10 },
        selectedMode: true,
      },
      xAxis: { type: "time", ...ax },
      yAxis: {
        type: "value",
        min: 0,
        max: 1,
        name: "Risk",
        nameTextStyle: { color: dark ? "#7C8AAB" : "#475569", fontSize: 10 },
        axisLabel: { formatter: (v: number) => `${Math.round(v * 100)}%`, ...ax.axisLabel },
        axisLine: ax.axisLine,
        splitLine: ax.splitLine,
        markLine: {
          silent: true,
          symbol: ["none", "none"],
          data: [{ yAxis: 0.8, lineStyle: { color: "#F43F5E", type: "dashed", width: 1 }, label: { formatter: "decision threshold 0.80", color: "#F43F5E", fontSize: 9 } }],
        },
      },
      series,
    };
  }, [cell, metrics, alerts, range, dark]);

  return (
    <div className="glass rounded-xl p-4">
      <div className="mb-1 text-[10px] font-medium uppercase tracking-widest text-ink-3">Risk projection</div>
      <div className="mb-3 text-sm font-semibold text-ink-0">{cell} — risk across dimensions</div>
      <div className="text-[10px] text-ink-3 mb-2">Solid line: observed · Dashed: projected · Shaded: decision threshold</div>
      {option ? (
        <ReactEChartsCore
          option={withChartDefaults(option)}
          lazyUpdate
          style={{ height: 280, width: "100%" }}
          opts={{ renderer: "canvas" }}
        />
      ) : (
        <div className="grid h-[280px] place-items-center text-sm text-ink-2">
          No telemetry data in the selected time window for this cell.
        </div>
      )}
    </div>
  );
}

// ─── Briefing panel ───────────────────────────────────────────────────────────

function BriefingPanel({
  cell,
  forecast,
  peersAtRisk,
  action,
}: {
  cell: string;
  forecast: AlertEvent | null;
  peersAtRisk: number;
  action: { title: string; verdict: string } | null;
}) {
  if (!forecast) return null;

  const tts = forecast.time_to_breach_seconds ?? 0;
  const etaLabel = tts < 60 ? `${Math.round(tts)} s` : `${Math.round(tts / 60)} min`;
  const etaColor = tts < 900 ? "text-bad" : tts < 1800 ? "text-warn" : "text-ok";
  const leadTime = tts < 300 ? "act now" : tts < 900 ? "< 15 min" : "within the hour";
  const confidence = Math.min(96, Math.round(forecast.confidence * 100));

  const domRisk = BREACH_LABEL[forecast.breach_metric ?? ""] ?? forecast.display_label;

  return (
    <div className="glass flex flex-col rounded-xl p-4">
      <div className="mb-3">
        <div className="text-[10px] font-medium uppercase tracking-widest text-ink-3">Briefing · {cell}</div>
        <p className="mt-1 text-sm leading-relaxed text-ink-1">
          In the next hour we expect a{" "}
          <span className={etaColor}>{domRisk.toLowerCase()} event</span>.
          {forecast.top_factors?.[0] && (
            <> {forecast.top_factors[0].display_label} is on track to hit threshold in {etaLabel}.</>
          )}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <BriefStat label="ETA" value={etaLabel} tone={tts < 900 ? "bad" : tts < 1800 ? "warn" : "ok"} />
        <BriefStat label="Confidence" value={`${confidence} %`} tone="ink" />
        <BriefStat label="Peers at risk" value={`${peersAtRisk} cells`} tone={peersAtRisk > 2 ? "bad" : "warn"} />
        <BriefStat label="Suggested lead time" value={leadTime} tone="ink" />
      </div>

      {action && (
        <div className="mt-3 rounded-lg border border-cy/30 bg-cy-soft/10 p-3">
          <div className="mb-1 text-[10px] font-medium uppercase tracking-widest text-cy">Recommended action</div>
          <div className="text-sm font-semibold text-ink-0">{action.title}</div>
          <a
            href="/optimization"
            className="mt-2 flex w-full items-center justify-center gap-1 rounded-md bg-cy py-2 text-xs font-semibold text-bg-0 transition hover:opacity-90"
          >
            Open recommendation
          </a>
        </div>
      )}
    </div>
  );
}

function BriefStat({ label, value, tone }: { label: string; value: string; tone: "ok" | "warn" | "bad" | "ink" }) {
  const cls = tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : tone === "bad" ? "text-bad" : "text-ink-0";
  return (
    <div className="rounded-lg border border-line-subtle bg-bg-2/40 p-2 text-center">
      <div className="text-[9px] font-medium uppercase tracking-widest text-ink-3">{label}</div>
      <div className={cn("mt-1 text-base font-bold tabular-nums", cls)}>{value}</div>
    </div>
  );
}
