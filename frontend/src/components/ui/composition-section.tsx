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
  weight: number;
  valueUsd: number | null;
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
        weight: t.weight,
        valueUsd: t.valueUsd,
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
        weight: s.weight,
        valueUsd: null,
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
      weight: a.weight,
      valueUsd: a.valueUsd,
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

      {/* Donut + Legend + Side cards (3 columns at lg+) */}
      <div className="flex flex-col lg:flex-row gap-5 items-start" data-testid="composition-body">
        {/* Donut — bigger now (320px) for visual centerpiece */}
        <div className="shrink-0 self-center lg:self-start">
          <CompositionDonut
            slices={slices}
            size={320}
            centerLabel={hasData ? totalLabel : undefined}
            centerSubLabel={hasData ? "총 자산" : undefined}
          />
        </div>

        {/* Legend table */}
        {hasData ? (
          <div
            className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-x-5 gap-y-1 self-stretch min-w-0"
            data-testid="composition-legend"
          >
            {legend.map((row) => (
              <div
                key={row.label}
                className="flex items-center justify-between text-[11px] gap-2 min-w-0"
                data-testid={`composition-legend-${row.label}`}
              >
                <span className="flex items-center gap-2 min-w-0">
                  <span
                    className="inline-block h-2 w-2 rounded-sm shrink-0"
                    style={{ background: row.color }}
                  />
                  <span className="truncate text-zinc-200">{row.label}</span>
                </span>
                <span className="flex items-baseline gap-2 shrink-0 tabular-nums">
                  {row.valueUsd != null && (
                    <span className="text-[10px] text-zinc-600">
                      ${row.valueUsd.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </span>
                  )}
                  <span className="text-zinc-300">{row.weight.toFixed(1)}%</span>
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-[11px] text-zinc-600">표시할 데이터가 없습니다.</p>
        )}

        {/* Side cards (3xl+ only) — Movers + Concentration mini cards */}
        <div
          className="hidden min-[1280px]:flex flex-col gap-3 w-[200px] shrink-0"
          data-testid="composition-side-cards"
        >
          {/* Movers — top 3 winners + losers */}
          {(summary.topMovers.winners.length > 0 || summary.topMovers.losers.length > 0) && (
            <div className={sideCardClass} data-testid="side-movers">
              <p className={sideCardLabelClass}>Movers</p>
              <div className="space-y-0.5">
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

          {/* Concentration */}
          {summary.concentration.topHolding && (
            <div className={sideCardClass} data-testid="side-concentration">
              <p className={sideCardLabelClass}>Concentration</p>
              <div className="flex items-baseline gap-2">
                <span
                  className={`text-sm font-semibold tabular-nums ${
                    summary.concentration.level === "high"
                      ? "text-amber-400"
                      : summary.concentration.level === "medium"
                      ? "text-zinc-200"
                      : "text-emerald-400"
                  }`}
                >
                  HHI {summary.concentration.herfindahl.toFixed(2)}
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
        </div>
      </div>
    </section>
  );
}
