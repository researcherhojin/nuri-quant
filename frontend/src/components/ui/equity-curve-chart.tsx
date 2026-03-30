"use client";

/**
 * EquityCurveChart — 백테스트 equity curve (Strategy vs SPY + Drawdown).
 */
import { useState } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

interface EquityPoint {
  date: string;
  strategy: number;
  spy: number;
  drawdown: number;
}

interface EquityCurveChartProps {
  data: EquityPoint[];
}

const PERIODS = [
  { label: "1Y", days: 252 },
  { label: "3Y", days: 756 },
  { label: "5Y", days: 1260 },
  { label: "ALL", days: 9999 },
] as const;

export function EquityCurveChart({ data }: EquityCurveChartProps) {
  const [period, setPeriod] = useState<number>(9999);

  const sliced = data.slice(-period);
  if (sliced.length === 0) return null;

  const chartData = sliced;

  return (
    <div>
      {/* Period selector */}
      <div className="flex items-center gap-1 mb-3">
        <span className="text-xs text-muted-foreground mr-2">Equity Curve</span>
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

      {/* Strategy vs SPY */}
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={chartData} syncId="equity" margin={{ top: 5, right: 5, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10, fill: "#71717a" }}
            tickLine={false}
            interval={Math.floor(chartData.length / 6)}
            tickFormatter={(v) => String(v).slice(2, 7)}
          />
          <YAxis
            tick={{ fontSize: 10, fill: "#71717a" }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${v}%`}
            width={50}
          />
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
              const label = name === "strategy" ? "Strategy" : "SPY";
              return [`${v > 0 ? "+" : ""}${v.toFixed(1)}%`, label];
            }}
          />
          <Line
            dataKey="spy"
            stroke="#71717a"
            strokeWidth={1.5}
            dot={false}
          />
          <Line
            dataKey="strategy"
            stroke="#10b981"
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Drawdown */}
      <ResponsiveContainer width="100%" height={80}>
        <ComposedChart data={chartData} syncId="equity" margin={{ top: 0, right: 5, bottom: 0, left: 0 }}>
          <XAxis dataKey="date" hide />
          <YAxis
            tick={{ fontSize: 9, fill: "#71717a" }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${v}%`}
            width={50}
            domain={["dataMin", 0]}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#18181b",
              border: "1px solid #3f3f46",
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(value) => [`${Number(value).toFixed(1)}%`, "Drawdown"]}
          />
          <Area
            dataKey="drawdown"
            stroke="#ef4444"
            fill="#ef4444"
            fillOpacity={0.15}
            strokeWidth={1}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div className="flex gap-4 mt-1 text-[10px] text-muted-foreground justify-center">
        <span><span className="inline-block w-3 h-0.5 bg-emerald-500 mr-1 align-middle" />Strategy</span>
        <span><span className="inline-block w-3 h-0.5 bg-zinc-500 mr-1 align-middle" />SPY</span>
        <span><span className="inline-block w-3 h-0.5 bg-red-500 mr-1 align-middle" />Drawdown</span>
      </div>
    </div>
  );
}
