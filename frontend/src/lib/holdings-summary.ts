/**
 * Holdings summary aggregation (#221)
 *
 * Pure functions that roll up the per-row EnrichedHolding array into four
 * dashboard-level views used by <HoldingsSummaryPanel> at the 2xl+ breakpoint:
 *
 *   1. Today's P&L         — weighted delta aggregation
 *   2. Sector breakdown    — top 4 sectors + Other bucket
 *   3. Top movers          — 3 winners + 3 losers by cumulative pnl
 *   4. Concentration       — Herfindahl index + single-largest weight
 *
 * Designed to avoid any new API call — all inputs come from fields already on
 * EnrichedHolding plus the existing totalPortfolioUsd/usdKrwRate that
 * buildEnrichedHoldings already takes.
 */

import type { EnrichedHolding } from "@/components/ui/holding-row";

export interface TodayPnL {
  /** Aggregate dollar move today (Σ value × dailyDelta) */
  totalUsd: number;
  /** Aggregate percent move today (weighted by positionPct) */
  totalPct: number;
  /** Holdings with dailyDelta > 0 */
  upCount: number;
  /** Holdings with dailyDelta < 0 */
  downCount: number;
}

export interface SectorSlice {
  name: string;
  /** % of portfolio that this sector represents (Σ positionPct) */
  weight: number;
  /** USD value of all holdings in this sector */
  valueUsd: number;
  /** Aggregate daily move % (value-weighted across constituents) */
  dailyDeltaPct: number | null;
  /** Deterministic color keyed to the rank (emerald/blue/pink/amber/violet/red) */
  color: string;
}

export interface TickerSlice {
  ticker: string;
  /** Display name (e.g. ".KS" stripped) */
  displayName: string;
  /** % of visible portfolio (renormalized to sum to 100) */
  weight: number;
  /** USD value of this position */
  valueUsd: number;
  /** Sector for color/grouping */
  sector: string | null;
  /** Aggregate daily move % across multi-account holdings of this ticker */
  dailyDeltaPct: number | null;
  /** Color hashed from rank */
  color: string;
}

export interface CumulativePnL {
  /** Total unrealized USD gain across visible holdings */
  totalUsd: number;
  /** Total return % = totalGain / totalCostBasis × 100 */
  totalPct: number;
}

export interface WinRateSummary {
  /** Holdings with pnlPct > 0 */
  winners: number;
  /** Holdings with pnlPct < 0 */
  losers: number;
  /** Holdings with pnlPct == 0 (or non-finite) — neither win nor loss */
  flat: number;
  /** winners / (winners + losers) × 100. Excludes flat. 0 when both are 0. */
  winRatePct: number;
}

export interface AccountSlice {
  account: string;
  /** USD total (holdings + cash) */
  valueUsd: number;
  /** % of total portfolio (holdings + cash across all accounts) */
  weight: number;
  /** Aggregate daily move % across this account's holdings (null when no data) */
  dailyDeltaPct: number | null;
  /** Deterministic color keyed to rank (emerald/blue/pink/amber/violet/zinc) */
  color: string;
}

export interface MoverEntry {
  account: string;
  ticker: string;
  pnlPct: number;
}

export interface ConcentrationSummary {
  /** Herfindahl–Hirschman index computed on portfolio fractions (0..1) */
  herfindahl: number;
  /** Single largest position */
  topHolding: { ticker: string; weight: number } | null;
  /** Coarse bucket for color coding */
  level: "low" | "medium" | "high";
}

export interface HoldingsSummary {
  today: TodayPnL;
  cumulative: CumulativePnL;
  /** Win rate aggregation (#223 iter 7): replaces 배당 in the hero for 단타 use case */
  winRate: WinRateSummary;
  byAccount: AccountSlice[];
  sectors: SectorSlice[];
  /** Ticker-level composition (#223): top N + Other bucket, normalized to 100 */
  byTicker: TickerSlice[];
  topMovers: { winners: MoverEntry[]; losers: MoverEntry[] };
  concentration: ConcentrationSummary;
}

export interface SummarizeOptions {
  totalPortfolioUsd: number;
  /**
   * Per-account total USD (holdings + cash). page.tsx merges `account_values`
   * and `cash_summary.accounts` from /api/dashboard before passing in.
   * Empty → byAccount slice is []  (card not rendered).
   */
  accountValues?: Array<{ account: string; value: number }>;
}

// Palette — tailwind 400-level shades so the donut reads against zinc-950.
const SECTOR_COLORS = [
  "#34d399", // emerald-400
  "#60a5fa", // blue-400
  "#f472b6", // pink-400
  "#fbbf24", // amber-400
  "#a78bfa", // violet-400
] as const;
// Larger palette for ticker-level composition (12 distinct colors for top 12).
const TICKER_COLORS = [
  "#34d399", // emerald-400
  "#60a5fa", // blue-400
  "#f472b6", // pink-400
  "#fbbf24", // amber-400
  "#a78bfa", // violet-400
  "#f87171", // red-400
  "#22d3ee", // cyan-400
  "#facc15", // yellow-400
  "#4ade80", // green-400
  "#a3e635", // lime-400
  "#fb923c", // orange-400
  "#e879f9", // fuchsia-400
] as const;
const OTHER_COLOR = "#71717a"; // zinc-500

export function summarizeHoldings(
  holdings: EnrichedHolding[],
  options: SummarizeOptions,
): HoldingsSummary {
  const totalUsd = options.totalPortfolioUsd;

  // ── NORMALIZATION ─────────────────────────────────────────────────────
  // `positionPct` on each holding is "% of total portfolio (holdings + cash)"
  // — e.g. NVDA = 2.8% of net worth. But the dashboard filters out pension
  // holdings before passing the array here, so Σ positionPct < 100 for the
  // visible subset (~27% in the user's current data). Showing those raw
  // numbers in the summary panel creates a disconnect: the donut looks full
  // but legends sum to 27%, HHI looks artificially low, today's weighted %
  // is muted against the total instead of the visible subset.
  //
  // Fix: compute everything relative to the VISIBLE holdings only. Each
  // holding's `visibleWeight` is its share of Σ positionPct, renormalized to
  // [0, 100]. Sector rollup, HHI, top position, and today's % all use
  // visibleWeight. Absolute USD values (today's $ move) stay as absolute.
  const visiblePctSum = holdings.reduce(
    (sum, h) => sum + (h.positionPct ?? 0),
    0,
  );
  // visible_value_usd = (visiblePctSum/100) × totalPortfolioUsd
  const visibleValueUsd = (visiblePctSum / 100) * totalUsd;
  const visibleWeight = (h: EnrichedHolding): number =>
    visiblePctSum > 0 ? ((h.positionPct ?? 0) / visiblePctSum) * 100 : 0;

  // 1) Today's P&L
  let todayUsdDelta = 0;
  let upCount = 0;
  let downCount = 0;
  for (const h of holdings) {
    if (h.dailyDeltaPct == null) continue;
    if (h.dailyDeltaPct > 0) upCount++;
    else if (h.dailyDeltaPct < 0) downCount++;
    if (h.positionPct != null && totalUsd > 0) {
      const valueUsd = (h.positionPct / 100) * totalUsd;
      todayUsdDelta += valueUsd * (h.dailyDeltaPct / 100);
    }
  }
  const todayTotalPct =
    visibleValueUsd > 0 ? (todayUsdDelta / visibleValueUsd) * 100 : 0;
  const today: TodayPnL = {
    totalUsd: todayUsdDelta,
    totalPct: todayTotalPct,
    upCount,
    downCount,
  };

  // 1b) Cumulative P&L — Σ (currentValue - costBasis) over visible holdings.
  // costBasis_i = currentValue_i / (1 + pnlPct_i / 100). Then total return =
  // totalGain / totalCost × 100. Skips holdings with non-finite pnlPct or
  // missing positionPct (they can't contribute meaningfully).
  let cumCostUsd = 0;
  let cumValueUsd = 0;
  for (const h of holdings) {
    if (!Number.isFinite(h.pnlPct)) continue;
    if (h.positionPct == null || totalUsd <= 0) continue;
    const valueUsd = (h.positionPct / 100) * totalUsd;
    const costUsd = valueUsd / (1 + h.pnlPct / 100);
    if (!Number.isFinite(costUsd)) continue;
    cumValueUsd += valueUsd;
    cumCostUsd += costUsd;
  }
  const cumGainUsd = cumValueUsd - cumCostUsd;
  const cumGainPct = cumCostUsd > 0 ? (cumGainUsd / cumCostUsd) * 100 : 0;
  const cumulative: CumulativePnL = {
    totalUsd: cumGainUsd,
    totalPct: cumGainPct,
  };

  // 1c) Win rate — # of holdings with pnlPct > 0 vs < 0. Drives the 4th hero
  // stat in place of 연 배당 (which is irrelevant for the 단타-heavy active
  // accounts). flat holdings (0 pnlPct or non-finite) are excluded from the
  // ratio so a win rate of 90% means "of holdings with movement, 90% are up".
  let wr_winners = 0;
  let wr_losers = 0;
  let wr_flat = 0;
  for (const h of holdings) {
    if (!Number.isFinite(h.pnlPct)) {
      wr_flat++;
    } else if (h.pnlPct > 0) {
      wr_winners++;
    } else if (h.pnlPct < 0) {
      wr_losers++;
    } else {
      wr_flat++;
    }
  }
  const wr_movers = wr_winners + wr_losers;
  const winRate: WinRateSummary = {
    winners: wr_winners,
    losers: wr_losers,
    flat: wr_flat,
    winRatePct: wr_movers > 0 ? (wr_winners / wr_movers) * 100 : 0,
  };

  // Per-account weighted daily delta (visible holdings only — pension's
  // daily delta is unavailable). Aggregate Σ(value × delta) / Σ(value) per
  // account label, then attach to byAccount slices below.
  const accountDeltaAgg = new Map<string, { value: number; deltaWeighted: number }>();
  for (const h of holdings) {
    if (h.dailyDeltaPct == null || h.positionPct == null || totalUsd <= 0) continue;
    const v = (h.positionPct / 100) * totalUsd;
    const cur = accountDeltaAgg.get(h.account) ?? { value: 0, deltaWeighted: 0 };
    cur.value += v;
    cur.deltaWeighted += v * h.dailyDeltaPct;
    accountDeltaAgg.set(h.account, cur);
  }

  // 2) By account — each account's share of total portfolio. Uses the raw
  //    `accountValues` (holdings + cash merged per account) not visibleWeight,
  //    because account breakdown is about "where is my money" — pension and
  //    cash-only accounts should show up even though they're filtered out of
  //    the main table.
  const rawAccounts = options.accountValues ?? [];
  const byAccount: AccountSlice[] = rawAccounts
    .filter((a) => a.value > 0)
    .sort((a, b) => b.value - a.value)
    .map((a, i): AccountSlice => {
      const agg = accountDeltaAgg.get(a.account);
      const dailyDeltaPct =
        agg && agg.value > 0 ? agg.deltaWeighted / agg.value : null;
      return {
        account: a.account,
        valueUsd: a.value,
        weight: totalUsd > 0 ? (a.value / totalUsd) * 100 : 0,
        dailyDeltaPct,
        color: SECTOR_COLORS[i] ?? OTHER_COLOR,
      };
    });

  // 3) Sector breakdown — aggregate visibleWeight + value + delta per sector.
  type SectorAgg = { weight: number; value: number; deltaW: number; deltaSum: number };
  const sectorMap = new Map<string, SectorAgg>();
  for (const h of holdings) {
    const w = visibleWeight(h);
    if (w <= 0) continue;
    const key = h.sector ?? "Other";
    const v = (h.positionPct ?? 0) / 100 * totalUsd;
    const cur = sectorMap.get(key) ?? { weight: 0, value: 0, deltaW: 0, deltaSum: 0 };
    cur.weight += w;
    cur.value += v;
    if (h.dailyDeltaPct != null && v > 0) {
      cur.deltaW += v;
      cur.deltaSum += v * h.dailyDeltaPct;
    }
    sectorMap.set(key, cur);
  }
  const sortedSectors = Array.from(sectorMap.entries()).sort((a, b) => b[1].weight - a[1].weight);
  const topSectors = sortedSectors.slice(0, 4);
  const restSectors = sortedSectors.slice(4);
  const buildSectorSlice = (name: string, agg: SectorAgg, color: string): SectorSlice => ({
    name,
    weight: agg.weight,
    valueUsd: agg.value,
    dailyDeltaPct: agg.deltaW > 0 ? agg.deltaSum / agg.deltaW : null,
    color,
  });
  const sectors: SectorSlice[] = topSectors.map(([name, agg], i) =>
    buildSectorSlice(name, agg, SECTOR_COLORS[i]),
  );
  if (restSectors.length > 0) {
    const otherAgg = restSectors.reduce<SectorAgg>(
      (acc, [, a]) => ({
        weight: acc.weight + a.weight,
        value: acc.value + a.value,
        deltaW: acc.deltaW + a.deltaW,
        deltaSum: acc.deltaSum + a.deltaSum,
      }),
      { weight: 0, value: 0, deltaW: 0, deltaSum: 0 },
    );
    if (otherAgg.weight > 0) {
      sectors.push(buildSectorSlice("Other", otherAgg, OTHER_COLOR));
    }
  }

  // 3b) By ticker — visible holdings, top 12 + Other. Same visibleWeight
  // normalization so the legend sums to 100. Multi-account holdings of the
  // same ticker are merged into a single slice. Also aggregates value-weighted
  // daily delta across constituent holdings.
  type TickerAgg = {
    weight: number;
    valueUsd: number;
    sector: string | null;
    displayName: string;
    deltaW: number;
    deltaSum: number;
  };
  const tickerMap = new Map<string, TickerAgg>();
  for (const h of holdings) {
    const w = visibleWeight(h);
    if (w <= 0) continue;
    const valueUsd = (h.positionPct ?? 0) / 100 * totalUsd;
    const display = h.name || h.ticker.replace(/\.KS$/, "");
    const existing = tickerMap.get(h.ticker);
    const deltaW = h.dailyDeltaPct != null && valueUsd > 0 ? valueUsd : 0;
    const deltaSum = h.dailyDeltaPct != null && valueUsd > 0 ? valueUsd * h.dailyDeltaPct : 0;
    if (existing) {
      existing.weight += w;
      existing.valueUsd += valueUsd;
      existing.deltaW += deltaW;
      existing.deltaSum += deltaSum;
    } else {
      tickerMap.set(h.ticker, {
        weight: w,
        valueUsd,
        sector: h.sector ?? null,
        displayName: display,
        deltaW,
        deltaSum,
      });
    }
  }
  const sortedTickers = Array.from(tickerMap.entries()).sort((a, b) => b[1].weight - a[1].weight);
  const TOP_TICKER_COUNT = 12;
  const topTickers = sortedTickers.slice(0, TOP_TICKER_COUNT);
  const restTickers = sortedTickers.slice(TOP_TICKER_COUNT);
  const buildTickerSlice = (
    ticker: string,
    displayName: string,
    data: TickerAgg,
    color: string,
  ): TickerSlice => ({
    ticker,
    displayName,
    weight: data.weight,
    valueUsd: data.valueUsd,
    sector: data.sector,
    dailyDeltaPct: data.deltaW > 0 ? data.deltaSum / data.deltaW : null,
    color,
  });
  const byTicker: TickerSlice[] = topTickers.map(([ticker, data], i) =>
    buildTickerSlice(ticker, data.displayName, data, TICKER_COLORS[i] ?? OTHER_COLOR),
  );
  if (restTickers.length > 0) {
    const otherAgg = restTickers.reduce<TickerAgg>(
      (acc, [, d]) => ({
        weight: acc.weight + d.weight,
        valueUsd: acc.valueUsd + d.valueUsd,
        sector: null,
        displayName: acc.displayName,
        deltaW: acc.deltaW + d.deltaW,
        deltaSum: acc.deltaSum + d.deltaSum,
      }),
      { weight: 0, valueUsd: 0, sector: null, displayName: `Other (${restTickers.length})`, deltaW: 0, deltaSum: 0 },
    );
    if (otherAgg.weight > 0) {
      byTicker.push(
        buildTickerSlice("__OTHER__", otherAgg.displayName, otherAgg, OTHER_COLOR),
      );
    }
  }

  // 4) Top movers — 3 best winners, 3 worst losers.
  //    Losers: only holdings whose pnlPct is strictly < 0. If everything is
  //    green, the losers list is empty (don't fake a "loss" by showing the
  //    least-green holding under a red ↓).
  const withPnl = holdings.filter((h) => Number.isFinite(h.pnlPct));
  const winners = [...withPnl]
    .filter((h) => h.pnlPct > 0)
    .sort((a, b) => b.pnlPct - a.pnlPct)
    .slice(0, 3)
    .map(
      (h): MoverEntry => ({ account: h.account, ticker: h.ticker, pnlPct: h.pnlPct }),
    );
  const losers = [...withPnl]
    .filter((h) => h.pnlPct < 0)
    .sort((a, b) => a.pnlPct - b.pnlPct)
    .slice(0, 3)
    .map(
      (h): MoverEntry => ({ account: h.account, ticker: h.ticker, pnlPct: h.pnlPct }),
    );

  // 5) Concentration — Herfindahl on VISIBLE-normalized fractions + single largest
  let hhi = 0;
  let topHolding: ConcentrationSummary["topHolding"] = null;
  for (const h of holdings) {
    const weight = visibleWeight(h);
    if (weight <= 0) continue;
    const frac = weight / 100;
    hhi += frac * frac;
    if (!topHolding || weight > topHolding.weight) {
      topHolding = { ticker: h.ticker, weight };
    }
  }
  // Academic buckets: HHI < 0.10 low, 0.10-0.18 medium, > 0.18 high.
  const level: ConcentrationSummary["level"] =
    hhi < 0.1 ? "low" : hhi < 0.18 ? "medium" : "high";

  return {
    today,
    cumulative,
    winRate,
    byAccount,
    sectors,
    byTicker,
    topMovers: { winners, losers },
    concentration: { herfindahl: hhi, topHolding, level },
  };
}
