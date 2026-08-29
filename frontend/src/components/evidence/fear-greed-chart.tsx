"use client";

/**
 * FearGreedChart — 공포·탐욕 지수 90일 라인 + 구간 존 (#1225).
 * 존 경계는 CNN Fear & Greed 표준 구간 (Plotly 원본과 동일).
 */
import { CHART_MUTED, CHART_TOOLTIP_BG, CHART_TOOLTIP_BORDER } from "@/lib/chart-theme";
import { EVIDENCE } from "@/lib/strings";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceArea,
} from "recharts";

import type { FearGreedData } from "@/components/evidence/chart-data";

export const FG_ZONES = [
  { from: 0, to: 25, color: "#d32f2f", label: "극단 공포" },
  { from: 25, to: 45, color: "#ff9800", label: "공포" },
  { from: 45, to: 55, color: "#616161", label: "중립" },
  { from: 55, to: 75, color: "#66bb6a", label: "탐욕" },
  { from: 75, to: 100, color: "#2e7d32", label: "극단 탐욕" },
] as const;

export function zoneLabel(value: number): string {
  const zone = FG_ZONES.find((z) => value < z.to) ?? FG_ZONES[FG_ZONES.length - 1];
  return zone.label;
}

export function fgTooltipFormatter(value: unknown): [string, string] {
  return [Number(value).toFixed(0), "지수"];
}

export function FearGreedChart({ data }: { data: FearGreedData }) {
  const rows = data.history.map((d) => ({ date: d.date.slice(5), value: d.value }));
  const latest = data.history[data.history.length - 1];

  return (
    <div className="min-w-0" data-testid="fear-greed-chart" role="img" aria-label={EVIDENCE.TITLE_FEAR_GREED}>
      {latest && (
        <div className="mb-2">
          <span className="text-[10px] px-2 py-0.5 rounded-sm bg-muted text-foreground">
            현재 {latest.value.toFixed(0)} · {zoneLabel(latest.value)}
          </span>
        </div>
      )}
      <div className="w-full min-w-0 h-56">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={200}>
          <LineChart data={rows} margin={{ top: 5, right: 5, bottom: 0, left: 0 }}>
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: CHART_MUTED }}
              tickLine={false}
              interval={Math.floor(rows.length / 6)}
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fontSize: 10, fill: CHART_MUTED }}
              tickLine={false}
              axisLine={false}
              width={30}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: CHART_TOOLTIP_BG,
                border: CHART_TOOLTIP_BORDER,
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: CHART_MUTED }}
              formatter={fgTooltipFormatter}
            />
            {FG_ZONES.map((z) => (
              <ReferenceArea key={z.label} y1={z.from} y2={z.to} fill={z.color} fillOpacity={0.07} />
            ))}
            <Line dataKey="value" stroke="var(--chart-1)" strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="flex gap-3 mt-1 text-[10px] text-muted-foreground justify-center">
        {FG_ZONES.map((z) => (
          <span key={z.label}>
            <span className="inline-block size-2.5 mr-1 align-middle" style={{ background: z.color, opacity: 0.6 }} />
            {z.label}
          </span>
        ))}
      </div>
    </div>
  );
}
