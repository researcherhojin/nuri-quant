/**
 * CompositionSection — main composition view for the dashboard (#223).
 *
 * Snowball Analytics-inspired layout: tabs to switch between
 *   - 자산 (ticker-level, top 12 + Other)
 *   - 섹터 (sector aggregation)
 *   - 계좌 (account aggregation, holdings + cash merged)
 *
 * Big donut on the left, scrolling legend on the right. Tabs are URL-driven
 * (?comp=ticker|sector|account) so the page stays a Server Component and the
 * URL is shareable / refreshable.
 *
 * Server Component. Donut child uses "use client" but data flows down.
 */

import Link from "next/link";

import { CompositionDonut, type DonutSlice } from "@/components/ui/composition-donut";
import type { HoldingsSummary } from "@/lib/holdings-summary";

export const COMPOSITION_TABS = ["ticker", "sector", "account"] as const;
export type CompositionTab = (typeof COMPOSITION_TABS)[number];

const TAB_LABELS: Record<CompositionTab, string> = {
  ticker: "자산",
  sector: "섹터",
  account: "계좌",
};

export function parseCompositionTab(raw: string | undefined): CompositionTab {
  if (raw === "sector" || raw === "account" || raw === "ticker") return raw;
  return "ticker";
}

interface CompositionSectionProps {
  summary: HoldingsSummary;
  totalUsd: number;
  activeTab: CompositionTab;
}

const sideCardClass =
  "rounded bg-zinc-900/40 border border-zinc-800/60 px-3 py-2 flex flex-col gap-1";
const sideCardLabelClass =
  "text-[9px] text-zinc-500 uppercase tracking-wide";

interface LegendRow {
  label: string;
  /** Optional second-line meta (e.g. sector for ticker rows) */
  meta?: string | null;
  weight: number;
  valueUsd: number | null;
  /** Aggregate daily move % across the slice (null when no data) */
  dailyDeltaPct: number | null;
  color: string;
}

function buildSlicesAndLegend(
  summary: HoldingsSummary,
  tab: CompositionTab,
): { slices: DonutSlice[]; legend: LegendRow[] } {
  if (tab === "ticker") {
    return {
      slices: summary.byTicker.map((t) => ({
        label: t.displayName,
        value: t.weight,
        color: t.color,
      })),
      legend: summary.byTicker.map((t) => ({
        label: t.displayName,
        meta: t.sector,
        weight: t.weight,
        valueUsd: t.valueUsd,
        dailyDeltaPct: t.dailyDeltaPct,
        color: t.color,
      })),
    };
  }
  if (tab === "sector") {
    return {
      slices: summary.sectors.map((s) => ({
        label: s.name,
        value: s.weight,
        color: s.color,
      })),
      legend: summary.sectors.map((s) => ({
        label: s.name,
        meta: null,
        weight: s.weight,
        valueUsd: s.valueUsd,
        dailyDeltaPct: s.dailyDeltaPct,
        color: s.color,
      })),
    };
  }
  // account
  return {
    slices: summary.byAccount.map((a) => ({
      label: a.account,
      value: a.weight,
      color: a.color,
    })),
    legend: summary.byAccount.map((a) => ({
      label: a.account,
      meta: null,
      weight: a.weight,
      valueUsd: a.valueUsd,
      dailyDeltaPct: a.dailyDeltaPct,
      color: a.color,
    })),
  };
}

function tabHref(tab: CompositionTab): string {
  return tab === "ticker" ? "/" : `/?comp=${tab}`;
}

export function CompositionSection({
  summary,
  totalUsd,
  activeTab,
}: CompositionSectionProps) {
  const { slices, legend } = buildSlicesAndLegend(summary, activeTab);
  const hasData = slices.length > 0;
  const totalLabel = `$${totalUsd.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

  return (
    <section className="flex flex-col gap-2" data-testid="composition-section">
      {/* Tabs row */}
      <div className="flex items-center justify-between">
        <div
          className="flex items-center gap-1 text-[11px]"
          data-testid="composition-tabs"
          role="tablist"
        >
          {COMPOSITION_TABS.map((t) => {
            const active = t === activeTab;
            return (
              <Link
                key={t}
                href={tabHref(t)}
                scroll={false}
                role="tab"
                aria-selected={active}
                data-testid={`composition-tab-${t}`}
                className={`px-2.5 py-1 rounded transition-colors ${
                  active
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-900/60"
                }`}
              >
                {TAB_LABELS[t]}
              </Link>
            );
          })}
        </div>
      </div>

      {/* Donut + Rich Legend (2 columns at lg+) */}
      <div className="flex flex-col lg:flex-row gap-6 items-start" data-testid="composition-body">
        {/* Donut — 320px centerpiece */}
        <div className="shrink-0 self-center lg:self-start">
          <CompositionDonut
            slices={slices}
            size={320}
            centerLabel={hasData ? totalLabel : undefined}
            centerSubLabel={hasData ? "총 자산" : undefined}
          />
        </div>

        {/* Rich legend — single column, dense rows. Each row:
            color dot · label · sector(meta) · $value · weight % · daily delta % */}
        {hasData ? (
          <div
            className="flex-1 flex flex-col gap-1 self-stretch min-w-0 max-w-[640px]"
            data-testid="composition-legend"
          >
            {legend.map((row) => {
              const deltaUp = (row.dailyDeltaPct ?? 0) >= 0;
              const hasDelta = row.dailyDeltaPct != null && Number.isFinite(row.dailyDeltaPct);
              const deltaColor = !hasDelta
                ? "text-zinc-700"
                : deltaUp
                ? "text-emerald-400"
                : "text-red-400";
              return (
                <div
                  key={row.label}
                  className="flex items-center gap-3 text-[11px] py-0.5 px-1 rounded hover:bg-zinc-900/40 min-w-0"
                  data-testid={`composition-legend-${row.label}`}
                >
                  {/* color dot */}
                  <span
                    className="inline-block h-2 w-2 rounded-sm shrink-0"
                    style={{ background: row.color }}
                  />
                  {/* primary label */}
                  <span className="text-zinc-200 truncate min-w-0 flex-1 sm:flex-none sm:w-[120px]">
                    {row.label}
                  </span>
                  {/* meta (sector for ticker rows) */}
                  <span className="hidden sm:inline-block text-zinc-600 truncate w-[110px] text-[10px]">
                    {row.meta ?? ""}
                  </span>
                  {/* USD value */}
                  <span className="hidden md:inline-block text-zinc-500 tabular-nums w-[80px] text-right text-[10px]">
                    {row.valueUsd != null
                      ? `$${row.valueUsd.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                      : ""}
                  </span>
                  {/* weight % */}
                  <span className="text-zinc-200 font-semibold tabular-nums w-[52px] text-right">
                    {row.weight.toFixed(1)}%
                  </span>
                  {/* daily delta */}
                  <span className={`tabular-nums w-[58px] text-right text-[10px] ${deltaColor}`}>
                    {hasDelta
                      ? `${deltaUp ? "+" : ""}${row.dailyDeltaPct!.toFixed(2)}%`
                      : "—"}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-[11px] text-zinc-600">표시할 데이터가 없습니다.</p>
        )}
      </div>

      {/* Mini stats strip — horizontal row of context cards below the donut.
          Movers (top 3 / 3) · Concentration · (room for more later). */}
      <div className="flex flex-row gap-3 mt-1 flex-wrap" data-testid="composition-side-cards">
        {(summary.topMovers.winners.length > 0 || summary.topMovers.losers.length > 0) && (
          <div className={`${sideCardClass} flex-1 min-w-[200px] max-w-[280px]`} data-testid="side-movers">
            <p className={sideCardLabelClass}>Movers (cumulative)</p>
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 mt-0.5">
              <div>
                {summary.topMovers.winners.map((m) => (
                  <div
                    key={`up-${m.account}-${m.ticker}`}
                    className="flex items-center justify-between text-[10px]"
                  >
                    <span className="flex items-center gap-1 min-w-0">
                      <span className="text-emerald-400 shrink-0">&uarr;</span>
                      <span className="text-zinc-200 truncate">{m.ticker}</span>
                    </span>
                    <span className="text-emerald-400 tabular-nums shrink-0 ml-1">
                      +{m.pnlPct.toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
              <div>
                {summary.topMovers.losers.length > 0 ? (
                  summary.topMovers.losers.map((m) => (
                    <div
                      key={`down-${m.account}-${m.ticker}`}
                      className="flex items-center justify-between text-[10px]"
                    >
                      <span className="flex items-center gap-1 min-w-0">
                        <span className="text-red-400 shrink-0">&darr;</span>
                        <span className="text-zinc-200 truncate">{m.ticker}</span>
                      </span>
                      <span className="text-red-400 tabular-nums shrink-0 ml-1">
                        {m.pnlPct.toFixed(1)}%
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-[10px] text-zinc-700">손실 없음</p>
                )}
              </div>
            </div>
          </div>
        )}

        {summary.concentration.topHolding && (
          <div className={`${sideCardClass} flex-1 min-w-[180px] max-w-[240px]`} data-testid="side-concentration">
            <p className={sideCardLabelClass}>집중도 (HHI)</p>
            <div className="flex items-baseline gap-2 mt-0.5">
              <span
                className={`text-sm font-semibold tabular-nums ${
                  summary.concentration.level === "high"
                    ? "text-amber-400"
                    : summary.concentration.level === "medium"
                    ? "text-zinc-200"
                    : "text-emerald-400"
                }`}
              >
                {summary.concentration.herfindahl.toFixed(2)}
              </span>
              <span className="text-[9px] text-zinc-600 uppercase">
                {summary.concentration.level}
              </span>
            </div>
            <p className="text-[10px] text-zinc-500 truncate">
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

        {/* Win rate snapshot */}
        <div className={`${sideCardClass} flex-1 min-w-[160px] max-w-[200px]`} data-testid="side-winrate">
          <p className={sideCardLabelClass}>승률</p>
          <div className="flex items-baseline gap-2 mt-0.5">
            <span
              className={`text-sm font-semibold tabular-nums ${
                summary.winRate.winners + summary.winRate.losers === 0
                  ? "text-zinc-600"
                  : summary.winRate.winRatePct >= 60
                  ? "text-emerald-400"
                  : summary.winRate.winRatePct >= 40
                  ? "text-amber-400"
                  : "text-red-400"
              }`}
            >
              {summary.winRate.winners + summary.winRate.losers > 0
                ? `${summary.winRate.winRatePct.toFixed(0)}%`
                : "—"}
            </span>
            <span className="text-[10px] text-zinc-500 tabular-nums">
              {summary.winRate.winners}W / {summary.winRate.losers}L
            </span>
          </div>
          {summary.winRate.flat > 0 && (
            <p className="text-[10px] text-zinc-700">보합 {summary.winRate.flat}</p>
          )}
        </div>
      </div>
    </section>
  );
}
