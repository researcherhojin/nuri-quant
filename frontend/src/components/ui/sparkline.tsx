/**
 * Sparkline — SVG polyline micro chart (Phase 2-D #214 follow-up).
 *
 * Renders a compact price trend chart for a numeric series. Pure JSX SVG,
 * Server Component compatible (no React hooks, no client boundary).
 * Used inline in HoldingRow to show 30-day price history per holding.
 *
 * Design:
 * - Min-max normalize the series to the [0, height] range
 * - Flip y-axis (SVG origin is top-left; prices go up visually)
 * - Color: emerald tint when ending ≥ starting, red tint otherwise
 * - Flat series → horizontal midline
 * - Empty/single-point series → em-dash placeholder
 */

import { SPARKLINE as S } from "@/lib/strings";

interface SparklineProps {
  series: number[];
  width?: number;
  height?: number;
  strokeWidth?: number;
  className?: string;
  /**
   * Optional horizontal reference line drawn across the chart.
   * Use case: avg cost basis so the reader can see "above or below break-even".
   * The baseline is clamped to the [min, max] of the series so it is always visible;
   * if it falls outside the range the line is drawn at the nearest edge.
   */
  baseline?: number | null;
}

export function Sparkline({
  series,
  width = 80,
  height = 18,
  strokeWidth = 1.25,
  className = "",
  baseline = null,
}: SparklineProps) {
  if (!series || series.length < 2) {
    return (
      <span
        className={`text-zinc-700 text-[10px] ${className}`}
        data-testid="sparkline"
        aria-label={S.TREND_30D}
      >
        —
      </span>
    );
  }

  const min = Math.min(...series);
  const max = Math.max(...series);
  const range = max - min;

  // Flat series → draw horizontal line at mid-height
  const points = series
    .map((v, i) => {
      const x = (i / (series.length - 1)) * (width - strokeWidth * 2) + strokeWidth;
      const y =
        range === 0
          ? height / 2
          : height - strokeWidth - ((v - min) / range) * (height - strokeWidth * 2);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  const isUp = series[series.length - 1] >= series[0];
  const stroke = isUp ? "rgb(52 211 153 / 0.9)" : "rgb(248 113 113 / 0.9)";
  const fill = isUp ? "rgb(52 211 153 / 0.08)" : "rgb(248 113 113 / 0.08)";

  // Area fill path: polyline + bottom corners closed
  const areaPath = `M ${points.split(" ").join(" L ")} L ${width - strokeWidth},${height - strokeWidth} L ${strokeWidth},${height - strokeWidth} Z`;

  // Baseline reference (e.g. avg cost basis) — dashed horizontal line at the normalized position
  // Only drawn when the baseline falls within the [min, max] range of the visible series.
  let baselineY: number | null = null;
  if (baseline != null && range > 0 && baseline >= min && baseline <= max) {
    baselineY = height - strokeWidth - ((baseline - min) / range) * (height - strokeWidth * 2);
  }

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={`shrink-0 ${className}`}
      data-testid="sparkline"
      data-direction={isUp ? "up" : "down"}
      aria-label={`${S.PERIOD_LABEL} (${isUp ? S.TREND_UP : S.TREND_DOWN})`}
      role="img"
    >
      <path d={areaPath} fill={fill} />
      {baselineY != null && (
        <line
          x1={0}
          x2={width}
          y1={baselineY}
          y2={baselineY}
          stroke="rgb(161 161 170 / 0.45)"
          strokeWidth={0.75}
          strokeDasharray="2 2"
          data-testid="sparkline-baseline"
        />
      )}
      <polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
