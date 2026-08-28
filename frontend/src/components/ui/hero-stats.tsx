/**
 * HeroStats — top-of-dashboard 4-stat hero strip (#223 iter 7).
 *
 * Inspired by Snowball Analytics' overview header. Replaces the old single
 * "$74,237" + verdict pill hero. Each stat occupies an equal column.
 *
 * Stat order (#223 iter 7 — tuned for 단타 use case):
 *   1. 총 자산        — total wealth (holdings + cash)
 *   2. 오늘 P&L       — today's $ + % move (visible holdings)
 *   3. 누적 수익률    — cumulative gain $ + %
 *   4. 승률           — winners / (winners+losers) × 100
 *
 * Note: 연 배당 was originally planned as the 4th stat but the user's active
 * accounts are short-term trading (단타), where dividend yield is not a
 * meaningful metric. Long-term/dividend holdings live in pension which is
 * filtered out of the visible subset. 승률 is the more useful 4th stat.
 *
 * Server Component. Pure presentational; consumes pre-computed numbers.
 */

import Link from "next/link";

import type { HoldingsSummary } from "@/lib/holdings-summary";
import { HERO } from "@/lib/strings";

interface HeroStatsProps {
  // #1284: 환율 미수집이면 통화 혼합 합계가 **미상**이다 — null 이 온다.
  // 0 으로 접으면 "자산 0원" 이라는 거짓을 헤드라인에 띄우게 된다.
  totalUsd: number | null;
  cashTotalUsd: number | null;
  holdingsValueUsd: number | null;
  summary: HoldingsSummary;
  /** 값을 못 낸 사유 (#1284). 조용한 "—" 는 결함처럼 보이므로 함께 표시한다. */
  unavailableReason?: string | null;
}

function formatBigUsd(v: number | null): string {
  return v == null ? "—" : `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
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
  unavailableReason,
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
          <p className="text-[11px] text-zinc-400 uppercase tracking-wide">{HERO.TOTAL_ASSET}</p>
          {/* verdict 배지는 VerdictBanner 로 승격 (#1206) — 히어로는 스냅샷 수치만 */}
          <div className="flex items-baseline gap-2 mt-0.5">
            <span className="text-xl font-semibold tabular-nums tracking-tight text-zinc-100">
              {formatBigUsd(totalUsd)}
            </span>
          </div>
          {unavailableReason ? (
            <p className="text-xs text-amber-400/90 mt-1" data-testid="hero-total-unavailable">
              {unavailableReason}
            </p>
          ) : (
            ((holdingsValueUsd ?? 0) > 0 || (cashTotalUsd ?? 0) > 0) && (
              <p className="text-xs text-zinc-400 mt-1 tabular-nums">
                {HERO.HOLDINGS_PREFIX} {formatBigUsd(holdingsValueUsd)}
                {" · "}
                {HERO.CASH_PREFIX} {formatBigUsd(cashTotalUsd)}
              </p>
            )
          )}
        </div>

        {/* 2. 오늘 P&L */}
        <div className="flex flex-col" data-testid="hero-today">
          <p className="text-[11px] text-zinc-400 uppercase tracking-wide">{HERO.TODAY_PNL}</p>
          <div className={`flex items-baseline gap-2 mt-0.5 ${todayColor}`}>
            <span className="text-xl font-semibold tabular-nums tracking-tight">
              {todayArrow} {formatDeltaUsd(t.totalUsd)}
            </span>
            <span className="text-sm tabular-nums">
              {t.totalPct >= 0 ? "+" : ""}
              {t.totalPct.toFixed(2)}%
            </span>
          </div>
          <p className="text-xs text-zinc-400 mt-1 tabular-nums">
            <span className="text-emerald-500">&uarr; {t.upCount}</span>
            {" · "}
            <span className="text-red-500">&darr; {t.downCount}</span>
          </p>
        </div>

        {/* 3. 누적 수익률 */}
        <div className="flex flex-col" data-testid="hero-cumulative">
          <p className="text-[11px] text-zinc-400 uppercase tracking-wide">{HERO.CUMULATIVE_RETURN}</p>
          <div className={`flex items-baseline gap-2 mt-0.5 ${cumColor}`}>
            <span className="text-xl font-semibold tabular-nums tracking-tight">
              {cumArrow} {formatDeltaUsd(c.totalUsd)}
            </span>
            <span className="text-sm tabular-nums">
              {c.totalPct >= 0 ? "+" : ""}
              {c.totalPct.toFixed(1)}%
            </span>
          </div>
          <p className="text-xs text-zinc-400 mt-1">{HERO.CUMULATIVE_SUB}</p>
        </div>

        {/* 4. 승률 (winners / (winners+losers) × 100) — replaces 연 배당.
            Color: emerald when ≥60%, amber 40-60, red <40. */}
        {(() => {
          const wr = summary.winRate;
          const movers = wr.winners + wr.losers;
          const wrColor =
            movers === 0
              ? "text-zinc-600"
              : wr.winRatePct >= 60
              ? "text-emerald-400"
              : wr.winRatePct >= 40
              ? "text-amber-400"
              : "text-red-400";
          return (
            <div className="flex flex-col" data-testid="hero-winrate">
              <p className="text-[11px] text-zinc-400 uppercase tracking-wide">{HERO.WIN_RATE}</p>
              <div className={`flex items-baseline gap-2 mt-0.5 ${wrColor}`}>
                <span className="text-xl font-semibold tabular-nums tracking-tight">
                  {movers > 0 ? `${wr.winRatePct.toFixed(0)}%` : "—"}
                </span>
                <span className="text-sm tabular-nums">
                  {movers > 0 ? `${wr.winners}W / ${wr.losers}L` : ""}
                </span>
              </div>
              {/* #1185: 승률은 보유 종목의 미실현 스냅샷 — 시스템 판정 성과(원장)로 오독 금지 */}
              <p className="text-xs text-zinc-400 mt-1">
                {wr.flat > 0 ? `${HERO.FLAT} ${wr.flat} · ` : ""}{HERO.WIN_RATE_SCOPE}
              </p>
            </div>
          );
        })()}
      </div>

      {/* #1185: 출처 분리 (§3.11) — 위 4지표는 전부 스냅샷. 판정 성과는 원장(/decisions)에서만 */}
      <p className="text-[10px] text-zinc-500" data-testid="hero-provenance">
        {HERO.PROVENANCE_SNAPSHOT}
        {" — "}
        {HERO.PROVENANCE_SCOPE}
        {" · "}
        {HERO.PROVENANCE_LEDGER_LINK}{" "}
        <Link href="/decisions" className="underline decoration-zinc-700 hover:text-zinc-300 transition-colors">
          /decisions →
        </Link>
      </p>
    </section>
  );
}
