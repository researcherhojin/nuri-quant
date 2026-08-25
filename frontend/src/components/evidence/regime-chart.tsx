"use client";

/**
 * RegimeChart — SPY 종가 + SMA50/200 라인 + VIX 서브차트 (#1225).
 * Plotly regime 차트의 네이티브 대체. VIX 30 기준선 = rules.yaml 신규 매수 차단선.
 */
import { EVIDENCE } from "@/lib/strings";
import {
  ResponsiveContainer,
  ComposedChart,
  LineChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from "recharts";

import type { RegimeData } from "@/components/evidence/chart-data";

export const VIX_BLOCK_LEVEL = 30;

const TOOLTIP_STYLE = {
  backgroundColor: "#18181b",
  border: "1px solid #3f3f46",
  borderRadius: 8,
  fontSize: 12,
} as const;

/** SPY·VIX 를 recharts row 로 (날짜 MM-DD 축약) */
export function buildRegimeRows(data: RegimeData) {
  const spy = data.spy.map((d) => ({
    date: d.date.slice(5),
    close: d.close,
    sma50: d.sma50,
    sma200: d.sma200,
  }));
  const vix = data.vix.map((d) => ({ date: d.date.slice(5), vix: d.value }));
  return { spy, vix };
}

/** 가격축 눈금 — 정수 표기 */
export function priceTick(v: unknown): string {
  return Number(v).toFixed(0);
}

export function regimeChipLabel(regime: RegimeData["regime"]): string | null {
  if (!regime) return null;
  return `${regime.regime} · 신뢰도 ${Math.round(regime.confidence * 100)}%`;
}

export function RegimeChart({ data }: { data: RegimeData }) {
  const { spy, vix } = buildRegimeRows(data);
  const closes = data.spy.map((d) => d.close);
  const minClose = Math.min(...closes) * 0.98;
  const maxClose = Math.max(...closes) * 1.02;
  const chip = regimeChipLabel(data.regime);

  return (
    <div className="min-w-0" data-testid="regime-chart" role="img" aria-label={EVIDENCE.TITLE_REGIME}>
      {chip && (
        <div className="mb-2">
          <span className="text-[10px] px-2 py-0.5 rounded bg-muted text-zinc-200">{chip}</span>
        </div>
      )}
      <div className="w-full min-w-0 h-64">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={200}>
          <ComposedChart data={spy} margin={{ top: 5, right: 5, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: "#71717a" }}
              tickLine={false}
              interval={Math.floor(spy.length / 6)}
            />
            <YAxis
              domain={[minClose, maxClose]}
              tick={{ fontSize: 10, fill: "#71717a" }}
              tickLine={false}
              axisLine={false}
              tickFormatter={priceTick}
              width={50}
            />
            <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: "#a1a1aa" }} />
            <Area
              dataKey="close"
              stroke="var(--chart-1)"
              fill="var(--chart-1)"
              fillOpacity={0.05}
              strokeWidth={1.5}
              dot={false}
            />
            <Line
              dataKey="sma50"
              stroke="#f59e0b"
              strokeWidth={1}
              dot={false}
              strokeDasharray="4 2"
              connectNulls
            />
            <Line
              dataKey="sma200"
              stroke="#9179F2"
              strokeWidth={1}
              dot={false}
              strokeDasharray="4 2"
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* VIX 서브차트 — 30 선 위는 신규 매수 차단 구간 */}
      {vix.length > 0 && (
        <div className="w-full min-w-0 h-24 mt-2" data-testid="vix-subchart">
          <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={80}>
            <LineChart data={vix} margin={{ top: 5, right: 5, bottom: 0, left: 0 }}>
              <XAxis dataKey="date" hide />
              <YAxis
                tick={{ fontSize: 9, fill: "#71717a" }}
                tickLine={false}
                axisLine={false}
                width={50}
              />
              <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: "#a1a1aa" }} />
              <ReferenceLine y={VIX_BLOCK_LEVEL} stroke="#f59e0b" strokeDasharray="4 2" />
              <Line dataKey="vix" stroke="#3FA6DA" strokeWidth={1} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="flex gap-4 mt-1 text-[10px] text-muted-foreground justify-center">
        <span>
          <span className="inline-block w-3 h-0.5 mr-1 align-middle" style={{ background: "var(--chart-1)" }} />
          SPY
        </span>
        <span>
          <span className="inline-block w-3 h-0.5 bg-amber-500 mr-1 align-middle" />
          SMA50
        </span>
        <span>
          <span className="inline-block w-3 h-0.5 mr-1 align-middle" style={{ background: "#9179F2" }} />
          SMA200
        </span>
        <span>
          <span className="inline-block w-3 h-0.5 mr-1 align-middle" style={{ background: "#3FA6DA" }} />
          VIX
        </span>
      </div>
    </div>
  );
}
