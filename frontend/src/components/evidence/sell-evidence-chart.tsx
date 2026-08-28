"use client";

/**
 * SellEvidenceChart — 위반 항목별 심각도 가로 바 (#1225).
 * 손절=빨강 · 비중초과=노랑, 툴팁에 조치·회복 조건 표시 (Plotly hover 대체).
 */
import { CHART_MUTED, CHART_TOOLTIP_BG, CHART_TOOLTIP_BORDER } from "@/lib/chart-theme";
import { EVIDENCE } from "@/lib/strings";
import { ResponsiveContainer, BarChart, Bar, Cell, XAxis, YAxis, Tooltip } from "recharts";

import { VIOLATION_COLORS, type SellEvidenceData, type SellViolation } from "@/components/evidence/chart-data";

export interface SellRow extends SellViolation {
  label: string;
}

export function buildSellRows(data: SellEvidenceData): SellRow[] {
  // 심각도 내림차순은 API 가 보장 — 라벨만 조립
  return data.violations.map((v) => ({
    ...v,
    label: `${v.ticker} · ${v.type === "stop_loss" ? "손절" : "비중"}`,
  }));
}

export function severityTick(v: unknown): string {
  return `${Number(v).toFixed(0)}%`;
}

/** 툴팁: 심각도% + 조치·회복 조건 */
export function sellTooltipFormatter(
  value: unknown,
  _name: unknown,
  entry?: { payload?: SellRow },
): [string, string] {
  const row = entry?.payload;
  const detail = row ? `${row.action} — ${row.recovery}` : "심각도";
  return [`${Number(value).toFixed(1)}%`, detail];
}

export function SellEvidenceChart({ data }: { data: SellEvidenceData }) {
  const rows = buildSellRows(data);
  const height = Math.max(rows.length * 30 + 40, 110);

  return (
    <div className="min-w-0" data-testid="sell-evidence-chart" role="img" aria-label={EVIDENCE.TITLE_SELL}>
      <div className="w-full min-w-0" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <BarChart data={rows} layout="vertical" margin={{ top: 5, right: 30, bottom: 0, left: 0 }}>
            <XAxis
              type="number"
              tick={{ fontSize: 10, fill: CHART_MUTED }}
              tickLine={false}
              tickFormatter={severityTick}
            />
            <YAxis
              type="category"
              dataKey="label"
              tick={{ fontSize: 10, fill: CHART_MUTED }}
              tickLine={false}
              axisLine={false}
              width={150}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: CHART_TOOLTIP_BG,
                border: CHART_TOOLTIP_BORDER,
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={sellTooltipFormatter}
            />
            <Bar dataKey="severity" barSize={16} isAnimationActive={false}>
              {rows.map((r) => (
                <Cell key={r.label} fill={VIOLATION_COLORS[r.type]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="flex gap-4 mt-1 text-[10px] text-muted-foreground justify-center">
        <span>
          <span className="inline-block w-2.5 h-2.5 mr-1 align-middle" style={{ background: VIOLATION_COLORS.stop_loss }} />
          손절선 위반 (SELL ALL)
        </span>
        <span>
          <span className="inline-block w-2.5 h-2.5 mr-1 align-middle" style={{ background: VIOLATION_COLORS.overweight }} />
          비중 초과 (REDUCE)
        </span>
      </div>
    </div>
  );
}
