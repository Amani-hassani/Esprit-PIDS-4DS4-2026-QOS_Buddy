"use client";

import { useMemo } from "react";
import {
  Activity,
  ArrowRight,
  Brain,
  Eye,
  Lightbulb,
  ShieldCheck,
} from "lucide-react";
import { useLive } from "@/lib/store";
import { cn } from "@/lib/utils";
import type {
  AlertEvent,
  DiagnosisEvent,
  InsightEvent,
  MetricEvent,
  ProposedActionEvent,
} from "@/lib/types";

type NodeStatus = "active" | "propagating" | "idle";

interface DagNode {
  id: string;
  label: string;
  agent: string;
  icon: React.ComponentType<{ className?: string }>;
  status: NodeStatus;
  primary: string;
  secondary: string;
}

function nodeStatus(hasData: boolean, upstreamActive: boolean): NodeStatus {
  if (hasData) return "active";
  if (upstreamActive) return "propagating";
  return "idle";
}

export function CausalDag({
  alert,
}: {
  alert: AlertEvent | null;
}) {
  const metrics   = useLive((s) => s.metrics);
  const diagnoses = useLive((s) => s.diagnoses);
  const insights  = useLive((s) => s.insights);
  const proposed  = useLive((s) => s.proposedActions);

  const nodes = useMemo<DagNode[]>(() => {
    // Monitoring node — latest anomaly metric
    const anomMetric: MetricEvent | undefined = [...metrics]
      .reverse()
      .find((m) => m.anomaly_flag);
    const monitoringActive = !!anomMetric;
    const monitoringNode: DagNode = {
      id: "monitoring",
      label: "Monitoring",
      agent: "monitoring-agent",
      icon: Eye,
      status: monitoringActive ? "active" : "idle",
      primary: anomMetric
        ? `score ${(anomMetric.anomaly_score ?? 0).toFixed(2)}`
        : "—",
      secondary: anomMetric ? `cell ${anomMetric.cell_id ?? "n/a"}` : "no anomaly",
    };

    // Detection node
    const detectionActive = !!alert;
    const detectionNode: DagNode = {
      id: "detection",
      label: "Detection",
      agent: "detection-agent",
      icon: Activity,
      status: nodeStatus(detectionActive, monitoringActive),
      primary: alert ? alert.severity : "—",
      secondary: alert
        ? `${Math.min(96, Math.round(alert.confidence * 100))}% confidence`
        : "no alert",
    };

    // Diagnostic node
    const diag: DiagnosisEvent | undefined = alert
      ? diagnoses[alert.correlation_id]
      : undefined;
    const diagnosticNode: DagNode = {
      id: "diagnostic",
      label: "Diagnostic",
      agent: "diagnostic-agent",
      icon: Brain,
      status: nodeStatus(!!diag, detectionActive),
      primary: diag ? diag.pattern_label : "—",
      secondary: diag
        ? `${diag.similar_incidents.length} similar case${diag.similar_incidents.length === 1 ? "" : "s"}`
        : "awaiting pattern",
    };

    // Insight node
    const insight: InsightEvent | undefined = alert
      ? insights[alert.correlation_id]
      : undefined;
    const insightNode: DagNode = {
      id: "insight",
      label: "Insight",
      agent: "insight-agent",
      icon: Lightbulb,
      status: nodeStatus(!!insight, !!diag),
      primary: insight
        ? `${Math.min(96, Math.round(insight.confidence * 100))}% conf`
        : "—",
      secondary: insight
        ? `${insight.citations.length} citation${insight.citations.length === 1 ? "" : "s"}`
        : "awaiting lesson",
    };

    // Optimization node — find the action closest to this incident
    const action: ProposedActionEvent | undefined = alert
      ? proposed.find(
          (p) =>
            p.correlation_id === alert.correlation_id ||
            p.cell_id === alert.cell_id,
        ) ?? proposed[0]
      : proposed[0];
    const optimizationNode: DagNode = {
      id: "optimization",
      label: "Optimization",
      agent: "optimization-agent",
      icon: ShieldCheck,
      status: nodeStatus(!!action, !!insight),
      primary: action ? action.title.slice(0, 22) + (action.title.length > 22 ? "…" : "") : "—",
      secondary: action ? `${action.verdict} · ${action.risk_level} risk` : "no action yet",
    };

    return [monitoringNode, detectionNode, diagnosticNode, insightNode, optimizationNode];
  }, [metrics, alert, diagnoses, insights, proposed]);

  const diagnosis = alert ? diagnoses[alert.correlation_id] : undefined;
  const edges = diagnosis?.causal_edges ?? [];

  return (
    <div className="glass rounded-xl p-4">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-medium text-ink-1">Causal chain</h3>
        <span className="text-xs text-ink-2">
          {nodes.filter((n) => n.status === "active").length} / {nodes.length} stages resolved
        </span>
      </div>

      <div className="flex items-stretch gap-1">
        {nodes.map((node, i) => (
          <div key={node.id} className="flex min-w-0 flex-1 items-center gap-1">
            <DagNodeCard node={node} />
            {i < nodes.length - 1 && (
              <ArrowConnector
                active={node.status === "active"}
                propagating={nodes[i + 1].status === "propagating"}
                strength={edges[i]?.strength}
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function DagNodeCard({ node }: { node: DagNode }) {
  const Icon = node.icon;

  const containerCls = cn(
    "flex flex-1 flex-col gap-1.5 rounded-lg border p-3 min-w-0 transition",
    node.status === "active"    && "border-ok/30 bg-ok-soft/20",
    node.status === "propagating" && "border-warn/30 bg-warn-soft/20",
    node.status === "idle"      && "border-line-subtle bg-bg-2/30",
  );

  const iconCls = cn(
    "grid h-7 w-7 shrink-0 place-items-center rounded-md",
    node.status === "active"    && "bg-ok-soft text-ok",
    node.status === "propagating" && "bg-warn-soft text-warn",
    node.status === "idle"      && "bg-bg-3 text-ink-3",
  );

  const primaryCls = cn(
    "truncate font-mono text-xs font-semibold tabular-nums",
    node.status === "active"    && "text-ok",
    node.status === "propagating" && "text-warn",
    node.status === "idle"      && "text-ink-3",
  );

  return (
    <div className={containerCls}>
      <div className="flex items-center gap-1.5">
        <div className={iconCls}>
          <Icon className="h-3.5 w-3.5" />
        </div>
        <span className="truncate text-[11px] font-medium text-ink-1">
          {node.label}
        </span>
      </div>
      <div className={primaryCls}>{node.primary}</div>
      <div className="truncate text-[10px] leading-tight text-ink-3">
        {node.secondary}
      </div>
      <span
        className={cn(
          "h-1 w-full rounded-full",
          node.status === "active"    && "bg-ok",
          node.status === "propagating" && "bg-warn animate-pulse",
          node.status === "idle"      && "bg-bg-3",
        )}
      />
    </div>
  );
}

function ArrowConnector({
  active,
  propagating,
  strength,
}: {
  active: boolean;
  propagating: boolean;
  strength?: number;
}) {
  const opacity = strength == null ? 1 : 0.3 + strength * 0.7;
  return (
    <div className="flex shrink-0 flex-col items-center gap-0.5" style={{ opacity }}>
      {strength != null && (
        <span className="font-mono text-[9px] leading-none text-ink-3">{strength.toFixed(2)}</span>
      )}
      <ArrowRight
        className={cn(
          "h-3.5 w-3.5",
          active      && "text-ok",
          propagating && "text-warn animate-pulse",
          !active && !propagating && "text-ink-3",
        )}
      />
    </div>
  );
}
