"use client";

/**
 * PriceChart — Recharts 기반 주가 차트.
 * 캔들 대신 라인+영역 차트 (가독성 우선).
 * SMA 20/50 오버레이 + 거래량 바.
 */
import { useState } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Area,
  Line,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

interface PriceData {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface PriceChartProps {
  data: PriceData[];
  ticker: string;
}

const PERIODS = [
  { label: "1D", days: 1 },
  { label: "3D", days: 3 },
  { label: "5D", days: 5 },
  { label: "2W", days: 10 },
  { label: "1M", days: 22 },
  { label: "3M", days: 66 },
  { label: "1Y", days: 252 },
  { label: "ALL", days: 9999 },
] as const;

/** 단순이동평균 계산 */
export function sma(data: number[], period: number): (number | null)[] {
  return data.map((_, i) => {
    if (i < period - 1) return null;
    const slice = data.slice(i - period + 1, i + 1);
    return slice.reduce((a, b) => a + b, 0) / period;
  });
}

export function formatVolume(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return String(v);
}

export function PriceChart({ data, ticker }: PriceChartProps) {
  const [period, setPeriod] = useState<number>(10); // 기본 2W (단타 기준)

  const sliced = data.slice(-period);
  const closes = data.map((d) => d.close);
  const sma20 = sma(closes, 20);
  const sma50 = sma(closes, 50);

  const offset = data.length - sliced.length;
  const chartData = sliced.map((d, i) => ({
    date: d.date.slice(5), // MM-DD
    close: d.close,
    volume: d.volume,
    sma20: sma20[offset + i],
    sma50: sma50[offset + i],
  }));

  const minClose = Math.min(...sliced.map((d) => d.low)) * 0.98;
  const maxClose = Math.max(...sliced.map((d) => d.high)) * 1.02;

  return (
    <div className="min-w-0">
      {/* Period selector */}
      <div className="flex items-center gap-1 mb-3">
        <span className="text-xs text-muted-foreground mr-2">{ticker}</span>
        {PERIODS.map((p) => (
          <button
            key={p.label}
            onClick={() => setPeriod(p.days)}
            className={`text-[10px] px-2 py-0.5 rounded transition-colors ${
              period === p.days
                ? "bg-muted text-zinc-200"
                : "text-muted-foreground hover:text-foreground/80"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Price + Volume chart */}
      <div className="w-full min-w-0 h-[280px]">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={280}>
          <ComposedChart data={chartData} margin={{ top: 5, right: 5, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: "#71717a" }}
              tickLine={false}
              interval={Math.floor(chartData.length / 6)}
            />
            <YAxis
              yAxisId="price"
              domain={[minClose, maxClose]}
              tick={{ fontSize: 10, fill: "#71717a" }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => v.toFixed(0)}
              width={50}
            />
            <YAxis yAxisId="volume" orientation="right" hide />
            <Tooltip
              contentStyle={{
                backgroundColor: "#18181b",
                border: "1px solid #3f3f46",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: "#a1a1aa" }}
              formatter={(value, name) => {
                const v = Number(value);
                if (name === "volume") return [formatVolume(v), "Vol"];
                if (name === "close") return [`$${v.toFixed(2)}`, "Close"];
                return [`$${v.toFixed(2)}`, String(name).toUpperCase()];
              }}
            />
            <Bar
              yAxisId="volume"
              dataKey="volume"
              fill="#3f3f46"
              opacity={0.3}
              barSize={2}
            />
            <Area
              yAxisId="price"
              dataKey="close"
              stroke="#10b981"
              fill="#10b981"
              fillOpacity={0.05}
              strokeWidth={1.5}
              dot={false}
            />
            <Line
              yAxisId="price"
              dataKey="sma20"
              stroke="#f59e0b"
              strokeWidth={1}
              dot={false}
              strokeDasharray="4 2"
              connectNulls
            />
            <Line
              yAxisId="price"
              dataKey="sma50"
              stroke="#6366f1"
              strokeWidth={1}
              dot={false}
              strokeDasharray="4 2"
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div className="flex gap-4 mt-1 text-[10px] text-muted-foreground justify-center">
        <span><span className="inline-block w-3 h-0.5 bg-emerald-500 mr-1 align-middle" />Close</span>
        <span><span className="inline-block w-3 h-0.5 bg-amber-500 mr-1 align-middle" style={{ borderBottom: "1px dashed" }} />SMA20</span>
        <span><span className="inline-block w-3 h-0.5 bg-indigo-500 mr-1 align-middle" style={{ borderBottom: "1px dashed" }} />SMA50</span>
      </div>
    </div>
  );
}
