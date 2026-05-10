"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Clock,
  Download,
  FileText,
  Pause,
  Play,
  Printer,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Volume2,
  XCircle,
} from "lucide-react";
import { useAuth } from "@/components/providers/auth-provider";
import { withChartDefaults } from "@/lib/chart-defaults";
import { useLive } from "@/lib/store";
import { cn } from "@/lib/utils";
import { askAi } from "@/lib/ai";
import type {
  AlertEvent,
  DiagnosisEvent,
  ExecutedActionEvent,
  InsightEvent,
  JiraTicket,
  MetricEvent,
  ProposedActionEvent,
} from "@/lib/types";

const ReactEChartsCore = dynamic(() => import("echarts-for-react"), { ssr: false });

const GATEWAY_URL   = process.env.NEXT_PUBLIC_GATEWAY_URL   ?? "http://localhost:8080";
const REPORTING_URL = process.env.NEXT_PUBLIC_REPORTING_URL ?? "http://localhost:8089";

type Tab = "brief" | "postmortem" | "trends";

export default function ReportingPage() {
  const { token, username, demoMode, role } = useAuth();
  const effectiveToken = demoMode ? `demo:${role}` : token;

  const liveAlerts   = useLive((s) => s.alerts);
  const liveMetrics  = useLive((s) => s.metrics);
  const liveExecuted = useLive((s) => s.executedActions);
  const liveProposed = useLive((s) => s.proposedActions);
  const liveTickets  = useLive((s) => s.jiraTickets);
  const diagnoses    = useLive((s) => s.diagnoses);
  const insights     = useLive((s) => s.insights);

  const [snapshotAlerts, setSnapshotAlerts] = useState<AlertEvent[]>([]);
  const [snapshotExec,   setSnapshotExec]   = useState<ExecutedActionEvent[]>([]);
  const [snapshotMetrics, setSnapshotMetrics] = useState<MetricEvent[]>([]);
  const [snapshotDiagnoses, setSnapshotDiagnoses] = useState<DiagnosisEvent[]>([]);
  const [snapshotInsights, setSnapshotInsights] = useState<InsightEvent[]>([]);
  const [snapshotProposed, setSnapshotProposed] = useState<ProposedActionEvent[]>([]);
  const [snapshotTickets, setSnapshotTickets] = useState<JiraTicket[]>([]);
  const [speaking, setSpeaking] = useState(false);
  const [tab, setTab] = useState<Tab>("brief");

  useEffect(() => {
    if (!effectiveToken) return;
    let cancelled = false;
    const load = async <T,>(stream: string, set: (v: T[]) => void) => {
      try {
        const r = await fetch(`${GATEWAY_URL}/api/snapshot/${stream}?count=200`, {
          headers: { authorization: `Bearer ${effectiveToken}` },
        });
        if (!r.ok) return;
        const j = (await r.json()) as { items?: T[] };
        if (!cancelled && j.items) set(j.items);
      } catch { /* ignore */ }
    };
    void load<AlertEvent>("qos.alerts", setSnapshotAlerts);
    void load<ExecutedActionEvent>("qos.action.executed", setSnapshotExec);
    void load<MetricEvent>("qos.metrics.raw", setSnapshotMetrics);
    void load<DiagnosisEvent>("qos.diagnosis", setSnapshotDiagnoses);
    void load<InsightEvent>("qos.insight", setSnapshotInsights);
    void load<ProposedActionEvent>("qos.action.proposed", setSnapshotProposed);
    void load<JiraTicket>("qos.jira", setSnapshotTickets);
    return () => { cancelled = true; };
  }, [effectiveToken]);

  const alerts = useMemo(() => {
    const byId = new Map<string, AlertEvent>();
    for (const a of snapshotAlerts) byId.set(a.event_id, a);
    for (const a of liveAlerts)     byId.set(a.event_id, a);
    return Array.from(byId.values()).sort(
      (a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime(),
    );
  }, [snapshotAlerts, liveAlerts]);

  const executed = useMemo(() => {
    const byId = new Map<string, ExecutedActionEvent>();
    for (const e of snapshotExec)   byId.set(e.event_id, e);
    for (const e of liveExecuted)   byId.set(e.event_id, e);
    return Array.from(byId.values()).sort(
      (a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime(),
    );
  }, [snapshotExec, liveExecuted]);

  const metrics = useMemo(() => {
    const byId = new Map<string, MetricEvent>();
    for (const m of snapshotMetrics) byId.set(m.event_id, m);
    for (const m of liveMetrics) byId.set(m.event_id, m);
    return Array.from(byId.values()).sort(
      (a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime(),
    );
  }, [snapshotMetrics, liveMetrics]);

  const diagnosesByCorrelation = useMemo(() => {
    const byId: Record<string, DiagnosisEvent> = {};
    for (const d of snapshotDiagnoses) byId[d.correlation_id] = d;
    for (const d of Object.values(diagnoses)) byId[d.correlation_id] = d;
    return byId;
  }, [snapshotDiagnoses, diagnoses]);

  const insightsByCorrelation = useMemo(() => {
    const byId: Record<string, InsightEvent> = {};
    for (const i of snapshotInsights) byId[i.correlation_id] = i;
    for (const i of Object.values(insights)) byId[i.correlation_id] = i;
    return byId;
  }, [snapshotInsights, insights]);

  const proposed = useMemo(() => {
    const byId = new Map<string, ProposedActionEvent>();
    for (const p of snapshotProposed) byId.set(p.action_id, p);
    for (const p of liveProposed) byId.set(p.action_id, p);
    return Array.from(byId.values()).sort(
      (a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime(),
    );
  }, [snapshotProposed, liveProposed]);

  const tickets = useMemo(() => {
    const byId = new Map<string, JiraTicket>();
    for (const t of snapshotTickets) byId.set(t.issue_key ?? `${t.event_id}-${t.audit_hash}`, t);
    for (const t of liveTickets) byId.set(t.issue_key ?? `${t.event_id}-${t.audit_hash}`, t);
    return Array.from(byId.values()).sort((a, b) => {
      const at = a.created_at ?? a.published_at ?? a.occurred_at ?? a.incident_started_at;
      const bt = b.created_at ?? b.published_at ?? b.occurred_at ?? b.incident_started_at;
      return new Date(bt ?? 0).getTime() - new Date(at ?? 0).getTime();
    });
  }, [snapshotTickets, liveTickets]);

  const stats = useMemo(
    () => buildStats(alerts, executed, metrics, diagnosesByCorrelation, proposed, tickets),
    [alerts, executed, metrics, diagnosesByCorrelation, proposed, tickets],
  );

  const briefText = useMemo(
    () => buildBriefText(stats, alerts, insightsByCorrelation),
    [stats, alerts, insightsByCorrelation],
  );

  const onPrint = () => {
    // Always render the executive brief before invoking print, otherwise the
    // postmortem/trends tabs would print as blank.
    setTab("brief");
    // Wait one paint so the brief is actually in the DOM, then print.
    requestAnimationFrame(() => requestAnimationFrame(() => window.print()));
  };

  const onSpeak = () => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
      return;
    }
    const utter = new SpeechSynthesisUtterance(briefText);
    utter.rate = 1.0;
    utter.onend   = () => setSpeaking(false);
    utter.onerror = () => setSpeaking(false);
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utter);
    setSpeaking(true);
  };

  const onExportJSON = () => {
    const blob = new Blob(
      [JSON.stringify({
        generated_at: new Date().toISOString(),
        generated_by: username ?? "unknown",
        stats,
        alerts: alerts.slice(0, 50),
        diagnoses: Object.values(diagnosesByCorrelation).slice(0, 50),
        insights: Object.values(insightsByCorrelation).slice(0, 50),
        proposed_actions: proposed.slice(0, 50),
        executed_actions: executed.slice(0, 50),
        jira_tickets: tickets.slice(0, 50),
        metrics: metrics.slice(-100),
      }, null, 2)],
      { type: "application/json" },
    );
    downloadBlob(blob, `qosmic-brief-${isoSlug()}.json`);
  };

  const onExportCSV = () => {
    const header = "event_id,occurred_at,severity,cell_id,detector,confidence,display_label\n";
    const rows = alerts.slice(0, 200).map((a) =>
      [a.event_id, a.occurred_at, a.severity, a.cell_id ?? "", a.detector, a.confidence.toFixed(3), `"${a.display_label.replace(/"/g, '""')}"`].join(","),
    ).join("\n");
    const blob = new Blob([header + rows], { type: "text/csv" });
    downloadBlob(blob, `qosmic-alerts-${isoSlug()}.csv`);
  };

  const TABS: Array<{ key: Tab; label: string }> = [
    { key: "brief",     label: "Executive brief" },
    { key: "postmortem", label: "Post-mortem" },
    { key: "trends",    label: "KPI trends" },
  ];

  return (
    <div className="space-y-6">
      {/* ── toolbar ── */}
      <header className="flex flex-wrap items-start justify-between gap-3 print:hidden">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Executive Reports</h1>
          <p className="text-sm text-ink-2">
            Live collector readout with real agent decisions, polished for shift handoff and leadership review.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={onSpeak}
            className={cn(
              "inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs transition",
              speaking
                ? "border-cy bg-cy-soft text-cy"
                : "border-line-subtle bg-bg-2 text-ink-1 hover:bg-bg-3 hover:text-ink-0",
            )}
          >
            {speaking ? <Pause className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5" />}
            {speaking ? "Stop reading" : "Read brief"}
          </button>
          <button onClick={onExportCSV} className="inline-flex items-center gap-2 rounded-md border border-line-subtle bg-bg-2 px-3 py-1.5 text-xs text-ink-1 transition hover:bg-bg-3 hover:text-ink-0">
            <Download className="h-3.5 w-3.5" />
            CSV
          </button>
          <button onClick={onExportJSON} className="inline-flex items-center gap-2 rounded-md border border-line-subtle bg-bg-2 px-3 py-1.5 text-xs text-ink-1 transition hover:bg-bg-3 hover:text-ink-0">
            <Download className="h-3.5 w-3.5" />
            JSON
          </button>
          <button onClick={onPrint} className="inline-flex items-center gap-2 rounded-md bg-cy px-3 py-1.5 text-xs font-medium text-bg-0 transition hover:opacity-90">
            <Printer className="h-3.5 w-3.5" />
            Export PDF
          </button>
        </div>
      </header>

      {/* ── tabs ── */}
      <nav className="flex gap-2 border-b border-line-subtle print:hidden">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={cn(
              "border-b-2 px-3 py-2 text-sm font-medium transition",
              tab === t.key
                ? "border-cy text-cy"
                : "border-transparent text-ink-2 hover:text-ink-0",
            )}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* ── brief ── */}
      {(tab === "brief" || typeof window === "undefined") && (
        <article className="brief glass space-y-6 rounded-2xl p-6 print:rounded-none print:border-0 print:p-0 print:shadow-none">
          <BriefHeader username={username ?? "NOC Operator"} stats={stats} />
          <BriefStats stats={stats} />
          <SectionWrap title="Executive summary" icon={FileText}>
            <ExecutiveSummary stats={stats} alerts={alerts} insights={insightsByCorrelation} />
          </SectionWrap>
          <SectionWrap title="Business and service impact" icon={TrendingDown}>
            <BusinessImpact stats={stats} />
          </SectionWrap>
          <SectionWrap title="Detection and response performance" icon={Clock}>
            <TimingStats stats={stats} />
          </SectionWrap>
          <SectionWrap title="Top incidents" icon={AlertTriangle}>
            <TopIncidents alerts={alerts} insights={insightsByCorrelation} />
          </SectionWrap>
          <SectionWrap title="What QoS Buddy already did" icon={CheckCircle2}>
            <ActionsTaken executed={executed.slice(0, 6)} proposed={proposed.slice(0, 6)} tickets={tickets.slice(0, 6)} />
          </SectionWrap>
          <SectionWrap title="Recommendations for leadership" icon={Sparkles}>
            <LeadershipRecommendations stats={stats} proposed={proposed} alerts={alerts} />
          </SectionWrap>
          <SectionWrap title="Plain-language interpretation" icon={FileText}>
            <pre className="whitespace-pre-wrap rounded-lg border border-line-subtle bg-bg-2/40 p-4 text-sm leading-relaxed text-ink-1">
              {briefText}
            </pre>
          </SectionWrap>
        </article>
      )}

      {/* ── post-mortem ── */}
      {tab === "postmortem" && (
        <PostMortemView
          alerts={alerts}
          diagnoses={diagnosesByCorrelation}
          insights={insightsByCorrelation}
          executed={executed}
        />
      )}

      {/* ── trends ── */}
      {tab === "trends" && (
        <TrendsView metrics={metrics} alerts={alerts} />
      )}

      <style jsx global>{`
        @media print {
          @page { margin: 14mm; size: A4; }
          html, body { background: white !important; color: black !important; }
          /* hide app chrome */
          aside, nav, header.shell-header, .print\\:hidden { display: none !important; }
          main { padding: 0 !important; max-width: none !important; }
          /* keep only the brief readable on paper */
          .brief { background: white !important; color: black !important; box-shadow: none !important; }
          .brief, .brief * {
            color: black !important;
            border-color: #cbd5e1 !important;
            background: transparent !important;
          }
          .brief pre { white-space: pre-wrap !important; word-break: break-word !important; }
          /* avoid splitting incident cards across pages */
          .brief section, .brief article { break-inside: avoid; page-break-inside: avoid; }
        }
      `}</style>
    </div>
  );
}

// ─── Post-mortem view ──────────────────────────────────────────────────────

function PostMortemView({
  alerts,
  diagnoses,
  insights,
  executed,
}: {
  alerts: AlertEvent[];
  diagnoses: Record<string, DiagnosisEvent>;
  insights: Record<string, InsightEvent>;
  executed: ExecutedActionEvent[];
}) {
  const incidents = useMemo(() => {
    const nonForecast = alerts.filter((a) => a.detector !== "forecast");
    // Deduplicate by correlation_id
    const seen = new Set<string>();
    const uniq: AlertEvent[] = [];
    for (const a of nonForecast) {
      if (!seen.has(a.correlation_id)) { seen.add(a.correlation_id); uniq.push(a); }
    }
    return uniq.slice(0, 5);
  }, [alerts]);

  if (incidents.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-line-subtle p-10 text-center text-sm text-ink-2">
        No incidents to post-mortem. The system has been healthy in this window.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {incidents.map((alert, idx) => {
        const diag    = diagnoses[alert.correlation_id];
        const insight = insights[alert.correlation_id];
        const action  = executed.find((e) => e.correlation_id === alert.correlation_id);
        return (
          <PostMortemCard
            key={alert.event_id}
            index={idx + 1}
            alert={alert}
            diagnosis={diag}
            insight={insight}
            action={action}
          />
        );
      })}
    </div>
  );
}

interface ReportingLesson {
  lesson:           string;
  root_cause_class: string;
  confidence:       number;
  recommendations:  string[];
  save_to_memory:   boolean;
}

const postmortemLessonCache = new Map<string, ReportingLesson>();

function PostMortemCard({
  index,
  alert,
  diagnosis,
  insight,
  action,
}: {
  index: number;
  alert: AlertEvent;
  diagnosis?: DiagnosisEvent;
  insight?: InsightEvent;
  action?: ExecutedActionEvent;
}) {
  const sevTone = sevToneClasses(alert.severity);

  const [llmLesson, setLlmLesson] = useState<ReportingLesson | null>(null);
  const [llmLoading, setLlmLoading] = useState(false);
  const [closed, setClosed] = useState(false);
  const [closing, setClosing] = useState(false);

  useEffect(() => {
    if (insight) return; // already have synthesis insight
    let cancelled = false;
    const cacheKey = alert.event_id;
    const cached = postmortemLessonCache.get(cacheKey);
    if (cached) {
      setLlmLesson(cached);
      setLlmLoading(false);
      return;
    }

    const immediateLesson = buildImmediatePostmortemLesson(alert, diagnosis);
    setLlmLesson(immediateLesson);

    // Generate one richer AI lesson at a time. The remaining cards keep the
    // deterministic lesson until the operator opens them in a later render.
    if (index > 1) {
      setLlmLoading(false);
      return;
    }

    setLlmLoading(true);

    const features = (alert.monitoring_features as Record<string, number> | undefined) ?? {};

    // 1) Try the reporting service on 8089 (richer structured lesson).
    // 2) If it errors or stays silent past 12s, fall back to askAi() via RAG (8088).
    const reportingPromise = fetch(`${REPORTING_URL}/api/postmortem`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        severity:          alert.severity,
        event_id:          alert.event_id,
        display_label:     alert.display_label,
        detector:          alert.detector,
        cell_id:           alert.cell_id,
        features,
        top_factors:       alert.top_factors ?? [],
        root_cause:        diagnosis?.pattern_label ?? null,
        diagnosis_summary: diagnosis?.pattern_label ?? null,
      }),
      signal: AbortSignal.timeout(5_000),
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data: ReportingLesson) => data);

    reportingPromise
      .then((data) => {
        if (!cancelled) {
          postmortemLessonCache.set(cacheKey, data);
          setLlmLesson(data);
          setLlmLoading(false);
        }
      })
      .catch(async () => {
        // RAG fallback — guarantees the operator never sees "Generating…" forever.
        const factors = alert.top_factors?.slice(0, 3)
          .map((f) => `${f.display_label} ${f.direction === "up" ? "↑" : "↓"}${Math.round(f.impact_pct)}%`)
          .join(", ") ?? "n/a";
        const prompt = [
          "You are writing a brief post-mortem lesson for a NOC operator.",
          "Output 2 short sentences (no bullets, no markdown). End with one actionable lesson.",
          "",
          `Incident: ${alert.display_label}`,
          `Cell: ${alert.cell_id ?? "fleet"} · Severity: ${alert.severity}`,
          `Pattern: ${diagnosis?.pattern_label ?? "under investigation"}`,
          `Top contributors: ${factors}`,
        ].join("\n");
        const answer = await askAi(
          prompt,
          { current_page: "/reporting", cell_id: alert.cell_id ?? undefined, alert_id: alert.event_id },
          "Reporting service offline and RAG unreachable — operator should record lesson manually.",
        );
        if (cancelled) return;
        const fallbackLesson = {
          lesson:           answer,
          root_cause_class: diagnosis?.pattern_label?.replace(/\s+/g, "_").toLowerCase() ?? "unclassified",
          confidence:       Math.min(96, Math.round(alert.confidence * 100)),
          recommendations:  buildRecommendations(alert, diagnosis),
          save_to_memory:   false,
        };
        postmortemLessonCache.set(cacheKey, fallbackLesson);
        setLlmLesson(fallbackLesson);
        setLlmLoading(false);
      });

    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alert.event_id]);

  async function closeIncident() {
    if (!llmLesson) return;
    setClosing(true);
    try {
      const r = await fetch(`${REPORTING_URL}/api/postmortem/close`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ event_id: alert.event_id, lesson: llmLesson.lesson }),
      });
      if (r.ok) setClosed(true);
    } finally {
      setClosing(false);
    }
  }

  const timeline: Array<{ ts: string; label: string; detail: string; ok: boolean }> = [
    {
      ts: alert.occurred_at,
      label: "Alert raised",
      detail: `${alert.detector} · ${Math.min(96, Math.round(alert.confidence * 100))}% confidence`,
      ok: true,
    },
    ...(diagnosis
      ? [{
          ts: diagnosis.occurred_at,
          label: "Pattern matched",
          detail: `${diagnosis.pattern_label} · ${diagnosis.similar_incidents.length} similar`,
          ok: true,
        }]
      : [{ ts: "", label: "Pattern match", detail: "Not yet resolved", ok: false }]
    ),
    ...(insight
      ? [{
          ts: insight.occurred_at,
          label: "Lesson generated",
          detail: `${Math.min(96, Math.round(insight.confidence * 100))}% confidence · ${insight.citations.length} citation${insight.citations.length === 1 ? "" : "s"}`,
          ok: true,
        }]
      : [{ ts: "", label: "Lesson generation", detail: "Pending", ok: false }]
    ),
    ...(action
      ? [{
          ts: action.occurred_at,
          label: action.success ? "Remediation applied" : "Remediation failed",
          detail: `${action.mode} · ${action.duration_ms != null ? `${action.duration_ms}ms` : "—"}`,
          ok: action.success,
        }]
      : [{ ts: "", label: "Remediation", detail: "No action dispatched", ok: false }]
    ),
  ];

  return (
    <article className="glass overflow-hidden rounded-2xl">
      {/* header */}
      <div className="relative overflow-hidden px-6 py-5">
        <div
          className="pointer-events-none absolute inset-0 opacity-20"
          style={{ background: "radial-gradient(600px 200px at 90% 0%, rgba(168,123,255,0.3), transparent)" }}
        />
        <div className="relative flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-xs text-ink-2">
              <span className="font-mono">PM-{String(index).padStart(3, "0")}</span>
              <span>·</span>
              <span className={cn("rounded px-1.5 py-0.5 uppercase tracking-wide text-[10px]", sevTone)}>
                {alert.severity}
              </span>
              {alert.cell_id && <span>Cell {alert.cell_id}</span>}
              <span>{new Date(alert.occurred_at).toLocaleString()}</span>
            </div>
            <h2 className="mt-1 text-xl font-semibold text-ink-0">{alert.display_label}</h2>
            {alert.technical_label && (
              <div className="mt-0.5 font-mono text-xs text-ink-3">{alert.technical_label}</div>
            )}
          </div>
          <StatusBadge alert={alert} hasAction={!!action} />
        </div>
      </div>

      <div className="grid grid-cols-1 divide-y divide-line-subtle lg:grid-cols-2 lg:divide-x lg:divide-y-0">
        {/* left: timeline + root cause */}
        <div className="space-y-5 p-6">
          <div>
            <h3 className="mb-3 text-xs font-medium uppercase tracking-wide text-ink-2">
              Incident timeline
            </h3>
            <ol className="relative border-l border-line-subtle pl-4 space-y-4">
              {timeline.map((step, i) => (
                <li key={i} className="relative">
                  <span
                    className={cn(
                      "absolute -left-[1.15rem] top-0.5 flex h-4 w-4 items-center justify-center rounded-full",
                      step.ts && step.ok  ? "bg-ok"   : "",
                      step.ts && !step.ok ? "bg-bad"  : "",
                      !step.ts            ? "bg-bg-3" : "",
                    )}
                  >
                    {step.ts && step.ok  && <CheckCircle2 className="h-3 w-3 text-bg-0" />}
                    {step.ts && !step.ok && <XCircle      className="h-3 w-3 text-bg-0" />}
                    {!step.ts            && <span className="h-2 w-2 rounded-full bg-ink-3" />}
                  </span>
                  <div className="ml-1">
                    <div className="flex items-baseline gap-2">
                      <span className="text-sm font-medium text-ink-0">{step.label}</span>
                      {step.ts && (
                        <span className="font-mono text-[11px] text-ink-3">
                          {new Date(step.ts).toLocaleTimeString()}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-ink-2">{step.detail}</div>
                  </div>
                </li>
              ))}
            </ol>
          </div>

          {diagnosis && (
            <div>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-2">
                Root cause
              </h3>
              <div className="rounded-lg border border-vio/30 bg-vio-soft/20 p-3">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-vio" />
                  <span className="font-medium text-ink-0">{diagnosis.pattern_label}</span>
                </div>
                <div className="mt-1 font-mono text-[11px] text-ink-3">{diagnosis.pattern_id}</div>
                {diagnosis.similar_incidents.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {diagnosis.similar_incidents.slice(0, 2).map((s) => (
                      <div key={s.incident_id} className="flex items-center gap-2 text-xs text-ink-2">
                        <ArrowRight className="h-3 w-3 shrink-0 text-ink-3" />
                        <span className="font-mono text-ink-3">{s.incident_id}</span>
                        <span>—</span>
                        <span className="truncate">{s.resolution}</span>
                        <span className="ml-auto shrink-0 font-mono text-[10px]">{Math.round(s.similarity_pct)}%</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {action && (
            <div>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-2">
                Resolution
              </h3>
              <div className={cn(
                "rounded-lg border p-3",
                action.success
                  ? "border-ok/30 bg-ok-soft/20"
                  : "border-bad/30 bg-bad-soft/20",
              )}>
                <div className="flex items-center gap-2">
                  {action.success
                    ? <CheckCircle2 className="h-4 w-4 text-ok" />
                    : <XCircle      className="h-4 w-4 text-bad" />
                  }
                  <span className={cn("text-sm font-medium", action.success ? "text-ok" : "text-bad")}>
                    {action.success ? "Applied successfully" : "Execution failed"}
                  </span>
                  {action.rolled_back && (
                    <span className="ml-2 rounded px-1.5 py-0.5 text-[10px] bg-warn-soft text-warn">
                      rolled back
                    </span>
                  )}
                </div>
                {action.diff_summary && (
                  <p className="mt-1 text-xs text-ink-1">{action.diff_summary}</p>
                )}
                <div className="mt-1 flex gap-3 text-[11px] text-ink-3">
                  <span>mode: {action.mode}</span>
                  {action.duration_ms != null && <span>{action.duration_ms}ms</span>}
                  <span className="font-mono">audit: {action.audit_hash.slice(0, 12)}…</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* right: AI lesson + contributing factors */}
        <div className="space-y-5 p-6">
          <div>
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-2">
              AI lesson
            </h3>
            {insight ? (
              <div className="rounded-lg border border-line-subtle bg-bg-2/40 p-4">
                <div className="mb-2 flex items-center gap-2">
                  <BookOpen className="h-3.5 w-3.5 text-vio" />
                  <span className="text-xs font-medium text-ink-1">
                    Synthesis · {Math.min(96, Math.round(insight.confidence * 100))}% confidence
                  </span>
                </div>
                <p className="text-sm leading-relaxed text-ink-1">{insight.summary}</p>
                {insight.citations.length > 0 && (
                  <div className="mt-3 space-y-2 border-t border-line-subtle pt-3">
                    {insight.citations.slice(0, 3).map((c) => (
                      <div key={c.doc_id} className="flex items-start gap-2 text-xs">
                        <span className="mt-0.5 rounded bg-info-soft px-1 py-0.5 font-mono text-[10px] text-info shrink-0">
                          {c.score.toFixed(2)}
                        </span>
                        <div>
                          <div className="font-medium text-ink-0">{c.title}</div>
                          <div className="text-ink-2 line-clamp-2">{c.snippet}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : llmLoading && !llmLesson ? (
              <div className="rounded-lg border border-line-subtle bg-bg-2/40 p-4 text-center text-sm text-ink-2 animate-pulse">
                Generating post-incident lesson…
              </div>
            ) : llmLesson ? (
              <div className="rounded-lg border border-line-subtle bg-bg-2/40 p-4">
                <div className="mb-2 flex items-center gap-2">
                  <BookOpen className="h-3.5 w-3.5 text-vio" />
                  <span className="text-xs font-medium text-ink-1">
                    Reporting agent · {llmLesson.root_cause_class.replace(/_/g, " ")} · {llmLesson.confidence}% confidence
                  </span>
                </div>
                {llmLesson.save_to_memory && (
                  <div className="mb-2 inline-flex rounded bg-ok-soft px-1.5 py-0.5 text-[10px] font-medium text-ok">
                    Saved to operator memory
                  </div>
                )}
                <p className="text-sm leading-relaxed text-ink-1">{llmLesson.lesson}</p>
                <div className="mt-3 border-t border-line-subtle pt-3">
                  {closed ? (
                    <span className="inline-flex items-center gap-1.5 rounded-md bg-ok-soft px-2 py-1 text-xs text-ok">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      Closed
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void closeIncident()}
                      disabled={closing}
                      className="inline-flex items-center gap-1.5 rounded-md bg-cy px-3 py-1.5 text-xs font-medium text-bg-0 transition hover:opacity-90 disabled:opacity-50"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      {closing ? "Closing..." : "Close incident"}
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-line-subtle p-4 text-center text-xs text-ink-3">
                Reporting service unavailable — no lesson generated.
              </div>
            )}
          </div>

          {(alert.top_factors?.length ?? 0) > 0 && (
            <div>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-2">
                Contributing factors
              </h3>
              <ul className="space-y-2">
                {alert.top_factors!.slice(0, 5).map((f) => {
                  const pct = Math.min(100, Math.max(2, Math.round(f.impact_pct)));
                  return (
                    <li key={f.display_label}>
                      <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                        <span className="text-ink-0">{f.display_label}</span>
                        <span className="font-mono text-ink-2">
                          {f.direction === "down" ? "↓" : "↑"} {Math.round(f.impact_pct)}%
                        </span>
                      </div>
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-2">
                        <div
                          className={cn("h-full rounded-full", f.direction === "down" ? "bg-warn" : "bg-bad")}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          <div>
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-2">
              Recommendations
            </h3>
            <ul className="space-y-1.5 text-sm text-ink-1">
              {(llmLesson?.recommendations ?? buildRecommendations(alert, diagnosis)).map((r, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-cy" />
                  {r}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </article>
  );
}

// ─── KPI trends view ───────────────────────────────────────────────────────

function TrendsView({ metrics, alerts }: { metrics: MetricEvent[]; alerts: AlertEvent[] }) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  if (metrics.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-line-subtle p-10 text-center text-sm text-ink-2">
        Waiting for metrics…
      </div>
    );
  }

  const kpis: Array<{ key: keyof MetricEvent; label: string; unit: string; color: string; warnLine?: number }> = [
    { key: "latency_ms",      label: "Round-trip delay",  unit: "ms",   color: "#A87BFF", warnLine: 80  },
    { key: "jitter_ms",       label: "Jitter",            unit: "ms",   color: "#00D4FF", warnLine: 20  },
    { key: "packet_loss_pct", label: "Packet loss",       unit: "%",    color: "#F43F5E", warnLine: 1   },
    { key: "throughput_mbps", label: "Throughput",        unit: "Mbps", color: "#34D399"                },
    { key: "anomaly_score",   label: "Anomaly score",     unit: "",     color: "#F59E0B", warnLine: 0.4 },
    { key: "mos_estimate",    label: "Voice quality MOS", unit: "",     color: "#60A5FA"                },
  ];

  const ax = {
    axisLabel: { color: dark ? "#7C8AAB" : "#475569", fontSize: 10 },
    axisLine:  { lineStyle: { color: dark ? "#2D3D5E" : "#CBD5E1" } },
    splitLine: { lineStyle: { color: dark ? "#1F2C44" : "#E2E8F0" } },
  };

  const alertMarks = (alertList: AlertEvent[]) =>
    alertList.slice(0, 20).map((a) => ({
      xAxis: new Date(a.occurred_at).getTime(),
      label: { show: false },
      lineStyle: {
        color: a.severity === "critical" || a.severity === "high" ? "#F43F5E" : "#F59E0B",
        width: 1,
        type: "dashed" as const,
      },
    }));

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      {kpis.map((kpi) => {
        const points: Array<[number, number]> = [];
        for (const m of metrics) {
          const v = m[kpi.key] as number | null | undefined;
          if (v != null) points.push([new Date(m.occurred_at).getTime(), v]);
        }
        if (points.length === 0) return null;

        const option = {
          backgroundColor: "transparent",
          grid: { left: 44, right: 12, top: 20, bottom: 24 },
          tooltip: {
            trigger: "axis",
            backgroundColor: dark ? "#0D1825" : "#FFFFFF",
            borderColor: dark ? "#2D3D5E" : "#E2E8F0",
            textStyle: { color: dark ? "#ECF2FB" : "#0F172A", fontSize: 11 },
          },
          xAxis: { type: "time" as const, ...ax },
          yAxis: { type: "value" as const, name: kpi.unit, nameTextStyle: { color: dark ? "#7C8AAB" : "#475569", fontSize: 10 }, ...ax },
          series: [
            {
              name: kpi.label,
              type: "line",
              data: points,
              smooth: true,
              showSymbol: false,
              sampling: "lttb",
              lineStyle: { color: kpi.color, width: 1.8 },
              areaStyle: {
                color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
                  colorStops: [{ offset: 0, color: kpi.color + "40" }, { offset: 1, color: kpi.color + "00" }] },
              },
              markLine: {
                silent: true,
                symbol: ["none", "none"],
                data: [
                  ...(kpi.warnLine != null
                    ? [{ yAxis: kpi.warnLine, lineStyle: { color: "#F59E0B", type: "dotted" as const, width: 1 }, label: { formatter: "warn", color: "#F59E0B", fontSize: 9 } }]
                    : []),
                  ...alertMarks(alerts),
                ],
              },
            },
          ],
        };

        return (
          <div key={kpi.key} className="glass rounded-xl p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-medium text-ink-1">{kpi.label}</h3>
              <span className="font-mono text-xs text-ink-3">
                {points.length} samples
              </span>
            </div>
            <ReactEChartsCore
              option={withChartDefaults(option)}
              lazyUpdate
              style={{ height: 160, width: "100%" }}
              opts={{ renderer: "canvas" }}
            />
          </div>
        );
      })}
    </div>
  );
}

// ─── Brief components ─────────────────────────────────────────────────────

interface Stats {
  totalAlerts: number;
  criticalAlerts: number;
  forecastAlerts: number;
  executed: number;
  successfulRemediations: number;
  uniqueCells: number;
  avgConfidence: number;
  worstKpi: { name: string; value: number; unit: string } | null;
  windowStart: string;
  mttdSeconds: number | null;
  mttrSeconds: number | null;
  detectionCoveragePct: number;
  actionedIncidents: number;
  pendingRecommendations: number;
  blockedActions: number;
  jiraTickets: number;
  estimatedUsersAtRisk: number;
  estimatedSlaBurnPct: number;
  serviceImpact: "Low" | "Moderate" | "High" | "Critical";
  endUserImpact: string;
  businessRisk: string;
  availabilityPosture: string;
  topAffectedService: string;
}

function buildStats(
  alerts: AlertEvent[],
  executed: ExecutedActionEvent[],
  metrics: MetricEvent[],
  diagnoses: Record<string, DiagnosisEvent>,
  proposed: ProposedActionEvent[],
  tickets: JiraTicket[],
): Stats {
  const cells = new Set<string>();
  for (const a of alerts) if (a.cell_id) cells.add(a.cell_id);
  const conf = alerts.length ? alerts.reduce((acc, a) => acc + a.confidence, 0) / alerts.length : 0;
  const last = metrics[metrics.length - 1];
  let worst: Stats["worstKpi"] = null;
  if (last) {
    const candidates = [
      { name: "Latency",      value: last.latency_ms,       unit: "ms",   bad: (v: number) => v / 200 },
      { name: "Packet loss",  value: last.packet_loss_pct,  unit: "%",    bad: (v: number) => v / 5   },
      { name: "Jitter",       value: last.jitter_ms,        unit: "ms",   bad: (v: number) => v / 50  },
      { name: "Throughput",   value: last.throughput_mbps,  unit: "Mbps", bad: (v: number) => 1 - Math.min(1, v / 300) },
      { name: "CPU",          value: last.cpu_pct,          unit: "%",    bad: (v: number) => v / 100 },
    ];
    let best = -1;
    for (const c of candidates) {
      if (c.value == null) continue;
      const s = c.bad(c.value);
      if (s > best) { best = s; worst = { name: c.name, value: c.value, unit: c.unit }; }
    }
  }
  const alertByCorrelation = new Map(alerts.map((a) => [a.correlation_id, a]));
  const detectionDurations = Object.values(diagnoses)
    .map((d) => diffSeconds(alertByCorrelation.get(d.correlation_id)?.occurred_at, d.occurred_at))
    .filter((v): v is number => v != null && v >= 0);
  const responseDurations = executed
    .map((e) => diffSeconds(alertByCorrelation.get(e.correlation_id)?.occurred_at, e.occurred_at))
    .filter((v): v is number => v != null && v >= 0);
  const executedCorrelationIds = new Set(executed.map((e) => e.correlation_id));
  const pending = proposed.filter((p) => p.verdict !== "rejected" && !executed.some((e) => e.action_id === p.action_id));
  const blocked = proposed.filter((p) => p.verdict === "rejected");
  const usersAtRisk = pending.reduce((acc, p) => acc + (p.estimated_users_affected ?? 0), 0);
  const slaBurn = proposed.reduce((max, p) => Math.max(max, p.estimated_sla_burn_pct ?? 0), 0);
  const serviceImpact = classifyServiceImpact(alerts, worst, usersAtRisk, slaBurn);
  return {
    totalAlerts: alerts.length,
    criticalAlerts: alerts.filter((a) => a.severity === "critical" || a.severity === "high").length,
    forecastAlerts: alerts.filter((a) => a.detector === "forecast").length,
    executed: executed.length,
    successfulRemediations: executed.filter((e) => e.success).length,
    uniqueCells: cells.size,
    avgConfidence: conf,
    worstKpi: worst,
    windowStart: alerts.length ? alerts[alerts.length - 1].occurred_at : new Date().toISOString(),
    mttdSeconds: mean(detectionDurations),
    mttrSeconds: mean(responseDurations),
    detectionCoveragePct: alerts.length ? (detectionDurations.length / alerts.length) * 100 : 100,
    actionedIncidents: Array.from(executedCorrelationIds).filter((id) => alertByCorrelation.has(id)).length,
    pendingRecommendations: pending.length,
    blockedActions: blocked.length,
    jiraTickets: tickets.length,
    estimatedUsersAtRisk: usersAtRisk,
    estimatedSlaBurnPct: slaBurn,
    serviceImpact,
    endUserImpact: describeEndUserImpact(worst),
    businessRisk: describeBusinessRisk(serviceImpact, pending.length, slaBurn),
    availabilityPosture: describeAvailabilityPosture(serviceImpact, alerts.length),
    topAffectedService: describeAffectedService(worst),
  };
}

function buildBriefText(stats: Stats, alerts: AlertEvent[], insights: Record<string, InsightEvent>): string {
  const top = alerts[0];
  const insight = top ? insights[top.correlation_id] : null;
  const posture =
    stats.criticalAlerts > 0 ? "attention required" :
    stats.totalAlerts > 0 ? "watching elevated conditions" :
    "stable";
  const actionLine = stats.executed > 0
    ? `${stats.successfulRemediations} of ${stats.executed} remediation actions completed successfully; review any remaining approvals on the Optimization page.`
    : "No remediation has been executed in this window; the current posture is observe and validate.";
  const parts = [
    `Executive operations brief, generated ${new Date().toLocaleString()}. Current posture: ${posture}.`,
    `The live collector and agent pipeline reported ${stats.totalAlerts} alert${stats.totalAlerts === 1 ? "" : "s"} across ${stats.uniqueCells} affected cell${stats.uniqueCells === 1 ? "" : "s"}; ${stats.criticalAlerts} are critical/high and ${stats.forecastAlerts} are forecasted breaches.`,
    `Business impact is rated ${stats.serviceImpact.toLowerCase()}: ${stats.businessRisk}`,
    `Mean time to detect is ${formatDuration(stats.mttdSeconds)} and mean time to react is ${formatDuration(stats.mttrSeconds)}.`,
    actionLine,
    top
      ? `Priority incident: ${top.display_label} on cell ${top.cell_id ?? "default"} (${top.severity}, ${Math.min(96, Math.round(top.confidence * 100))} percent confidence from ${top.detector}).`
      : "No incidents are currently active. The network is healthy.",
    ...(insight ? [`Assistant lesson: ${insight.summary.split("\n")[0]}`] : []),
    ...(stats.worstKpi ? [`KPI focus: ${stats.worstKpi.name} is currently the weakest signal at ${stats.worstKpi.value.toFixed(1)} ${stats.worstKpi.unit}.`] : []),
  ];
  return parts.join(" ");
}

function ExecutiveSummary({
  stats,
  alerts,
  insights,
}: {
  stats: Stats;
  alerts: AlertEvent[];
  insights: Record<string, InsightEvent>;
}) {
  const top = alerts[0];
  const insight = top ? insights[top.correlation_id] : null;
  return (
    <div className="rounded-lg border border-line-subtle bg-bg-2/40 p-4 text-sm leading-relaxed text-ink-1">
      <p>
        QoS Buddy rates the current network posture as <strong>{stats.availabilityPosture}</strong>.
        The main service area to watch is <strong>{stats.topAffectedService}</strong>, with impact
        currently assessed as <strong>{stats.serviceImpact}</strong>.
      </p>
      <p className="mt-2">
        {top
          ? `The highest priority signal is ${top.display_label}${top.cell_id ? ` on cell ${top.cell_id}` : ""}. ${insight?.summary.split("\n")[0] ?? "The system has correlated the incident with live collector data and recent operational memory."}`
          : "No active incident is dominating the reporting window. The recommendation is to keep normal monitoring active."}
      </p>
      <p className="mt-2">
        For business leaders, the practical meaning is: {stats.endUserImpact} {stats.businessRisk}
      </p>
    </div>
  );
}

function BusinessImpact({ stats }: { stats: Stats }) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      <BriefStat label="Impact rating" value={stats.serviceImpact} tone={stats.serviceImpact === "High" || stats.serviceImpact === "Critical" ? "bad" : stats.serviceImpact === "Moderate" ? "info" : "ok"} />
      <BriefStat label="Users at risk" value={stats.estimatedUsersAtRisk ? stats.estimatedUsersAtRisk.toLocaleString() : "0"} tone={stats.estimatedUsersAtRisk > 0 ? "info" : "ok"} />
      <BriefStat label="SLA exposure" value={`${Math.round(stats.estimatedSlaBurnPct)}%`} tone={stats.estimatedSlaBurnPct > 20 ? "bad" : stats.estimatedSlaBurnPct > 0 ? "info" : "ok"} />
      <div className="rounded-lg border border-line-subtle bg-bg-2/40 p-4 md:col-span-3">
        <div className="text-xs uppercase tracking-wide text-ink-2">Business interpretation</div>
        <p className="mt-1 text-sm leading-relaxed text-ink-1">
          {stats.businessRisk} Expected customer-facing effect: {stats.endUserImpact}
        </p>
      </div>
    </div>
  );
}

function TimingStats({ stats }: { stats: Stats }) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
      <BriefStat label="MTTD" value={formatDuration(stats.mttdSeconds)} tone={stats.mttdSeconds == null ? "muted" : "ok"} />
      <BriefStat label="MTTR" value={formatDuration(stats.mttrSeconds)} tone={stats.mttrSeconds == null ? "muted" : "ok"} />
      <BriefStat label="Diagnosed" value={`${Math.round(stats.detectionCoveragePct)}%`} tone={stats.detectionCoveragePct >= 80 ? "ok" : "info"} />
      <BriefStat label="Actioned incidents" value={stats.actionedIncidents.toString()} tone={stats.actionedIncidents > 0 ? "ok" : "muted"} />
      <div className="rounded-lg border border-line-subtle bg-bg-2/40 p-4 md:col-span-4">
        <div className="text-xs uppercase tracking-wide text-ink-2">How to read this</div>
        <p className="mt-1 text-sm leading-relaxed text-ink-1">
          MTTD measures the average time from alert creation to diagnosis. MTTR measures the average
          time from alert creation to an executed remediation action. If MTTR is unavailable, incidents
          are still being monitored, waiting for approval, or blocked by policy.
        </p>
      </div>
    </div>
  );
}

function ActionsTaken({
  executed,
  proposed,
  tickets,
}: {
  executed: ExecutedActionEvent[];
  proposed: ProposedActionEvent[];
  tickets: JiraTicket[];
}) {
  const hasActivity = executed.length > 0 || proposed.length > 0 || tickets.length > 0;
  if (!hasActivity) {
    return <div className="rounded-lg border border-dashed border-line-subtle p-4 text-center text-sm text-ink-2">No recommendations, tickets, or remediation actions were recorded in this window.</div>;
  }
  return (
    <div className="space-y-3">
      {executed.length > 0 && <ExecutedList executed={executed} />}
      {proposed.length > 0 && (
        <ul className="space-y-2">
          {proposed.map((p) => (
            <li key={p.action_id} className="rounded-lg border border-line-subtle bg-bg-2/40 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-ink-0">{p.title}</span>
                <span className={cn("rounded px-2 py-0.5 text-[11px] uppercase", p.verdict === "rejected" ? "bg-bad-soft text-bad" : p.verdict === "auto" ? "bg-ok-soft text-ok" : "bg-warn-soft text-warn")}>{p.verdict}</span>
              </div>
              <p className="mt-1 text-xs text-ink-1">{p.description}</p>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-2">
                <span>Risk {p.risk_level}</span>
                <span>Scope {p.impact_radius}</span>
                {p.estimated_users_affected != null && <span>{p.estimated_users_affected.toLocaleString()} users protected/affected</span>}
                {p.estimated_sla_burn_pct != null && <span>{Math.round(p.estimated_sla_burn_pct)}% SLA exposure</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
      {tickets.length > 0 && (
        <ul className="space-y-2">
          {tickets.map((t) => (
            <li key={t.issue_key ?? `${t.event_id}-${t.audit_hash}`} className="rounded-lg border border-line-subtle bg-bg-2/40 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium text-ink-0">{t.issue_key ?? "Jira ticket"} - {t.summary ?? t.display_label}</span>
                <span className="rounded bg-info-soft px-2 py-0.5 text-[11px] text-info">{t.status ?? "created"}</span>
              </div>
              <div className="mt-1 text-xs text-ink-2">
                Created for business follow-up and operational accountability{t.issue_url ? `: ${t.issue_url}` : "."}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function LeadershipRecommendations({
  stats,
  proposed,
  alerts,
}: {
  stats: Stats;
  proposed: ProposedActionEvent[];
  alerts: AlertEvent[];
}) {
  const recommendations = buildLeadershipRecommendations(stats, proposed, alerts);
  return (
    <ul className="space-y-2">
      {recommendations.map((r) => (
        <li key={r} className="flex items-start gap-2 rounded-lg border border-line-subtle bg-bg-2/40 p-3 text-sm text-ink-1">
          <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-cy" />
          <span>{r}</span>
        </li>
      ))}
    </ul>
  );
}

function BriefHeader({ username, stats }: { username: string; stats: Stats }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line-subtle pb-4">
      <div>
        <div className="text-xs uppercase tracking-wide text-ink-2">Qosmic NOC Brief</div>
        <div className="text-3xl font-semibold tracking-tight text-ink-0">Operations status</div>
        <div className="mt-1 text-xs text-ink-2">
          Window from {new Date(stats.windowStart).toLocaleString()} · generated {new Date().toLocaleString()}
        </div>
        <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
          <span className="rounded-full bg-ok-soft px-2 py-0.5 text-ok">Live collector</span>
          <span className="rounded-full bg-info-soft px-2 py-0.5 text-info">Keycloak-authenticated</span>
          <span className="rounded-full bg-cy-soft px-2 py-0.5 text-cy">Agent decisions</span>
        </div>
      </div>
      <div className="rounded-lg border border-line-subtle bg-bg-2/40 p-3 text-xs">
        <div className="text-ink-2">Prepared for</div>
        <div className="font-medium text-ink-0">{username}</div>
      </div>
    </div>
  );
}

function BriefStats({ stats }: { stats: Stats }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <BriefStat label="Total alerts"     value={stats.totalAlerts.toString()} />
      <BriefStat label="Critical / high"  value={stats.criticalAlerts.toString()} tone={stats.criticalAlerts > 0 ? "bad" : "ok"} />
      <BriefStat label="Forecasts"        value={stats.forecastAlerts.toString()} tone="info" />
      <BriefStat label="Remediations"     value={`${stats.successfulRemediations}/${stats.executed}`} tone={stats.executed > 0 ? "ok" : "muted"} />
      <BriefStat label="Cells affected"   value={stats.uniqueCells.toString()} />
      <BriefStat label="Avg confidence"   value={`${Math.min(96, Math.round(stats.avgConfidence * 100))}%`} />
      {stats.worstKpi && (
        <div className="col-span-2 rounded-xl border border-bad/30 bg-bad-soft/20 p-3">
          <div className="text-xs uppercase tracking-wide text-ink-2">Worst KPI right now</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="font-mono text-2xl tabular-nums text-bad">{stats.worstKpi.value.toFixed(1)}</span>
            <span className="text-sm text-ink-2">{stats.worstKpi.unit}</span>
          </div>
          <div className="text-xs text-ink-2">{stats.worstKpi.name}</div>
        </div>
      )}
    </div>
  );
}

function BriefStat({ label, value, tone = "ink" }: { label: string; value: string; tone?: "ink" | "ok" | "bad" | "info" | "muted" }) {
  const cls = tone === "ok" ? "text-ok" : tone === "bad" ? "text-bad" : tone === "info" ? "text-info" : tone === "muted" ? "text-ink-2" : "text-ink-0";
  return (
    <div className="rounded-xl border border-line-subtle bg-bg-2/40 p-3">
      <div className="text-xs uppercase tracking-wide text-ink-2">{label}</div>
      <div className={cn("mt-1 font-mono text-2xl tabular-nums", cls)}>{value}</div>
    </div>
  );
}

function SectionWrap({ title, icon: Icon, children }: { title: string; icon: any; children: React.ReactNode }) {
  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-4 w-4 text-ink-2" />
        <h2 className="text-sm font-medium text-ink-1">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function TopIncidents({ alerts, insights }: { alerts: AlertEvent[]; insights: Record<string, InsightEvent> }) {
  const top = alerts.slice(0, 5);
  if (top.length === 0) {
    return <div className="rounded-lg border border-dashed border-line-subtle p-4 text-center text-sm text-ink-2">No incidents in the current window.</div>;
  }
  return (
    <ul className="space-y-2">
      {top.map((a) => {
        const ins = insights[a.correlation_id];
        const Dir = a.breach_metric === "throughput_mbps" ? TrendingDown : TrendingUp;
        return (
          <li key={a.event_id} className="rounded-lg border border-line-subtle bg-bg-2/40 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Dir className={cn("h-4 w-4", a.severity === "critical" || a.severity === "high" ? "text-bad" : a.severity === "medium" ? "text-warn" : "text-info")} />
                <span className="font-medium text-ink-0">{a.display_label}</span>
              </div>
              <span className="font-mono text-[11px] text-ink-2">
                <Clock className="mr-1 inline h-3 w-3" />
                {new Date(a.occurred_at).toLocaleTimeString()}
              </span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-2">
              {a.cell_id && <span>Cell {a.cell_id}</span>}
              <span>{a.detector}</span>
              <span>Confidence {Math.min(96, Math.round(a.confidence * 100))}%</span>
              <span className="uppercase">{a.severity}</span>
            </div>
            {ins && <p className="mt-1 line-clamp-2 text-xs text-ink-1">{ins.summary.split("\n")[0]}</p>}
          </li>
        );
      })}
    </ul>
  );
}

function ExecutedList({ executed }: { executed: ExecutedActionEvent[] }) {
  if (executed.length === 0) {
    return <div className="rounded-lg border border-dashed border-line-subtle p-4 text-center text-sm text-ink-2">No remediations have run in this window.</div>;
  }
  return (
    <ul className="space-y-2">
      {executed.map((e) => (
        <li key={e.event_id} className="rounded-lg border border-line-subtle bg-bg-2/40 p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <CheckCircle2 className={cn("h-4 w-4", e.success ? "text-ok" : "text-bad")} />
              <span className="font-medium text-ink-0">{e.diff_summary ?? e.action_id}</span>
            </div>
            <span className="font-mono text-[11px] text-ink-2">{new Date(e.occurred_at).toLocaleTimeString()}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-2">
            <span>Mode: {e.mode}</span>
            {e.duration_ms != null && <span>{e.duration_ms} ms</span>}
            {e.rolled_back && <span className="text-warn">rolled back</span>}
            <span className="font-mono text-ink-3">audit {e.audit_hash.slice(0, 12)}…</span>
          </div>
        </li>
      ))}
    </ul>
  );
}

function StatusBadge({ alert, hasAction }: { alert: AlertEvent; hasAction: boolean }) {
  if (hasAction) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-ok-soft px-3 py-1 text-xs font-medium text-ok">
        <CheckCircle2 className="h-3.5 w-3.5" /> Resolved
      </span>
    );
  }
  if (alert.severity === "critical" || alert.severity === "high") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-bad-soft px-3 py-1 text-xs font-medium text-bad animate-pulse">
        <AlertTriangle className="h-3.5 w-3.5" /> Active
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-warn-soft px-3 py-1 text-xs font-medium text-warn">
      <Clock className="h-3.5 w-3.5" /> Monitoring
    </span>
  );
}

// ─── helpers ─────────────────────────────────────────────────────────────

function diffSeconds(start?: string, end?: string): number | null {
  if (!start || !end) return null;
  const delta = new Date(end).getTime() - new Date(start).getTime();
  return Number.isFinite(delta) ? Math.max(0, delta / 1000) : null;
}

function mean(values: number[]): number | null {
  if (values.length === 0) return null;
  return values.reduce((acc, v) => acc + v, 0) / values.length;
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "n/a";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${minutes.toFixed(minutes < 10 ? 1 : 0)}m`;
  return `${(minutes / 60).toFixed(1)}h`;
}

function classifyServiceImpact(
  alerts: AlertEvent[],
  worst: Stats["worstKpi"],
  usersAtRisk: number,
  slaBurn: number,
): Stats["serviceImpact"] {
  const severe = alerts.filter((a) => a.severity === "critical" || a.severity === "high").length;
  if (severe >= 3 || usersAtRisk >= 5000 || slaBurn >= 40) return "Critical";
  if (severe >= 1 || usersAtRisk >= 1000 || slaBurn >= 20) return "High";
  if (alerts.length > 0 || usersAtRisk > 0 || worst) return "Moderate";
  return "Low";
}

function describeEndUserImpact(worst: Stats["worstKpi"]): string {
  if (!worst) return "End users should experience normal service quality.";
  const name = worst.name.toLowerCase();
  if (name.includes("latency")) return "Customers may notice slower page loads, delayed transactions, or lag in interactive applications.";
  if (name.includes("jitter")) return "Voice, video, and collaboration sessions may become unstable or uneven.";
  if (name.includes("packet")) return "Some sessions may retry, stall, or disconnect until packet loss improves.";
  if (name.includes("throughput")) return "Data-heavy applications may feel slow, especially downloads, streaming, and cloud access.";
  if (name.includes("cpu")) return "Network elements may have reduced headroom, increasing the chance of slower service under load.";
  return "Service quality is degraded enough to warrant continued monitoring.";
}

function describeBusinessRisk(
  impact: Stats["serviceImpact"],
  pendingRecommendations: number,
  slaBurn: number,
): string {
  if (impact === "Critical") {
    return "Customer experience and SLA commitments are at material risk; leadership should track the incident until closure.";
  }
  if (impact === "High") {
    return "There is a credible risk of customer complaints, SLA burn, and operational escalation if the condition persists.";
  }
  if (pendingRecommendations > 0) {
    return "Risk is controlled, but pending recommendations should be approved or rejected to reduce exposure.";
  }
  if (slaBurn > 0) {
    return "SLA exposure is visible but currently limited; continued monitoring is recommended.";
  }
  return "No material business risk is visible in this reporting window.";
}

function describeAvailabilityPosture(impact: Stats["serviceImpact"], alerts: number): string {
  if (impact === "Critical") return "critical attention required";
  if (impact === "High") return "degraded but actively managed";
  if (alerts > 0 || impact === "Moderate") return "elevated monitoring";
  return "stable";
}

function describeAffectedService(worst: Stats["worstKpi"]): string {
  if (!worst) return "overall network availability";
  const name = worst.name.toLowerCase();
  if (name.includes("latency") || name.includes("jitter")) return "real-time voice, video, and interactive services";
  if (name.includes("packet")) return "session reliability and application continuity";
  if (name.includes("throughput")) return "mobile data and enterprise internet performance";
  if (name.includes("cpu")) return "network element capacity and service headroom";
  return "customer-facing connectivity";
}

function buildLeadershipRecommendations(
  stats: Stats,
  proposed: ProposedActionEvent[],
  alerts: AlertEvent[],
): string[] {
  const recs: string[] = [];
  if (stats.pendingRecommendations > 0) {
    recs.push(`Review ${stats.pendingRecommendations} pending recommendation${stats.pendingRecommendations === 1 ? "" : "s"} on the Optimization page so recoverable service risk does not sit idle.`);
  }
  if (stats.blockedActions > 0) {
    recs.push(`Review ${stats.blockedActions} policy-blocked action${stats.blockedActions === 1 ? "" : "s"} to decide whether policy is correctly protecting the network or blocking useful remediation.`);
  }
  if (stats.serviceImpact === "High" || stats.serviceImpact === "Critical") {
    recs.push("Keep this incident visible to service assurance leadership until the impact rating returns to Moderate or Low.");
  }
  if (stats.mttrSeconds == null && alerts.length > 0) {
    recs.push("Ask operations to close the loop on active incidents: each major alert should have an owner, a decision, and a recorded outcome.");
  }
  if (stats.jiraTickets > 0) {
    recs.push(`Use the ${stats.jiraTickets} Jira ticket${stats.jiraTickets === 1 ? "" : "s"} as the executive follow-up trail for accountability, customer communication, and post-incident review.`);
  }
  const reversible = proposed.filter((p) => p.is_reversible && p.verdict !== "rejected").length;
  if (reversible > 0) {
    recs.push(`${reversible} proposed action${reversible === 1 ? " is" : "s are"} reversible; prioritize these first because they reduce service risk while keeping rollback available.`);
  }
  if (recs.length === 0) {
    recs.push("Maintain normal monitoring and keep the live collector running; no executive intervention is required in this window.");
  }
  return recs.slice(0, 6);
}

function sevToneClasses(sev: AlertEvent["severity"]): string {
  if (sev === "critical" || sev === "high") return "bg-bad-soft text-bad";
  if (sev === "medium") return "bg-warn-soft text-warn";
  return "bg-info-soft text-info";
}

function buildRecommendations(alert: AlertEvent, diagnosis?: DiagnosisEvent): string[] {
  const recs: string[] = [];
  if (alert.severity === "critical" || alert.severity === "high") {
    recs.push("Escalate to senior NOC engineer — severity warrants immediate attention.");
  }
  if (alert.detector === "forecast") {
    recs.push("Pre-emptive action window available before breach — review the Optimization page.");
  }
  if (diagnosis?.similar_incidents.some((s) => s.resolution.toLowerCase() !== "pending")) {
    const resolved = diagnosis.similar_incidents.find((s) => s.resolution.toLowerCase() !== "pending");
    recs.push(`Precedent from ${resolved!.incident_id}: "${resolved!.resolution}"`);
  }
  if (recs.length === 0) {
    recs.push("Monitor KPIs over the next 5 minutes before escalation.");
    recs.push("Check the Diagnostic page for the full root-cause pattern.");
  }
  return recs;
}

function buildImmediatePostmortemLesson(alert: AlertEvent, diagnosis?: DiagnosisEvent): ReportingLesson {
  const root = diagnosis?.pattern_label ?? inferRootCauseFromAlert(alert);
  const cell = alert.cell_id ? `cell ${alert.cell_id}` : "the monitored network";
  const confidence = Math.min(96, Math.round(alert.confidence * 100));
  const lesson = [
    `${alert.display_label} was detected on ${cell} with ${confidence}% confidence.`,
    `Current interpretation: ${root}.`,
    alert.detector === "forecast"
      ? "Treat this as a prevention window and review the proposed action before service impact increases."
      : "Validate KPI recovery after any action and keep the incident open until the signal returns to normal.",
  ].join(" ");
  return {
    lesson,
    root_cause_class: root.replace(/\s+/g, "_").toLowerCase(),
    confidence,
    recommendations: buildRecommendations(alert, diagnosis),
    save_to_memory: false,
  };
}

function inferRootCauseFromAlert(alert: AlertEvent): string {
  const metric = (alert.breach_metric ?? alert.display_label ?? "").toLowerCase();
  if (metric.includes("throughput")) return "capacity or congestion pressure";
  if (metric.includes("packet") || metric.includes("loss")) return "transport reliability degradation";
  if (metric.includes("jitter")) return "real-time service instability";
  if (metric.includes("latency") || metric.includes("delay")) return "transport delay degradation";
  if (metric.includes("cpu") || metric.includes("memory")) return "network element resource pressure";
  return "network quality degradation";
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function isoSlug(): string {
  return new Date().toISOString().slice(0, 19).replace(/:/g, "-");
}
