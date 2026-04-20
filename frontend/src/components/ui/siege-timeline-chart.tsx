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
}

interface SiegeTimelineChartProps {
  items: CertificationPoint[]; // 최신순 (id DESC) — 내부에서 오래된→최신 로 flip
}

function fmtTime(iso: string): string {
  // "2026-04-20T22:31:56+09:00" → "04-20 22:31"
  return iso.slice(5, 16).replace("T", " ");
}

interface ChartPoint {
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
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis
              dataKey="short"
              tick={{ fontSize: 10, fill: "#71717a" }}
              tickLine={false}
              interval={Math.max(0, Math.floor(chartData.length / 6) - 1)}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#71717a" }}
              tickLine={false}
              axisLine={false}
              domain={[0, 100]}
              tickFormatter={(v) => `${v}`}
              width={32}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#18181b",
                border: "1px solid #3f3f46",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: "#a1a1aa" }}
              labelFormatter={(_, payload) => {
                const p = payload?.[0]?.payload as ChartPoint | undefined;
                return p ? `#${p.id} — ${p.short}` : "";
              }}
              formatter={(value, _name, item) => {
                const p = item.payload as ChartPoint;
                const status = p.certified ? "✅ CERTIFIED" : "❌ REJECTED";
                return [
                  `${status} (${value}) — ${p.failed}F/${p.warnings}W  regime=${p.regime ?? "-"}  caller=${p.caller ?? "-"}`,
                  "score",
                ];
              }}
            />
            {transitionIndexes.map((i) => (
              <ReferenceLine
                key={`t-${i}`}
                x={chartData[i].short}
                stroke="#a1a1aa"
                strokeDasharray="4 3"
                strokeWidth={1}
                ifOverflow="extendDomain"
                label={{
                  value: "▲",
                  position: "top",
                  fill: "#a1a1aa",
                  fontSize: 10,
                }}
              />
            ))}
            <Line
              dataKey="score"
              stroke="#71717a"
              strokeWidth={1.5}
              dot={(dotProps) => {
                // 각 point 를 certified 여부 색상으로 찍기
                const { cx, cy, payload, index } = dotProps as {
                  cx: number;
                  cy: number;
                  payload: ChartPoint;
                  index: number;
                };
                const fill = payload.certified ? "#10b981" : "#ef4444";
                return <circle key={`dot-${index}`} cx={cx} cy={cy} r={3.5} fill={fill} stroke="#18181b" strokeWidth={1} />;
              }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 text-[10px] text-muted-foreground">
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
      </div>
    </div>
  );
}
