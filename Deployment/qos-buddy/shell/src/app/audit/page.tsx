"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Brain,
  CheckCircle2,
  ChevronRight,
  Clock,
  Download,
  Eye,
  ExternalLink,
  Lightbulb,
  Link2,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import { RoleGate, useAuth } from "@/components/providers/auth-provider";
import { useLive } from "@/lib/store";
import { cn } from "@/lib/utils";
import type {
  AlertEvent,
  AuditEvent,
  DiagnosisEvent,
  ExecutedActionEvent,
  InsightEvent,
  ProposedActionEvent,
} from "@/lib/types";

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8080";

export default function AuditPage() {
  return (
    <RoleGate allow={["noc_executive", "ai_engineer", "site_admin"]}>
      <AuditPageContent />
    </RoleGate>
  );
}

function AuditPageContent() {
  const { token, demoMode, role } = useAuth();
  const effectiveToken = demoMode ? `demo:${role}` : token;

  const liveAudit   = useLive((s) => s.auditEvents);
  const alerts      = useLive((s) => s.alerts);
  const diagnoses   = useLive((s) => s.diagnoses);
  const insights    = useLive((s) => s.insights);
  const proposed    = useLive((s) => s.proposedActions);
  const executed    = useLive((s) => s.executedActions);

  const [snapshot,     setSnapshot]     = useState<AuditEvent[]>([]);
  const [filterActor,  setFilterActor]  = useState("all");
  const [filterAction, setFilterAction] = useState("all");
  const [selected,     setSelected]     = useState<AuditEvent | null>(null);

  useEffect(() => {
    if (!effectiveToken) return;
    let cancelled = false;
    fetch(`${GATEWAY_URL}/api/snapshot/qos.audit?count=200`, {
      headers: { authorization: `Bearer ${effectiveToken}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => { if (!cancelled && j?.items) setSnapshot(j.items as AuditEvent[]); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [effectiveToken]);

  const merged = useMemo(() => {
    const byId = new Map<string, AuditEvent>();
    for (const e of snapshot)  byId.set(e.event_id, e);
    for (const e of liveAudit) byId.set(e.event_id, e);
    return Array.from(byId.values()).sort(
      (a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime(),
    );
  }, [snapshot, liveAudit]);

  const actors  = useMemo(() => Array.from(new Set(merged.map((e) => e.actor))).sort(),  [merged]);
  const actions = useMemo(() => Array.from(new Set(merged.map((e) => e.action))).sort(), [merged]);

  const filtered = useMemo(() => merged.filter((e) => {
    if (filterActor  !== "all" && e.actor  !== filterActor)  return false;
    if (filterAction !== "all" && e.action !== filterAction) return false;
    return true;
  }), [merged, filterActor, filterAction]);

  const integrity = useMemo(() => {
    const ordered = [...merged].reverse();
    const breaks: string[] = [];
    let prev: string | null = null;
    for (const e of ordered) {
      if (prev != null && e.prev_hash != null && e.prev_hash !== prev) breaks.push(e.event_id);
      prev = e.hash;
    }
    return { checked: ordered.length, breaks, ok: breaks.length === 0 && ordered.length > 0 };
  }, [merged]);

  const onExport = () => {
    const blob = new Blob([JSON.stringify(filtered, null, 2)], { type: "application/json" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url;
    a.download = `qos-audit-${new Date().toISOString().slice(0, 19)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // resolve trace context for a selected entry
  const trace = useMemo<TraceContext | null>(() => {
    if (!selected) return null;
    return resolveTrace(selected, alerts, diagnoses, insights, proposed, executed);
  }, [selected, alerts, diagnoses, insights, proposed, executed]);

  return (
    <div className="flex h-full gap-4">
      {/* ── main column ── */}
      <div className={cn("min-w-0 flex-1 space-y-6 transition-all", selected ? "lg:max-w-[calc(100%-26rem)]" : "")}>
        <header className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Audit Log</h1>
            <p className="text-sm text-ink-2">
              Hash-chained, tamper-evident ledger. Click any row to consult the
              full decision trace.
            </p>
          </div>
          <button
            onClick={onExport}
            className="inline-flex shrink-0 items-center gap-2 rounded-md border border-line-subtle bg-bg-2 px-3 py-1.5 text-xs text-ink-1 transition hover:bg-bg-3 hover:text-ink-0"
          >
            <Download className="h-3.5 w-3.5" />
            Export
          </button>
        </header>

        <ChainIntegrity {...integrity} />

        <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <StatTile label="Total entries"  value={merged.length.toString()}                                  icon={Shield}     tone="info" />
          <StatTile label="Unique actors"  value={actors.length.toString()}                                  icon={ShieldCheck} tone="info" />
          <StatTile label="Failed actions" value={merged.filter((e) => !e.succeeded).length.toString()}      icon={ShieldAlert} tone={merged.some((e) => !e.succeeded) ? "warn" : "ok"} />
        </section>

        <section className="flex flex-wrap items-end gap-3">
          <FilterSelect label="Actor"  value={filterActor}  onChange={setFilterActor}  options={[{ value: "all", label: "All actors" },  ...actors.map((a) => ({ value: a, label: a }))]} />
          <FilterSelect label="Action" value={filterAction} onChange={setFilterAction} options={[{ value: "all", label: "All actions" }, ...actions.map((a) => ({ value: a, label: a }))]} />
          <span className="ml-auto text-xs text-ink-2">{filtered.length} of {merged.length} entries</span>
        </section>

        <section>
          {filtered.length === 0 ? (
            <div className="rounded-lg border border-dashed border-line-subtle p-8 text-center text-sm text-ink-2">
              No audit entries match the current filter.
            </div>
          ) : (
            <div className="glass overflow-hidden rounded-xl">
              <div className="max-h-[620px] overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 z-10 bg-bg-1/95 backdrop-blur">
                    <tr className="text-left text-[11px] uppercase tracking-wide text-ink-2">
                      <th className="px-4 py-2 font-medium">When</th>
                      <th className="px-4 py-2 font-medium">Actor</th>
                      <th className="px-4 py-2 font-medium">Action</th>
                      <th className="px-4 py-2 font-medium">Target</th>
                      <th className="px-4 py-2 font-medium">Auth</th>
                      <th className="px-4 py-2 font-medium">Result</th>
                      <th className="px-4 py-2 font-medium">Hash</th>
                      <th className="px-4 py-2" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line-subtle">
                    {filtered.map((e) => (
                      <AuditRow
                        key={e.event_id}
                        entry={e}
                        selected={selected?.event_id === e.event_id}
                        onClick={() => setSelected((prev) => prev?.event_id === e.event_id ? null : e)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      </div>

      {/* ── consult panel ── */}
      {selected && (
        <ConsultPanel
          entry={selected}
          trace={trace}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

// ─── Consult panel ────────────────────────────────────────────────────────

interface TraceContext {
  correlationId: string | null;
  alert: AlertEvent | null;
  diagnosis: DiagnosisEvent | null;
  insight: InsightEvent | null;
  action: ProposedActionEvent | null;
  execution: ExecutedActionEvent | null;
}

function resolveTrace(
  entry: AuditEvent,
  alerts: AlertEvent[],
  diagnoses: Record<string, DiagnosisEvent>,
  insights: Record<string, InsightEvent>,
  proposed: ProposedActionEvent[],
  executed: ExecutedActionEvent[],
): TraceContext {
  // target_id is typically the action_id for action-related audit entries
  const targetId = entry.target_id ?? null;

  const exec   = targetId ? executed.find((e) => e.action_id === targetId || e.event_id === targetId) ?? null : null;
  const action = targetId ? proposed.find((p) => p.action_id === targetId) ?? null : null;

  const correlationId =
    exec?.correlation_id ??
    action?.correlation_id ??
    entry.correlation_id ??
    null;

  const alert    = correlationId ? alerts.find((a) => a.correlation_id === correlationId) ?? null : null;
  const diagnosis = correlationId ? diagnoses[correlationId] ?? null : null;
  const insight   = correlationId ? insights[correlationId]  ?? null : null;

  return { correlationId, alert, diagnosis, insight, action, execution: exec };
}

function ConsultPanel({
  entry,
  trace,
  onClose,
}: {
  entry: AuditEvent;
  trace: TraceContext | null;
  onClose: () => void;
}) {
  const [replayStep, setReplayStep] = useState<number | null>(null);
  const jaegerTraceId = trace?.execution?.trace_id ?? trace?.alert?.trace_id ?? entry.trace_id ?? null;

  const traceSteps = useMemo(() => {
    if (!trace) return [];
    const steps: Array<{ label: string; detail: string; ts: string; icon: any; color: string }> = [];
    if (trace.alert)
      steps.push({ label: "Alert raised", detail: `${trace.alert.display_label} · ${trace.alert.severity}`, ts: trace.alert.occurred_at, icon: Activity, color: "text-warn" });
    if (trace.diagnosis)
      steps.push({ label: "Pattern matched", detail: `${trace.diagnosis.pattern_label} · ${trace.diagnosis.similar_incidents.length} similar`, ts: trace.diagnosis.occurred_at, icon: Brain, color: "text-vio" });
    if (trace.insight)
      steps.push({ label: "Lesson generated", detail: `${Math.min(96, Math.round(trace.insight.confidence * 100))}% confidence · ${trace.insight.citations.length} citations`, ts: trace.insight.occurred_at, icon: Lightbulb, color: "text-cy" });
    if (trace.action)
      steps.push({ label: "Action proposed", detail: `${trace.action.title} · ${trace.action.verdict}`, ts: trace.action.occurred_at, icon: Sparkles, color: "text-info" });
    if (trace.execution)
      steps.push({ label: trace.execution.success ? "Executed ✓" : "Execution failed", detail: `${trace.execution.mode} · ${trace.execution.duration_ms ?? "?"}ms`, ts: trace.execution.occurred_at, icon: trace.execution.success ? CheckCircle2 : XCircle, color: trace.execution.success ? "text-ok" : "text-bad" });
    steps.push({ label: `Audit: ${entry.action}`, detail: `${entry.actor} · ${entry.auth_level}`, ts: entry.occurred_at, icon: Shield, color: "text-ink-2" });
    return steps;
  }, [trace, entry]);

  function startReplay() {
    setReplayStep(0);
    let i = 0;
    const tick = () => {
      i++;
      if (i < traceSteps.length) {
        setReplayStep(i);
        setTimeout(tick, 600);
      } else {
        setTimeout(() => setReplayStep(null), 1200);
      }
    };
    setTimeout(tick, 600);
  }

  return (
    <aside className="hidden lg:flex w-[24rem] shrink-0 flex-col glass rounded-xl overflow-hidden">
      {/* header */}
      <div className="flex items-center justify-between border-b border-line-subtle px-4 py-3">
        <div>
          <div className="text-xs uppercase tracking-wide text-ink-2">Consult</div>
          <div className="font-mono text-sm font-medium text-ink-0 truncate max-w-[18rem]">{entry.action}</div>
        </div>
        <button onClick={onClose} className="rounded p-1 text-ink-2 hover:bg-bg-2 hover:text-ink-0">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto space-y-5 p-4">
        {/* event detail */}
        <section>
          <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink-2">Event detail</div>
          <div className="rounded-lg border border-line-subtle bg-bg-2/40 divide-y divide-line-subtle text-xs">
            <DetailRow label="Actor"    value={<span className="font-medium text-ink-0">{entry.actor}</span>} />
            <DetailRow label="Role"     value={entry.actor_role} />
            <DetailRow label="Auth"     value={<AuthBadge level={entry.auth_level} />} />
            <DetailRow label="Target"   value={<span className="font-mono text-ink-2">{entry.target_id ?? "—"}</span>} />
            <DetailRow label="Result"   value={entry.succeeded
              ? <span className="flex items-center gap-1 text-ok"><CheckCircle2 className="h-3.5 w-3.5" /> Succeeded</span>
              : <span className="flex items-center gap-1 text-bad"><XCircle className="h-3.5 w-3.5" /> Failed</span>}
            />
            <DetailRow label="Time"     value={<span className="font-mono">{new Date(entry.occurred_at).toLocaleString()}</span>} />
            <DetailRow label="Hash"     value={<span className="font-mono text-[10px] text-ink-3 break-all">{entry.hash}</span>} />
            {entry.prev_hash && (
              <DetailRow label="Prev"   value={<span className="font-mono text-[10px] text-ink-3 break-all">{entry.prev_hash}</span>} />
            )}
          </div>
          {jaegerTraceId && (
            <a
              href={`http://localhost:16686/trace/${jaegerTraceId}`}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-3 inline-flex items-center gap-1 text-xs text-cy hover:underline"
            >
              <ExternalLink className="h-3 w-3" />
              View trace in Jaeger
            </a>
          )}
        </section>

        {/* trace replay */}
        {traceSteps.length > 1 && (
          <section>
            <div className="mb-2 flex items-center justify-between">
              <div className="text-[11px] font-medium uppercase tracking-wide text-ink-2">Decision trace</div>
              <button
                onClick={startReplay}
                disabled={replayStep !== null}
                className="inline-flex items-center gap-1.5 rounded-md border border-line-subtle bg-bg-2 px-2 py-1 text-[11px] text-ink-1 transition hover:bg-bg-3 hover:text-ink-0 disabled:opacity-50"
              >
                <Zap className="h-3 w-3" />
                Replay
              </button>
            </div>
            <ol className="relative border-l border-line-subtle pl-4 space-y-3">
              {traceSteps.map((step, i) => {
                const Icon = step.icon;
                const visible = replayStep === null || i <= replayStep;
                const active  = replayStep !== null && i === replayStep;
                return (
                  <li
                    key={i}
                    className={cn(
                      "relative transition-all duration-500",
                      visible ? "opacity-100" : "opacity-20",
                    )}
                  >
                    <span
                      className={cn(
                        "absolute -left-[1.2rem] top-0.5 flex h-4 w-4 items-center justify-center rounded-full border border-line-subtle bg-bg-1",
                        active && "ring-2 ring-cy ring-offset-1 ring-offset-bg-0",
                      )}
                    >
                      <Icon className={cn("h-2.5 w-2.5", visible ? step.color : "text-ink-3")} />
                    </span>
                    <div className="ml-1">
                      <div className="flex items-baseline gap-2">
                        <span className={cn("text-xs font-medium", visible ? "text-ink-0" : "text-ink-3")}>
                          {step.label}
                        </span>
                        <span className="font-mono text-[10px] text-ink-3">
                          {new Date(step.ts).toLocaleTimeString()}
                        </span>
                      </div>
                      <div className="text-[11px] text-ink-2">{step.detail}</div>
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>
        )}

        {/* alert context */}
        {trace?.alert && (
          <section>
            <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink-2">Incident context</div>
            <div className="rounded-lg border border-line-subtle bg-bg-2/40 p-3 space-y-2 text-xs">
              <div className="font-medium text-ink-0">{trace.alert.display_label}</div>
              <div className="flex flex-wrap gap-2 text-ink-2">
                <SevBadge sev={trace.alert.severity} />
                {trace.alert.cell_id && <span>Cell {trace.alert.cell_id}</span>}
                <span>{trace.alert.detector}</span>
                <span>{Math.min(96, Math.round(trace.alert.confidence * 100))}% confidence</span>
              </div>
              {trace.alert.top_factors && trace.alert.top_factors.length > 0 && (
                <div className="space-y-1 pt-1 border-t border-line-subtle">
                  {trace.alert.top_factors.slice(0, 3).map((f) => (
                    <div key={f.display_label} className="flex items-center justify-between gap-2">
                      <span className="text-ink-1 truncate">{f.display_label}</span>
                      <span className="font-mono text-ink-3 shrink-0">
                        {f.direction === "down" ? "↓" : "↑"} {Math.round(f.impact_pct)}%
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}

        {/* AI lesson */}
        {trace?.insight && (
          <section>
            <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink-2">AI lesson</div>
            <div className="rounded-lg border border-vio/30 bg-vio-soft/20 p-3 text-xs">
              <p className="text-ink-1 leading-relaxed line-clamp-6">{trace.insight.summary}</p>
              {trace.insight.citations.length > 0 && (
                <div className="mt-2 pt-2 border-t border-line-subtle text-ink-3">
                  {trace.insight.citations.length} citation{trace.insight.citations.length === 1 ? "" : "s"} · {Math.min(96, Math.round(trace.insight.confidence * 100))}% confidence
                </div>
              )}
            </div>
          </section>
        )}

        {/* no trace */}
        {!trace?.alert && !trace?.action && (
          <div className="rounded-lg border border-dashed border-line-subtle p-5 text-center text-xs text-ink-2">
            No pipeline context found for this entry. The action may not be linked to a live alert in the current session.
          </div>
        )}
      </div>
    </aside>
  );
}

// ─── sub-components ───────────────────────────────────────────────────────

function ChainIntegrity({ checked, breaks, ok }: { checked: number; breaks: string[]; ok: boolean }) {
  if (checked === 0) {
    return (
      <div className="rounded-xl border border-line-subtle bg-bg-2/40 p-4 text-sm text-ink-2">
        Waiting for audit entries to verify chain integrity…
      </div>
    );
  }
  return (
    <div className={cn("flex items-center gap-3 rounded-xl border p-4", ok ? "border-ok/30 bg-ok-soft/30 text-ok" : "border-bad/30 bg-bad-soft/30 text-bad")}>
      {ok ? <ShieldCheck className="h-5 w-5 shrink-0" /> : <ShieldAlert className="h-5 w-5 shrink-0" />}
      <div className="flex-1">
        <div className="text-sm font-medium">
          {ok ? `Chain intact across ${checked} entries` : `${breaks.length} integrity break${breaks.length === 1 ? "" : "s"} detected`}
        </div>
        <div className="text-xs opacity-80">
          {ok
            ? "Each entry's prev_hash matches the previous entry's hash — ledger is tamper-evident."
            : `Affected IDs: ${breaks.slice(0, 3).join(", ")}${breaks.length > 3 ? "…" : ""}`}
        </div>
      </div>
    </div>
  );
}

function StatTile({ label, value, icon: Icon, tone }: { label: string; value: string; icon: any; tone: "ok" | "warn" | "info" }) {
  const cls = tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : "text-info";
  return (
    <div className="glass rounded-xl p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-ink-2">{label}</span>
        <Icon className={cn("h-4 w-4", cls)} />
      </div>
      <div className={cn("mt-2 font-mono text-2xl tabular-nums", cls)}>{value}</div>
    </div>
  );
}

function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-ink-2">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-line-subtle bg-bg-2 px-2 py-1 text-sm text-ink-0 focus:outline-none focus:ring-1 focus:ring-cy"
      >
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

function AuditRow({ entry, selected, onClick }: { entry: AuditEvent; selected: boolean; onClick: () => void }) {
  const t = new Date(entry.occurred_at);
  return (
    <tr
      onClick={onClick}
      className={cn(
        "cursor-pointer text-sm transition",
        selected ? "bg-cy-soft/30" : "hover:bg-bg-2/40",
      )}
    >
      <td className="px-4 py-2 align-top">
        <div className="font-mono text-xs text-ink-0">{t.toLocaleTimeString()}</div>
        <div className="text-[11px] text-ink-3">{t.toLocaleDateString()}</div>
      </td>
      <td className="px-4 py-2 align-top">
        <div className="font-medium text-ink-0">{entry.actor}</div>
        <div className="text-[11px] text-ink-3">{entry.actor_role}</div>
      </td>
      <td className="px-4 py-2 align-top">
        <span className="rounded bg-bg-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-1">{entry.action}</span>
      </td>
      <td className="px-4 py-2 align-top font-mono text-[11px] text-ink-2">{entry.target_id ?? "—"}</td>
      <td className="px-4 py-2 align-top">
        <AuthBadge level={entry.auth_level} />
      </td>
      <td className="px-4 py-2 align-top">
        {entry.succeeded
          ? <CheckCircle2 className="h-4 w-4 text-ok" />
          : <XCircle      className="h-4 w-4 text-bad" />}
      </td>
      <td className="px-4 py-2 align-top">
        <div className="flex items-center gap-1 font-mono text-[11px] text-ink-2" title={entry.hash}>
          <Link2 className="h-3 w-3 text-ink-3" />
          {entry.hash.slice(0, 10)}…
        </div>
        {entry.prev_hash && (
          <div className="font-mono text-[10px] text-ink-3" title={`prev: ${entry.prev_hash}`}>
            ↑ {entry.prev_hash.slice(0, 8)}
          </div>
        )}
      </td>
      <td className="px-4 py-2 align-top">
        <ChevronRight className={cn("h-4 w-4 transition", selected ? "text-cy rotate-90" : "text-ink-3")} />
      </td>
    </tr>
  );
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 px-3 py-1.5">
      <span className="text-ink-3 shrink-0">{label}</span>
      <span className="text-right text-ink-1">{value}</span>
    </div>
  );
}

function AuthBadge({ level }: { level: AuditEvent["auth_level"] }) {
  return (
    <span className={cn(
      "rounded px-1.5 py-0.5 text-[11px]",
      level === "webauthn" ? "bg-ok-soft text-ok"
        : level === "session" ? "bg-info-soft text-info"
        : "bg-bg-2 text-ink-2",
    )}>
      {level}
    </span>
  );
}

function SevBadge({ sev }: { sev: AlertEvent["severity"] }) {
  const cls = sev === "critical" || sev === "high" ? "bg-bad-soft text-bad"
    : sev === "medium" ? "bg-warn-soft text-warn"
    : "bg-info-soft text-info";
  return <span className={cn("rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide", cls)}>{sev}</span>;
}
