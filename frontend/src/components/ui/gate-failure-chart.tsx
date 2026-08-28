"use client";

/**
 * GateFailureChart — V2.1 (NEXT_SESSION §2.8) observation density 강화.
 *
 * 왜: V2 timeline 이 21 runs / 1 portfolio state 같은 degenerate 입력에서
 * flat line 으로 보이는 문제. condition 수준 분포 (어느 gate 가 noisy 한가)
 * 는 같은 데이터에서도 즉시 variation 보임 → 관찰 가치 확보.
 *
 * 구조: 각 run (x) 에 대해 failed + warning condition 수를 category 별로
 * stacked bar. category = condition id 의 prefix (`:` 전).
 *   - position_limit / sector_limit / stop_loss / leverage_ban / conflict_free /
 *     drift_safe / macro_event_alignment / data_fresh(:us_equity:primary…) /
 *     volatility_gate(:…) / external_data(:…)
 *
 * 색상은 severity 별 팔레트 — error red 계열 / warning amber 계열.
 */
import { CHART_GRID_STROKE, CHART_MUTED, CHART_TOOLTIP_BG, CHART_TOOLTIP_BORDER, CHART_TOOLTIP_ITEM } from "@/lib/chart-theme";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { CertificationPoint, GateCondition } from "@/components/ui/siege-timeline-chart";

export interface GateBarRow {
  id: number;
  short: string;
  /** category → failed/warning count. stacked bar dataKey 소스. */
  [category: string]: number | string;
}

export interface CategoryMeta {
  category: string;
  severity: "error" | "warning";
  color: string;
}

/** Gate id 의 prefix (`:` 전) 를 category 로 normalize. unknown 은 "other". */
export function normalizeGateCategory(id: string): string {
  if (!id) return "other";
  return id.split(":")[0] || "other";
}

/** severity + category 를 색으로. error = red tone, warning = amber tone. 같은 category 안에서 고정. */
const CATEGORY_COLORS: Record<string, { error: string; warning: string }> = {
  position_limit: { error: "#ef4444", warning: "#f59e0b" },
  sector_limit: { error: "#dc2626", warning: "#d97706" },
  stop_loss: { error: "#b91c1c", warning: "#b45309" },
  leverage_ban: { error: "#991b1b", warning: "#92400e" },
  conflict_free: { error: "#f87171", warning: "#fbbf24" },
  drift_safe: { error: "#fb923c", warning: "#fcd34d" },
  macro_event_alignment: { error: "#fdba74", warning: "#fde68a" },
  data_fresh: { error: "#fed7aa", warning: "#fef3c7" },
  volatility_gate: { error: "#c084fc", warning: "#a855f7" },
  external_data: { error: "#93c5fd", warning: "#60a5fa" },
};

export function colorForCategory(category: string, severity: "error" | "warning"): string {
  const entry = CATEGORY_COLORS[category];
  if (entry) return entry[severity];
  return severity === "error" ? "#64748b" : "#94a3b8";
}

/**
 * items (id DESC) 를 받아 각 run 의 conditions[] 를 category 별로 count.
 * passed=true 인 condition 은 skip (관심: failed + warning 만).
 * 반환: (oldest→newest) 순서 + union categories (stack key 고정 순서).
 */
export interface GateFailureData {
  rows: GateBarRow[];
  categories: CategoryMeta[];
  totalRuns: number;
  runsWithIssues: number;
}

export function buildGateFailureData(items: CertificationPoint[]): GateFailureData {
  const ordered = [...items].reverse();
  const catSeverities = new Map<string, "error" | "warning">();
  const rows: GateBarRow[] = ordered.map((p) => {
    const short = p.timestamp.slice(5, 16).replace("T", " ");
    const row: GateBarRow = { id: p.id, short };
    for (const c of p.conditions ?? []) {
      if (c.passed) continue; // only failures + warnings contribute
      const cat = normalizeGateCategory(c.id);
      const key = `${cat}__${c.severity}`;
      row[key] = ((row[key] as number) ?? 0) + 1;
      // category severity: 섞일 수 있으나 동일 category 가 run 마다 다른 severity 일 때
      // "더 심각한 것" 우선 (error > warning) 으로 메타 저장.
      const prev = catSeverities.get(key);
      if (!prev || (prev === "warning" && c.severity === "error")) {
        catSeverities.set(key, c.severity);
      }
    }
    return row;
  });
  const categories: CategoryMeta[] = Array.from(catSeverities.entries())
    .map(([key, severity]) => {
      const category = key.split("__")[0];
      return { category: key, severity, color: colorForCategory(category, severity) };
    })
    .sort((a, b) => {
      // error 먼저, 그 다음 알파벳
      if (a.severity !== b.severity) return a.severity === "error" ? -1 : 1;
      return a.category.localeCompare(b.category);
    });
  const runsWithIssues = rows.filter((r) =>
    Object.keys(r).some((k) => k !== "id" && k !== "short"),
  ).length;
  return { rows, categories, totalRuns: ordered.length, runsWithIssues };
}

/** Legend 표기용 — `data_fresh__warning` → `data_fresh (warning)`. */
export function formatCategoryLabel(key: string): string {
  const [cat, sev] = key.split("__");
  return `${cat} (${sev})`;
}

/**
 * Recharts `<Tooltip formatter>` callback — mock 환경에서 직접 호출 안 되므로
 * module-level named export 로 빼서 unit test 가능하게.
 * 반환: `[displayValue, displayLabel]`.
 */
export function tooltipValueFormatter(value: unknown, name: unknown): [string, string] {
  const label = typeof name === "string" ? formatCategoryLabel(name) : String(name);
  return [`${value}`, label];
}

/** Recharts `<Legend formatter>` — 카테고리 key 를 사람이 읽는 label 로 치환. */
export function legendFormatter(v: unknown): string {
  return typeof v === "string" ? formatCategoryLabel(v) : String(v);
}

interface GateFailureChartProps {
  items: CertificationPoint[];
}

export function GateFailureChart({ items }: GateFailureChartProps) {
  if (!items.length) return null;
  const { rows, categories, totalRuns, runsWithIssues } = buildGateFailureData(items);
  if (!categories.length) {
    return (
      <div className="h-32 flex items-center justify-center text-xs text-muted-foreground">
        최근 {totalRuns}건 모두 failed/warning condition 없음 — gate breakdown 표시할 항목 없음.
      </div>
    );
  }
  return (
    <div className="min-w-0 space-y-2">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-muted-foreground">
          Gate Failures — 최근 {totalRuns}건 ({runsWithIssues} 건에 실패/경고 분포)
        </span>
        <span className="text-[10px] text-muted-foreground/70">
          stacked: category × severity
        </span>
      </div>
      <div className="w-full min-w-0 h-56">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={200}>
          <BarChart data={rows} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
            <XAxis
              dataKey="short"
              tick={{ fontSize: 10, fill: CHART_MUTED }}
              tickLine={false}
              interval={Math.max(0, Math.floor(rows.length / 6) - 1)}
            />
            <YAxis
              tick={{ fontSize: 10, fill: CHART_MUTED }}
              tickLine={false}
              axisLine={false}
              width={28}
              allowDecimals={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: CHART_TOOLTIP_BG,
                border: CHART_TOOLTIP_BORDER,
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: CHART_MUTED }}
              itemStyle={{ color: CHART_TOOLTIP_ITEM }}
              formatter={tooltipValueFormatter as never}
            />
            <Legend
              wrapperStyle={{ fontSize: 10, color: CHART_MUTED }}
              formatter={legendFormatter as never}
            />
            {categories.map((c) => (
              <Bar key={c.category} dataKey={c.category} stackId="fail" fill={c.color} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/** util — certifications-card 에서 직접 사용할 수 있도록 named export. */
export type { GateCondition };
