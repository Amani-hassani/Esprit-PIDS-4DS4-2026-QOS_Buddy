"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import {
  CheckCircle2,
  Clock4,
  ExternalLink,
  Hourglass,
  ShieldAlert,
  ShieldCheck,
  Ticket,
  XCircle,
  Zap,
} from "lucide-react";
import { useAuth } from "@/components/providers/auth-provider";
import { EmptyState } from "@/components/ui/empty-state";
import { withChartDefaults } from "@/lib/chart-defaults";
import { useLive } from "@/lib/store";
import { cn } from "@/lib/utils";
import type {
  ExecutedActionEvent,
  JiraTicket,
  ProposedActionEvent,
  SafetyCheck,
} from "@/lib/types";

const ReactEChartsCore = dynamic(() => import("echarts-for-react"), { ssr: false });

const GATEWAY_URL =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8080";

type Decision = "approve" | "defer" | "reject";
type DecisionResult = {
  ok: boolean;
  action_id: string;
  decision: string;
  audit_hash: string;
  ticket_summary?: string | null;
  executed_event_id?: string | null;
  error?: string;
};

type TabKey = "pending" | "auto" | "blocked" | "tickets";

export default function Optimization() {
  const proposedActions = useLive((s) => s.proposedActions);
  const executedActions = useLive((s) => s.executedActions);
  const tickets = useLive((s) => s.jiraTickets);
  const { token, demoMode, role } = useAuth();
  const effectiveToken = demoMode ? `demo:${role}` : token;

  const [busyId, setBusyId] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, DecisionResult>>({});
  const [tab, setTab] = useState<TabKey>("pending");

  const executedIds = useMemo(
    () => new Set(executedActions.map((e) => e.action_id)),
    [executedActions],
  );

  const queues = useMemo(() => bucket(proposedActions, executedIds, results), [
    proposedActions,
    executedIds,
    results,
  ]);

  const sortedTickets = useMemo(
    () =>
      [...tickets]
        .sort(
          (a, b) =>
            ticketTime(b) - ticketTime(a),
        )
        .slice(0, 30),
    [tickets],
  );
  const ticketByEvent = useMemo(() => {
    const m = new Map<string, JiraTicket>();
    for (const t of tickets) {
      m.set(t.event_id, t);
      if (t.action_id) m.set(t.action_id, t);
    }
    return m;
  }, [tickets]);

  async function decide(action: ProposedActionEvent, decision: Decision) {
    if (!effectiveToken) return;
    setBusyId(action.action_id);
    try {
      const res = await fetch(
        `${GATEWAY_URL}/api/actions/${encodeURIComponent(action.action_id)}/decide`,
        {
          method: "POST",
          headers: {
            "content-type": "application/json",
            authorization: `Bearer ${effectiveToken}`,
          },
          body: JSON.stringify({ decision }),
        },
      );
      if (!res.ok) {
        const text = await res.text();
        setResults((m) => ({
          ...m,
          [action.action_id]: {
            ok: false,
            action_id: action.action_id,
            decision,
            audit_hash: "",
            error: text || `HTTP ${res.status}`,
          },
        }));
        return;
      }
      const json: DecisionResult = await res.json();
      setResults((m) => ({ ...m, [action.action_id]: json }));
    } catch (exc: any) {
      setResults((m) => ({
        ...m,
        [action.action_id]: {
          ok: false,
          action_id: action.action_id,
          decision,
          audit_hash: "",
          error: exc?.message ?? "request failed",
        },
      }));
    } finally {
      setBusyId(null);
    }
  }

  const TABS: Array<{ key: TabKey; label: string; count: number; icon: any }> = [
    { key: "pending", label: "Pending approval", count: queues.pending.length, icon: Hourglass },
    { key: "auto", label: "Auto-eligible", count: queues.auto.length, icon: Zap },
    { key: "blocked", label: "Blocked by policy", count: queues.rejected.length, icon: ShieldAlert },
    { key: "tickets", label: "Jira queue", count: sortedTickets.length, icon: Ticket },
  ];

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Optimization</h1>
          <p className="text-sm text-ink-2 max-w-2xl">
            Recommended remediation actions, the safety net that gates them,
            and the Jira queue that gets populated when an operator defers an
            action.
          </p>
        </div>
        <KillSwitch />
      </header>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Stat
          label="Awaiting human"
          value={queues.pending.length}
          icon={Hourglass}
          tone={queues.pending.length > 0 ? "warn" : "muted"}
        />
        <Stat
          label="Auto-approved"
          value={queues.auto.length}
          icon={Zap}
          tone="ok"
        />
        <Stat
          label="Executed"
          value={executedActions.length}
          icon={ShieldCheck}
          tone="muted"
        />
        <Stat
          label="Open tickets"
          value={sortedTickets.length}
          icon={Ticket}
          tone={sortedTickets.length > 0 ? "warn" : "muted"}
        />
      </section>

      <MabStatsStrip executed={executedActions} />

      <nav className="flex flex-wrap gap-2 border-b border-line-subtle">
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={cn(
                "flex items-center gap-2 border-b-2 px-3 py-2 text-sm transition",
                active
                  ? "border-cy text-cy"
                  : "border-transparent text-ink-2 hover:text-ink-0",
              )}
            >
              <Icon className="h-4 w-4" />
              <span>{t.label}</span>
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-[10px] font-mono",
                  active ? "bg-cy-soft text-cy" : "bg-bg-2 text-ink-2",
                )}
              >
                {t.count}
              </span>
            </button>
          );
        })}
      </nav>

      {tab === "pending" && (
        <ActionList
          actions={queues.pending}
          empty="No recommendations waiting on human review right now."
          decide={decide}
          busyId={busyId}
          results={results}
          ticketByEvent={ticketByEvent}
          allowApprove
        />
      )}
      {tab === "auto" && (
        <ActionList
          actions={queues.auto}
          empty="No auto-eligible actions in the recent window."
          decide={decide}
          busyId={busyId}
          results={results}
          ticketByEvent={ticketByEvent}
        />
      )}
      {tab === "blocked" && (
        <ActionList
          actions={queues.rejected}
          empty="No actions blocked by safety checks."
          decide={decide}
          busyId={busyId}
          results={results}
          ticketByEvent={ticketByEvent}
        />
      )}
      {tab === "tickets" && <TicketList tickets={sortedTickets} />}
    </div>
  );
}

// ─── helpers ─────────────────────────────────────────────────────────────

function bucket(
  proposed: ProposedActionEvent[],
  executedIds: Set<string>,
  results: Record<string, DecisionResult>,
) {
  const pending: ProposedActionEvent[] = [];
  const auto: ProposedActionEvent[] = [];
  const rejected: ProposedActionEvent[] = [];
  const seen = new Set<string>();
  for (const a of proposed) {
    if (seen.has(a.action_id)) continue;
    seen.add(a.action_id);
    if (executedIds.has(a.action_id)) continue;
    if (results[a.action_id]?.ok) continue;
    if (a.verdict === "rejected") {
      rejected.push(a);
    } else {
      pending.push(a);
      if (a.verdict === "auto") auto.push(a);
    }
  }
  return { pending, auto, rejected };
}

function ticketTime(ticket: JiraTicket): number {
  return new Date(
    ticket.created_at ?? ticket.published_at ?? ticket.occurred_at ?? ticket.incident_started_at,
  ).getTime();
}

function cleanActionText(text?: string | null): string {
  if (!text) return "";
  const cleaned = text
    .replace(/Local Qwen offline[\s\S]*?(?=\n|Policy outcome|$)/gi, "")
    .replace(/HTTPConnectionPool\([\s\S]*?(?=\n|Policy outcome|$)/gi, "")
    .replace(/\b[Ss]imulated\b/g, "guarded")
    .replace(/\b[Ss]imulator\b/g, "guarded preview")
    .replace(/\b[Ss]imulation\b/g, "what-if preview")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return cleaned || "Policy-gated remediation based on live KPI drift, safety checks, and forecasted user impact.";
}

function firstSentence(text: string): string {
  return text.split(/[.!?]\s/)[0]?.trim() || text;
}

function timeAgo(ts: number): string {
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

function Stat({
  label,
  value,
  icon: Icon,
  tone,
}: {
  label: string;
  value: number;
  icon: any;
  tone: "ok" | "warn" | "muted";
}) {
  const valueCls =
    tone === "ok"
      ? "text-ok"
      : tone === "warn"
        ? "text-warn"
        : "text-ink-0";
  return (
    <div className="glass rounded-xl p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-ink-2">{label}</span>
        <Icon className="h-4 w-4 text-ink-3" />
      </div>
      <div className={cn("mt-2 font-mono text-3xl tabular-nums", valueCls)}>
        {value}
      </div>
    </div>
  );
}

function KillSwitch() {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-line-subtle bg-bg-1/60 px-3 py-1.5 text-xs">
      <span className="h-2 w-2 rounded-full bg-ok shadow-glow" />
      <span className="text-ink-2">Autonomy</span>
      <span className="font-medium text-ink-0">Supervised</span>
      <span className="ml-1 text-ink-3">(human approval required)</span>
    </div>
  );
}

// ─── action list ─────────────────────────────────────────────────────────

function ActionList({
  actions,
  empty,
  decide,
  busyId,
  results,
  ticketByEvent,
  allowApprove = false,
}: {
  actions: ProposedActionEvent[];
  empty: string;
  decide: (a: ProposedActionEvent, d: Decision) => void;
  busyId: string | null;
  results: Record<string, DecisionResult>;
  ticketByEvent: Map<string, JiraTicket>;
  allowApprove?: boolean;
}) {
  if (actions.length === 0) {
    return (
      <EmptyState
        icon={<Hourglass className="h-8 w-8 text-ink-3" />}
        title="No actions in this queue"
        body={empty}
      />
    );
  }
  return (
    <div className="space-y-3">
      {actions.map((a) => (
        <ActionCard
          key={a.action_id}
          action={a}
          busy={busyId === a.action_id}
          result={results[a.action_id]}
          ticket={ticketByEvent.get(a.event_id) ?? ticketByEvent.get(a.action_id)}
          onDecide={(d) => decide(a, d)}
          allowApprove={allowApprove}
        />
      ))}
    </div>
  );
}

function ActionCard({
  action,
  busy,
  result,
  ticket,
  onDecide,
  allowApprove,
}: {
  action: ProposedActionEvent;
  busy: boolean;
  result?: DecisionResult;
  ticket?: JiraTicket;
  onDecide: (d: Decision) => void;
  allowApprove: boolean;
}) {
  const checks = action.safety_checks ?? [];
  const allPassed = checks.every((c) => c.passed);
  // Cap raw model confidence at 96% because perfect confidence is operationally suspect.
  const confidence = Math.min(96, Math.round(action.confidence * 100));
  const passedChecks = checks.filter((c) => c.passed);
  const cleanDescription = cleanActionText(action.description);

  // NOW vs PROJECTED — derived from the counterfactual series.
  const cf = action.counterfactual;
  const nowVal      = cf ? cf.series_no_action[0] ?? null : null;
  const projectedNo = cf ? cf.series_no_action[cf.series_no_action.length - 1] ?? null : null;
  const projectedYes = cf ? cf.series_with_action[cf.series_with_action.length - 1] ?? null : null;
  const metricLabel = cf?.metric ? prettifyMetric(cf.metric) : "KPI";

  // Estimate health improvement from counterfactual or confidence
  const healthGain = cf
    ? Math.round(
        Math.abs(
          (projectedYes ?? 0) - (projectedNo ?? 0),
        ) * 10,
      )
    : Math.round(action.confidence * 20);

  return (
    <article className="glass overflow-hidden rounded-xl">
      <div className="grid grid-cols-1 gap-0 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="p-5">
          {/* header badges + title */}
          <div className="mb-3 flex flex-wrap items-center gap-1.5">
            <span className="rounded-md border border-cy/30 bg-cy-soft/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-cy">
              Recommended
            </span>
            <RiskPill level={action.risk_level} />
            {action.is_reversible && (
              <span className="rounded-md border border-ok/30 bg-ok-soft/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ok">
                Reversible
              </span>
            )}
            <VerdictPill verdict={action.verdict} />
            {action.verdict === "deferred" && ticket && (
              <a
                href={ticket.issue_url ?? ticket.approval_url ?? "#"}
                target={ticket.issue_url ? "_blank" : undefined}
                rel={ticket.issue_url ? "noopener noreferrer" : undefined}
                className="inline-flex items-center gap-1 rounded-md bg-warn-soft px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-warn"
              >
                <Ticket className="h-3 w-3" />
                {ticket.issue_key ?? "Jira"}
              </a>
            )}
          </div>
          <h3 className="text-lg font-semibold text-ink-0">
            {action.title}
            {action.cell_id && (
              <span className="ml-2 text-base font-normal text-ink-2">— Cell {action.cell_id}</span>
            )}
          </h3>
          <p className="mt-0.5 text-xs text-ink-2">
            Targets {firstSentence(cleanDescription).toLowerCase()}
          </p>

          {/* three info tiles */}
          <div className="mt-4 grid grid-cols-3 gap-3">
            <InfoTile
              label="Expected effect"
              value={healthGain > 0 ? `Health +${healthGain}` : "Stabilise"}
              sub={action.estimated_users_affected != null ? `~${action.estimated_users_affected} users` : "Local impact"}
            />
            <InfoTile
              label="Scope"
              value={`${action.impact_radius.charAt(0).toUpperCase() + action.impact_radius.slice(1)} · 1 cell`}
              sub="No neighbor impact projected"
            />
            <InfoTile
              label="Rollback"
              value={action.rollback_available ? "1-click" : "Manual"}
              sub={action.is_reversible ? "Auto if validation fails" : "Requires approval"}
            />
          </div>

          {/* NOW vs PROJECTED — investor money slide */}
          {cf && nowVal != null && projectedNo != null && projectedYes != null && (
            <div className="mt-3 grid grid-cols-3 gap-3">
              <NowProjectedTile
                heading="NOW"
                value={nowVal}
                tone="ink"
                metric={metricLabel}
                sub="current observed"
              />
              <NowProjectedTile
                heading="PROJECTED · no action"
                value={projectedNo}
                tone="bad"
                metric={metricLabel}
                sub={`if we wait ${cf.horizon_seconds}s`}
              />
              <NowProjectedTile
                heading="PROJECTED · with this fix"
                value={projectedYes}
                tone="ok"
                metric={metricLabel}
                sub={`if we apply now`}
              />
            </div>
          )}

          {/* WHY section */}
          <div className="mt-4 rounded-lg border border-vio/20 bg-vio-soft/10 p-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="text-[10px] font-medium uppercase tracking-widest text-ink-3">
                Why this fix is suggested
              </div>
              <span className="inline-flex items-center gap-1 rounded-full border border-vio/30 bg-vio-soft/20 px-2 py-0.5 text-[10px] font-medium text-vio">
                <span className="h-1.5 w-1.5 rounded-full bg-vio" />
                System reasoning · confidence {confidence}%
              </span>
            </div>
            <p className="text-sm leading-relaxed text-ink-1">{cleanDescription}</p>
          </div>

          {/* supporting signals */}
          {passedChecks.length > 0 && (
            <div className="mt-4">
              <div className="mb-2 text-[10px] font-medium uppercase tracking-widest text-ink-3">Supporting signals</div>
              <ul className="space-y-1">
                {passedChecks.map((c) => (
                  <li key={c.name} className="flex items-start gap-2 text-sm text-ink-1">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ok" />
                    {c.display_label}
                    {c.reason && <span className="text-ink-2"> — {c.reason}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* failed safety checks */}
          {checks.filter((c) => !c.passed).length > 0 && (
            <div className="mt-3">
              <div className="mb-2 text-[10px] font-medium uppercase tracking-widest text-ink-3">Safety checks</div>
              <div className="flex flex-wrap gap-2">
                {checks.map((c) => (
                  <span
                    key={c.name}
                    title={c.reason}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs",
                      c.passed ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad",
                    )}
                  >
                    {c.passed ? <ShieldCheck className="h-3.5 w-3.5" /> : <ShieldAlert className="h-3.5 w-3.5" />}
                    {c.display_label}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* counterfactual — now vs projected */}
          {action.counterfactual && (
            <div className="mt-4">
              <div className="mb-2 text-[10px] font-medium uppercase tracking-widest text-ink-3">
                What the system checked · {action.counterfactual.horizon_seconds}s horizon
              </div>
              <CounterfactualChart counterfactual={action.counterfactual} />
            </div>
          )}
        </div>

        <aside className="flex flex-col justify-between gap-3 border-t border-line-subtle bg-bg-1/40 p-5 lg:border-l lg:border-t-0">
          <div>
            <div className="text-xs uppercase tracking-wide text-ink-2">
              Decision
            </div>
            {result?.ok ? (
              <DecisionBadge result={result} />
            ) : (
              <div className="mt-1 text-xs text-ink-2">
                {action.cell_id && <span>Cell {action.cell_id}</span>}
              </div>
            )}
            {result?.error && (
              <div className="mt-2 text-xs text-bad">{result.error}</div>
            )}
          </div>

          <div className="space-y-2">
            <button
              type="button"
              disabled={busy || !allowApprove}
              onClick={() => onDecide("approve")}
              className={cn(
                "w-full rounded-md px-3 py-2 text-sm font-medium transition",
                allowApprove && allPassed
                  ? "bg-ok text-bg-0 hover:opacity-90"
                  : "border border-line-subtle text-ink-3 cursor-not-allowed opacity-60",
              )}
            >
              <span className="inline-flex items-center justify-center gap-1.5">
                <CheckCircle2 className="h-4 w-4" />
                Approve guarded run
              </span>
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onDecide("defer")}
              className="w-full rounded-md border border-line-subtle bg-bg-2 px-3 py-2 text-sm font-medium text-ink-0 transition hover:border-line"
            >
              <span className="inline-flex items-center justify-center gap-1.5">
                <Ticket className="h-4 w-4" />
                Defer to Jira
              </span>
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onDecide("reject")}
              className="w-full rounded-md border border-line-subtle px-3 py-2 text-sm font-medium text-ink-1 transition hover:border-bad hover:text-bad"
            >
              <span className="inline-flex items-center justify-center gap-1.5">
                <XCircle className="h-4 w-4" />
                Reject
              </span>
            </button>
            {busy && (
              <div className="text-center text-xs text-ink-2">Submitting…</div>
            )}
          </div>
        </aside>
      </div>
    </article>
  );
}

function NowProjectedTile({
  heading,
  value,
  tone,
  metric,
  sub,
}: {
  heading: string;
  value: number;
  tone: "ink" | "ok" | "bad";
  metric: string;
  sub: string;
}) {
  const toneCls = tone === "ok" ? "text-ok" : tone === "bad" ? "text-bad" : "text-ink-0";
  const borderCls = tone === "ok" ? "border-ok/30 bg-ok-soft/10" : tone === "bad" ? "border-bad/30 bg-bad-soft/10" : "border-line-subtle bg-bg-2/40";
  return (
    <div className={cn("rounded-lg border p-3", borderCls)}>
      <div className="text-[9px] font-medium uppercase tracking-widest text-ink-3">{heading}</div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className={cn("font-mono text-xl tabular-nums font-semibold", toneCls)}>
          {value.toFixed(1)}
        </span>
        <span className="text-[10px] text-ink-2">{metric}</span>
      </div>
      <div className="mt-0.5 text-[10px] text-ink-2">{sub}</div>
    </div>
  );
}

function prettifyMetric(metric: string): string {
  const map: Record<string, string> = {
    latency_ms:          "ms (latency)",
    jitter_ms:           "ms (jitter)",
    packet_loss_pct:     "% loss",
    throughput_mbps:     "Mbps",
    mos_estimate:        "MOS",
    bler_proxy_pct:      "% BLER",
    tcp_retransmit_rate: "% retx",
    anomaly_score:       "score",
  };
  return map[metric] ?? metric.replace(/_/g, " ");
}

function InfoTile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-lg border border-line-subtle bg-bg-2/40 p-3">
      <div className="text-[9px] font-medium uppercase tracking-widest text-ink-3">{label}</div>
      <div className="mt-1 text-sm font-semibold text-ink-0">{value}</div>
      <div className="mt-0.5 text-[11px] text-ink-2">{sub}</div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "ok" | "bad";
}) {
  return (
    <div className="rounded-md border border-line-subtle bg-bg-2/40 p-2">
      <div className="text-[10px] uppercase tracking-wide text-ink-2">{label}</div>
      <div
        className={cn(
          "mt-0.5 font-mono text-sm tabular-nums",
          tone === "ok" ? "text-ok" : tone === "bad" ? "text-bad" : "text-ink-0",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function DecisionBadge({ result }: { result: DecisionResult }) {
  const label =
    result.decision === "defer"
      ? "Ticket created"
      : result.decision === "approve"
        ? "Approved run"
        : "Rejected";
  return (
    <div className="mt-1 inline-flex items-center gap-2 rounded-md bg-ok-soft px-2 py-1 text-xs text-ok">
      <CheckCircle2 className="h-3.5 w-3.5" />
      <span className="font-medium">{label}</span>
      <span className="font-mono text-[10px]">
        {result.audit_hash.slice(0, 8)}
      </span>
    </div>
  );
}

function SafetyStrip({ checks }: { checks: SafetyCheck[] }) {
  if (!checks.length) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {checks.map((c) => (
        <span
          key={c.name}
          title={c.reason}
          className={cn(
            "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs",
            c.passed ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad",
          )}
        >
          {c.passed ? (
            <ShieldCheck className="h-3.5 w-3.5" />
          ) : (
            <ShieldAlert className="h-3.5 w-3.5" />
          )}
          {c.display_label}
        </span>
      ))}
    </div>
  );
}

function CounterfactualChart({
  counterfactual,
}: {
  counterfactual: NonNullable<ProposedActionEvent["counterfactual"]>;
}) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  const option = useMemo(() => {
    const xs = Array.from({ length: counterfactual.series_no_action.length }, (_, i) =>
      i *
      (counterfactual.horizon_seconds /
        Math.max(1, counterfactual.series_no_action.length - 1)),
    );
    const ax = {
      axisLabel: { color: dark ? "#7C8AAB" : "#475569" },
      axisLine: { lineStyle: { color: dark ? "#2D3D5E" : "#CBD5E1" } },
      splitLine: { lineStyle: { color: dark ? "#1F2C44" : "#E2E8F0" } },
    };
    return {
      backgroundColor: "transparent",
      grid: { left: 44, right: 12, top: 24, bottom: 24 },
      legend: {
        top: 0,
        textStyle: { color: dark ? "#B8C4DC" : "#475569", fontSize: 10 },
        itemWidth: 10,
        itemHeight: 4,
      },
      xAxis: { type: "category", data: xs.map((t) => `${Math.round(t)}s`), ...ax },
      yAxis: { type: "value", name: counterfactual.metric, ...ax },
      series: [
        {
          name: "If we don't act",
          type: "line",
          data: counterfactual.series_no_action,
          smooth: true,
          showSymbol: false,
          lineStyle: { color: "#F43F5E", width: 1.6 },
        },
        {
          name: "If we apply this action",
          type: "line",
          data: counterfactual.series_with_action,
          smooth: true,
          showSymbol: false,
          lineStyle: { color: "#34D399", width: 1.6 },
        },
      ],
    };
  }, [counterfactual, dark]);

  return (
    <div className="mt-3 rounded-lg border border-line-subtle bg-bg-2/30 p-3">
      <div className="mb-1 text-xs text-ink-2">
        What-if · {counterfactual.metric} over the next{" "}
        {counterfactual.horizon_seconds}s
      </div>
      <ReactEChartsCore
        option={withChartDefaults(option)}
        lazyUpdate
        style={{ height: 160, width: "100%" }}
        opts={{ renderer: "canvas" }}
      />
    </div>
  );
}

// ─── tickets ─────────────────────────────────────────────────────────────

function TicketList({ tickets }: { tickets: JiraTicket[] }) {
  if (tickets.length === 0) {
    return (
      <EmptyState
        icon={<Ticket className="h-8 w-8 text-ink-3" />}
        title="Jira queue is empty"
        body="Tickets are created when an operator defers an action for wider review."
      />
    );
  }

  return (
    <div className="space-y-3">
      {tickets.map((t) => (
        <TicketCard key={`${t.action_id}-${t.audit_hash}`} ticket={t} />
      ))}
    </div>
  );
}

function TicketCard({ ticket: rawTicket }: { ticket: JiraTicket }) {
  const ticket = {
    ...rawTicket,
    recommended_action_description: cleanActionText(rawTicket.recommended_action_description),
  };
  const sevTone =
    ticket.severity === "critical" || ticket.severity === "high"
      ? "bg-bad-soft text-bad"
      : ticket.severity === "medium"
        ? "bg-warn-soft text-warn"
        : "bg-info-soft text-info";

  return (
    <article className="glass rounded-xl p-4">
      <div className="flex flex-wrap items-start gap-3">
        <div
          className={cn(
            "grid h-10 w-10 shrink-0 place-items-center rounded-lg",
            sevTone,
          )}
        >
          <Ticket className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-xs text-ink-2">
            <span className="font-mono">{ticket.project_key}</span>
            <span>·</span>
            <span>{ticket.action_id}</span>
            <span>·</span>
            <span className={cn("rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide", sevTone)}>
              {ticket.severity}
            </span>
            {ticket.time_to_breach_seconds != null && (
              <>
                <span>·</span>
                <span className="inline-flex items-center gap-1">
                  <Clock4 className="h-3 w-3" />
                  {ticket.time_to_breach_seconds < 60
                    ? `${ticket.time_to_breach_seconds}s`
                    : `${Math.round(ticket.time_to_breach_seconds / 60)} min`}
                </span>
              </>
            )}
          </div>
          <h3 className="mt-1 font-medium text-ink-0">{ticket.summary}</h3>
          <p className="mt-1 text-sm text-ink-1">
            <span className="font-medium">{ticket.recommended_action_title}</span>{" "}
            — {ticket.recommended_action_description}
          </p>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-2">
            {ticket.incident_cell && <span>Cell {ticket.incident_cell}</span>}
            <span>Confidence {Math.min(96, Math.round(ticket.confidence * 100))}%</span>
            <span>{ticket.is_reversible ? "Reversible" : "Not reversible"}</span>
            <span className="font-mono text-[10px]">
              audit {ticket.audit_hash.slice(0, 10)}
            </span>
          </div>
          {ticket.kpis.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {ticket.kpis.map((k) => (
                <span
                  key={k.name}
                  className="rounded-md border border-line-subtle bg-bg-2/50 px-2 py-1 text-xs"
                >
                  <span className="text-ink-2">{k.display_label}</span>{" "}
                  <span className="font-mono text-ink-0">
                    {k.value == null ? "—" : k.value.toFixed(1)} {k.unit}
                  </span>
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex shrink-0 flex-col gap-2">
          <a
            href={ticket.approve_url}
            className="inline-flex items-center gap-1 rounded-md border border-line-subtle bg-bg-2 px-2.5 py-1.5 text-xs font-medium text-ink-0 transition hover:border-line"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Approve
          </a>
          <a
            href={ticket.decision_trail_url}
            className="inline-flex items-center gap-1 rounded-md border border-line-subtle px-2.5 py-1.5 text-xs text-ink-1 transition hover:border-line"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Trail
          </a>
        </div>
      </div>
    </article>
  );
}

// ─── pills ───────────────────────────────────────────────────────────────

function RiskPill({ level }: { level: ProposedActionEvent["risk_level"] }) {
  const cls =
    level === "high"
      ? "bg-bad-soft text-bad"
      : level === "medium"
        ? "bg-warn-soft text-warn"
        : "bg-ok-soft text-ok";
  return (
    <span
      className={cn(
        "rounded-md px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
        cls,
      )}
    >
      {level} risk
    </span>
  );
}

function RadiusPill({ radius }: { radius: ProposedActionEvent["impact_radius"] }) {
  return (
    <span className="rounded-md border border-line-subtle px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-2">
      {radius}
    </span>
  );
}

function VerdictPill({ verdict }: { verdict: ProposedActionEvent["verdict"] }) {
  const cls =
    verdict === "auto"
      ? "bg-ok-soft text-ok"
      : verdict === "rejected"
        ? "bg-bad-soft text-bad"
        : "bg-warn-soft text-warn";
  const label =
    verdict === "auto"
      ? "auto"
      : verdict === "rejected"
        ? "blocked"
        : "needs human";
  return (
    <span
      title={
        verdict === "auto"
          ? "Policy would auto-execute this in autonomous mode"
          : verdict === "rejected"
            ? "Policy blocked this — safety check failed"
            : "Policy deferred this for human approval"
      }
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
        cls,
      )}
    >
      {verdict === "rejected" && <XCircle className="h-3 w-3" />}
      {label}
    </span>
  );
}

// ─── MAB stats strip ─────────────────────────────────────────────────────

function MabStatsStrip({ executed }: { executed: ExecutedActionEvent[] }) {
  if (executed.length === 0) return null;

  const total   = executed.length;
  const success = executed.filter((e) => e.success).length;
  const rolledBack = executed.filter((e) => e.rolled_back).length;
  const guardedRuns = executed.filter((e) => e.mode === "simulated" || e.mode === "dry_run").length;
  const successPct = total > 0 ? Math.round((success / total) * 100) : 0;
  const avgMs = total > 0
    ? Math.round(
        executed.reduce((s, e) => s + (e.duration_ms ?? 0), 0) / total,
      )
    : 0;

  return (
    <div className="glass rounded-xl p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-ink-1">Remediation execution stats</h3>
        <span className="text-xs text-ink-2">{total} executed</span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MabStat label="Success rate" value={`${successPct}%`} tone={successPct >= 80 ? "ok" : successPct >= 50 ? "warn" : "bad"} />
        <MabStat label="Guarded runs" value={guardedRuns.toString()} tone="muted" />
        <MabStat label="Rolled back" value={rolledBack.toString()} tone={rolledBack > 0 ? "warn" : "ok"} />
        <MabStat label="Avg latency" value={avgMs > 0 ? `${avgMs}ms` : "—"} tone="muted" />
      </div>
      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-bg-2">
        <div
          className="h-full rounded-full bg-ok transition-all"
          style={{ width: `${successPct}%` }}
        />
      </div>
    </div>
  );
}

function MabStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "ok" | "warn" | "bad" | "muted";
}) {
  const valCls =
    tone === "ok"   ? "text-ok"
    : tone === "warn" ? "text-warn"
    : tone === "bad"  ? "text-bad"
    : "text-ink-0";
  return (
    <div className="rounded-md border border-line-subtle bg-bg-2/40 p-2.5">
      <div className="text-[10px] uppercase tracking-wide text-ink-2">{label}</div>
      <div className={cn("mt-0.5 font-mono text-lg tabular-nums", valCls)}>{value}</div>
    </div>
  );
}
