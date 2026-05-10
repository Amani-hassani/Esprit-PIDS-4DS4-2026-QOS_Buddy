"use client";

import { AlertTriangle, Clock, Hourglass } from "lucide-react";
import { useEffect, useState } from "react";
import { useLive } from "@/lib/store";
import { cn, formatCountdown } from "@/lib/utils";

/**
 * Picks the most urgent forecast alert and renders a live countdown.
 * No mock data — when there is no forecast alert, it renders "Stable".
 */
export function TimeToBreach() {
  const alerts = useLive((s) => s.alerts);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  // pick the soonest unresolved forecast alert
  const active = alerts
    .filter((a) => a.detector !== "forecast")
    .sort((a, b) => {
      const sev = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };
      const bySeverity = (sev[b.severity] ?? 0) - (sev[a.severity] ?? 0);
      if (bySeverity !== 0) return bySeverity;
      return new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime();
    })[0];

  if (active) {
    return (
      <span className="hidden md:inline-flex items-center gap-2 rounded-lg border border-bad/40 bg-bad-soft px-3 py-1.5 text-xs font-medium text-bad">
        <AlertTriangle className="h-3.5 w-3.5" />
        <span>Active breach</span>
        <span className="font-mono text-sm">{active.cell_id ?? "fleet"}</span>
        <span className="hidden lg:inline text-ink-2">{active.display_label}</span>
      </span>
    );
  }

  const forecast = alerts
    .filter((a) => a.detector === "forecast" && a.time_to_breach_seconds != null)
    .sort(
      (a, b) =>
        (a.time_to_breach_seconds ?? Number.POSITIVE_INFINITY) -
        (b.time_to_breach_seconds ?? Number.POSITIVE_INFINITY),
    )[0];

  if (!forecast || forecast.time_to_breach_seconds == null) {
    return (
      <span className="hidden md:inline-flex items-center gap-2 rounded-lg border border-line-subtle bg-bg-2 px-3 py-1.5 text-xs text-ink-2">
        <Clock className="h-3.5 w-3.5" />
        Network stable — no forecasted breach
      </span>
    );
  }

  // recompute the countdown relative to occurred_at
  const occurredAt = new Date(forecast.occurred_at).getTime();
  const elapsed = (now - occurredAt) / 1000;
  const remaining = Math.max(0, (forecast.time_to_breach_seconds ?? 0) - elapsed);

  // forecast already breached — show stable instead of frozen 00:00
  if (remaining <= 0) {
    return (
      <span className="hidden md:inline-flex items-center gap-2 rounded-lg border border-line-subtle bg-bg-2 px-3 py-1.5 text-xs text-ink-2">
        <Clock className="h-3.5 w-3.5" />
        Network stable — no forecasted breach
      </span>
    );
  }

  const tone =
    remaining < 60
      ? "bad"
      : remaining < 180
        ? "warn"
        : "info";

  return (
    <span
      className={cn(
        "hidden md:inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-medium",
        tone === "bad" && "border-bad/40 bg-bad-soft text-bad",
        tone === "warn" && "border-warn/40 bg-warn-soft text-warn",
        tone === "info" && "border-info/40 bg-info-soft text-info",
      )}
    >
      <Hourglass className="h-3.5 w-3.5" />
      <span>Time to breach</span>
      <span className="font-mono text-sm">{formatCountdown(remaining)}</span>
      {forecast.cell_id && (
        <span className="hidden lg:inline text-ink-2">on {forecast.cell_id}</span>
      )}
    </span>
  );
}
