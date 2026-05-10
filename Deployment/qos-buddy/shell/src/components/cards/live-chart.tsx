"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import { useTheme } from "next-themes";
import { withChartDefaults } from "@/lib/chart-defaults";
import { useLive } from "@/lib/store";
import type { MetricEvent } from "@/lib/types";

// ECharts is heavy — load it client-side only.
const ReactEChartsCore = dynamic(() => import("echarts-for-react"), {
  ssr: false,
  loading: () => (
    <div className="grid h-[320px] place-items-center rounded-xl border border-dashed border-line-subtle bg-bg-2/40 text-sm text-ink-2">
      Preparing chart…
    </div>
  ),
});

interface LiveChartProps {
  title?: string;
}

/**
 * Live multi-KPI chart driven by the metrics ring buffer in the live store.
 * Renders an honest empty state until real data arrives — no synthetic seeds.
 */
export function LiveChart({ title = "Network behaviour - last 10 minutes" }: LiveChartProps) {
  const metrics = useLive((s) => s.metrics);
  const alerts = useLive((s) => s.alerts);
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  const option = useMemo(() => {
    // Bucket into 10s windows to match the live host collector cadence.
    const BUCKET = 10_000;
    const bucketMap = new Map<number, MetricEvent>();
    for (const m of metrics) {
      const key = Math.floor(new Date(m.occurred_at).getTime() / BUCKET) * BUCKET;
      bucketMap.set(key, m);
    }
    const sampled = Array.from(bucketMap.values()).sort(
      (a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime(),
    );

    const points = sampled.map((m) => ({
      t: new Date(m.occurred_at).getTime(),
      latency: m.latency_ms ?? null,
      jitter: m.jitter_ms ?? null,
      loss: m.packet_loss_pct ?? null,
      throughput: m.throughput_mbps ?? null,
      anomaly: m.anomaly_flag ? 1 : 0,
    }));

    const lineColor = (n: 0 | 1 | 2 | 3) =>
      ["#00D4FF", "#A87BFF", "#F43F5E", "#34D399"][n];

    const ax = {
      axisLabel: { color: dark ? "#7C8AAB" : "#475569" },
      axisLine: { lineStyle: { color: dark ? "#2D3D5E" : "#CBD5E1" } },
      splitLine: { lineStyle: { color: dark ? "#1F2C44" : "#E2E8F0" } },
    };

    const anomalyMarks = points
      .filter((p) => p.anomaly === 1)
      .map((p) => [{ xAxis: p.t }, { xAxis: p.t }]);

    return {
      backgroundColor: "transparent",
      animation: false,
      grid: { left: 56, right: 16, top: 36, bottom: 32 },
      legend: {
        top: 4,
        textStyle: { color: dark ? "#B8C4DC" : "#475569" },
        icon: "roundRect",
        itemWidth: 10,
        itemHeight: 4,
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: dark ? "#0D1825" : "#FFFFFF",
        borderColor: dark ? "#2D3D5E" : "#E2E8F0",
        textStyle: { color: dark ? "#ECF2FB" : "#0F172A" },
      },
      xAxis: { type: "time", ...ax },
      yAxis: [
        { type: "value", name: "ms / %", position: "left", ...ax },
        {
          type: "value",
          name: "Mbps",
          position: "right",
          ...ax,
          splitLine: { show: false },
        },
      ],
      series: [
        line("Round-trip delay (ms)", points.map((p) => [p.t, p.latency]), lineColor(0)),
        line("Delay variation (ms)", points.map((p) => [p.t, p.jitter]), lineColor(1)),
        line("Packet loss (%)", points.map((p) => [p.t, p.loss]), lineColor(2)),
        line(
          "Throughput (Mbps)",
          points.map((p) => [p.t, p.throughput]),
          lineColor(3),
          1,
        ),
        {
          name: "Anomaly windows",
          type: "line",
          data: [],
          markArea: {
            silent: true,
            itemStyle: { color: "rgba(244,63,94,0.10)" },
            data: anomalyMarks,
          },
        },
      ],
    };
  }, [metrics, dark]);

  if (metrics.length === 0) {
    return (
      <div className="glass flex h-[360px] flex-col rounded-xl p-4">
        <h3 className="mb-3 text-sm font-medium text-ink-1">{title}</h3>
        <div className="flex-1 grid place-items-center text-sm text-ink-2">
          Waiting for live samples from the monitoring agent…
        </div>
      </div>
    );
  }

  return (
    <div className="glass rounded-xl p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-ink-1">{title}</h3>
        <span className="text-xs text-ink-2">
          {metrics.length} samples · {alerts.length} alerts
        </span>
      </div>
      <ReactEChartsCore
        option={withChartDefaults(option)}
        lazyUpdate
        style={{ height: 320, width: "100%" }}
        opts={{ renderer: "canvas" }}
      />
    </div>
  );
}

function line(
  name: string,
  data: Array<[number, number | null]>,
  color: string,
  yAxisIndex = 0,
) {
  return {
    name,
    type: "line",
    yAxisIndex,
    data,
    smooth: true,
    showSymbol: false,
    sampling: "lttb",
    lineStyle: { width: 1.6, color },
    areaStyle:
      yAxisIndex === 0
        ? {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: `${color}40` },
                { offset: 1, color: `${color}00` },
              ],
            },
          }
        : undefined,
    emphasis: { focus: "series" },
  };
}
