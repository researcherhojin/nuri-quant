/**
 * HoldingsSummaryPanel — right-side sticky cards for 2xl+ wide screens (#221).
 *
 * Renders four compact cards fed by summarizeHoldings():
 *   1. Today       — aggregate $ and % move today
 *   2. By sector   — donut + top-5 legend
 *   3. Movers      — top 3 winners / top 3 losers by cumulative pnl
 *   4. Concentration — Herfindahl + single-largest position
 *
 * Server Component; the donut child is the only "use client" boundary.
 * No new data fetches — everything comes from the already-enriched holdings
 * array that page.tsx already has in scope.
 */

import { SectorDonut } from "@/components/ui/sector-donut";
import type { HoldingsSummary } from "@/lib/holdings-summary";

interface HoldingsSummaryPanelProps {
  summary: HoldingsSummary;
  className?: string;
}

const cardClass =
  "rounded bg-zinc-900/40 border border-zinc-800/60 px-3 py-2";
const cardLabelClass =
  "text-[9px] text-zinc-500 uppercase tracking-wide";

function formatUsd(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1000) return `$${Math.round(abs).toLocaleString()}`;
  return `$${abs.toFixed(2)}`;
}

export function HoldingsSummaryPanel({
  summary,
  className = "",
}: HoldingsSummaryPanelProps) {
  const t = summary.today;
  const todayPositive = t.totalUsd >= 0;
  const todayColor = todayPositive ? "text-emerald-400" : "text-red-400";
  const todayArrow = todayPositive ? "\u25B2" : "\u25BC";

  const hasAnyMover =
    summary.topMovers.winners.length > 0 || summary.topMovers.losers.length > 0;

  const concLevelColor =
    summary.concentration.level === "high"
      ? "text-amber-400"
      : summary.concentration.level === "medium"
      ? "text-zinc-200"
      : "text-emerald-400";

  return (
    <aside
      className={`flex flex-col gap-3 ${className}`}
      data-testid="holdings-summary-panel"
      aria-label="보유 종목 요약"
    >
      {/* 1) Today */}
      <div className={cardClass} data-testid="summary-today">
        <p className={cardLabelClass}>Today</p>
        <div className={`flex items-baseline gap-1.5 mt-0.5 ${todayColor}`}>
          <span className="text-sm font-semibold tabular-nums">
            {todayArrow} {formatUsd(t.totalUsd)}
          </span>
          <span className="text-[10px] tabular-nums">
            {t.totalPct >= 0 ? "+" : ""}
            {t.totalPct.toFixed(2)}%
          </span>
        </div>
        <p className="text-[10px] text-zinc-500 mt-0.5 tabular-nums">
          <span className="text-emerald-500">&uarr; {t.upCount}</span>
          {" \u00B7 "}
          <span className="text-red-500">&darr; {t.downCount}</span>
        </p>
      </div>

      {/* 2) By sector */}
      {summary.sectors.length > 0 && (
        <div className={cardClass} data-testid="summary-sectors">
          <p className={cardLabelClass}>By sector</p>
          <div className="flex justify-center py-1">
            <SectorDonut slices={summary.sectors} size={110} />
          </div>
          <div className="flex flex-col gap-0.5 mt-1">
            {summary.sectors.map((s) => (
              <div
                key={s.name}
                className="flex items-center justify-between text-[10px]"
              >
                <span className="flex items-center gap-1.5 text-zinc-400 min-w-0">
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-sm shrink-0"
                    style={{ background: s.color }}
                  />
                  <span className="truncate">{s.name}</span>
                </span>
                <span className="text-zinc-300 tabular-nums shrink-0 ml-2">
                  {s.weight.toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 3) Movers */}
      {hasAnyMover && (
        <div className={cardClass} data-testid="summary-movers">
          <p className={cardLabelClass}>Movers</p>
          <div className="space-y-0.5 mt-1">
            {summary.topMovers.winners.map((m) => (
              <div
                key={`up-${m.account}-${m.ticker}`}
                className="flex items-center justify-between text-[10px]"
              >
                <span className="flex items-center gap-1 min-w-0">
                  <span className="text-emerald-400 shrink-0">&uarr;</span>
                  <span className="text-zinc-200 truncate">{m.ticker}</span>
                </span>
                <span className="text-emerald-400 tabular-nums shrink-0 ml-2">
                  +{m.pnlPct.toFixed(1)}%
                </span>
              </div>
            ))}
            {summary.topMovers.winners.length > 0 &&
              summary.topMovers.losers.length > 0 && (
                <div className="border-t border-zinc-800/60 my-1" />
              )}
            {summary.topMovers.losers.map((m) => (
              <div
                key={`down-${m.account}-${m.ticker}`}
                className="flex items-center justify-between text-[10px]"
              >
                <span className="flex items-center gap-1 min-w-0">
                  <span className="text-red-400 shrink-0">&darr;</span>
                  <span className="text-zinc-200 truncate">{m.ticker}</span>
                </span>
                <span className="text-red-400 tabular-nums shrink-0 ml-2">
                  {m.pnlPct.toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 4) Concentration */}
      {summary.concentration.topHolding && (
        <div className={cardClass} data-testid="summary-concentration">
          <p className={cardLabelClass}>Concentration</p>
          <div className="flex items-baseline gap-2 mt-0.5">
            <span className={`text-sm font-semibold tabular-nums ${concLevelColor}`}>
              HHI {summary.concentration.herfindahl.toFixed(2)}
            </span>
            <span className="text-[9px] text-zinc-600 uppercase">
              {summary.concentration.level}
            </span>
          </div>
          <p className="text-[10px] text-zinc-500 mt-0.5 truncate">
            Top:{" "}
            <span className="text-zinc-200">
              {summary.concentration.topHolding.ticker}
            </span>{" "}
            <span className="text-zinc-400 tabular-nums">
              {summary.concentration.topHolding.weight.toFixed(1)}%
            </span>
          </p>
        </div>
      )}
    </aside>
  );
}
