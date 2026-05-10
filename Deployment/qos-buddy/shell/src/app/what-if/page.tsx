"use client";

import { type ComponentType, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import {
  Activity,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Eye,
  FlaskConical,
  Lightbulb,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  XCircle,
} from "lucide-react";
import { useLive } from "@/lib/store";
import { EmptyState } from "@/components/ui/empty-state";
import { withChartDefaults } from "@/lib/chart-defaults";
import { cn } from "@/lib/utils";
import { RoleGate, useAuth } from "@/components/providers/auth-provider";
import type { MetricEvent, ProposedActionEvent } from "@/lib/types";

const ReactEChartsCore = dynamic(() => import("echarts-for-react"), { ssr: false });
const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8080";

// ─── KPI metadata ─────────────────────────────────────────────────────────

interface KpiSpec {
  key: keyof MetricEvent;
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  warnAt: number;
  badAt: number;
  higherIsBetter?: boolean;
  weight: number;
}

const KPIS: KpiSpec[] = [
  { key: "latency_ms",      label: "Round-trip delay",  unit: "ms",   min: 0,   max: 300, step: 1,  warnAt: 80,  badAt: 150, weight: 0.28 },
  { key: "jitter_ms",       label: "Jitter",            unit: "ms",   min: 0,   max: 100, step: 1,  warnAt: 20,  badAt: 50,  weight: 0.18 },
  { key: "packet_loss_pct", label: "Packet loss",       unit: "%",    min: 0,   max: 10,  step: 0.1,warnAt: 1,   badAt: 3,   weight: 0.30 },
  { key: "throughput_mbps", label: "Throughput",        unit: "Mbps", min: 0,   max: 500, step: 5,  warnAt: 50,  badAt: 10,  higherIsBetter: true, weight: 0.14 },
  { key: "cpu_pct",         label: "CPU utilisation",   unit: "%",    min: 0,   max: 100, step: 1,  warnAt: 70,  badAt: 90,  weight: 0.10 },
];

interface ProjectionPoint {
  t: number;
  value: number;
}

interface WhatIfArm {
  action_label: string;
  confidence: number;
  projected_improvement: number;
  breach_risk_after: number;
  safety_pass: boolean;
  time_series_no_action: ProjectionPoint[];
  time_series_with_action: ProjectionPoint[];
}

interface WhatIfResponse {
  arms: WhatIfArm[];
  baseline_kpis: Record<string, number>;
}

// ─── Stress score ─────────────────────────────────────────────────────────

function kpiStress(spec: KpiSpec, value: number): number {
  if (spec.higherIsBetter) {
    // lower = worse
    if (value >= spec.warnAt) return 0;
    if (value <= spec.badAt)  return 1;
    return (spec.warnAt - value) / (spec.warnAt - spec.badAt);
  }
  if (value <= spec.warnAt) return 0;
  if (value >= spec.badAt)  return 1;
  return (value - spec.warnAt) / (spec.badAt - spec.warnAt);
}

function compositeScore(values: Record<string, number>): number {
  let total = 0;
  let weight = 0;
  for (const spec of KPIS) {
    const v = values[spec.key as string];
    if (v == null) continue;
    total  += kpiStress(spec, v) * spec.weight;
    weight += spec.weight;
  }
  return weight > 0 ? total / weight : 0;
}

// ─── Breach horizon helpers ───────────────────────────────────────────────

function linearTrend(points: number[]): number {
  const n = points.length;
  if (n < 2) return 0;
  const sumX = (n * (n - 1)) / 2;
  const sumX2 = ((n - 1) * n * (2 * n - 1)) / 6;
  const sumY = points.reduce((a, b) => a + b, 0);
  const sumXY = points.reduce((acc, y, i) => acc + i * y, 0);
  return (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
}

function secondsToBreachFromTrend(last: number, slope: number, threshold: number, higherIsBetter?: boolean): number | null {
  if (slope === 0) return null;
  if (!higherIsBetter) {
    if (last >= threshold) return 0;
    if (slope <= 0) return null;
    return (threshold - last) / slope;
  } else {
    if (last <= threshold) return 0;
    if (slope >= 0) return null;
    return (last - threshold) / (-slope);
  }
}

function cleanScenarioText(text?: string | null): string {
  if (!text) return "";
  return text
    .replace(/\b[Ss]imulated\b/g, "guarded")
    .replace(/\b[Ss]imulator\b/g, "guarded preview")
    .replace(/\b[Ss]imulation\b/g, "what-if preview")
    .trim();
}

// ─── Page ─────────────────────────────────────────────────────────────────

export default function WhatIfPage() {
  return (
    <RoleGate allow={["noc_executive", "ai_engineer", "site_admin"]}>
      <WhatIfPageContent />
    </RoleGate>
  );
}

function WhatIfPageContent() {
  const metrics  = useLive((s) => s.metrics);
  const { demoMode, role, token } = useAuth();

  const latest = metrics[metrics.length - 1];
  const selectedCell = latest?.cell_id ?? null;
  const [simulation, setSimulation] = useState<WhatIfResponse | null>(null);
  const [simLoading, setSimLoading] = useState(false);
  const [simError, setSimError] = useState<string | null>(null);

  // Initialise sliders from latest metric, falling back to midpoints
  const [values, setValues] = useState<Record<string, number>>(() => {
    const init: Record<string, number> = {};
    for (const s of KPIS) {
      const lv = latest?.[s.key] as number | null | undefined;
      init[s.key as string] = lv != null ? lv : s.higherIsBetter ? s.max * 0.7 : s.min;
    }
    return init;
  });

  function resetToLive() {
    if (!latest) return;
    const next: Record<string, number> = {};
    for (const s of KPIS) {
      const lv = latest?.[s.key] as number | null | undefined;
      next[s.key as string] = lv != null ? lv : values[s.key as string];
    }
    setValues(next);
  }

  async function runWhatIf(overrides: Record<string, number>) {
    const authHeader = demoMode ? `Bearer demo:${role}` : token ? `Bearer ${token}` : null;
    if (!authHeader) {
      setSimError("Authentication is not ready.");
      return;
    }
    setSimLoading(true);
    setSimError(null);
    try {
      const r = await fetch(`${GATEWAY_URL}/api/what-if`, {
        method: "POST",
        headers: {
          authorization: authHeader,
          "content-type": "application/json",
        },
        body: JSON.stringify({ kpi_overrides: overrides, cell_id: selectedCell }),
      });
      if (!r.ok) {
        throw new Error(`what-if request failed with ${r.status}`);
      }
      const data = (await r.json()) as WhatIfResponse;
      setSimulation(data);
    } catch {
      setSimError("Could not reach the what-if simulator.");
    } finally {
      setSimLoading(false);
    }
  }

  const score = useMemo(() => compositeScore(values), [values]);
  const scoreLabel = score < 0.4 ? "Healthy" : score < 0.75 ? "Degraded" : "Critical";
  const scoreCls   = score < 0.4 ? "text-ok" : score < 0.75 ? "text-warn" : "text-bad";
  const scoreRing  = score < 0.4 ? "#34D399" : score < 0.75 ? "#F59E0B" : "#F43F5E";

  // Breach horizon from live metrics
  const breachHorizon = useMemo(() => {
    const window = metrics.slice(-60); // last 60 samples
    return KPIS.map((spec) => {
      const vals: number[] = window
        .map((m) => m[spec.key] as number | null)
        .filter((v): v is number => v != null);
      if (vals.length < 3) return { spec, secsToWarn: null, secsToBad: null };
      const slope = linearTrend(vals);
      const last  = vals[vals.length - 1];
      return {
        spec,
        current: last,
        slope,
        secsToWarn: secondsToBreachFromTrend(last, slope, spec.warnAt, spec.higherIsBetter),
        secsToBad:  secondsToBreachFromTrend(last, slope, spec.badAt,  spec.higherIsBetter),
      };
    });
  }, [metrics]);

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">What-If Sandbox</h1>
          <p className="text-sm text-ink-2">
            Drag KPI sliders to explore hypothetical network states. The
            composite stress score estimates how the detection pipeline would
            react — no real packets sent.
          </p>
        </div>
        <span className="inline-flex items-center gap-2 rounded-lg border border-warn/40 bg-warn-soft/30 px-3 py-1.5 text-xs text-warn">
          <FlaskConical className="h-3.5 w-3.5" />
          Guarded preview — no network changes
        </span>
      </header>

      {/* ── scenario builder + reaction ── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-3">
          <div className="glass rounded-xl p-5">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-medium text-ink-1">KPI scenario builder</h3>
              <div className="flex items-center gap-2">
                {selectedCell && <span className="text-xs text-ink-3">cell {selectedCell}</span>}
                <button
                  onClick={resetToLive}
                  disabled={!latest || simLoading}
                  className="rounded-md border border-line-subtle bg-bg-2 px-2.5 py-1 text-xs text-ink-1 transition hover:bg-bg-3 hover:text-ink-0 disabled:opacity-40"
                >
                  Reset to live
                </button>
                <button
                  onClick={() => void runWhatIf(values)}
                  disabled={simLoading}
                  className="inline-flex items-center gap-1.5 rounded-md bg-cy px-3 py-1 text-xs font-medium text-bg-0 transition hover:opacity-90 disabled:opacity-50"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  {simLoading ? "Running..." : "Run what-if"}
                </button>
              </div>
            </div>
            <div className="space-y-5">
              {KPIS.map((spec) => {
                const v = values[spec.key as string];
                const stress = kpiStress(spec, v);
                const tone = stress < 0.33 ? "ok" : stress < 0.67 ? "warn" : "bad";
                const pct = ((v - spec.min) / (spec.max - spec.min)) * 100;
                const liveVal = latest?.[spec.key] as number | null | undefined;
                return (
                  <div key={spec.key as string}>
                    <div className="mb-1.5 flex items-center justify-between text-xs">
                      <span className="font-medium text-ink-1">{spec.label}</span>
                      <div className="flex items-center gap-3">
                        {liveVal != null && (
                          <span className="text-ink-3">live: {liveVal.toFixed(1)}{spec.unit}</span>
                        )}
                        <span className={cn(
                          "font-mono font-semibold tabular-nums",
                          tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : "text-bad",
                        )}>
                          {v.toFixed(spec.step < 1 ? 1 : 0)}{spec.unit}
                        </span>
                      </div>
                    </div>
                    <div className="relative">
                      <input
                        type="range"
                        min={spec.min}
                        max={spec.max}
                        step={spec.step}
                        value={v}
                        onChange={(e) => setValues((prev) => ({ ...prev, [spec.key as string]: parseFloat(e.target.value) }))}
                        className="slider w-full"
                      />
                      {/* threshold markers */}
                      <div className="mt-0.5 flex justify-between text-[10px] text-ink-3">
                        <span>{spec.min}{spec.unit}</span>
                        <span className="text-warn">
                          warn {spec.warnAt}{spec.unit}
                        </span>
                        <span className="text-bad">
                          act {spec.badAt}{spec.unit}
                        </span>
                        <span>{spec.max}{spec.unit}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* ── reaction panel ── */}
        <div className="space-y-3">
          <ScoreGauge score={score} label={scoreLabel} color={scoreRing} cls={scoreCls} />
          <ReactionPanel score={score} values={values} />
        </div>
      </div>

      {/* ── breach horizon ── */}
      <BreachHorizon rows={breachHorizon} />

      {/* ── counterfactual browser ── */}
      <CounterfactualBrowser
        arms={simulation?.arms ?? []}
        loading={simLoading}
        error={simError}
      />

      <style jsx global>{`
        .slider {
          -webkit-appearance: none;
          height: 4px;
          border-radius: 2px;
          background: hsl(var(--bg-3));
          outline: none;
          cursor: pointer;
        }
        .slider::-webkit-slider-thumb {
          -webkit-appearance: none;
          width: 16px;
          height: 16px;
          border-radius: 50%;
          background: hsl(var(--cy));
          border: 2px solid hsl(var(--bg-0));
          cursor: pointer;
          transition: transform 0.1s;
        }
        .slider::-webkit-slider-thumb:hover {
          transform: scale(1.2);
        }
        .slider::-moz-range-thumb {
          width: 16px;
          height: 16px;
          border-radius: 50%;
          background: hsl(var(--cy));
          border: 2px solid hsl(var(--bg-0));
          cursor: pointer;
        }
      `}</style>
    </div>
  );
}

// ─── Score gauge ──────────────────────────────────────────────────────────

function ScoreGauge({
  score, label, color, cls,
}: {
  score: number; label: string; color: string; cls: string;
}) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";
  const pct  = Math.round(score * 100);

  const option = {
    backgroundColor: "transparent",
    series: [{
      type: "gauge",
      startAngle: 200,
      endAngle: -20,
      min: 0,
      max: 100,
      radius: "85%",
      axisLine: {
        lineStyle: {
          width: 14,
          color: [[0.4, "#34D399"], [0.75, "#F59E0B"], [1, "#F43F5E"]],
        },
      },
      pointer: {
        length: "55%",
        width: 4,
        itemStyle: { color: color },
      },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      detail: {
        valueAnimation: true,
        formatter: "{value}",
        color: dark ? "#ECF2FB" : "#0F172A",
        fontSize: 28,
        fontFamily: "var(--font-jet)",
        offsetCenter: [0, "30%"],
      },
      data: [{ value: pct }],
    }],
  };

  return (
    <div className="glass rounded-xl p-4 text-center">
      <div className="text-xs uppercase tracking-wide text-ink-2 mb-1">Composite stress score</div>
      <ReactEChartsCore
        option={withChartDefaults(option)}
        notMerge
        lazyUpdate
        style={{ height: 160, width: "100%" }}
        opts={{ renderer: "canvas" }}
      />
      <div className={cn("text-lg font-semibold -mt-4", cls)}>{label}</div>
      <div className="mt-1 text-[11px] text-ink-3">
        0 = healthy · 1 = critical
      </div>
    </div>
  );
}

// ─── Reaction panel ───────────────────────────────────────────────────────

function ReactionPanel({ score, values }: { score: number; values: Record<string, number> }) {
  const loss   = values["packet_loss_pct"] ?? 0;
  const lat    = values["latency_ms"]      ?? 0;
  const thput  = values["throughput_mbps"] ?? 999;

  const stages: Array<{ icon: ComponentType<{ className?: string }>; name: string; fires: boolean; reason: string }> = [
    {
      icon: Eye,
      name: "Monitoring",
      fires: true,
      reason: "Always running — publishes every sample to qos.metrics.raw",
    },
    {
      icon: Activity,
      name: "Detection",
      fires: score >= 0.4,
      reason: score >= 0.75
        ? `Would raise a critical alert — score ${(score * 100).toFixed(0)}`
        : score >= 0.4
        ? `Would raise a watch-level alert — score ${(score * 100).toFixed(0)}`
        : `Below detection threshold (score ${(score * 100).toFixed(0)} < 40)`,
    },
    {
      icon: TrendingUp,
      name: "Prediction",
      fires: (lat > 60 || loss > 0.5 || thput < 100),
      reason: (lat > 60 || loss > 0.5 || thput < 100)
        ? "KPI trending toward threshold — forecast alert likely"
        : "KPIs stable, no breach projected",
    },
    {
      icon: Brain,
      name: "Diagnostic",
      fires: score >= 0.4,
      reason: score >= 0.4
        ? "Would receive the alert and run pattern matching"
        : "No alert to diagnose",
    },
    {
      icon: Lightbulb,
      name: "Insight",
      fires: score >= 0.4,
      reason: score >= 0.4
        ? "Would synthesise a lesson from the knowledge base"
        : "Idle — no diagnosis upstream",
    },
    {
      icon: ShieldCheck,
      name: "Optimization",
      fires: score >= 0.4,
      reason: score >= 0.75
        ? "Would propose a high-priority action; human approval likely required"
        : score >= 0.4
        ? "Would propose a low-risk automated action"
        : "No action needed",
    },
  ];

  return (
    <div className="glass rounded-xl p-4">
      <h3 className="mb-3 text-sm font-medium text-ink-1">Pipeline reaction</h3>
      <ol className="space-y-2">
        {stages.map((s, i) => {
          const Icon = s.icon;
          return (
            <li key={s.name} className="flex items-start gap-3">
              <div className={cn(
                "mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md",
                s.fires ? "bg-ok-soft text-ok" : "bg-bg-3 text-ink-3",
              )}>
                <Icon className="h-3.5 w-3.5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 text-xs">
                  <span className={cn("font-medium", s.fires ? "text-ink-0" : "text-ink-3")}>{s.name}</span>
                  {s.fires
                    ? <CheckCircle2 className="h-3 w-3 text-ok" />
                    : <XCircle      className="h-3 w-3 text-ink-3" />
                  }
                </div>
                <div className="text-[11px] text-ink-2 leading-tight">{s.reason}</div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// ─── Breach horizon ───────────────────────────────────────────────────────

function BreachHorizon({
  rows,
}: {
  rows: Array<{
    spec: KpiSpec;
    current?: number;
    slope?: number;
    secsToWarn: number | null;
    secsToBad: number | null;
  }>;
}) {
  function fmtSecs(s: number | null): React.ReactNode {
    if (s === null) return <span className="text-ok">no breach</span>;
    if (s === 0)    return <span className="text-bad animate-pulse font-semibold">now</span>;
    if (s < 60)     return <span className="text-bad font-semibold">{Math.ceil(s)}s</span>;
    if (s < 300)    return <span className="text-warn">{Math.ceil(s / 60)}m {Math.ceil(s % 60)}s</span>;
    return <span className="text-ink-2">{Math.ceil(s / 60)}m</span>;
  }

  const hasTrends = rows.some((r) => r.slope != null);
  if (!hasTrends) return null;

  return (
    <div className="glass rounded-xl overflow-hidden">
      <div className="border-b border-line-subtle px-4 py-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-ink-1">Breach horizon · live trend extrapolation</h3>
        <span className="text-xs text-ink-2">based on last 60 samples</span>
      </div>
      <table className="w-full text-sm">
        <thead className="bg-bg-1/60 text-left text-[11px] uppercase tracking-wide text-ink-2">
          <tr>
            <th className="px-4 py-2 font-medium">KPI</th>
            <th className="px-4 py-2 font-medium">Current</th>
            <th className="px-4 py-2 font-medium">Trend /s</th>
            <th className="px-4 py-2 font-medium">Warn threshold</th>
            <th className="px-4 py-2 font-medium">Act threshold</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line-subtle">
          {rows.map(({ spec, current, slope, secsToWarn, secsToBad }) => {
            if (current == null) return null;
            const stress = kpiStress(spec, current);
            const toneCls = stress < 0.33 ? "text-ok" : stress < 0.67 ? "text-warn" : "text-bad";
            const slopeSign = (slope ?? 0) > 0.005 ? "↑" : (slope ?? 0) < -0.005 ? "↓" : "—";
            const slopeTone = spec.higherIsBetter
              ? (slope ?? 0) < -0.005 ? "text-warn" : "text-ok"
              : (slope ?? 0) > 0.005 ? "text-warn" : "text-ok";
            return (
              <tr key={spec.key as string} className="hover:bg-bg-2/30">
                <td className="px-4 py-2.5">
                  <div className="font-medium text-ink-0">{spec.label}</div>
                  <div className="text-[11px] text-ink-3">{spec.unit}</div>
                </td>
                <td className="px-4 py-2.5 font-mono tabular-nums">
                  <span className={toneCls}>{current.toFixed(spec.step < 1 ? 1 : 0)}</span>
                </td>
                <td className="px-4 py-2.5 font-mono tabular-nums">
                  <span className={slopeTone}>
                    {slopeSign} {Math.abs(slope ?? 0).toFixed(2)}/s
                  </span>
                </td>
                <td className="px-4 py-2.5">{fmtSecs(secsToWarn)}</td>
                <td className="px-4 py-2.5">{fmtSecs(secsToBad)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Counterfactual browser ───────────────────────────────────────────────

function CounterfactualBrowser({
  arms,
  loading,
  error,
}: {
  arms: WhatIfArm[];
  loading: boolean;
  error: string | null;
}) {
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);

  useEffect(() => {
    setSelectedLabel((current) => current ?? arms[0]?.action_label ?? null);
  }, [arms]);

  const selected = arms.find((arm) => arm.action_label === selectedLabel) ?? arms[0] ?? null;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-ink-1">Counterfactual explorer</h3>
        <span className="text-xs text-ink-2">
          {loading ? "what-if running" : arms.length > 0 ? `${arms.length} recommended paths` : "run a what-if to compare actions"}
        </span>
      </div>

      {error && (
        <div className="rounded-xl border border-bad/30 bg-bad-soft/20 p-4 text-sm text-bad">{error}</div>
      )}

      {loading && (
        <div className="glass rounded-xl p-4 space-y-3 animate-pulse">
          <div className="h-4 w-1/3 rounded bg-bg-3" />
          <div className="h-48 rounded bg-bg-3" />
          <div className="h-3 w-2/3 rounded bg-bg-3" />
        </div>
      )}

      {!loading && arms.length === 0 && !error && (
        <EmptyState
          icon={<Sparkles className="h-8 w-8 text-ink-3" />}
          title="No what-if yet"
          body="Adjust the KPI sliders and run a what-if to compare the top recommended actions."
        />
      )}

      {!loading && arms.length > 0 && (
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_280px]">
          <div className="space-y-3">
            {arms.map((arm) => {
              const selectedArm = arm.action_label === selected?.action_label;
              return (
                <button
                  key={arm.action_label}
                  type="button"
                  onClick={() => setSelectedLabel(arm.action_label)}
                  className={cn(
                    "glass w-full rounded-xl border p-4 text-left transition hover:border-cy/50",
                    selectedArm ? "border-cy/70" : "border-line-subtle",
                  )}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Sparkles className="h-4 w-4 text-vio" />
                    <span className="font-medium text-ink-0">{arm.action_label}</span>
                    <span className="ml-auto inline-flex items-center gap-1 text-xs text-ink-2">
                      {arm.safety_pass
                        ? <ShieldCheck className="h-3.5 w-3.5 text-ok" />
                        : <XCircle className="h-3.5 w-3.5 text-bad" />}
                      {arm.safety_pass ? "Safety checks pass" : "Safety checks fail"}
                    </span>
                  </div>
                  <WhatIfProjectionChart arm={arm} />
                  <RiskBar value={arm.breach_risk_after} />
                </button>
              );
            })}
          </div>

          {selected && (
            <div className="glass rounded-xl p-4">
              <div className="text-xs uppercase tracking-wide text-ink-2">Selected action</div>
              <h4 className="mt-1 text-base font-semibold text-ink-0">{selected.action_label}</h4>
              <div className="mt-4 grid gap-3 text-sm">
                <CfStat label="Recommendation confidence" value={`${Math.min(96, Math.round(selected.confidence * 100))}%`} />
                <CfStat label="Projected improvement" value={`${selected.projected_improvement.toFixed(1)} health points`} />
                <CfStat label="Breach risk after" value={`${Math.round(selected.breach_risk_after * 100)}%`} />
                <CfStat label="Safety checks" value={selected.safety_pass ? "Passed" : "Needs review"} />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function WhatIfProjectionChart({ arm }: { arm: WhatIfArm }) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";
  const xs = arm.time_series_no_action.map((point) => `${point.t}s`);
  const ax = {
    axisLabel: { color: dark ? "#7C8AAB" : "#475569", fontSize: 10 },
    axisLine: { lineStyle: { color: dark ? "#2D3D5E" : "#CBD5E1" } },
    splitLine: { lineStyle: { color: dark ? "#1F2C44" : "#E2E8F0" } },
  };
  const option = {
    backgroundColor: "transparent",
    animation: true,
    animationDuration: 300,
    animationEasing: "cubicOut",
    grid: { left: 44, right: 12, top: 28, bottom: 28 },
    legend: { top: 0, textStyle: { color: dark ? "#B8C4DC" : "#475569", fontSize: 10 }, itemWidth: 10, itemHeight: 4 },
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    xAxis: { type: "category" as const, data: xs, ...ax },
    yAxis: { type: "value" as const, name: "Projected KPI", nameTextStyle: { color: dark ? "#7C8AAB" : "#475569", fontSize: 10 }, ...ax },
    series: [
      {
        name: "No action",
        type: "line",
        data: arm.time_series_no_action.map((point) => point.value),
        smooth: true,
        showSymbol: false,
        lineStyle: { color: "#F43F5E", width: 1.8, type: "dashed" },
      },
      {
        name: "With action",
        type: "line",
        data: arm.time_series_with_action.map((point) => point.value),
        smooth: true,
        showSymbol: false,
        lineStyle: { color: "#34D399", width: 1.8 },
      },
    ],
  };

  return (
    <ReactEChartsCore
      option={withChartDefaults(option)}
      notMerge
      lazyUpdate
      style={{ height: 200, width: "100%" }}
      opts={{ renderer: "canvas" }}
    />
  );
}

function RiskBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const tone = pct > 50 ? "bg-bad" : pct > 20 ? "bg-warn" : "bg-ok";
  return (
    <div className="mt-3">
      <div className="mb-1 flex items-center justify-between text-[11px] text-ink-2">
        <span>Breach risk after action</span>
        <span className="font-mono text-ink-1">{pct}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-bg-3">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function LegacyCounterfactualBrowser({ actions }: { actions: ProposedActionEvent[] }) {
  const [expanded, setExpanded] = useState<string | null>(actions[0]?.action_id ?? null);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-ink-1">Counterfactual explorer</h3>
        <span className="text-xs text-ink-2">{actions.length} action{actions.length === 1 ? "" : "s"} with projections</span>
      </div>
      {actions.map((action) => {
        const cf = action.counterfactual!;
        const open = expanded === action.action_id;
        return (
          <div key={action.action_id} className="glass overflow-hidden rounded-xl">
            <button
              type="button"
              onClick={() => setExpanded(open ? null : action.action_id)}
              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition hover:bg-bg-2/30"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 shrink-0 text-vio" />
                  <span className="font-medium text-ink-0 truncate">{action.title}</span>
                  <RiskPill level={action.risk_level} />
                </div>
                <div className="mt-0.5 text-[11px] text-ink-2">
                  Projecting <span className="font-mono">{cf.metric}</span> over {cf.horizon_seconds}s
                  {action.cell_id && <> · cell {action.cell_id}</>}
                </div>
              </div>
              {open
                ? <ChevronUp   className="h-4 w-4 shrink-0 text-ink-3" />
                : <ChevronDown className="h-4 w-4 shrink-0 text-ink-3" />
              }
            </button>
            {open && (
              <div className="border-t border-line-subtle p-4">
                <CfChart counterfactual={cf} />
                <div className="mt-3 grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
                  <CfStat label="Metric"      value={cf.metric} />
                  <CfStat label="Horizon"     value={`${cf.horizon_seconds}s`} />
                  <CfStat label="Confidence"  value={`${Math.min(96, Math.round(action.confidence * 100))}%`} />
                  <CfStat label="Verdict"     value={action.verdict} />
                </div>
                {cleanScenarioText(action.description) && (
                  <p className="mt-3 text-sm text-ink-1 border-t border-line-subtle pt-3">{cleanScenarioText(action.description)}</p>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function CfChart({ counterfactual }: { counterfactual: NonNullable<ProposedActionEvent["counterfactual"]> }) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";
  const n    = counterfactual.series_no_action.length;
  const xs   = Array.from({ length: n }, (_, i) =>
    `${Math.round(i * (counterfactual.horizon_seconds / Math.max(1, n - 1)))}s`,
  );
  const ax = {
    axisLabel: { color: dark ? "#7C8AAB" : "#475569", fontSize: 10 },
    axisLine:  { lineStyle: { color: dark ? "#2D3D5E" : "#CBD5E1" } },
    splitLine: { lineStyle: { color: dark ? "#1F2C44" : "#E2E8F0" } },
  };
  const option = {
    backgroundColor: "transparent",
    grid: { left: 44, right: 12, top: 28, bottom: 28 },
    legend: { top: 0, textStyle: { color: dark ? "#B8C4DC" : "#475569", fontSize: 10 }, itemWidth: 10, itemHeight: 4 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category" as const, data: xs, ...ax },
    yAxis: { type: "value" as const, name: counterfactual.metric, nameTextStyle: { color: dark ? "#7C8AAB" : "#475569", fontSize: 10 }, ...ax },
    series: [
      { name: "Without action", type: "line", data: counterfactual.series_no_action, smooth: true, showSymbol: false, lineStyle: { color: "#F43F5E", width: 1.8 }, areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "#F43F5E25" }, { offset: 1, color: "#F43F5E00" }] } } },
      { name: "With action",    type: "line", data: counterfactual.series_with_action, smooth: true, showSymbol: false, lineStyle: { color: "#34D399", width: 1.8 }, areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "#34D39925" }, { offset: 1, color: "#34D39900" }] } } },
    ],
  };
  return (
    <ReactEChartsCore
      option={withChartDefaults(option)}
      notMerge
      lazyUpdate
      style={{ height: 200, width: "100%" }}
      opts={{ renderer: "canvas" }}
    />
  );
}

function CfStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line-subtle bg-bg-2/40 p-2">
      <div className="text-[10px] uppercase tracking-wide text-ink-2">{label}</div>
      <div className="mt-0.5 font-mono text-sm text-ink-0">{value}</div>
    </div>
  );
}

function RiskPill({ level }: { level: "low" | "medium" | "high" }) {
  return (
    <span className={cn(
      "rounded-md px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
      level === "high"   ? "bg-bad-soft text-bad"
      : level === "medium" ? "bg-warn-soft text-warn"
      : "bg-ok-soft text-ok",
    )}>
      {level}
    </span>
  );
}
