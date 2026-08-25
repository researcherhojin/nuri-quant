"use client";

/**
 * PortfolioTreemap — 종목별 가치(면적) × 손익(색) treemap (#1225).
 * violation 테두리: 손절=빨강, 비중초과=노랑 — Plotly 원본에서 계산만 되고
 * 배선 안 됐던 테두리를 네이티브에서 실제로 그린다.
 */
import type { ReactElement } from "react";
import { EVIDENCE } from "@/lib/strings";
import { ResponsiveContainer, Treemap, Tooltip } from "recharts";

import {
  pnlColor,
  VIOLATION_COLORS,
  type HeatmapData,
  type HeatmapItem,
} from "@/components/evidence/chart-data";

export interface TreemapDatum {
  // recharts TreemapDataType 이 string 인덱스 시그니처를 요구한다
  [key: string]: unknown;
  name: string;
  size: number;
  pnl_pct: number;
  weight_pct: number;
  violation: HeatmapItem["violation"];
}

/** API items → Treemap data (가치 0 이하는 1 로 클립 — 원본 동작) */
export function buildTreemapData(data: HeatmapData): TreemapDatum[] {
  return data.items.map((i) => ({
    name: i.ticker,
    size: Math.max(i.current_value_usd, 1),
    pnl_pct: i.pnl_pct,
    weight_pct: i.weight_pct,
    violation: i.violation,
  }));
}

export function cellStroke(violation: HeatmapItem["violation"]): string {
  return violation ? VIOLATION_COLORS[violation] : "#27272a";
}

export interface CellProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  name?: string;
  pnl_pct?: number;
  violation?: HeatmapItem["violation"];
  depth?: number;
}

export function TreemapCell(props: CellProps): ReactElement {
  const { x = 0, y = 0, width = 0, height = 0, name, pnl_pct, violation, depth } = props;
  // depth 0 = 루트 컨테이너 — 칠하지 않는다
  if (depth === 0) return <g />;
  const pnl = pnl_pct ?? 0;
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={pnlColor(pnl)}
        stroke={cellStroke(violation ?? null)}
        strokeWidth={violation ? 2 : 1}
      />
      {width > 44 && height > 20 && (
        <text x={x + 6} y={y + 16} fill="#fafafa" fontSize={11} fontWeight={500}>
          {name}
        </text>
      )}
      {width > 60 && height > 36 && (
        <text x={x + 6} y={y + 30} fill="#d4d4d8" fontSize={10}>
          {pnl >= 0 ? "+" : ""}
          {pnl.toFixed(1)}%
        </text>
      )}
    </g>
  );
}

export function valueTooltipFormatter(value: unknown): [string, string] {
  return [`$${Number(value).toLocaleString()}`, "가치"];
}

export function PortfolioTreemap({ data }: { data: HeatmapData }) {
  const rows = buildTreemapData(data);
  return (
    <div className="w-full min-w-0 h-80" data-testid="portfolio-treemap" role="img" aria-label={EVIDENCE.TITLE_HEATMAP}>
      <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={280}>
        <Treemap
          data={rows}
          dataKey="size"
          nameKey="name"
          isAnimationActive={false}
          content={(props) => <TreemapCell {...(props as CellProps)} />}
        >
          <Tooltip
            contentStyle={{
              backgroundColor: "#18181b",
              border: "1px solid #3f3f46",
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={valueTooltipFormatter}
          />
        </Treemap>
      </ResponsiveContainer>
      <div className="flex gap-4 mt-1 text-[10px] text-muted-foreground justify-center">
        <span>
          <span className="inline-block w-2.5 h-2.5 mr-1 align-middle" style={{ background: "#2e7d32" }} />
          이익
        </span>
        <span>
          <span className="inline-block w-2.5 h-2.5 mr-1 align-middle" style={{ background: "#d32f2f" }} />
          손실
        </span>
        <span>
          <span
            className="inline-block w-2.5 h-2.5 mr-1 align-middle border-2"
            style={{ borderColor: VIOLATION_COLORS.stop_loss }}
          />
          손절 위반
        </span>
        <span>
          <span
            className="inline-block w-2.5 h-2.5 mr-1 align-middle border-2"
            style={{ borderColor: VIOLATION_COLORS.overweight }}
          />
          비중 초과
        </span>
      </div>
    </div>
  );
}
