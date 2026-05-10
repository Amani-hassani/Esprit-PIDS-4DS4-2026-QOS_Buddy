"use client";

import { useMemo } from "react";
import { useLive } from "@/lib/store";
import { cn } from "@/lib/utils";

/**
 * Animated 5-stage Observe → Analyze → Decide → Act → Learn loop.
 * Each node lights up when there is a recent event of its kind in the live store.
 *
 * "Recent" = last 90 seconds, which keeps the loop visibly alive without flapping.
 */
const STAGES = [
  { id: "observe", label: "Observe", description: "Live KPIs from monitoring" },
  { id: "analyze", label: "Analyze", description: "Anomalies and forecasts" },
  { id: "decide", label: "Decide", description: "Recommended action with safety checks" },
  { id: "act", label: "Act", description: "Guarded change applied" },
  { id: "learn", label: "Learn", description: "Lesson recorded into the library" },
] as const;

export function OadalLoop() {
  const metrics = useLive((s) => s.metrics);
  const alerts = useLive((s) => s.alerts);
  const insights = useLive((s) => s.insights);
  const proposed = useLive((s) => s.proposedActions);
  const executed = useLive((s) => s.executedActions);

  const active = useMemo(() => {
    const now = Date.now();
    const recent = (iso?: string) => {
      if (!iso) return false;
      return now - new Date(iso).getTime() < 90_000;
    };
    return {
      observe: recent(metrics[metrics.length - 1]?.occurred_at),
      analyze: alerts.some((a) => recent(a.occurred_at)),
      decide: proposed.some((p) => recent(p.occurred_at)),
      act: executed.some((e) => recent(e.occurred_at)),
      learn: Object.values(insights).some((i) => recent(i.occurred_at)),
    } as Record<(typeof STAGES)[number]["id"], boolean>;
  }, [metrics, alerts, proposed, executed, insights]);

  return (
    <div className="glass rounded-xl p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-ink-1">Pipeline activity</h3>
        <span className="text-xs text-ink-2">Live last 90s</span>
      </div>

      <div className="relative">
        <svg viewBox="0 0 800 120" className="w-full">
          <defs>
            <linearGradient id="loop-grad" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor="hsl(var(--cy))" stopOpacity="0.6" />
              <stop offset="100%" stopColor="hsl(var(--vio))" stopOpacity="0.6" />
            </linearGradient>
          </defs>
          <line
            x1={50}
            y1={60}
            x2={750}
            y2={60}
            stroke="url(#loop-grad)"
            strokeWidth={2}
            strokeDasharray="6 6"
          />
        </svg>

        <div className="absolute inset-0 flex items-center justify-between px-6">
          {STAGES.map((s, i) => (
            <Node
              key={s.id}
              index={i}
              label={s.label}
              description={s.description}
              active={active[s.id]}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function Node({
  index,
  label,
  description,
  active,
}: {
  index: number;
  label: string;
  description: string;
  active: boolean;
}) {
  return (
    <div className="flex flex-col items-center gap-1.5">
      <span
        className={cn(
          "grid h-10 w-10 place-items-center rounded-full border-2 font-mono text-xs font-semibold transition",
          active
            ? "border-cy bg-cy-soft text-cy ring-glow"
            : "border-line-subtle bg-bg-2 text-ink-3",
        )}
      >
        {index + 1}
      </span>
      <span
        className={cn(
          "text-xs font-medium",
          active ? "text-ink-0" : "text-ink-2",
        )}
      >
        {label}
      </span>
      <span className="hidden md:block max-w-[120px] text-center text-[10px] leading-tight text-ink-3">
        {description}
      </span>
    </div>
  );
}
