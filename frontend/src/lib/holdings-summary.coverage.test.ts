/**
 * Coverage push for summarizeHoldings (#221) — exercises the three branches the
 * existing suite never hits:
 *
 *   - L208: `continue` when pnlPct is non-finite (excluded from cumulative P&L)
 *   - L212: `continue` when costUsd is non-finite (pnlPct === -100 → divide by 0)
 *   - L232: `wr_flat++` inside the non-finite pnlPct branch of the win-rate loop
 *   - L351-354: the multi-account ticker-merge branch (`if (existing)`), only
 *     reachable when the same ticker is held across two accounts
 *
 * Privacy: neutral placeholder tickers / accounts / round numbers only.
 */
import { describe, expect, it } from "vitest";

import { summarizeHoldings } from "./holdings-summary";
import type { EnrichedHolding } from "@/components/ui/holding-row";

/** Build an EnrichedHolding fixture from only the fields summarizeHoldings reads. */
function holding(overrides: Partial<EnrichedHolding>): EnrichedHolding {
  return {
    account: "Brokerage Alpha",
    ticker: "AAPL",
    name: "AAPL",
    sector: "Technology",
    positionPct: 10,
    pnlPct: 0,
    dailyDeltaPct: 0,
    ...overrides,
  } as EnrichedHolding;
}

const OPTS = { totalPortfolioUsd: 100_000 };

describe("summarizeHoldings — uncovered branches", () => {
  it("L208: skips a holding with non-finite pnlPct in cumulative P&L", () => {
    const holdings = [
      holding({ ticker: "AAPL", positionPct: 50, pnlPct: 20 }),
      // NaN pnlPct → excluded from cumulative cost/value rollup (L208 continue)
      holding({ ticker: "MSFT", positionPct: 50, pnlPct: NaN }),
    ];

    const summary = summarizeHoldings(holdings, OPTS);

    // Only AAPL contributes: value = 50% × 100k = 50,000;
    // cost = 50,000 / 1.20 ≈ 41,666.67; gain ≈ 8,333.33; pct = 20.
    expect(summary.cumulative.totalUsd).toBeCloseTo(8_333.33, 1);
    expect(summary.cumulative.totalPct).toBeCloseTo(20, 5);
    // The NaN holding still counts as flat in the win-rate loop (L232).
    expect(summary.winRate.flat).toBe(1);
  });

  it("L212: skips a holding whose costUsd is non-finite (pnlPct === -100)", () => {
    const holdings = [
      holding({ ticker: "AAPL", positionPct: 40, pnlPct: 10 }),
      // pnlPct === -100 → 1 + (-100/100) = 0 → costUsd = value/0 = Infinity
      // → Number.isFinite(costUsd) === false → L212 continue.
      holding({ ticker: "MSFT", positionPct: 60, pnlPct: -100 }),
    ];

    const summary = summarizeHoldings(holdings, OPTS);

    // Only AAPL contributes to cumulative: value = 40,000; cost = 40,000/1.1;
    // gain ≈ 3,636.36; pct = 10. The -100 position is dropped, not Infinity.
    expect(Number.isFinite(summary.cumulative.totalUsd)).toBe(true);
    expect(summary.cumulative.totalUsd).toBeCloseTo(3_636.36, 1);
    expect(summary.cumulative.totalPct).toBeCloseTo(10, 5);
    // -100% is a finite loss → counted as a loser, not flat.
    expect(summary.winRate.losers).toBe(1);
  });

  it("L232: non-finite pnlPct is counted as flat in the win-rate loop", () => {
    const holdings = [
      holding({ ticker: "AAPL", positionPct: 30, pnlPct: 5 }), // winner
      holding({ ticker: "MSFT", positionPct: 30, pnlPct: -5 }), // loser
      holding({ ticker: "GOOGL", positionPct: 40, pnlPct: NaN }), // flat (L232)
    ];

    const summary = summarizeHoldings(holdings, OPTS);

    expect(summary.winRate.winners).toBe(1);
    expect(summary.winRate.losers).toBe(1);
    expect(summary.winRate.flat).toBe(1);
    // 1 winner / (1 winner + 1 loser) = 50% — flat excluded from the ratio.
    expect(summary.winRate.winRatePct).toBeCloseTo(50, 5);
  });

  it("L351-354: merges the same ticker held across two accounts into one slice", () => {
    const holdings = [
      // Same ticker AAPL in two accounts → second hit takes the `existing` path
      // and accumulates weight/value/deltaW/deltaSum onto the first slice.
      holding({
        account: "Brokerage Alpha",
        ticker: "AAPL",
        positionPct: 30,
        dailyDeltaPct: 2,
      }),
      holding({
        account: "Brokerage Beta",
        ticker: "AAPL",
        positionPct: 10,
        dailyDeltaPct: -1,
      }),
      holding({ account: "Brokerage Alpha", ticker: "MSFT", positionPct: 60 }),
    ];

    const summary = summarizeHoldings(holdings, OPTS);

    // One merged AAPL slice, not two. visiblePctSum = 30+10+60 = 100.
    const aapl = summary.byTicker.find((t) => t.ticker === "AAPL");
    expect(aapl).toBeDefined();
    expect(summary.byTicker.filter((t) => t.ticker === "AAPL")).toHaveLength(1);
    // Merged weight = (30 + 10) / 100 × 100 = 40.
    expect(aapl?.weight).toBeCloseTo(40, 5);
    // Merged value = (30% + 10%) × 100k = 40,000.
    expect(aapl?.valueUsd).toBeCloseTo(40_000, 5);
    // Value-weighted daily delta: (30k×2 + 10k×-1) / (30k + 10k) = 50k/40k = 1.25.
    expect(aapl?.dailyDeltaPct).toBeCloseTo(1.25, 5);
  });
});
