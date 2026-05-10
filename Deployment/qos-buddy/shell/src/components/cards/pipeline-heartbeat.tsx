"use client";

import { useMemo } from "react";
import { Activity, Brain, Cpu, Eye, ShieldCheck, TrendingUp } from "lucide-react";
import { useLive } from "@/lib/store";
import { cn } from "@/lib/utils";

const STALE_WARN_S = 30;
const STALE_DEAD_S = 90;

interface AgentDef {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
}

const AGENTS: AgentDef[] = [
  { id: "monitoring",   label: "Monitoring",   icon: Eye,         description: "Live collector to qos.metrics.raw" },
  { id: "detection",    label: "Detection",    icon: Activity,    description: "Live KPI and behaviour alerts" },
  { id: "prediction",   label: "Prediction",   icon: TrendingUp,  description: "Time-to-breach forecasts" },
  { id: "diagnostic",   label: "Diagnostic",   icon: Brain,       description: "Root-cause and similar incidents" },
  { id: "optimization", label: "Optimization", icon: ShieldCheck, description: "Policy-gated remediation actions" },
  { id: "mlops",        label: "MLOps",        icon: Cpu,         description: "Model health, audit trail, and lesson memory" },
];

export function PipelineHeartbeat() {
  const metrics    = useLive((s) => s.metrics);
  const alerts     = useLive((s) => s.alerts);
  const diagnoses  = useLive((s) => s.diagnoses);
  const proposed   = useLive((s) => s.proposedActions);
  const executed   = useLive((s) => s.executedActions);
  const insights   = useLive((s) => s.insights);
  const audits     = useLive((s) => s.auditEvents);

  const lastSeen = useMemo<Record<string, number>>(() => {
    const ts = (iso?: string | null) => (iso ? new Date(iso).getTime() : 0);
    const latest = (arr: { occurred_at?: string }[]) =>
      arr.reduce((best, x) => Math.max(best, ts(x.occurred_at)), 0);

    const detectionAlerts = alerts.filter((a) => a.detector !== "forecast");
    const predictionAlerts = alerts.filter((a) => a.detector === "forecast");

    return {
      monitoring:   latest(metrics),
      detection:    latest(detectionAlerts),
      prediction:   latest(predictionAlerts),
      diagnostic:   latest(Object.values(diagnoses)),
      optimization: Math.max(latest(proposed), latest(executed)),
      mlops:        Math.max(latest(Object.values(insights)), latest(audits)),
    };
  }, [metrics, alerts, diagnoses, proposed, executed, insights, audits]);

  const now = Date.now();
  const activeCount = AGENTS.filter((a) => {
    const age = lastSeen[a.id] ? (now - lastSeen[a.id]) / 1000 : Infinity;
    return age < STALE_DEAD_S;
  }).length;

  return (
    <div className="glass rounded-xl p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-ink-1">Agent and MLOps heartbeat</h3>
        <span className="flex items-center gap-1.5 text-xs text-ink-2">
          <Cpu className="h-3.5 w-3.5" />
          {activeCount}
          <span>/ {AGENTS.length} active</span>
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        {AGENTS.map((agent) => {
          const last = lastSeen[agent.id];
          const ageSec = last ? (now - last) / 1000 : Infinity;
          const tone =
            !last || ageSec > STALE_DEAD_S ? "dead"
            : ageSec > STALE_WARN_S ? "warn"
            : "ok";
          const Icon = agent.icon;

          return (
            <div
              key={agent.id}
              className={cn(
                "group flex flex-col items-center gap-1.5 rounded-lg border p-3 text-center transition",
                tone === "ok"   && "border-ok/30 bg-ok-soft/30",
                tone === "warn" && "border-warn/30 bg-warn-soft/30",
                tone === "dead" && "border-line-subtle bg-bg-2/40",
              )}
              title={agent.description}
            >
              <div
                className={cn(
                  "grid h-8 w-8 place-items-center rounded-lg",
                  tone === "ok"   && "bg-ok-soft text-ok",
                  tone === "warn" && "bg-warn-soft text-warn",
                  tone === "dead" && "bg-bg-3 text-ink-3",
                )}
              >
                <Icon className="h-4 w-4" />
              </div>

              <span
                className={cn(
                  "text-xs font-medium leading-tight",
                  tone === "ok"   && "text-ok",
                  tone === "warn" && "text-warn",
                  tone === "dead" && "text-ink-3",
                )}
              >
                {agent.label}
              </span>

              <span className="text-[10px] text-ink-3 leading-tight">
                {!last ? "no data"
                  : ageSec < 5  ? "just now"
                  : ageSec < 60 ? `${Math.round(ageSec)}s ago`
                  : `${Math.round(ageSec / 60)}m ago`}
              </span>

              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  tone === "ok"   && "bg-ok animate-pulse",
                  tone === "warn" && "bg-warn animate-pulse",
                  tone === "dead" && "bg-ink-3",
                )}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
