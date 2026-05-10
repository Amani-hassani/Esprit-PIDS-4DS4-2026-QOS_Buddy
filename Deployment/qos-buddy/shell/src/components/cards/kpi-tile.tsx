"use client";

import { useMemo } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { cn, formatNumber } from "@/lib/utils";

export type KpiTone = "ok" | "warn" | "bad" | "neutral";

interface KpiTileProps {
  label: string;
  value: number | null | undefined;
  unit: string;
  history: number[]; // for the sparkline + trend
  /** Lower is better (latency, jitter, loss) vs higher is better (throughput, MOS). */
  goodDirection: "lower" | "higher";
  /** Optional thresholds; when set we color-code the tile. */
  warn?: number;
  bad?: number;
}

/**
 * A single live KPI tile. Pure presentational — value/history come from the
 * live store. No mock fallback: empty history renders an honest empty state.
 */
export function KpiTile({
  label,
  value,
  unit,
  history,
  goodDirection,
  warn,
  bad,
}: KpiTileProps) {
  const tone: KpiTone = useMemo(() => {
    if (value === null || value === undefined || Number.isNaN(value)) return "neutral";
    if (warn === undefined && bad === undefined) return "neutral";
    const breach = (limit?: number) => {
      if (limit === undefined) return false;
      return goodDirection === "lower" ? value > limit : value < limit;
    };
    if (breach(bad)) return "bad";
    if (breach(warn)) return "warn";
    return "ok";
  }, [value, warn, bad, goodDirection]);

  const trend = useMemo(() => {
    if (history.length < 6) return 0;
    const a = avg(history.slice(-12, -6));
    const b = avg(history.slice(-6));
    if (!Number.isFinite(a) || !Number.isFinite(b) || a === 0) return 0;
    return ((b - a) / Math.abs(a)) * 100;
  }, [history]);

  const TrendIcon = trend > 1 ? ArrowUpRight : trend < -1 ? ArrowDownRight : Minus;
  const trendIsBad =
    Math.abs(trend) > 1 &&
    ((goodDirection === "lower" && trend > 0) ||
      (goodDirection === "higher" && trend < 0));

  return (
    <div
      className={cn(
        "glass relative rounded-xl p-4 transition",
        tone === "bad" && "border-bad/40 ring-1 ring-bad/20 shadow-[0_0_30px_-12px_hsl(var(--bad)/0.6)]",
        tone === "warn" && "border-warn/40 ring-1 ring-warn/20",
        tone === "ok" && "border-ok/30",
      )}
    >
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-ink-2">
            {label}
          </div>
          <div className="mt-1 flex items-baseline gap-1.5">
            <span className="font-mono text-3xl font-semibold tabular-nums text-ink-0">
              {formatNumber(value)}
            </span>
            <span className="text-xs text-ink-2">{unit}</span>
          </div>
        </div>
        <span
          className={cn(
            "inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-xs font-medium",
            trendIsBad ? "bg-bad-soft text-bad" : "bg-ok-soft text-ok",
            Math.abs(trend) <= 1 && "bg-bg-3 text-ink-2",
          )}
          title={`Trend: ${trend.toFixed(1)}%`}
        >
          <TrendIcon className="h-3 w-3" />
          {Math.abs(trend) > 1 ? `${Math.abs(trend).toFixed(0)}%` : "flat"}
        </span>
      </div>

      <Sparkline data={history} tone={tone} />

      {/* status pip */}
      <span
        className={cn(
          "absolute right-3 top-3 h-1.5 w-1.5 rounded-full",
          tone === "bad" && "bg-bad pulse-dot text-bad",
          tone === "warn" && "bg-warn pulse-dot text-warn",
          tone === "ok" && "bg-ok",
          tone === "neutral" && "bg-ink-3",
        )}
      />
    </div>
  );
}

function avg(xs: number[]): number {
  if (xs.length === 0) return Number.NaN;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

function Sparkline({ data, tone }: { data: number[]; tone: KpiTone }) {
  if (data.length < 2) {
    return (
      <div className="mt-3 h-8 rounded-md border border-dashed border-line-subtle bg-bg-2/40" />
    );
  }
  const w = 220;
  const h = 32;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const step = w / Math.max(1, data.length - 1);
  const path = data
    .map((v, i) => `${i === 0 ? "M" : "L"} ${(i * step).toFixed(2)} ${(h - ((v - min) / range) * h).toFixed(2)}`)
    .join(" ");
  const stroke =
    tone === "bad"
      ? "hsl(var(--bad))"
      : tone === "warn"
        ? "hsl(var(--warn))"
        : tone === "ok"
          ? "hsl(var(--ok))"
          : "hsl(var(--cy))";

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      className="mt-3 h-8 w-full"
    >
      <path d={path} fill="none" stroke={stroke} strokeWidth={1.6} />
    </svg>
  );
}
