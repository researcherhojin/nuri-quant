"use client";

/**
 * CompositionDonut — large Recharts donut for the dashboard composition
 * section (#223). Pre-computed slices flow in from a Server Component
 * parent. Tailored for the Snowball Analytics-style centered donut with
 * the total value displayed in the middle.
 *
 * Brought back Recharts because the donut here is the centerpiece of the
 * dashboard, not a thin sidebar widget — at 240px diameter the chart needs
 * proper rendering, hover tooltips, and animation.
 */

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

export interface DonutSlice {
  /** Display label shown in the tooltip */
  label: string;
  /** Numeric weight (the donut auto-normalizes to 100% so any units OK) */
  value: number;
  /** Hex color for the slice */
  color: string;
}

interface CompositionDonutProps {
  slices: DonutSlice[];
  /** Pixel diameter of the donut (default 240) */
  size?: number;
  /** Centered text inside the donut (e.g. "$74,237") */
  centerLabel?: string;
  centerSubLabel?: string;
}

export function CompositionDonut({
  slices,
  size = 240,
  centerLabel,
  centerSubLabel,
}: CompositionDonutProps) {
  if (slices.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs text-zinc-600"
        style={{ width: size, height: size }}
        data-testid="composition-donut-empty"
      >
        — 데이터 없음
      </div>
    );
  }
  return (
    <div className="relative" style={{ width: size, height: size }} data-testid="composition-donut">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
          <Pie
            data={slices}
            dataKey="value"
            nameKey="label"
            innerRadius={size * 0.34}
            outerRadius={size * 0.48}
            paddingAngle={1}
            stroke="#0a0a0a"
            strokeWidth={1}
            isAnimationActive={false}
            // #223 iter 7: standard donut orientation — start at 12 o'clock
            // (90°) and go clockwise (decreasing angle). Combined with the
            // weight-desc sort upstream, the largest slice sits at the top
            // and the rest follow clockwise — what users expect from a pie.
            startAngle={90}
            endAngle={-270}
          >
            {slices.map((s) => (
              <Cell key={s.label} fill={s.color} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              background: "#18181b",
              border: "1px solid #27272a",
              borderRadius: 4,
              fontSize: 11,
              padding: "4px 8px",
            }}
            itemStyle={{ color: "#e4e4e7" }}
            formatter={(value, name) => {
              const n = typeof value === "number" ? value : Number(value);
              return [Number.isFinite(n) ? `${n.toFixed(1)}%` : "—", String(name)];
            }}
          />
        </PieChart>
      </ResponsiveContainer>
      {(centerLabel || centerSubLabel) && (
        <div
          className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none"
          data-testid="composition-donut-center"
        >
          {centerLabel && (
            <span className="text-lg font-semibold tabular-nums text-zinc-100">
              {centerLabel}
            </span>
          )}
          {centerSubLabel && (
            <span className="text-[10px] text-zinc-500 mt-0.5">{centerSubLabel}</span>
          )}
        </div>
      )}
    </div>
  );
}
