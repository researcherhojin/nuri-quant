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

interface SparklineProps {
  series: number[];
  width?: number;
  height?: number;
  strokeWidth?: number;
  className?: string;
}

export function Sparkline({
  series,
  width = 80,
  height = 18,
  strokeWidth = 1.25,
  className = "",
}: SparklineProps) {
  if (!series || series.length < 2) {
    return (
      <span
        className={`text-zinc-700 text-[10px] ${className}`}
        data-testid="sparkline"
        aria-label="30일 추세"
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

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={`shrink-0 ${className}`}
      data-testid="sparkline"
      data-direction={isUp ? "up" : "down"}
      aria-label={`30일 추세 (${isUp ? "상승" : "하락"})`}
      role="img"
    >
      <path d={areaPath} fill={fill} />
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
