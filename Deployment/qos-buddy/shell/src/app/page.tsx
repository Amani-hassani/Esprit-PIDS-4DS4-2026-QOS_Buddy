"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  CheckCircle2,
  ChevronRight,
} from "lucide-react";
import { KpiTile } from "@/components/cards/kpi-tile";
import { LiveChart } from "@/components/cards/live-chart";
import { PipelineHeartbeat } from "@/components/cards/pipeline-heartbeat";
import { useAuth } from "@/components/providers/auth-provider";
import { useLive } from "@/lib/store";
import { cn, formatNumber } from "@/lib/utils";
import { askAi } from "@/lib/ai";
import type { AlertEvent, MetricEvent, ProposedActionEvent } from "@/lib/types";

export default function CommandCenter() {
  const { role } = useAuth();
  const metrics  = useLive((s) => s.metrics);
  const alerts   = useLive((s) => s.alerts);
  const proposed = useLive((s) => s.proposedActions);
  const executed = useLive((s) => s.executedActions);
  const latest   = useMemo(() => metrics[metrics.length - 1] ?? null, [metrics]);

  const series = useMemo(() => buildSeries(metrics), [metrics]);

  const executedIds = useMemo(() => new Set(executed.map((e) => e.action_id)), [executed]);

  const pendingActions = useMemo(
    () => proposed.filter((a) => !executedIds.has(a.action_id) && a.verdict !== "rejected"),
    [proposed, executedIds],
  );

  const activeSituations = useMemo(() => {
    const seen = new Set<string>();
    const uniq: AlertEvent[] = [];
    const cutoff = Date.now() - 30 * 60_000;
    for (const a of alerts) {
      if (a.detector === "forecast") continue;
      if (new Date(a.occurred_at).getTime() < cutoff) continue;
      if (!seen.has(a.correlation_id)) { seen.add(a.correlation_id); uniq.push(a); }
    }
    const SEV = { critical: 4, high: 3, medium: 2, low: 1, info: 0 } as const;
    return uniq.sort((a, b) => (SEV[b.severity] ?? 0) - (SEV[a.severity] ?? 0));
  }, [alerts]);

  const forecastPreviews = useMemo(() => {
    const seen = new Map<string, AlertEvent>();
    for (const a of alerts) {
      if (a.detector !== "forecast" || a.time_to_breach_seconds == null) continue;
      const key = `${a.cell_id ?? ""}:${a.breach_metric ?? a.event_id}`;
      const ex = seen.get(key);
      if (!ex || new Date(a.occurred_at) > new Date(ex.occurred_at)) seen.set(key, a);
    }
    return Array.from(seen.values())
      .sort((a, b) => (a.time_to_breach_seconds ?? Infinity) - (b.time_to_breach_seconds ?? Infinity))
      .slice(0, 3);
  }, [alerts]);

  const criticalCell = useMemo(
    () => activeSituations[0]?.cell_id ?? latest?.cell_id ?? null,
    [activeSituations, latest],
  );

  const cellMetric = useMemo(() => {
    if (!criticalCell) return latest;
    for (let i = metrics.length - 1; i >= 0; i--) {
      if (metrics[i].cell_id === criticalCell) return metrics[i];
    }
    return latest;
  }, [metrics, criticalCell, latest]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Command Center</h1>
          <p className="text-sm text-ink-2">Live network health - active situations - decisions</p>
        </div>
        {latest?.cell_id && (
          <div className="rounded-lg border border-line-subtle bg-bg-2 px-3 py-1.5 text-xs">
            <span className="text-ink-2">Active cell</span>{" "}
            <span className="font-mono text-ink-0">{latest.cell_id}</span>
            {latest.zone_id && (
              <>
                <span className="mx-1 text-ink-3">·</span>
                <span className="text-ink-2">Zone </span>
                <span className="font-mono text-ink-0">{latest.zone_id}</span>
              </>
            )}
          </div>
        )}
      </header>

      {/* ── KPI tiles ── */}
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile label="Round-trip delay"  value={latest?.latency_ms ?? null}      unit="ms"   history={series.latency}    goodDirection="lower"  warn={80}  bad={150} />
        <KpiTile label="Delay variation"   value={latest?.jitter_ms ?? null}       unit="ms"   history={series.jitter}     goodDirection="lower"  warn={20}  bad={50}  />
        <KpiTile label="Packet loss"       value={latest?.packet_loss_pct ?? null} unit="%"    history={series.loss}       goodDirection="lower"  warn={1}   bad={3}   />
        <KpiTile label="Throughput"        value={latest?.throughput_mbps ?? null} unit="Mbps" history={series.throughput} goodDirection="higher"  warn={5}   bad={1}   />
      </section>

      {/* ── Network behaviour graph + Streaming shift note ── */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <LiveChart />
        </div>
        <div className="lg:col-span-2">
          <LiveTelemetry
            metric={cellMetric}
            alert={activeSituations[0] ?? null}
            actions={pendingActions}
            role={role}
          />
        </div>
      </section>

      {/* ── Active Situations + Decision Queue ── */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ActiveSituations alerts={activeSituations} />
        <DecisionQueue actions={pendingActions} />
      </section>

      {/* ── Projection (what's next) ── */}
      {forecastPreviews.length > 0 && (
        <ForecastPreviewCard forecasts={forecastPreviews} />
      )}

      <PipelineHeartbeat />
    </div>
  );
}

// ─── Active Situations ────────────────────────────────────────────────────────

const SEV_TONE = {
  critical: { bar: "bg-bad",     badge: "bg-bad-soft text-bad"   },
  high:     { bar: "bg-bad/70",  badge: "bg-bad-soft text-bad"   },
  medium:   { bar: "bg-warn",    badge: "bg-warn-soft text-warn" },
  low:      { bar: "bg-info",    badge: "bg-info-soft text-info" },
  info:     { bar: "bg-info/60", badge: "bg-info-soft text-info" },
} as const;

function ActiveSituations({ alerts }: { alerts: AlertEvent[] }) {
  const open = alerts.length;
  return (
    <div className="glass flex flex-col rounded-xl p-4" style={{ minHeight: 320 }}>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-[10px] font-medium uppercase tracking-widest text-ink-3">Active Situations</div>
          <div className="text-xs text-ink-2">Last 30 min - live collector every 10s</div>
        </div>
        {open > 0 && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-bad px-2.5 py-0.5 text-[11px] font-semibold text-white">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" />
            {open} OPEN
          </span>
        )}
      </div>

      {alerts.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 py-8 text-center">
          <CheckCircle2 className="h-8 w-8 text-ok" />
          <span className="text-sm text-ink-2">No active situations</span>
        </div>
      ) : (
        <>
          <ul className="flex-1 space-y-2 overflow-y-auto pr-1" style={{ maxHeight: 240 }}>
            {alerts.slice(0, 10).map((a) => (
              <AlertRow key={a.correlation_id ?? a.event_id} alert={a} />
            ))}
          </ul>
          <div className="mt-3 border-t border-line-subtle pt-3">
            <Link
              href="/detection-prediction"
              className="flex w-full items-center justify-center gap-1 rounded-lg border border-line-subtle py-2 text-xs font-medium text-ink-1 transition hover:border-cy hover:text-cy"
            >
              Open all {open} situation{open !== 1 ? "s" : ""} →
            </Link>
          </div>
        </>
      )}
    </div>
  );
}

function AlertRow({ alert }: { alert: AlertEvent }) {
  const tone = SEV_TONE[alert.severity] ?? SEV_TONE.medium;
  const minsAgo = Math.max(0, Math.round((Date.now() - new Date(alert.occurred_at).getTime()) / 60_000));
  const factors = alert.top_factors?.slice(0, 2).map((f) => f.display_label).join(" · ");

  return (
    <li className="flex items-stretch overflow-hidden rounded-lg border border-line-subtle bg-bg-2/40 transition hover:border-line">
      <div className={cn("w-1 shrink-0", tone.bar)} />
      <div className="flex-1 px-2 py-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className={cn("rounded px-1 py-0.5 text-[9px] font-medium uppercase tracking-wide", tone.badge)}>
              {alert.severity}
            </span>
            {alert.cell_id && <span className="text-[10px] text-ink-3">Cell {alert.cell_id}</span>}
          </div>
          <span className="shrink-0 text-[10px] text-ink-3">{minsAgo} min ago</span>
        </div>
        <div className="mt-0.5 text-sm font-medium leading-snug text-ink-0">{alert.display_label}</div>
        {factors && <div className="mt-0.5 truncate text-[11px] text-ink-2">{factors}</div>}
        {alert.time_to_breach_seconds != null && (
          <div className="mt-0.5 text-[11px] text-warn">
            Breach in {Math.round(alert.time_to_breach_seconds / 60)} min
          </div>
        )}
      </div>
    </li>
  );
}

// ─── Decision Queue ───────────────────────────────────────────────────────────

function DecisionQueue({ actions }: { actions: ProposedActionEvent[] }) {
  return (
    <div className="glass flex flex-col rounded-xl p-4" style={{ minHeight: 320 }}>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-[10px] font-medium uppercase tracking-widest text-ink-3">Awaiting You</div>
          <div className="text-xs text-ink-2">Decisions queued</div>
        </div>
        {actions.length > 0 && (
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-cy text-[11px] font-bold text-bg-0">
            {actions.length}
          </span>
        )}
      </div>

      {actions.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 py-8 text-center">
          <CheckCircle2 className="h-8 w-8 text-ok" />
          <span className="text-sm text-ink-2">Queue clear — no pending decisions</span>
        </div>
      ) : (
        <div className="flex-1 space-y-3 overflow-y-auto pr-1" style={{ maxHeight: 240 }}>
          {actions.slice(0, 5).map((action, idx) => (
            <DecisionCard key={action.action_id} action={action} featured={idx === 0} />
          ))}
        </div>
      )}
    </div>
  );
}

function DecisionCard({ action, featured }: { action: ProposedActionEvent; featured: boolean }) {
  const riskColor =
    action.risk_level === "low" ? "text-ok" :
    action.risk_level === "medium" ? "text-warn" : "text-bad";

  if (featured) {
    return (
      <div className="rounded-lg border border-cy/30 bg-cy-soft/10 p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-cy">Suggested Fix</span>
          {action.estimated_sla_burn_pct != null && (
            <span className="text-[10px] text-ink-3">est. {Math.ceil(action.estimated_sla_burn_pct)} min</span>
          )}
        </div>
        <div className="mb-1 text-sm font-semibold text-ink-0">{action.title}</div>
        <div className="mb-3 flex flex-wrap items-center gap-1.5 text-[11px]">
          {action.cell_id && <span className="text-ink-2">Cell {action.cell_id}</span>}
          <span className="text-ink-3">·</span>
          <span className={riskColor}>{action.risk_level} risk</span>
          <span className="text-ink-3">·</span>
          <span className="text-ink-2">{action.is_reversible ? "reversible" : "irreversible"}</span>
        </div>
        <div className="flex gap-2">
          <Link href="/optimization" className="flex flex-1 items-center justify-center rounded-md bg-cy py-2 text-xs font-semibold text-bg-0 transition hover:opacity-90">
            Review
          </Link>
          <Link href="/optimization" className="flex flex-1 items-center justify-center rounded-md border border-line-subtle py-2 text-xs text-ink-1 transition hover:bg-bg-3">
            Defer
          </Link>
        </div>
      </div>
    );
  }

  return (
    <Link href="/optimization" className="group flex items-center gap-3 rounded-lg border border-line-subtle bg-bg-2/40 p-3 transition hover:border-line">
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-ink-0">{action.title}</div>
        <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-ink-2">
          {action.cell_id && <span>Cell {action.cell_id}</span>}
          <span>·</span>
          <span className={riskColor}>{action.risk_level}</span>
          {action.verdict === "deferred" && (
            <><span>·</span><span className="text-ink-3">approval pending</span></>
          )}
        </div>
      </div>
      <ChevronRight className="h-4 w-4 shrink-0 text-ink-3 transition group-hover:text-cy" />
    </Link>
  );
}

// ─── Forecast Preview ─────────────────────────────────────────────────────────

function ForecastPreviewCard({ forecasts }: { forecasts: AlertEvent[] }) {
  return (
    <div className="glass rounded-xl p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-[10px] font-medium uppercase tracking-widest text-ink-3">Next 60 min</div>
          <div className="text-base font-semibold text-ink-0">What&apos;s likely to happen</div>
        </div>
        <span className="rounded-full border border-vio/30 bg-vio-soft/20 px-2.5 py-0.5 text-[11px] font-medium text-vio">
          PROJECTION
        </span>
      </div>

      <ul className="space-y-3">
        {forecasts.map((f) => {
          const tts = f.time_to_breach_seconds ?? 0;
          const label = tts < 60 ? `~${Math.round(tts)}s` : `~${Math.round(tts / 60)} min`;
          const urgency =
            tts < 900  ? "bg-bad-soft text-bad"  :
            tts < 1800 ? "bg-warn-soft text-warn" : "bg-info-soft text-info";

          return (
            <li key={f.event_id} className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-ink-0">
                  {f.cell_id ? `${f.cell_id} ` : ""}{f.display_label}
                </div>
                {f.top_factors?.[0] && (
                  <div className="text-[11px] text-ink-2">{f.top_factors[0].display_label}</div>
                )}
              </div>
              <span className={cn("shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold", urgency)}>
                {label}
              </span>
            </li>
          );
        })}
      </ul>

      <div className="mt-4 border-t border-line-subtle pt-3">
        <Link href="/forecast" className="flex w-full items-center justify-center gap-1 rounded-lg border border-vio/30 bg-vio-soft/10 py-2 text-xs font-medium text-vio transition hover:bg-vio-soft/20">
          Open forecast outlook →
        </Link>
      </div>
    </div>
  );
}

// ─── Live Telemetry ───────────────────────────────────────────────────────────

function LiveTelemetry({
  metric,
  alert,
  actions,
  role,
}: {
  metric: MetricEvent | null;
  alert: AlertEvent | null;
  actions: ProposedActionEvent[];
  role: string;
}) {
  const [shiftNote, setShiftNote] = useState<string | null>(null);
  const [noteLoading, setNoteLoading] = useState(false);

  useEffect(() => {
    if (!metric) return;
    let cancelled = false;
    const fallback = buildDeterministicNote(alert, actions, metric);
    setShiftNote(fallback);

    const load = async () => {
      setNoteLoading(true);
      const prompt = buildShiftPrompt(metric, alert, actions);
      const answer = await askAi(
        prompt,
        { current_page: "/", role, cell_id: metric.cell_id ?? undefined, alert_id: alert?.event_id },
        fallback,
      );
      if (!cancelled) {
        setShiftNote(answer);
        setNoteLoading(false);
      }
    };
    void load();
    const id = window.setInterval(() => void load(), 60_000);
    return () => { cancelled = true; window.clearInterval(id); };
  // re-synthesize only when cell or top alert changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metric?.cell_id, alert?.event_id, role]);

  if (!metric) return null;

  const cellLabel = alert?.cell_id
    ? `Cell ${alert.cell_id} · drilling on ${alert.severity}`
    : metric.cell_id ? `Cell ${metric.cell_id} · Live` : "Fleet · Live";

  const kpis = ([
    { label: "Latency",          value: metric.latency_ms,          target: 200, unit: "ms",   dir: "lower"  as const },
    { label: "Throughput",       value: metric.throughput_mbps,     target: 5,   unit: "Mbps", dir: "higher" as const },
    { label: "Packet loss",      value: metric.packet_loss_pct,     target: 5,   unit: "%",    dir: "lower"  as const },
    { label: "Block error rate", value: metric.bler_proxy_pct,      target: 10,  unit: "%",    dir: "lower"  as const },
    { label: "Voice quality",    value: metric.mos_estimate,        target: 4,   unit: "MOS",  dir: "higher" as const },
    { label: "Retransmit rate",  value: metric.tcp_retransmit_rate, target: 5,   unit: "%",    dir: "lower"  as const },
  ] as const).filter((k): k is typeof k & { value: number } => k.value != null);

  const featuredAction = actions[0] ?? null;

  return (
    <div className="glass overflow-hidden rounded-xl">
      {/* header */}
      <div className="flex items-center justify-between gap-3 border-b border-line-subtle px-5 py-3">
        <div>
          <div className="text-[10px] font-medium uppercase tracking-widest text-ink-3">Live Telemetry</div>
          <div className="mt-0.5 text-sm font-semibold text-ink-0">{cellLabel}</div>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-bad px-2.5 py-0.5 text-[11px] font-semibold text-white">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" />
          STREAMING
        </span>
      </div>

      {/* KPI bars */}
      <div className="grid grid-cols-1 gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
        {kpis.map((k) => <KpiBar key={k.label} {...k} />)}
      </div>

      {/* shift note */}
      <div className="border-t border-line-subtle bg-bg-2/30 px-5 py-4">
        <div className="mb-1 flex items-center gap-2 text-[10px] font-medium uppercase tracking-widest text-ink-3">
          <span>Shift Note</span>
          <span className="rounded-full border border-vio/30 bg-vio-soft/20 px-1.5 py-0.5 text-[9px] font-semibold text-vio">
            QWEN2.5 · RAG
          </span>
          {noteLoading && (
            <span className="inline-flex items-center gap-1 text-vio">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-vio" />
              synthesizing
            </span>
          )}
        </div>
        <p className="text-sm leading-relaxed text-ink-1">
          {shiftNote ?? buildDeterministicNote(alert, actions, metric)}
        </p>
        {featuredAction && (
          <div className="mt-3 flex flex-wrap gap-2">
            <Link href="/optimization" className="inline-flex items-center gap-1.5 rounded-md bg-cy px-3 py-1.5 text-xs font-medium text-bg-0 transition hover:opacity-90">
              Open recommendation
            </Link>
            {alert && (
              <Link href="/diagnostic" className="inline-flex items-center gap-1.5 rounded-md border border-line-subtle bg-bg-2 px-3 py-1.5 text-xs text-ink-1 transition hover:bg-bg-3">
                See incident
              </Link>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function KpiBar({
  label,
  value,
  target,
  unit,
  dir,
}: {
  label: string;
  value: number | null | undefined;
  target: number;
  unit: string;
  dir: "lower" | "higher";
}) {
  if (value == null) return null;
  const good = dir === "lower" ? value <= target * 0.8 : value >= target;
  const bad  = dir === "lower" ? value > target * 1.5  : value < target * 0.5;
  const pct  = dir === "lower"
    ? Math.min(100, (value / (target * 2)) * 100)
    : Math.min(100, (value / target) * 100);
  const barColor = bad ? "bg-bad" : good ? "bg-ok" : "bg-warn";
  const valColor = bad ? "text-bad" : good ? "text-ok" : "text-warn";
  const targetWord = dir === "lower" ? "threshold" : "target";

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2 text-xs">
        <span className="text-ink-2">{label}</span>
        <span className="flex items-center gap-1 font-mono">
          <span className={valColor}>{formatNumber(value)}</span>
          {unit && <span className="text-ink-3">{unit}</span>}
          <span className="text-ink-3">· {targetWord} {target}</span>
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-3">
        <div
          className={cn("h-full rounded-full transition-all duration-700", barColor)}
          style={{ width: `${Math.max(2, pct)}%` }}
        />
      </div>
    </div>
  );
}

function buildShiftPrompt(
  metric: MetricEvent,
  alert: AlertEvent | null,
  actions: ProposedActionEvent[],
): string {
  const lines: string[] = [];
  lines.push("You are the senior NOC engineer briefing the next shift. Write 2–3 short sentences (no bullets, no headers, no markdown).");
  lines.push("Speak in plain operator English, name the cell, and end with what the operator should do next.");
  lines.push("");
  lines.push(`Cell: ${metric.cell_id ?? "fleet"}`);
  const kpiBits: string[] = [];
  if (metric.latency_ms != null)      kpiBits.push(`latency ${metric.latency_ms.toFixed(0)}ms`);
  if (metric.jitter_ms != null)       kpiBits.push(`jitter ${metric.jitter_ms.toFixed(0)}ms`);
  if (metric.packet_loss_pct != null) kpiBits.push(`loss ${metric.packet_loss_pct.toFixed(2)}%`);
  if (metric.throughput_mbps != null) kpiBits.push(`throughput ${metric.throughput_mbps.toFixed(1)}Mbps`);
  if (metric.mos_estimate != null)    kpiBits.push(`MOS ${metric.mos_estimate.toFixed(2)}`);
  if (kpiBits.length) lines.push(`Live KPIs: ${kpiBits.join(", ")}.`);
  if (alert) {
    const mins = Math.max(1, Math.round((Date.now() - new Date(alert.occurred_at).getTime()) / 60_000));
    lines.push(`Top alert: ${alert.severity.toUpperCase()} · ${alert.display_label} · open for ${mins} min.`);
    if (alert.top_factors?.length) {
      lines.push(`Contributing signals: ${alert.top_factors.slice(0, 3).map((f) => f.display_label).join("; ")}.`);
    }
    if (alert.time_to_breach_seconds != null) {
      lines.push(`Forecasted breach in ~${Math.round(alert.time_to_breach_seconds / 60)} min.`);
    }
  } else {
    lines.push("No active alerts.");
  }
  if (actions[0]) {
    lines.push(`Top recommendation queued: ${actions[0].title} (${actions[0].risk_level} risk, ${actions[0].is_reversible ? "reversible" : "needs approval"}).`);
  }
  return lines.join("\n");
}

function buildDeterministicNote(
  alert: AlertEvent | null,
  actions: ProposedActionEvent[],
  metric: MetricEvent | null,
): string {
  if (!alert) return "Network metrics are within acceptable bounds. Monitoring continues across all cells.";
  const cell    = alert.cell_id ? `Cell ${alert.cell_id}` : "The network";
  const mins    = Math.max(1, Math.round((Date.now() - new Date(alert.occurred_at).getTime()) / 60_000));
  const action  = actions[0];
  let note = `${cell} has been ${alert.display_label.toLowerCase()} for ${mins} minute${mins === 1 ? "" : "s"}.`;
  if (action) {
    note += ` The system is recommending to ${action.title.toLowerCase()} — ${action.risk_level} risk, ${action.is_reversible ? "fully reversible" : "requires approval"}.`;
  } else {
    note += " Monitoring for escalation. Check the diagnostic page for root cause analysis.";
  }
  return note;
}

// ─── helpers ─────────────────────────────────────────────────────────────────

function buildSeries(metrics: MetricEvent[]) {
  const latency: number[] = [], jitter: number[] = [], loss: number[] = [], throughput: number[] = [];
  for (const m of metrics) {
    if (m.latency_ms != null)      latency.push(m.latency_ms);
    if (m.jitter_ms != null)       jitter.push(m.jitter_ms);
    if (m.packet_loss_pct != null) loss.push(m.packet_loss_pct);
    if (m.throughput_mbps != null) throughput.push(m.throughput_mbps);
  }
  return { latency, jitter, loss, throughput };
}
