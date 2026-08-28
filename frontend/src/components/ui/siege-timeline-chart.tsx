"use client";

/**
 * SiegeTimelineChart — 최근 N개 SIEGE 인증 실행의 score 변화를 timeline 으로.
 *
 * 목적: E4-0a (#410) 가 매 certify() 실행을 persist — 변화 관찰 via V1 API.
 * - Score line (y=score, x=timestamp)
 * - Point color: green=certified, red=rejected
 * - Vertical dashed markers: portfolio_hash change (portfolio state transition)
 * - Tooltip: id, regime, caller, passed/failed/warnings
 */
import { CHART_CELL_STROKE, CHART_GRID_STROKE, CHART_MUTED, CHART_TOOLTIP_BG, CHART_TOOLTIP_BORDER } from "@/lib/chart-theme";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export interface GateCondition {
  id: string;
  description: string;
  passed: boolean;
  detail: string;
  severity: "error" | "warning";
}

export interface CertificationPoint {
  id: number;
  timestamp: string;
  certified: boolean;
  score: number;
  total_conditions: number;
  passed: number;
  failed: number;
  warnings: number;
  regime: string | null;
  portfolio_hash: string | null;
  caller: string | null;
  conditions?: GateCondition[];
}

interface SiegeTimelineChartProps {
  items: CertificationPoint[]; // 최신순 (id DESC) — 내부에서 오래된→최신 로 flip
}

function fmtTime(iso: string): string {
  // "2026-04-20T22:31:56+09:00" → "04-20 22:31"
  return iso.slice(5, 16).replace("T", " ");
}

export interface ChartPoint {
  idx: number;
  id: number;
  timestamp: string;
  short: string;
  certified: boolean;
  score: number;
  failed: number;
  warnings: number;
  regime: string | null;
  caller: string | null;
  hashChanged: boolean;
}

// ─── Extracted render helpers — module-level 로 분리해 Recharts mock 과 무관하게 unit test ───

export function tickFormatter(v: number): string {
  return `${v}`;
}

export function labelFormatter(_label: unknown, payload?: { payload?: ChartPoint }[]): string {
  const p = payload?.[0]?.payload;
  return p ? `#${p.id} — ${p.short}` : "";
}

export function valueFormatter(value: unknown, _name: unknown, item: { payload: ChartPoint }): [string, string] {
  const p = item.payload;
  const status = p.certified ? "✓ CERTIFIED" : "✕ REJECTED";
  return [
    `${status} (${value}) — ${p.failed}F/${p.warnings}W  regime=${p.regime ?? "-"}  caller=${p.caller ?? "-"}`,
    "score",
  ];
}

export interface DotRenderProps {
  cx: number;
  cy: number;
  payload: ChartPoint;
  index: number;
}

export function dotFill(payload: ChartPoint): string {
  return payload.certified ? "#10b981" : "#ef4444";
}

/**
 * caller 별 shape 분류 — V2.1 교훈 #39:
 * user-triggered (cli) vs automated (api:*) vs historical backfill (audit:*)
 * 를 dot 모양으로 즉시 구별. legend 에 caller × count 도 함께.
 */
export type DotShape = "circle" | "triangle" | "square" | "diamond";

export function callerShape(caller: string | null): DotShape {
  if (!caller) return "circle";
  if (caller === "cli" || caller === "direct") return "circle";
  if (caller.startsWith("api:")) return "triangle";
  if (caller.startsWith("audit:")) return "square"; // E4-0b historical backfill
  if (caller === "scheduler") return "diamond";
  return "circle";
}

/** hashChanged (portfolio state 전환) dot 은 radius 키워 강조. 그 외 기본 3.5. */
export function dotRadius(hashChanged: boolean): number {
  return hashChanged ? 5 : 3.5;
}

export function renderDot(dotProps: unknown): React.ReactElement {
  const { cx, cy, payload, index } = dotProps as DotRenderProps;
  const fill = dotFill(payload);
  const r = dotRadius(payload.hashChanged);
  const shape = callerShape(payload.caller);
  const key = `dot-${index}`;
  const commonStroke = { stroke: CHART_CELL_STROKE, strokeWidth: 1 };

  if (shape === "triangle") {
    const h = r * 1.3;
    return (
      <polygon
        key={key}
        points={`${cx},${cy - h} ${cx - h},${cy + h * 0.8} ${cx + h},${cy + h * 0.8}`}
        fill={fill}
        {...commonStroke}
      />
    );
  }
  if (shape === "square") {
    const s = r * 1.1;
    return (
      <rect
        key={key}
        x={cx - s}
        y={cy - s}
        width={s * 2}
        height={s * 2}
        fill={fill}
        {...commonStroke}
      />
    );
  }
  if (shape === "diamond") {
    const h = r * 1.3;
    return (
      <polygon
        key={key}
        points={`${cx},${cy - h} ${cx + h},${cy} ${cx},${cy + h} ${cx - h},${cy}`}
        fill={fill}
        {...commonStroke}
      />
    );
  }
  return (
    <circle key={key} cx={cx} cy={cy} r={r} fill={fill} {...commonStroke} />
  );
}

/**
 * Legend 용 SVG 아이콘 — renderDot 과 shape 동기화.
 * tailwind 크기 (w-2 h-2) 와 시각 균형을 위해 8×8 viewBox.
 */
export function LegendShape({ shape, className = "" }: { shape: DotShape; className?: string }): React.ReactElement {
  const common = "inline-block w-2 h-2 " + className;
  const fill = CHART_MUTED;
  if (shape === "triangle") {
    return (
      <svg className={common} viewBox="0 0 8 8" aria-hidden>
        <polygon points="4,0 8,8 0,8" fill={fill} />
      </svg>
    );
  }
  if (shape === "square") {
    return <span className={common + " bg-zinc-400"} aria-hidden />;
  }
  if (shape === "diamond") {
    return (
      <svg className={common} viewBox="0 0 8 8" aria-hidden>
        <polygon points="4,0 8,4 4,8 0,4" fill={fill} />
      </svg>
    );
  }
  return <span className={common + " rounded-full bg-zinc-400"} aria-hidden />;
}

/** caller 별 count — legend 에 표시 (distinct caller 수를 가시화). */
export function countByCaller(points: ChartPoint[]): { caller: string; count: number; shape: DotShape }[] {
  const counts = new Map<string, number>();
  for (const p of points) {
    const c = p.caller ?? "(none)";
    counts.set(c, (counts.get(c) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([caller, count]) => ({ caller, count, shape: callerShape(caller === "(none)" ? null : caller) }));
}

export function SiegeTimelineChart({ items }: SiegeTimelineChartProps) {
  if (!items.length) {
    return (
      <div className="h-60 flex items-center justify-center text-xs text-muted-foreground">
        아직 certification 실행 기록이 없습니다. <code className="ml-1">make certify</code>
      </div>
    );
  }

  // API 는 id DESC (최신순). Chart 는 과거→현재 순으로 뒤집기.
  const ordered = [...items].reverse();

  // Portfolio hash 전환점 감지 — 첫 row 는 false, 이후는 prev 와 비교.
  const chartData: ChartPoint[] = ordered.map((p, idx) => ({
    idx,
    id: p.id,
    timestamp: p.timestamp,
    short: fmtTime(p.timestamp),
    certified: p.certified,
    score: p.score,
    failed: p.failed,
    warnings: p.warnings,
    regime: p.regime,
    caller: p.caller,
    hashChanged:
      idx > 0 && ordered[idx - 1].portfolio_hash !== p.portfolio_hash,
  }));

  const transitionIndexes = chartData.filter((p) => p.hashChanged).map((p) => p.idx);
  const certifiedCount = chartData.filter((p) => p.certified).length;

  return (
    <div className="min-w-0 space-y-2">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-muted-foreground">
          SIEGE Timeline — 최근 {items.length}건 ({certifiedCount} CERTIFIED / {items.length - certifiedCount} REJECTED)
        </span>
        <span className="text-[10px] text-muted-foreground/70">
          score 0–100, 점선 = portfolio state 변경
        </span>
      </div>

      <div className="w-full min-w-0 h-60">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={200}>
          <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
            <XAxis
              dataKey="short"
              tick={{ fontSize: 10, fill: CHART_MUTED }}
              tickLine={false}
              interval={Math.max(0, Math.floor(chartData.length / 6) - 1)}
            />
            <YAxis
              tick={{ fontSize: 10, fill: CHART_MUTED }}
              tickLine={false}
              axisLine={false}
              domain={[0, 100]}
              tickFormatter={tickFormatter}
              width={32}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: CHART_TOOLTIP_BG,
                border: CHART_TOOLTIP_BORDER,
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: CHART_MUTED }}
              labelFormatter={labelFormatter as never}
              formatter={valueFormatter as never}
            />
            {transitionIndexes.map((i) => (
              <ReferenceLine
                key={`t-${i}`}
                x={chartData[i].short}
                stroke={CHART_MUTED}
                strokeDasharray="4 3"
                strokeWidth={1}
                ifOverflow="extendDomain"
                label={{
                  value: "▲",
                  position: "top",
                  fill: CHART_MUTED,
                  fontSize: 10,
                }}
              />
            ))}
            <Line
              dataKey="score"
              stroke={CHART_MUTED}
              strokeWidth={1.5}
              dot={renderDot as never}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Legend — 결과 색 + 전환 선 + caller shape 분류 */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-muted-foreground">
        <span>
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 mr-1.5 align-middle" />
          CERTIFIED
        </span>
        <span>
          <span className="inline-block w-2 h-2 rounded-full bg-red-500 mr-1.5 align-middle" />
          REJECTED
        </span>
        <span>
          <span className="inline-block w-3 h-px bg-zinc-400 mr-1.5 align-middle border-t border-dashed" />
          portfolio state 변경
        </span>
        <span className="w-full mt-0.5 text-muted-foreground/70">caller:</span>
        {countByCaller(chartData).map(({ caller, count, shape }) => (
          <span key={caller} className="flex items-center">
            <LegendShape shape={shape} className="mr-1 align-middle" />
            {caller}
            <span className="text-muted-foreground/60 ml-1">×{count}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
