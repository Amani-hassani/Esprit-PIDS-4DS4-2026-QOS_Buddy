"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Cpu,
  FlaskConical,
  Gauge,
  Network,
  Play,
  Radio,
  Timer,
  TrendingDown,
  Waves,
  Zap,
} from "lucide-react";
import { RoleGate, useAuth } from "@/components/providers/auth-provider";
import { useLive } from "@/lib/store";
import { cn } from "@/lib/utils";

const GATEWAY_URL =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8080";

type ScenarioId =
  | "latency_storm"
  | "jitter_surge"
  | "packet_loss"
  | "cpu_saturation"
  | "throughput_collapse"
  | "bgp_flap";

interface Scenario {
  id: ScenarioId;
  title: string;
  description: string;
  icon: any;
  defaultDuration: number;
  expectedSeverity: "medium" | "high" | "critical";
  expectedKpi: string;
}

const SCENARIOS: Scenario[] = [
  {
    id: "latency_storm",
    title: "Latency Storm",
    description:
      "Latency ramps from baseline to ~250 ms over the burst — drives MOS down and triggers behavioural detection.",
    icon: Timer,
    defaultDuration: 25,
    expectedSeverity: "high",
    expectedKpi: "latency_ms",
  },
  {
    id: "jitter_surge",
    title: "Jitter Surge",
    description:
      "Jitter climbs to ~60 ms simulating intermittent congestion. MOS estimate degrades and detection picks it up quickly.",
    icon: Waves,
    defaultDuration: 20,
    expectedSeverity: "medium",
    expectedKpi: "jitter_ms",
  },
  {
    id: "packet_loss",
    title: "Packet Loss",
    description:
      "Packet loss spikes to ~8% with retransmits climbing. Threshold detector fires almost immediately.",
    icon: Network,
    defaultDuration: 20,
    expectedSeverity: "critical",
    expectedKpi: "packet_loss_pct",
  },
  {
    id: "cpu_saturation",
    title: "CPU Saturation",
    description:
      "Host CPU climbs past 90%, memory tracks alongside. Diagnostic agent should match host_saturation pattern.",
    icon: Cpu,
    defaultDuration: 25,
    expectedSeverity: "medium",
    expectedKpi: "cpu_pct",
  },
  {
    id: "throughput_collapse",
    title: "Throughput Collapse",
    description:
      "Throughput drops from 320 Mbps toward ~20 Mbps. Forecaster should project breach within seconds.",
    icon: TrendingDown,
    defaultDuration: 25,
    expectedSeverity: "high",
    expectedKpi: "throughput_mbps",
  },
  {
    id: "bgp_flap",
    title: "BGP Flap",
    description:
      "Intermittent connectivity — KPIs alternate between healthy and severely degraded. Behavioural detection should win over thresholds.",
    icon: Radio,
    defaultDuration: 30,
    expectedSeverity: "critical",
    expectedKpi: "anomaly_score",
  },
];

interface RunStatus {
  scenario: ScenarioId;
  duration: number;
  startedAt: number;
}

export default function ScenarioLabPage() {
  return (
    <RoleGate allow={["site_admin"]}>
      <ScenarioLabPageContent />
    </RoleGate>
  );
}

function ScenarioLabPageContent() {
  const { token, role, demoMode } = useAuth();
  const effectiveToken = demoMode ? `demo:${role}` : token;
  const [running, setRunning] = useState<RunStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const alerts = useLive((s) => s.alerts);

  // role gate — also enforced server-side
  const allowed = role === "site_admin";

  // tick every 250ms while running so the progress bar updates
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setTick((t) => t + 1), 250);
    return () => clearInterval(id);
  }, [running]);

  const elapsed = running ? (Date.now() - running.startedAt) / 1000 : 0;
  const progressPct = running
    ? Math.min(100, Math.max(0, (elapsed / running.duration) * 100))
    : 0;

  // count chaos-induced alerts that arrived during/after the burst
  const reactionAlerts = useMemo(() => {
    if (!running && !lastResult) return [];
    const since = (running?.startedAt ?? 0) - 1000;
    return alerts.filter((a) => new Date(a.occurred_at).getTime() >= since);
  }, [alerts, running, lastResult, tick]);

  async function inject(s: Scenario) {
    if (!effectiveToken || running) return;
    setError(null);
    setLastResult(null);
    const startedAt = Date.now();
    setRunning({
      scenario: s.id,
      duration: s.defaultDuration,
      startedAt,
    });
    try {
      const res = await fetch(`${GATEWAY_URL}/api/chaos/inject`, {
        method: "POST",
        headers: {
          authorization: `Bearer ${effectiveToken}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({
          scenario: s.id,
          cell_id: "C1",
          duration_seconds: s.defaultDuration,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`${res.status} ${text}`);
      }
      const json = await res.json();
      setLastResult(
        `Injected ${json.samples_published} synthetic samples · audit ${String(
          json.audit_hash,
        ).slice(0, 12)}…`,
      );
    } catch (e: any) {
      setError(e?.message ?? "injection failed");
    } finally {
      setRunning(null);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Scenario Lab
          </h1>
          <p className="text-sm text-ink-2">
            Inject realistic incident scenarios into the synthesis pipeline.
            Each burst publishes synthetic{" "}
            <span className="font-mono">qos.metrics.raw</span> samples that the
            rest of the agents react to end-to-end.
          </p>
        </div>
        <ScenarioWatermark />
      </header>

      {!allowed && (
        <div className="glass rounded-xl border border-warn/30 bg-warn-soft/30 p-4 text-sm text-warn">
          Your role does not permit injection. Site admin or AI engineer
          required.
        </div>
      )}

      <RunStatusBanner
        running={running}
        progressPct={progressPct}
        lastResult={lastResult}
        error={error}
      />

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {SCENARIOS.map((s) => (
          <ScenarioCard
            key={s.id}
            scenario={s}
            disabled={!allowed || running !== null}
            onRun={() => inject(s)}
            isRunning={running?.scenario === s.id}
          />
        ))}
      </section>

      {reactionAlerts.length > 0 && (
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-medium text-ink-1">
              Pipeline reaction
            </h2>
            <span className="text-xs text-ink-2">
              {reactionAlerts.length} alert
              {reactionAlerts.length === 1 ? "" : "s"} since last injection
            </span>
          </div>
          <div className="glass rounded-xl p-3">
            <ul className="divide-y divide-line-subtle">
              {reactionAlerts.slice(0, 6).map((a) => (
                <li
                  key={a.event_id}
                  className="flex items-start gap-3 px-2 py-2 text-sm"
                >
                  <span
                    className={cn(
                      "mt-1 inline-block h-2 w-2 rounded-full",
                      a.severity === "critical" || a.severity === "high"
                        ? "bg-bad"
                        : a.severity === "medium"
                          ? "bg-warn"
                          : "bg-info",
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-ink-0">
                        {a.display_label}
                      </span>
                      <span className="rounded bg-bg-2 px-1.5 py-0.5 text-[11px] text-ink-2">
                        {a.detector}
                      </span>
                    </div>
                    <div className="text-[11px] text-ink-3">
                      {a.cell_id ? `Cell ${a.cell_id} · ` : ""}
                      {new Date(a.occurred_at).toLocaleTimeString()} · confidence{" "}
                      {Math.min(96, Math.round(a.confidence * 100))}%
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}
    </div>
  );
}

function ScenarioWatermark() {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-warn/40 bg-warn-soft/40 px-3 py-1.5 text-xs text-warn">
      <FlaskConical className="h-3.5 w-3.5" />
      <span className="uppercase tracking-wide">Scenario lab</span>
    </div>
  );
}

function RunStatusBanner({
  running,
  progressPct,
  lastResult,
  error,
}: {
  running: RunStatus | null;
  progressPct: number;
  lastResult: string | null;
  error: string | null;
}) {
  if (running) {
    const scenario = SCENARIOS.find((s) => s.id === running.scenario);
    const remaining = Math.max(
      0,
      running.duration - (Date.now() - running.startedAt) / 1000,
    );
    return (
      <div className="glass rounded-xl border border-cy/30 bg-cy-soft/20 p-4">
        <div className="mb-2 flex items-center gap-2 text-sm">
          <Zap className="h-4 w-4 text-cy animate-pulse" />
          <span className="font-medium text-ink-0">
            Injecting {scenario?.title ?? running.scenario}
          </span>
          <span className="ml-auto font-mono text-xs text-ink-2">
            ~{Math.ceil(remaining)}s remaining
          </span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-2">
          <div
            className="h-full rounded-full bg-cy transition-all"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <div className="mt-2 text-[11px] text-ink-3">
          Watch Detection, Forecast and Optimization tabs — alerts and proposed
          actions should arrive within seconds.
        </div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-xl border border-bad/30 bg-bad-soft/30 p-3 text-sm text-bad">
        <AlertTriangle className="mr-2 inline h-4 w-4" />
        {error}
      </div>
    );
  }
  if (lastResult) {
    return (
      <div className="rounded-xl border border-ok/30 bg-ok-soft/30 p-3 text-sm text-ok">
        <Gauge className="mr-2 inline h-4 w-4" />
        {lastResult}
      </div>
    );
  }
  return null;
}

function ScenarioCard({
  scenario,
  disabled,
  isRunning,
  onRun,
}: {
  scenario: Scenario;
  disabled: boolean;
  isRunning: boolean;
  onRun: () => void;
}) {
  const Icon = scenario.icon;
  const sevTone =
    scenario.expectedSeverity === "critical" || scenario.expectedSeverity === "high"
      ? "bg-bad-soft text-bad"
      : "bg-warn-soft text-warn";
  return (
    <div className="glass flex flex-col rounded-xl p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="grid h-9 w-9 place-items-center rounded-lg bg-bg-2 text-ink-0">
          <Icon className="h-4 w-4" />
        </span>
        <div className="flex-1">
          <div className="font-medium text-ink-0">{scenario.title}</div>
          <div className="text-[11px] text-ink-3">{scenario.expectedKpi}</div>
        </div>
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-[11px] uppercase tracking-wide",
            sevTone,
          )}
        >
          {scenario.expectedSeverity}
        </span>
      </div>
      <p className="flex-1 text-sm text-ink-1">{scenario.description}</p>
      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="text-[11px] text-ink-3">
          {scenario.defaultDuration}s burst · cell C1
        </span>
        <button
          onClick={onRun}
          disabled={disabled}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition",
            disabled
              ? "cursor-not-allowed border border-line-subtle bg-bg-2 text-ink-3"
              : isRunning
                ? "bg-cy-soft text-cy"
                : "bg-cy text-bg-0 hover:opacity-90",
          )}
        >
          <Play className="h-3 w-3" />
          {isRunning ? "Running…" : "Inject"}
        </button>
      </div>
    </div>
  );
}
