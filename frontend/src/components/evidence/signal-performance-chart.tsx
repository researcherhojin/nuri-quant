"use client";

/**
 * SignalPerformanceChart — 시그널별 승률 가로 바(드리프트 색) + PF 라인 (#1225).
 * 승률 0.5 기준선 = 동전던지기 (edge 미입증 기준, STRATEGY §3.11).
 */
import { CHART_MUTED, CHART_TOOLTIP_BG, CHART_TOOLTIP_BORDER } from "@/lib/chart-theme";
import { EVIDENCE } from "@/lib/strings";
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Cell,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
} from "recharts";

import { DRIFT_COLORS, type SignalPerformanceData } from "@/components/evidence/chart-data";

export const COIN_FLIP_WIN_RATE = 0.5;

export function driftColor(status: string): string {
  return DRIFT_COLORS[status] ?? "var(--chart-1)";
}

export function winRateTick(v: unknown): string {
  return `${Math.round(Number(v) * 100)}%`;
}

export function signalTooltipFormatter(value: unknown, name: unknown): [string, string] {
  const v = Number(value);
  if (name === "win_rate") return [`${(v * 100).toFixed(1)}%`, "승률"];
  if (name === "profit_factor") return [v.toFixed(2), "PF"];
  return [String(value), String(name)];
}

export function SignalPerformanceChart({ data }: { data: SignalPerformanceData }) {
  const rows = data.signals;
  // 행당 28px — 시그널 수에 따라 늘어난다
  const height = Math.max(rows.length * 28 + 40, 120);

  return (
    <div className="min-w-0" data-testid="signal-performance-chart" role="img" aria-label={EVIDENCE.TITLE_SIGNALS}>
      <div className="w-full min-w-0" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <ComposedChart data={rows} layout="vertical" margin={{ top: 5, right: 30, bottom: 0, left: 0 }}>
            <XAxis
              type="number"
              domain={[0, 1]}
              tick={{ fontSize: 10, fill: CHART_MUTED }}
              tickLine={false}
              tickFormatter={winRateTick}
            />
            {/* PF 는 1 을 넘으므로 별도 상단 축 (숨김) — 승률 [0,1] 축과 분리 */}
            <XAxis xAxisId="pf" type="number" orientation="top" hide domain={[0, "auto"]} />
            <YAxis
              type="category"
              dataKey="signal_id"
              tick={{ fontSize: 10, fill: CHART_MUTED }}
              tickLine={false}
              axisLine={false}
              width={130}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: CHART_TOOLTIP_BG,
                border: CHART_TOOLTIP_BORDER,
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={signalTooltipFormatter}
            />
            <ReferenceLine x={COIN_FLIP_WIN_RATE} stroke={CHART_MUTED} strokeDasharray="4 2" />
            <Bar dataKey="win_rate" barSize={14} isAnimationActive={false}>
              {rows.map((r) => (
                <Cell key={r.signal_id} fill={driftColor(r.drift_status)} />
              ))}
            </Bar>
            <Line
              xAxisId="pf"
              dataKey="profit_factor"
              stroke="#9179F2"
              strokeWidth={1}
              dot={{ r: 2 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="flex gap-4 mt-1 text-[10px] text-muted-foreground justify-center">
        <span>
          <span className="inline-block size-2.5 mr-1 align-middle" style={{ background: "var(--chart-1)" }} />
          승률 (안정)
        </span>
        <span>
          <span className="inline-block size-2.5 mr-1 align-middle" style={{ background: DRIFT_COLORS.degrading }} />
          드리프트 열화
        </span>
        <span>
          <span className="inline-block size-2.5 mr-1 align-middle" style={{ background: DRIFT_COLORS.critical }} />
          드리프트 위험
        </span>
        <span>
          <span className="inline-block w-3 h-0.5 mr-1 align-middle" style={{ background: "#9179F2" }} />
          Profit Factor
        </span>
      </div>
    </div>
  );
}
