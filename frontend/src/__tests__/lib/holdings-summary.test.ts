import { describe, it, expect } from "vitest";

import { summarizeHoldings } from "@/lib/holdings-summary";
import type { EnrichedHolding } from "@/components/ui/holding-row";

function holding(over: Partial<EnrichedHolding> = {}): EnrichedHolding {
  return {
    account: "Main",
    ticker: "AAPL",
    name: "Apple",
    currency: "USD",
    pnlPct: 10,
    dailyDeltaPct: 1,
    sparkline: [],
    latestPrice: 110,
    avgPrice: 100,
    status: { kind: "hold" },
    stopLoss: 93,
    target1: 120,
    target2: 140,
    target1Reached: false,
    target2Reached: false,
    watch: { kind: "none" },
    sector: "Tech",
    positionPct: 10,
    ...over,
  };
}

describe("summarizeHoldings", () => {
  it("returns zeros for an empty portfolio", () => {
    const s = summarizeHoldings([], { totalPortfolioUsd: 100_000 });
    expect(s.today.totalUsd).toBe(0);
    expect(s.today.totalPct).toBe(0);
    expect(s.today.upCount).toBe(0);
    expect(s.today.downCount).toBe(0);
    expect(s.sectors).toEqual([]);
    expect(s.topMovers.winners).toEqual([]);
    expect(s.topMovers.losers).toEqual([]);
    expect(s.concentration.herfindahl).toBe(0);
    expect(s.concentration.topHolding).toBeNull();
  });

  describe("today P&L", () => {
    it("weights delta by position value and sums USD + percent", () => {
      // Portfolio $100k. Holding A at 10% ($10k) up 2% → +$200.
      // Holding B at 20% ($20k) down 1% → -$200.
      // Net $0, weighted% = 0.10*2 + 0.20*(-1) = 0.0 (weighted contribution percent).
      const s = summarizeHoldings(
        [
          holding({ ticker: "A", positionPct: 10, dailyDeltaPct: 2 }),
          holding({ ticker: "B", positionPct: 20, dailyDeltaPct: -1 }),
        ],
        { totalPortfolioUsd: 100_000 },
      );
      expect(s.today.totalUsd).toBeCloseTo(0, 5);
      expect(s.today.totalPct).toBeCloseTo(0, 5);
      expect(s.today.upCount).toBe(1);
      expect(s.today.downCount).toBe(1);
    });

    it("skips holdings with null dailyDeltaPct", () => {
      const s = summarizeHoldings(
        [
          holding({ ticker: "A", dailyDeltaPct: null, positionPct: 50 }),
          holding({ ticker: "B", dailyDeltaPct: 2, positionPct: 50 }),
        ],
        { totalPortfolioUsd: 10_000 },
      );
      expect(s.today.upCount).toBe(1);
      expect(s.today.downCount).toBe(0);
      // Only B contributes: value $5000 × 2% = $100
      expect(s.today.totalUsd).toBeCloseTo(100, 5);
    });

    it("counts up vs down even when positionPct is null (so value contribution is skipped)", () => {
      const s = summarizeHoldings(
        [
          holding({ ticker: "A", dailyDeltaPct: 3, positionPct: null }),
          holding({ ticker: "B", dailyDeltaPct: -2, positionPct: null }),
        ],
        { totalPortfolioUsd: 10_000 },
      );
      expect(s.today.upCount).toBe(1);
      expect(s.today.downCount).toBe(1);
      expect(s.today.totalUsd).toBe(0);
      expect(s.today.totalPct).toBe(0);
    });
  });

  describe("sectors", () => {
    it("aggregates positionPct per sector, sorted descending", () => {
      const s = summarizeHoldings(
        [
          holding({ ticker: "NVDA", sector: "Semi", positionPct: 20 }),
          holding({ ticker: "AMD", sector: "Semi", positionPct: 10 }),
          holding({ ticker: "AAPL", sector: "BigTech", positionPct: 15 }),
        ],
        { totalPortfolioUsd: 100_000 },
      );
      expect(s.sectors.map((x) => x.name)).toEqual(["Semi", "BigTech"]);
      expect(s.sectors[0].weight).toBe(30);
      expect(s.sectors[1].weight).toBe(15);
    });

    it("buckets sectors beyond top-4 into Other", () => {
      const s = summarizeHoldings(
        [
          holding({ ticker: "A", sector: "Semi", positionPct: 30 }),
          holding({ ticker: "B", sector: "BigTech", positionPct: 20 }),
          holding({ ticker: "C", sector: "Finance", positionPct: 15 }),
          holding({ ticker: "D", sector: "Energy", positionPct: 10 }),
          holding({ ticker: "E", sector: "REIT", positionPct: 5 }),
          holding({ ticker: "F", sector: "Utilities", positionPct: 5 }),
        ],
        { totalPortfolioUsd: 100_000 },
      );
      expect(s.sectors).toHaveLength(5);
      const names = s.sectors.map((x) => x.name);
      expect(names.slice(0, 4)).toEqual(["Semi", "BigTech", "Finance", "Energy"]);
      expect(names[4]).toBe("Other");
      expect(s.sectors[4].weight).toBe(10); // REIT(5) + Utilities(5)
    });

    it("labels null sector as 'Other'", () => {
      const s = summarizeHoldings(
        [
          holding({ ticker: "X", sector: null, positionPct: 5 }),
          holding({ ticker: "Y", sector: "Semi", positionPct: 10 }),
        ],
        { totalPortfolioUsd: 100_000 },
      );
      const names = s.sectors.map((x) => x.name);
      expect(names).toContain("Semi");
      expect(names).toContain("Other");
    });

    it("assigns distinct colors to each top-4 slice", () => {
      const s = summarizeHoldings(
        [
          holding({ ticker: "A", sector: "S1", positionPct: 30 }),
          holding({ ticker: "B", sector: "S2", positionPct: 20 }),
          holding({ ticker: "C", sector: "S3", positionPct: 15 }),
          holding({ ticker: "D", sector: "S4", positionPct: 10 }),
        ],
        { totalPortfolioUsd: 100_000 },
      );
      const colors = s.sectors.map((x) => x.color);
      expect(new Set(colors).size).toBe(4);
    });
  });

  describe("top movers", () => {
    it("picks 3 best winners and 3 worst losers", () => {
      const s = summarizeHoldings(
        [
          holding({ ticker: "A", pnlPct: 50 }),
          holding({ ticker: "B", pnlPct: 40 }),
          holding({ ticker: "C", pnlPct: 30 }),
          holding({ ticker: "D", pnlPct: 20 }),
          holding({ ticker: "E", pnlPct: -5 }),
          holding({ ticker: "F", pnlPct: -15 }),
          holding({ ticker: "G", pnlPct: -25 }),
        ],
        { totalPortfolioUsd: 100_000 },
      );
      expect(s.topMovers.winners.map((m) => m.ticker)).toEqual(["A", "B", "C"]);
      expect(s.topMovers.losers.map((m) => m.ticker)).toEqual(["G", "F", "E"]);
    });

    it("returns fewer than 3 when portfolio is small", () => {
      const s = summarizeHoldings(
        [
          holding({ ticker: "A", pnlPct: 5 }),
          holding({ ticker: "B", pnlPct: -10 }),
        ],
        { totalPortfolioUsd: 10_000 },
      );
      expect(s.topMovers.winners).toHaveLength(2);
      expect(s.topMovers.losers).toHaveLength(2);
    });
  });

  describe("concentration", () => {
    it("computes Herfindahl on portfolio fractions", () => {
      // Two equal 50% positions: HHI = 0.5² + 0.5² = 0.5
      const s = summarizeHoldings(
        [
          holding({ ticker: "A", positionPct: 50 }),
          holding({ ticker: "B", positionPct: 50 }),
        ],
        { totalPortfolioUsd: 100_000 },
      );
      expect(s.concentration.herfindahl).toBeCloseTo(0.5, 5);
      expect(s.concentration.topHolding?.ticker).toBe("A"); // first encountered with max weight
      expect(s.concentration.topHolding?.weight).toBe(50);
      expect(s.concentration.level).toBe("high");
    });

    it("classifies low / medium / high thresholds", () => {
      const low = summarizeHoldings(
        Array.from({ length: 20 }, (_, i) =>
          holding({ ticker: `T${i}`, positionPct: 5 }),
        ),
        { totalPortfolioUsd: 100_000 },
      );
      // 20 × 0.05² = 0.05
      expect(low.concentration.level).toBe("low");

      const med = summarizeHoldings(
        Array.from({ length: 8 }, (_, i) =>
          holding({ ticker: `T${i}`, positionPct: 12.5 }),
        ),
        { totalPortfolioUsd: 100_000 },
      );
      // 8 × 0.125² = 0.125
      expect(med.concentration.level).toBe("medium");

      const high = summarizeHoldings(
        [
          holding({ ticker: "A", positionPct: 60 }),
          holding({ ticker: "B", positionPct: 40 }),
        ],
        { totalPortfolioUsd: 100_000 },
      );
      expect(high.concentration.level).toBe("high");
    });
  });
});
