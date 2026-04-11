"use client";

/**
 * SectorDonut — small Recharts donut for the holdings summary panel (#221).
 *
 * Receives pre-aggregated SectorSlice[] from summarizeHoldings(). Client
 * Component because Recharts uses refs + layout effects; the parent panel
 * stays a Server Component and just renders this as a child.
 */

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import type { SectorSlice } from "@/lib/holdings-summary";

interface SectorDonutProps {
  slices: SectorSlice[];
  /** Pixel diameter (default matches panel card width budget) */
  size?: number;
}

export function SectorDonut({ slices, size = 110 }: SectorDonutProps) {
  if (slices.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-[10px] text-zinc-600"
        style={{ width: size, height: size }}
        data-testid="sector-donut-empty"
      >
        —
      </div>
    );
  }
  return (
    <div style={{ width: size, height: size }} data-testid="sector-donut">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
          <Pie
            data={slices}
            dataKey="weight"
            nameKey="name"
            innerRadius={size * 0.3}
            outerRadius={size * 0.48}
            paddingAngle={1}
            stroke="none"
            isAnimationActive={false}
          >
            {slices.map((s) => (
              <Cell key={s.name} fill={s.color} />
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
            formatter={(value) => {
              const n = typeof value === "number" ? value : Number(value);
              return Number.isFinite(n) ? `${n.toFixed(1)}%` : "—";
            }}
            separator=""
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
