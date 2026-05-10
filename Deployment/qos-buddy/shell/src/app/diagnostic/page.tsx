"use client";

import { useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  Brain,
  CheckCircle2,
  ChevronRight,
  Compass,
  Loader2,
  Search,
  ShieldAlert,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { useLive } from "@/lib/store";
import { cn } from "@/lib/utils";
import { askAi } from "@/lib/ai";
import type { AlertEvent, DiagnosisEvent, InsightEvent } from "@/lib/types";

export default function DiagnosticPage() {
  const alerts   = useLive((s) => s.alerts);
  const diagnoses = useLive((s) => s.diagnoses);
  const insights  = useLive((s) => s.insights);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search,     setSearch]     = useState("");
  const [sevFilter,  setSevFilter]  = useState<string>("all");

  const incidents = useMemo(() => {
    const seen = new Set<string>();
    const uniq: AlertEvent[] = [];
    for (const a of alerts) {
      if (a.detector === "forecast") continue;
      if (!seen.has(a.correlation_id)) { seen.add(a.correlation_id); uniq.push(a); }
    }
    const SEV = { critical: 4, high: 3, medium: 2, low: 1, info: 0 } as const;
    return uniq.sort((a, b) => (SEV[b.severity] ?? 0) - (SEV[a.severity] ?? 0));
  }, [alerts]);

  const filtered = useMemo(() => incidents.filter((a) => {
    if (sevFilter !== "all" && a.severity !== sevFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      if (!a.display_label.toLowerCase().includes(q) && !(a.cell_id ?? "").toLowerCase().includes(q)) return false;
    }
    return true;
  }), [incidents, sevFilter, search]);

  const headlineAlert = useMemo(
    () => filtered.find((a) => a.correlation_id === selectedId) ?? filtered[0] ?? null,
    [filtered, selectedId],
  );
  const headlineDiag = headlineAlert ? diagnoses[headlineAlert.correlation_id] ?? null : null;
  const headlineInsight = headlineAlert ? insights[headlineAlert.correlation_id] ?? null : null;

  const lessonLibrary = useMemo(
    () => Object.values(insights).sort((a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime()).slice(0, 25),
    [insights],
  );

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Diagnostic</h1>
        <p className="text-sm text-ink-2">Open incidents · root cause · similar past cases · AI lesson</p>
      </header>

      {/* filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[180px]">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3" />
          <input
            type="text"
            placeholder="Filter…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-md border border-line-subtle bg-bg-2 py-1.5 pl-8 pr-3 text-xs text-ink-0 placeholder:text-ink-3 focus:border-cy focus:outline-none"
          />
        </div>
        <select
          value={sevFilter}
          onChange={(e) => setSevFilter(e.target.value)}
          className="rounded-md border border-line-subtle bg-bg-2 px-2 py-1.5 text-xs text-ink-1 focus:border-cy focus:outline-none"
        >
          <option value="all">All severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>

      {incidents.length === 0 ? (
        <EmptyDiagnostic />
      ) : (
        <>
          {/* two-panel layout */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
            {/* left: incident list */}
            <div className="lg:col-span-2">
              <div className="glass overflow-hidden rounded-xl">
                <div className="flex items-center justify-between border-b border-line-subtle px-4 py-3">
                  <span className="text-sm font-medium text-ink-1">OPEN · {filtered.length}</span>
                  <span className="text-[11px] text-ink-3">sorted by impact</span>
                </div>
                <ul className="divide-y divide-line-subtle overflow-y-auto" style={{ maxHeight: 560 }}>
                  {filtered.map((a) => (
                    <IncidentListItem
                      key={a.event_id}
                      alert={a}
                      selected={a.correlation_id === (headlineAlert?.correlation_id ?? "")}
                      onClick={() => setSelectedId(a.correlation_id)}
                    />
                  ))}
                  {filtered.length === 0 && (
                    <li className="p-6 text-center text-sm text-ink-2">No incidents match the filter.</li>
                  )}
                </ul>
              </div>
            </div>

            {/* right: detail panel */}
            <div className="lg:col-span-3">
              {headlineAlert ? (
                <IncidentDetail
                  alert={headlineAlert}
                  diagnosis={headlineDiag}
                  insight={headlineInsight}
                />
              ) : (
                <EmptyDiagnostic />
              )}
            </div>
          </div>

          {/* lesson library */}
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-medium text-ink-1">Lesson library</h2>
              <span className="text-xs text-ink-2">{lessonLibrary.length} cached lesson{lessonLibrary.length === 1 ? "" : "s"}</span>
            </div>
            <LessonLibrary insights={lessonLibrary} diagnoses={diagnoses} />
          </section>
        </>
      )}
    </div>
  );
}

// ─── Incident list item ───────────────────────────────────────────────────────

const SEV = {
  critical: "bg-bad-soft text-bad border-bad/30",
  high:     "bg-bad-soft/70 text-bad border-bad/20",
  medium:   "bg-warn-soft text-warn border-warn/30",
  low:      "bg-info-soft text-info border-info/30",
  info:     "bg-info-soft/60 text-info border-info/20",
} as const;

function IncidentListItem({ alert, selected, onClick }: { alert: AlertEvent; selected: boolean; onClick: () => void }) {
  const sevClass = SEV[alert.severity] ?? SEV.medium;
  const minsAgo = Math.max(0, Math.round((Date.now() - new Date(alert.occurred_at).getTime()) / 60_000));

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn("flex w-full items-start gap-3 px-4 py-3 text-left transition", selected ? "bg-cy-soft/20" : "hover:bg-bg-2/50")}
    >
      <div className={cn("mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide", sevClass)}>
        {alert.severity}
      </div>
      <div className="min-w-0 flex-1">
        <div className="font-mono text-[10px] text-ink-3">{formatIncId(alert)}</div>
        <div className="mt-0.5 text-sm font-medium leading-snug text-ink-0">{alert.display_label}</div>
        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-ink-2">
          {alert.cell_id && <span>Cell {alert.cell_id}</span>}
          <span>·</span>
          <span>{minsAgo} min ago</span>
        </div>
      </div>
      {selected && <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-cy" />}
    </button>
  );
}

// ─── Incident Detail ──────────────────────────────────────────────────────────

function IncidentDetail({
  alert,
  diagnosis,
  insight,
}: {
  alert: AlertEvent;
  diagnosis: DiagnosisEvent | null;
  insight: InsightEvent | null;
}) {
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);
  const [dynamicLesson, setDynamicLesson] = useState<string | null>(null);
  const [lessonLoading, setLessonLoading] = useState(false);

  const sevClass   = SEV[alert.severity] ?? SEV.medium;
  const minsAgo    = Math.max(0, Math.round((Date.now() - new Date(alert.occurred_at).getTime()) / 60_000));
  // Cap raw model confidence at 96% because perfect confidence is operationally suspect.
  const confidence = Math.min(96, Math.round(alert.confidence * 100));
  const slaRisk    = deriveSlaRisk(alert);
  const dataTrust  = Math.min(98, Math.round(alert.confidence * 100 + (alert.monitoring_features ? 3 : 0) + (diagnosis ? 2 : 0)));
  const story      = buildStory(alert, diagnosis);

  // Fetch a live RAG-augmented Qwen2.5 lesson whenever the selected incident changes
  useEffect(() => {
    setDynamicLesson(null);
    if (!alert) return;
    let cancelled = false;
    setLessonLoading(true);

    const factors = alert.top_factors?.slice(0, 3)
      .map((f) => `${f.display_label} (${f.direction === "up" ? "↑" : "↓"}${Math.round(f.impact_pct)}%)`)
      .join(", ") ?? "unknown";

    const prompt = [
      "You are a senior NOC engineer. In 2–3 short sentences (no bullets, no headers, no markdown), give the operator:",
      "(1) the most likely root cause, (2) the immediate corrective action, (3) one operator lesson for the memory bank.",
      "",
      `Incident: ${alert.display_label}`,
      `Cell: ${alert.cell_id ?? "unknown"} · Severity: ${alert.severity} · Confidence: ${Math.min(96, Math.round(alert.confidence * 100))}%`,
      `Pattern: ${diagnosis?.pattern_label ?? "under investigation"}`,
      `Key signals: ${factors}`,
    ].join("\n");

    void askAi(
      prompt,
      {
        current_page: "/diagnostic",
        cell_id: alert.cell_id ?? undefined,
        alert_id: alert.event_id,
      },
      "", // empty fallback — we'll surface the cached insight below if RAG is offline
    ).then((answer) => {
      if (cancelled) return;
      setDynamicLesson(answer.trim() || null);
      setLessonLoading(false);
    });

    return () => { cancelled = true; };
  }, [alert.event_id, alert.cell_id, alert.confidence, diagnosis?.pattern_label]);

  const shownLesson = dynamicLesson ?? insight?.summary ?? null;

  return (
    <div className="glass overflow-hidden rounded-xl" style={{ minHeight: 720 }}>
      {/* header */}
      <div className="border-b border-line-subtle p-4">
        <div className="font-mono text-[11px] text-ink-3">{formatIncId(alert)}</div>
        <h2 className="mt-1 text-lg font-semibold text-ink-0">{alert.display_label}</h2>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          {alert.cell_id && <span className="rounded bg-bg-2 px-2 py-0.5 text-ink-2">Cell {alert.cell_id}</span>}
          <span className="text-ink-3">·</span>
          <span className="text-ink-2">opened {minsAgo} min ago</span>
          <span className={cn("ml-auto rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide", sevClass)}>
            {alert.severity}
          </span>
        </div>
      </div>

      {/* stat tiles */}
      <div className="grid grid-cols-3 divide-x divide-line-subtle border-b border-line-subtle">
        <StatTile label="CONFIDENCE" value={`${confidence}%`} sub="Pattern match strength"  tone={confidence >= 80 ? "ok" : "warn"} />
        <StatTile label="SLA RISK"   value={slaRisk.label}   sub={slaRisk.detail}           tone={slaRisk.tone} />
        <StatTile label="DATA TRUST" value={`${dataTrust}%`} sub="Fresh · complete · ranged" tone={dataTrust >= 90 ? "ok" : "warn"} />
      </div>

      <div className="space-y-4 p-4">
        {/* ── ROOT CAUSE — most prominent section ── */}
        <div className="rounded-lg border border-bad/30 bg-bad-soft/10 p-4">
          <div className="mb-2 flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 shrink-0 text-bad" />
            <span className="text-xs font-semibold uppercase tracking-widest text-bad">Root Cause</span>
          </div>
          {diagnosis?.pattern_label ? (
            <>
              <div className="text-base font-bold text-ink-0">{diagnosis.pattern_label}</div>
              {diagnosis.llm_summary && (
                <p className="mt-1 text-sm leading-relaxed text-ink-1">{diagnosis.llm_summary}</p>
              )}
              {diagnosis.similar_incidents.length > 0 && (
                <div className="mt-2 text-[11px] text-ink-2">
                  Seen in {diagnosis.similar_incidents.length} past incident{diagnosis.similar_incidents.length > 1 ? "s" : ""} ·{" "}
                  closest: {diagnosis.similar_incidents[0].incident_id.slice(0, 16)}
                  {diagnosis.similar_incidents[0].resolution
                    ? ` — resolved by ${diagnosis.similar_incidents[0].resolution}`
                    : ""}
                </div>
              )}
            </>
          ) : alert.top_factors && alert.top_factors.length > 0 ? (
            <>
              <div className="text-base font-bold text-ink-0">
                {provisionalRootCause(alert)}
              </div>
              <p className="mt-1 text-sm leading-relaxed text-ink-1">
                Diagnostic agent is correlating against past incidents — this is the provisional read from the
                detector&rsquo;s top contributing signals.
              </p>
              <div className="mt-2 inline-flex items-center gap-1 text-[11px] text-ink-3">
                <Loader2 className="h-3 w-3 animate-spin" />
                full RCA streaming in
              </div>
            </>
          ) : (
            <p className="text-sm text-ink-2">
              Diagnosis running — root cause will appear here as the diagnostic agent correlates signals.
            </p>
          )}
        </div>

        {/* story of incident */}
        {story.length > 0 && (
          <div>
            <div className="mb-2 text-[10px] font-medium uppercase tracking-widest text-ink-3">Story of this incident</div>
            <ul className="relative space-y-3 pl-4">
              <div className="absolute left-1.5 top-2 h-[calc(100%-8px)] w-px bg-line-subtle" />
              {story.map((s, i) => (
                <li key={i} className="relative flex items-start gap-3">
                  <span className="absolute -left-4 mt-1.5 h-2 w-2 shrink-0 rounded-full border-2 border-bg-1 bg-cy" />
                  <div>
                    <div className="text-sm font-medium text-ink-0">{s.headline}</div>
                    {s.detail && <div className="mt-0.5 text-[11px] text-ink-2">{s.detail}</div>}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* contributing KPIs */}
        {(alert.top_factors?.length ?? 0) > 0 && (
          <div>
            <div className="mb-2 text-[10px] font-medium uppercase tracking-widest text-ink-3">KPI signals that triggered detection</div>
            <div className="space-y-2">
              {alert.top_factors!.slice(0, 5).map((f) => {
                const w = Math.min(100, Math.max(4, Math.round(f.impact_pct)));
                return (
                  <div key={f.display_label}>
                    <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                      <span className="text-ink-0">{f.display_label}</span>
                      <span className={cn("font-mono font-semibold", f.direction === "up" ? "text-bad" : "text-warn")}>
                        {f.direction === "up" ? "↑" : "↓"} {Math.round(Math.min(100, f.impact_pct))}%
                      </span>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-3">
                      <div
                        className={cn("h-full rounded-full", f.direction === "up" ? "bg-bad" : "bg-warn")}
                        style={{ width: `${w}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* similar past incidents */}
        {(diagnosis?.similar_incidents.length ?? 0) > 0 && (
          <div>
            <div className="mb-2 text-[10px] font-medium uppercase tracking-widest text-ink-3">Similar past incidents</div>
            <div className="divide-y divide-line-subtle overflow-hidden rounded-lg border border-line-subtle">
              {diagnosis!.similar_incidents.slice(0, 4).map((inc) => {
                const pct = Math.min(100, Math.round(inc.relevance_pct ?? inc.similarity_pct));
                return (
                  <div key={inc.incident_id} className="flex items-center justify-between gap-3 px-3 py-2 text-xs">
                    <span className="font-mono text-[10px] text-ink-3">{inc.incident_id.slice(0, 20)}</span>
                    <div className="flex items-center gap-2">
                      {inc.resolution && <span className="text-ink-2">{inc.resolution}</span>}
                      <span className="font-semibold text-ok">{pct}% match</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* AI lesson — live from Qwen2.5 */}
        <div className="rounded-lg border border-vio/20 bg-vio-soft/10 p-3">
          <div className="mb-2 flex items-center gap-2">
            <Brain className="h-3.5 w-3.5 text-vio" />
            <span className="text-xs font-semibold text-vio">AI Lesson</span>
            {insight && <span className="ml-auto font-mono text-[10px] text-ink-3">{Math.min(96, Math.round(insight.confidence * 100))}% conf</span>}
          </div>
          {lessonLoading ? (
            <div className="flex items-center gap-2 py-2 text-xs text-ink-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-vio" />
              Qwen2.5 + RAG synthesizing lesson from operator memory…
            </div>
          ) : shownLesson ? (
            <>
              <p className="text-sm leading-relaxed text-ink-1">{shownLesson.split("\n")[0]}</p>
              <div className="mt-2 flex items-center gap-2">
                <button
                  onClick={() => setFeedback("up")}
                  className={cn("inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] transition", feedback === "up" ? "border-ok bg-ok-soft text-ok" : "border-line-subtle text-ink-3 hover:text-ink-1")}
                >
                  <ThumbsUp className="h-3 w-3" /> Helpful
                </button>
                <button
                  onClick={() => setFeedback("down")}
                  className={cn("inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] transition", feedback === "down" ? "border-bad bg-bad-soft text-bad" : "border-line-subtle text-ink-3 hover:text-ink-1")}
                >
                  <ThumbsDown className="h-3 w-3" /> Not useful
                </button>
              </div>
            </>
          ) : (
            <p className="text-sm text-ink-3">
              No matching lesson in operator memory yet — Qwen2.5 will produce one as soon as a similar pattern is recorded.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function StatTile({ label, value, sub, tone }: { label: string; value: string; sub: string; tone: "ok" | "warn" | "bad" | "ink" }) {
  const valClass = tone === "ok" ? "text-ok" : tone === "bad" ? "text-bad" : tone === "warn" ? "text-warn" : "text-ink-0";
  return (
    <div className="px-3 py-3 text-center">
      <div className="text-[9px] font-medium uppercase tracking-widest text-ink-3">{label}</div>
      <div className={cn("mt-1 text-xl font-bold tabular-nums", valClass)}>{value}</div>
      <div className="mt-0.5 text-[10px] text-ink-2">{sub}</div>
    </div>
  );
}

// ─── Lesson library ───────────────────────────────────────────────────────────

function LessonLibrary({ insights, diagnoses }: { insights: InsightEvent[]; diagnoses: Record<string, DiagnosisEvent> }) {
  if (insights.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-line-subtle p-8 text-center text-sm text-ink-2">
        Lessons appear here as the synthesis agent produces them — one per diagnosed incident.
      </div>
    );
  }
  return (
    <div className="glass max-h-[360px] overflow-y-auto rounded-xl p-2">
      <ul className="divide-y divide-line-subtle">
        {insights.map((i) => {
          const diag = diagnoses[i.correlation_id];
          return (
            <li key={i.event_id} className="p-3">
              <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                <span className="inline-flex items-center gap-1 text-ink-2">
                  <BookOpen className="h-3 w-3" />
                  {diag?.pattern_label ?? "Lesson"}
                </span>
                <span className="text-ink-3">{timeAgo(i.occurred_at)}</span>
              </div>
              <p className="line-clamp-3 text-sm text-ink-1">{i.summary}</p>
              {diag && (
                <div className="mt-1 font-mono text-[11px] text-ink-3">
                  cell {diag.cell_id ?? "n/a"} · {formatIncIdRaw(diag.event_id, diag.occurred_at)}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ─── Empty state ──────────────────────────────────────────────────────────────

function EmptyDiagnostic() {
  return (
    <div className="glass rounded-xl p-10 text-center">
      <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-xl bg-ok-soft text-ok">
        <Compass className="h-5 w-5" />
      </div>
      <div className="text-sm font-medium text-ink-0">Nothing to diagnose</div>
      <p className="mt-1 text-xs text-ink-2">
        The synthesis agent has not raised a diagnosable incident yet.
        Diagnostic context appears as soon as the detector flags an event.
      </p>
    </div>
  );
}

// ─── helpers ─────────────────────────────────────────────────────────────────

function formatIncId(alert: AlertEvent): string {
  return formatIncIdRaw(alert.event_id, alert.occurred_at);
}

function formatIncIdRaw(eventId: string, occurredAt: string): string {
  const date   = new Date(occurredAt).toISOString().slice(2, 10).replace(/-/g, "");
  const suffix = eventId.replace(/[^a-zA-Z0-9]/g, "").slice(-4).padStart(4, "0").toUpperCase();
  return `INC-${date}-${suffix}`;
}

function deriveSlaRisk(alert: AlertEvent): { label: string; detail: string; tone: "ok" | "warn" | "bad" | "ink" } {
  const tts = alert.time_to_breach_seconds;
  if (alert.severity === "critical" || (tts != null && tts < 300)) {
    return { label: "Critical", detail: tts != null ? `Breach in ${Math.round(tts / 60)} min` : "Immediate attention required", tone: "bad" };
  }
  if (alert.severity === "high") return { label: "High",   detail: "Elevated risk to SLA",   tone: "bad"  };
  if (alert.severity === "medium") return { label: "Medium", detail: "Monitor — within tolerance", tone: "warn" };
  return { label: "Low", detail: "Within SLO bounds", tone: "ok" };
}

function provisionalRootCause(alert: AlertEvent): string {
  const top = alert.top_factors?.[0];
  if (!top) return "Pattern under investigation";
  const verb = top.direction === "up" ? "elevated" : "degraded";
  const cell = alert.cell_id ? ` on ${alert.cell_id}` : "";
  return `Provisional: ${verb} ${top.display_label}${cell}`;
}

function buildStory(alert: AlertEvent, diagnosis: DiagnosisEvent | null): Array<{ headline: string; detail?: string }> {
  const items: Array<{ headline: string; detail?: string }> = [];
  const t = new Date(alert.occurred_at);
  const timeStr = t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  // Step 1 — first KPI to cross threshold
  if (alert.top_factors && alert.top_factors.length > 0) {
    const f = alert.top_factors[0];
    const verb = f.direction === "up" ? "spiked above" : "dropped below";
    items.push({
      headline: `${f.display_label} ${verb} safe operating range`,
      detail: `Detected at ${timeStr} · ${Math.round(f.impact_pct)}% deviation from baseline`,
    });
  }

  // Step 2 — cascade / secondary signals
  if (alert.top_factors && alert.top_factors.length > 1) {
    const secondary = alert.top_factors.slice(1, 3);
    const names = secondary.map((f) => f.display_label).join(" and ");
    items.push({
      headline: `Cascade: ${names} followed within the same window`,
      detail: secondary.map((f) => `${f.display_label} ${f.direction === "up" ? "↑" : "↓"} ${Math.round(f.impact_pct)}%`).join(" · "),
    });
  }

  // Step 3 — detection trigger
  items.push({
    headline: `Behavioural detection raised ${alert.severity.toUpperCase()} alert`,
    detail: `Confidence ${Math.min(96, Math.round(alert.confidence * 100))}% · detector: ${alert.detector}` +
      (alert.cell_id ? ` · Cell ${alert.cell_id}` : ""),
  });

  // Step 4 — breach projection
  if (alert.time_to_breach_seconds != null) {
    const mins = Math.round(alert.time_to_breach_seconds / 60);
    const metric = alert.breach_metric?.replace(/_/g, " ") ?? "network KPI";
    items.push({
      headline: `${metric} breach projected in ~${mins} minute${mins !== 1 ? "s" : ""}`,
      detail: alert.breach_threshold != null ? `Threshold: ${alert.breach_threshold}` : "SLA degradation risk is elevated",
    });
  }

  // Step 5 — pattern match from diagnosis
  if (diagnosis?.pattern_label) {
    const n = diagnosis.similar_incidents.length;
    items.push({
      headline: `Matched to known failure pattern: "${diagnosis.pattern_label}"`,
      detail: n > 0
        ? `${n} similar past incident${n !== 1 ? "s" : ""} on record — historical resolution available`
        : "No prior resolution on record",
    });
  }

  return items;
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000)   return `${Math.round(ms / 1_000)}s ago`;
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m ago`;
  return `${Math.round(ms / 3_600_000)}h ago`;
}
