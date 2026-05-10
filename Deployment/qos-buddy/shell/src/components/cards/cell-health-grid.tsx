"use client";

import { useMemo } from "react";
import { useLive } from "@/lib/store";
import { cn } from "@/lib/utils";
import { useAuth } from "@/components/providers/auth-provider";
import type { Severity } from "@/lib/types";

const ACTIVE_WINDOW_S = 300;

const SEV_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];

function worstSev(sevs: Severity[]): Severity | null {
  for (const s of SEV_ORDER) {
    if (sevs.includes(s)) return s;
  }
  return null;
}

const SEV_STYLES: Record<Severity, string> = {
  critical: "bg-bad/20 border-bad/50 text-bad",
  high:     "bg-warn/20 border-warn/50 text-warn",
  medium:   "bg-yellow-500/15 border-yellow-500/40 text-yellow-400",
  low:      "bg-blue-500/15 border-blue-500/40 text-blue-400",
  info:     "bg-ok-soft/30 border-ok/30 text-ok",
};

const SEV_PIP: Record<Severity, string> = {
  critical: "bg-bad animate-pulse",
  high:     "bg-warn animate-pulse",
  medium:   "bg-yellow-400 animate-pulse",
  low:      "bg-blue-400",
  info:     "bg-ok",
};

export function CellHealthGrid() {
  const metrics = useLive((s) => s.metrics);
  const alerts  = useLive((s) => s.alerts);
  const { preferences } = useAuth();
  const now     = Date.now();
  const focusCells = useMemo(
    () => new Set(preferences.cell_focus ?? []),
    [preferences.cell_focus],
  );

  const cells = useMemo(() => {
    const byCell = new Map<string, { latency: number | null; anomaly: boolean }>();
    for (const m of metrics) {
      if (!m.cell_id) continue;
      byCell.set(m.cell_id, {
        latency: m.latency_ms ?? null,
        anomaly: !!m.anomaly_flag,
      });
    }

    const alertsByCellSev = new Map<string, Severity[]>();
    for (const a of alerts) {
      if (!a.cell_id) continue;
      const ageMs = now - new Date(a.occurred_at).getTime();
      if (ageMs > ACTIVE_WINDOW_S * 1000) continue;
      const existing = alertsByCellSev.get(a.cell_id) ?? [];
      existing.push(a.severity);
      alertsByCellSev.set(a.cell_id, existing);
    }

    return Array.from(byCell.entries())
      .map(([id, stat]) => {
        const sevs = alertsByCellSev.get(id) ?? [];
        const sev = worstSev(sevs) ?? (stat.anomaly ? "medium" : "info");
        return { id, sev, latency: stat.latency, focused: focusCells.has(id) };
      })
      .sort((a, b) => {
        if (a.focused !== b.focused) return a.focused ? -1 : 1;
        return SEV_ORDER.indexOf(a.sev) - SEV_ORDER.indexOf(b.sev);
      });
  }, [metrics, alerts, now, focusCells]);

  if (cells.length === 0) return null;

  const counts = SEV_ORDER.reduce<Record<string, number>>((acc, s) => {
    acc[s] = cells.filter((c) => c.sev === s).length;
    return acc;
  }, {});

  return (
    <div className="glass rounded-xl p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-ink-1">Cell health</h3>
        <div className="flex gap-3 text-xs text-ink-2">
          {counts["critical"] > 0 && (
            <span className="text-bad">{counts["critical"]} critical</span>
          )}
          {counts["high"] > 0 && (
            <span className="text-warn">{counts["high"]} high</span>
          )}
          <span className="text-ink-3">{cells.length} cells</span>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-2 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10">
        {cells.map((cell) => (
          <div
            key={cell.id}
            title={`Cell ${cell.id} · ${cell.sev}${cell.latency != null ? ` · ${cell.latency.toFixed(0)}ms` : ""}`}
            className={cn(
              "flex flex-col items-center gap-1 rounded-lg border p-2 text-center transition",
              SEV_STYLES[cell.sev],
              cell.focused && "ring-2 ring-cy ring-offset-1 ring-offset-bg-0",
            )}
          >
            <span className="truncate text-[11px] font-mono font-medium leading-none w-full text-center">
              {cell.id.length > 8 ? cell.id.slice(-6) : cell.id}
            </span>
            {cell.latency != null && (
              <span className="text-[9px] tabular-nums opacity-70">
                {cell.latency.toFixed(0)}ms
              </span>
            )}
            <span className={cn("h-1.5 w-1.5 rounded-full", SEV_PIP[cell.sev])} />
          </div>
        ))}
      </div>
    </div>
  );
}
