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

      {/* Donut + Legend */}
      <div className="flex flex-col lg:flex-row gap-6 items-start" data-testid="composition-body">
        {/* Donut */}
        <div className="shrink-0 self-center lg:self-start">
          <CompositionDonut
            slices={slices}
            size={240}
            centerLabel={hasData ? totalLabel : undefined}
            centerSubLabel={hasData ? "총 자산" : undefined}
          />
        </div>

        {/* Legend table */}
        {hasData ? (
          <div
            className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 self-stretch"
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
      </div>
    </section>
  );
}
