/**
 * HoldingsSummaryPanel — right-side sticky cards for 3xl+ wide screens (#221).
 *
 * Renders four compact cards fed by summarizeHoldings():
 *   1. Today       — aggregate $ and % move today
 *   2. By sector   — label + horizontal barlist (pure CSS, no chart lib)
 *   3. Movers      — top 3 winners / top 3 losers by cumulative pnl
 *   4. Concentration — Herfindahl + single-largest position
 *
 * Pure Server Component — no "use client" boundary now that the donut
 * has been replaced by a CSS barlist. The barlist matches the rest of
 * the dashboard's text-heavy aesthetic better than a flashy Recharts
 * donut did (#221 iter-3).
 */

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

      {/* 2) By sector — barlist (pure CSS, one row per slice).
          Each row: colored bar (tinted by slice.color) as background at %
          width, label + pct overlaid on top. No Recharts. */}
      {summary.sectors.length > 0 && (
        <div className={cardClass} data-testid="summary-sectors">
          <p className={cardLabelClass}>By sector</p>
          <div className="flex flex-col gap-1 mt-1.5" data-testid="sector-barlist">
            {summary.sectors.map((s) => (
              <div
                key={s.name}
                className="relative h-[16px] rounded-sm overflow-hidden bg-zinc-900/60"
                data-testid={`sector-bar-${s.name}`}
              >
                <div
                  className="absolute inset-y-0 left-0 rounded-sm"
                  style={{ width: `${s.weight}%`, background: s.color, opacity: 0.28 }}
                />
                <div className="relative flex items-center justify-between h-full px-1.5 text-[10px]">
                  <span className="flex items-center gap-1.5 min-w-0">
                    <span
                      className="inline-block h-1.5 w-1.5 rounded-sm shrink-0"
                      style={{ background: s.color }}
                    />
                    <span className="truncate text-zinc-200">{s.name}</span>
                  </span>
                  <span className="text-zinc-300 tabular-nums shrink-0 ml-2">
                    {s.weight.toFixed(1)}%
                  </span>
                </div>
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
