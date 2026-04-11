/**
 * HeroStats — top-of-dashboard 4-stat hero strip (#223).
 *
 * Inspired by Snowball Analytics' overview header. Replaces the old single
 * "$74,237" + verdict pill hero. Each stat occupies an equal column.
 *
 * Stat order (Snowball convention):
 *   1. 총 자산        — total wealth (holdings + cash)
 *   2. 오늘 P&L       — today's $ + % move (visible holdings)
 *   3. 누적 수익률    — cumulative gain $ + %
 *   4. 연 배당        — placeholder (data not yet collected)
 *
 * Server Component. Pure presentational; consumes pre-computed numbers.
 */

import { StatusBadge } from "@/components/ui/status-badge";
import type { HoldingsSummary } from "@/lib/holdings-summary";

interface HeroStatsProps {
  totalUsd: number;
  cashTotalUsd: number;
  holdingsValueUsd: number;
  summary: HoldingsSummary;
  verdictLabel: string;
}

function formatBigUsd(v: number): string {
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatDeltaUsd(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1000) return `$${Math.round(abs).toLocaleString()}`;
  return `$${abs.toFixed(0)}`;
}

export function HeroStats({
  totalUsd,
  cashTotalUsd,
  holdingsValueUsd,
  summary,
  verdictLabel,
}: HeroStatsProps) {
  const t = summary.today;
  const c = summary.cumulative;
  const todayUp = t.totalUsd >= 0;
  const cumUp = c.totalUsd >= 0;
  const todayColor = todayUp ? "text-emerald-400" : "text-red-400";
  const cumColor = cumUp ? "text-emerald-400" : "text-red-400";
  const todayArrow = todayUp ? "\u25B2" : "\u25BC";
  const cumArrow = cumUp ? "\u25B2" : "\u25BC";

  return (
    <section className="flex flex-col gap-2" data-testid="hero-stats">
      {/* 4-column big stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {/* 1. 총 자산 */}
        <div className="flex flex-col" data-testid="hero-total">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wide">총 자산</p>
          <div className="flex items-baseline gap-2 mt-0.5">
            <span className="text-3xl font-semibold tabular-nums tracking-tight text-zinc-100">
              {formatBigUsd(totalUsd)}
            </span>
            <StatusBadge status={verdictLabel} />
          </div>
          {(holdingsValueUsd > 0 || cashTotalUsd > 0) && (
            <p className="text-[10px] text-zinc-500 mt-1 tabular-nums">
              보유 ${holdingsValueUsd.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              {" · "}
              현금 ${cashTotalUsd.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </p>
          )}
        </div>

        {/* 2. 오늘 P&L */}
        <div className="flex flex-col" data-testid="hero-today">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wide">오늘 P&amp;L</p>
          <div className={`flex items-baseline gap-2 mt-0.5 ${todayColor}`}>
            <span className="text-3xl font-semibold tabular-nums tracking-tight">
              {todayArrow} {formatDeltaUsd(t.totalUsd)}
            </span>
            <span className="text-sm tabular-nums">
              {t.totalPct >= 0 ? "+" : ""}
              {t.totalPct.toFixed(2)}%
            </span>
          </div>
          <p className="text-[10px] text-zinc-500 mt-1 tabular-nums">
            <span className="text-emerald-500">&uarr; {t.upCount}</span>
            {" · "}
            <span className="text-red-500">&darr; {t.downCount}</span>
          </p>
        </div>

        {/* 3. 누적 수익률 */}
        <div className="flex flex-col" data-testid="hero-cumulative">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wide">누적 수익률</p>
          <div className={`flex items-baseline gap-2 mt-0.5 ${cumColor}`}>
            <span className="text-3xl font-semibold tabular-nums tracking-tight">
              {cumArrow} {formatDeltaUsd(c.totalUsd)}
            </span>
            <span className="text-sm tabular-nums">
              {c.totalPct >= 0 ? "+" : ""}
              {c.totalPct.toFixed(1)}%
            </span>
          </div>
          <p className="text-[10px] text-zinc-500 mt-1">실현 미실현 합계</p>
        </div>

        {/* 4. 연 배당 (placeholder — data not collected yet) */}
        <div className="flex flex-col" data-testid="hero-dividend">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wide">연 배당</p>
          <div className="flex items-baseline gap-2 mt-0.5 text-zinc-600">
            <span className="text-3xl font-semibold tabular-nums tracking-tight">—</span>
          </div>
          <p className="text-[10px] text-zinc-700 mt-1">데이터 수집 예정</p>
        </div>
      </div>
    </section>
  );
}
