"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Info,
  Layers,
  Sparkles,
} from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { useLive } from "@/lib/store";
import { cn } from "@/lib/utils";
import { askAi } from "@/lib/ai";
import type { AlertEvent, Severity, TopFactor } from "@/lib/types";

interface AlertGroup {
  head: AlertEvent;
  related: AlertEvent[]; // includes head
}

const SEVERITY_TONE: Record<
  Severity,
  { bg: string; text: string; icon: React.ComponentType<{ className?: string }> }
> = {
  info:     { bg: "bg-info-soft", text: "text-info", icon: Info },
  low:      { bg: "bg-info-soft", text: "text-info", icon: Info },
  medium:   { bg: "bg-warn-soft", text: "text-warn", icon: AlertTriangle },
  high:     { bg: "bg-bad-soft",  text: "text-bad",  icon: AlertCircle },
  critical: { bg: "bg-bad-soft",  text: "text-bad",  icon: AlertCircle },
};

const SEV_RANK: Record<Severity, number> = {
  info: 0, low: 1, medium: 2, high: 3, critical: 4,
};

const BUCKET_MS = 60_000; // one anomaly logged per 60-second window

export function IncidentStream() {
  const alerts = useLive((s) => s.alerts);
  // Selection is keyed on correlation_id (stable across re-groupings), not
  // event_id (which can change when a more-severe alert overtakes the head
  // inside the same 60s bucket). This prevents snap-close on new alerts.
  const [selectedCorr, setSelectedCorr] = useState<string | null>(null);
  const [initializing, setInitializing] = useState(true);

  useEffect(() => {
    const id = window.setTimeout(() => setInitializing(false), 2000);
    return () => window.clearTimeout(id);
  }, []);

  // Group concurrent breaches by correlation_id, then throttle so the operator
  // sees at most ONE incident per 60s window (the most-severe head wins).
  const groups = useMemo<AlertGroup[]>(() => {
    const byCorr = new Map<string, AlertEvent[]>();
    for (const a of alerts) {
      if (a.detector === "forecast") continue;
      const key = a.correlation_id ?? a.event_id;
      const arr = byCorr.get(key);
      if (arr) arr.push(a); else byCorr.set(key, [a]);
    }
    const allGroups: AlertGroup[] = Array.from(byCorr.values()).map((arr) => {
      arr.sort((x, y) => {
        const s = (SEV_RANK[y.severity] ?? 0) - (SEV_RANK[x.severity] ?? 0);
        if (s !== 0) return s;
        return new Date(y.occurred_at).getTime() - new Date(x.occurred_at).getTime();
      });
      return { head: arr[0], related: arr };
    });

    // 60-second bucket throttle
    const byBucket = new Map<number, AlertGroup>();
    for (const g of allGroups) {
      const t = new Date(g.head.occurred_at).getTime();
      const bucket = Math.floor(t / BUCKET_MS);
      const ex = byBucket.get(bucket);
      if (!ex) {
        byBucket.set(bucket, g);
        continue;
      }
      const exRank = SEV_RANK[ex.head.severity] ?? 0;
      const newRank = SEV_RANK[g.head.severity] ?? 0;
      if (newRank > exRank ||
          (newRank === exRank && t > new Date(ex.head.occurred_at).getTime())) {
        byBucket.set(bucket, g);
      }
    }

    return Array.from(byBucket.values()).sort(
      (a, b) => new Date(b.head.occurred_at).getTime() - new Date(a.head.occurred_at).getTime(),
    );
  }, [alerts]);

  return (
    <div className="glass flex h-full flex-col rounded-xl p-4">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-medium text-ink-1">Incident stream</h3>
          <p className="mt-0.5 text-[11px] text-ink-3">
            One anomaly per 60s · click a row to see KPIs that informed it & the AI explanation
          </p>
        </div>
        <span className="shrink-0 text-xs text-ink-2">
          {groups.length} logged · {alerts.filter((a) => a.detector !== "forecast").length} raw
        </span>
      </div>

      {alerts.length === 0 && initializing ? (
        <div className="space-y-2">
          <AlertCardSkeleton />
          <AlertCardSkeleton />
          <AlertCardSkeleton />
        </div>
      ) : groups.length === 0 ? (
        <EmptyState
          icon={<Info className="h-8 w-8 text-ink-3" />}
          title="No anomalies detected"
          body="The detection agent is running. Anomalies will appear here at most once every 60 seconds."
        />
      ) : (
        <ul className="flex-1 space-y-2 overflow-y-auto pr-1" style={{ maxHeight: 560 }}>
          {groups.slice(0, 30).map((g) => {
            const corr = g.head.correlation_id ?? g.head.event_id;
            return (
              <IncidentItem
                key={corr}
                group={g}
                selected={corr === selectedCorr}
                onToggle={() =>
                  setSelectedCorr((prev) => (prev === corr ? null : corr))
                }
              />
            );
          })}
        </ul>
      )}
    </div>
  );
}

function IncidentItem({
  group,
  selected,
  onToggle,
}: {
  group: AlertGroup;
  selected: boolean;
  onToggle: () => void;
}) {
  const alert = group.head;
  const concurrentCount = group.related.length;
  const tone = SEVERITY_TONE[alert.severity] ?? SEVERITY_TONE.medium;
  const Icon = tone.icon;
  const incId = formatIncId(alert);

  return (
    <li
      className={cn(
        "rounded-lg border bg-bg-2/40 transition-colors",
        selected ? "border-cy" : "border-line-subtle hover:border-line",
      )}
    >
      {/* ── clickable header ── */}
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start gap-3 p-3 text-left"
      >
        <span
          className={cn(
            "mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md",
            tone.bg,
            tone.text,
          )}
        >
          <Icon className="h-3.5 w-3.5" />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-ink-0">
              {alert.display_label}
            </span>
            {concurrentCount > 1 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-vio-soft/30 px-1.5 py-0.5 text-[10px] font-medium text-vio">
                <Layers className="h-2.5 w-2.5" />
                {concurrentCount} concurrent
              </span>
            )}
            <span className="ml-auto shrink-0 text-xs text-ink-2">
              {timeAgo(alert.occurred_at)}
            </span>
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-ink-2">
            <span className="font-mono text-[10px] text-ink-3">{incId}</span>
            {alert.cell_id && <span>Cell {alert.cell_id}</span>}
            <span>·</span>
            <span className="capitalize">{alert.severity}</span>
            <span>·</span>
            <span>Confidence {Math.min(96, Math.round(alert.confidence * 100))}%</span>
            <span>·</span>
            <span>Detector {alert.detector}</span>
          </div>

          {/* peek of top factors so the operator can scan quickly */}
          {(alert.top_factors?.length ?? 0) > 0 && !selected && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {alert.top_factors!.slice(0, 3).map((f) => (
                <span
                  key={f.display_label}
                  className="inline-flex items-center gap-1 rounded-full border border-line-subtle bg-bg-2 px-2 py-0.5 text-[10px] text-ink-1"
                >
                  <span className={f.direction === "down" ? "text-warn" : "text-bad"}>
                    {f.direction === "down" ? "↓" : "↑"}
                  </span>
                  <span>{f.display_label}</span>
                  <span className="text-ink-3">{Math.round(f.impact_pct)}%</span>
                </span>
              ))}
            </div>
          )}
        </div>

        {selected ? (
          <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-cy" />
        ) : (
          <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-ink-3" />
        )}
      </button>

      {/* ── expanded detail ── */}
      {selected && <IncidentDetail group={group} />}
    </li>
  );
}

function IncidentDetail({ group }: { group: AlertGroup }) {
  const alert = group.head;
  const concurrentCount = group.related.length;

  return (
    <div className="space-y-3 border-t border-line-subtle px-3 pb-4 pt-3">
      {/* breach warning */}
      {alert.time_to_breach_seconds != null && (
        <div className="flex items-center gap-2 rounded-md bg-bad-soft/30 px-3 py-2">
          <AlertCircle className="h-4 w-4 shrink-0 text-bad" />
          <span className="text-xs text-bad">
            {formatKpiLabel(alert.breach_metric ?? "")} approaching breach in{" "}
            ~{Math.round(alert.time_to_breach_seconds / 60)} min
            {alert.breach_threshold != null &&
              ` — threshold ${alert.breach_threshold}`}
          </span>
        </div>
      )}

      {/* AI explanation — Qwen2.5 + RAG */}
      <AiExplanation alert={alert} />

      {/* contributing signals (KPIs that informed the decision) */}
      {(alert.top_factors?.length ?? 0) > 0 && (
        <div>
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-ink-3">
            KPIs that informed this detection
          </div>
          <ul className="space-y-2">
            {alert.top_factors!.slice(0, 6).map((f: TopFactor) => {
              const w = Math.min(100, Math.max(2, Math.round(f.impact_pct)));
              return (
                <li key={f.display_label} className="text-xs">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="text-ink-0">{f.display_label}</span>
                    <span className="font-mono text-ink-2">
                      {f.direction === "down" ? "↓" : "↑"}{" "}
                      {Math.round(f.impact_pct)}%
                    </span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-3">
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
        </div>
      )}

      {/* KPI snapshot at detection time */}
      {alert.monitoring_features &&
        Object.keys(alert.monitoring_features).length > 0 && (
          <div>
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-ink-3">
              Live KPI snapshot at detection
            </div>
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
              {Object.entries(alert.monitoring_features).map(([k, v]) => (
                <div
                  key={k}
                  className="flex items-center justify-between rounded-md bg-bg-2 px-2 py-1.5"
                >
                  <span className="text-[10px] text-ink-2">{formatKpiLabel(k)}</span>
                  <span className="font-mono text-[11px] text-ink-0">
                    {typeof v === "number" ? v.toFixed(2) : String(v)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

      {/* concurrent / related alerts in same correlation */}
      {concurrentCount > 1 && (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-ink-3">
            <Layers className="h-3 w-3" />
            Concurrent breaches in this incident
          </div>
          <ul className="space-y-1">
            {group.related
              .filter((a) => a.event_id !== alert.event_id)
              .slice(0, 6)
              .map((a) => {
                const t = SEVERITY_TONE[a.severity] ?? SEVERITY_TONE.medium;
                return (
                  <li
                    key={a.event_id}
                    className="flex items-center gap-2 rounded-md bg-bg-2 px-2 py-1.5 text-[11px]"
                  >
                    <span
                      className={cn(
                        "h-1.5 w-1.5 shrink-0 rounded-full",
                        t.text.replace("text-", "bg-"),
                      )}
                    />
                    <span className="truncate text-ink-1">{a.display_label}</span>
                    <span className="ml-auto font-mono text-[10px] text-ink-3">
                      {timeAgo(a.occurred_at)}
                    </span>
                  </li>
                );
              })}
          </ul>
        </div>
      )}

      {/* meta footer */}
      <div className="flex flex-wrap items-center gap-3 text-[10px] text-ink-3">
        <span>Detector: {alert.detector}</span>
        {alert.correlation_id && (
          <span>Correlation: {alert.correlation_id.slice(0, 8)}</span>
        )}
        <span>Logged at {new Date(alert.occurred_at).toLocaleTimeString()}</span>
      </div>
    </div>
  );
}

function AiExplanation({ alert }: { alert: AlertEvent }) {
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const cacheRef = useRef(new Map<string, string>());

  // Cache & re-fetch keyed on correlation_id (or event_id fallback). The head
  // alert object itself can change as new same-bucket alerts arrive; we don't
  // want to re-prompt the LLM each time.
  const cacheKey = alert.correlation_id ?? alert.event_id;

  useEffect(() => {
    let cancelled = false;
    const cached = cacheRef.current.get(cacheKey);
    if (cached) {
      setText(cached);
      setLoading(false);
      return;
    }
    setLoading(true);
    setText(null);
    const prompt = buildExplainPrompt(alert);
    askAi(
      prompt,
      {
        current_page: "/detection-prediction",
        cell_id: alert.cell_id ?? undefined,
        alert_id: alert.event_id,
      },
      buildFallbackExplanation(alert),
    ).then((answer) => {
      if (cancelled) return;
      cacheRef.current.set(cacheKey, answer);
      setText(answer);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cacheKey]);

  return (
    <div className="rounded-md border border-vio/30 bg-vio-soft/10 p-3">
      <div className="mb-1.5 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-widest text-vio">
        <Sparkles className="h-3 w-3" />
        AI explanation
        <span className="rounded-full border border-vio/30 bg-vio-soft/20 px-1.5 py-0.5 text-[9px] text-vio">
          QWEN2.5 · RAG
        </span>
        {loading && (
          <span className="inline-flex items-center gap-1">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-vio" />
            synthesizing
          </span>
        )}
      </div>
      <p className="text-xs leading-relaxed text-ink-1">
        {text ?? "Asking the analyst…"}
      </p>
    </div>
  );
}

function buildFallbackExplanation(alert: AlertEvent): string {
  const cell = alert.cell_id ?? "the fleet";
  const confidence = Math.min(96, Math.round(alert.confidence * 100));
  const factors = alert.top_factors?.slice(0, 3) ?? [];
  const driver = factors[0]?.display_label ?? "live KPI movement";
  const supporting = factors.slice(1).map((f) => f.display_label).join(" and ");
  return supporting
    ? `${alert.display_label} is active on ${cell}. ${driver} is the main driver, with ${supporting} confirming the pattern; confidence is ${confidence}%. Check the queued recommendation and validate KPI recovery on the live chart.`
    : `${alert.display_label} is active on ${cell}. ${driver} is driving the detection; confidence is ${confidence}%. Check the queued recommendation and validate KPI recovery on the live chart.`;
}

function buildExplainPrompt(alert: AlertEvent): string {
  const lines: string[] = [];
  lines.push(
    "You are a senior NOC analyst. In 2–3 short sentences (no bullets, no markdown) explain this anomaly to the operator: what is happening, which KPIs informed the detection, and the likely operational impact. End with one concrete next check.",
  );
  lines.push("");
  lines.push(`Anomaly: ${alert.display_label}`);
  lines.push(`Severity: ${alert.severity}`);
  lines.push(`Detector: ${alert.detector}`);
  if (alert.cell_id) lines.push(`Cell: ${alert.cell_id}`);
  lines.push(`Confidence: ${Math.min(96, Math.round(alert.confidence * 100))}%`);
  if (alert.top_factors?.length) {
    lines.push(
      `Top contributing factors: ${alert.top_factors
        .slice(0, 4)
        .map(
          (f) =>
            `${f.display_label} ${f.direction === "down" ? "↓" : "↑"} ${Math.round(f.impact_pct)}%`,
        )
        .join("; ")}.`,
    );
  }
  if (alert.monitoring_features && Object.keys(alert.monitoring_features).length > 0) {
    const kpiLine = Object.entries(alert.monitoring_features)
      .slice(0, 6)
      .map(
        ([k, v]) =>
          `${formatKpiLabel(k)}=${typeof v === "number" ? v.toFixed(2) : String(v)}`,
      )
      .join(", ");
    lines.push(`Live KPI snapshot: ${kpiLine}.`);
  }
  if (alert.time_to_breach_seconds != null) {
    lines.push(
      `Forecast: breach in ~${Math.round(alert.time_to_breach_seconds / 60)} min.`,
    );
  }
  return lines.join("\n");
}

function AlertCardSkeleton() {
  return (
    <div className="glass rounded-xl p-4 space-y-2 animate-pulse">
      <div className="h-4 w-1/3 rounded bg-bg-3" />
      <div className="h-3 w-2/3 rounded bg-bg-3" />
      <div className="h-3 w-1/2 rounded bg-bg-3" />
    </div>
  );
}

function formatIncId(alert: AlertEvent): string {
  const d = new Date(alert.occurred_at);
  const suffix = alert.event_id.slice(-4).toUpperCase();
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `INC-${d.getFullYear()}${mo}${day}-${suffix}`;
}

function formatKpiLabel(key: string): string {
  const map: Record<string, string> = {
    latency_ms:          "Latency (ms)",
    jitter_ms:           "Jitter (ms)",
    packet_loss_pct:     "Packet loss (%)",
    throughput_mbps:     "Throughput (Mbps)",
    mos_estimate:        "Voice quality (MOS)",
    bler_proxy_pct:      "Block error (%)",
    tcp_retransmit_rate: "Retransmit (%)",
    anomaly_score:       "Anomaly score",
  };
  return map[key] ?? key.replace(/_/g, " ");
}

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const diff = Math.max(0, Date.now() - then) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return `${Math.round(diff / 3600)}h ago`;
}
