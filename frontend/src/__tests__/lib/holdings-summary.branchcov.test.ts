/**
 * Branch coverage top-up for holdings-summary (#221).
 *
 * Targets the four REACHABLE uncovered branch arms with real behaviour tests:
 *   - line 177: `(h.positionPct ?? 0)` null-fallback inside visibleWeight() —
 *     fires when a holding has positionPct === null but visiblePctSum > 0.
 *   - line 280: `SECTOR_COLORS[i] ?? OTHER_COLOR` — fires for the 6th+ account
 *     (SECTOR_COLORS has only 5 entries).
 *   - line 309: `agg.deltaW > 0 ? ... : null` — :null arm when a sector's
 *     holdings have no usable daily delta.
 *   - line 349: `h.name || h.ticker.replace(...)` — right arm when name is "".
 *
 * The remaining 5 arms are genuinely unreachable (redundant nullish guards
 * behind an earlier `if (w <= 0) continue`, the 12-cap palette invariant on
 * topTickers, and the always-positive otherAgg.weight). `/* v8 ignore *​/` is
 * non-functional in this repo's vitest 4.1.7 + plugin-react toolchain (the SWC
 * transform strips the comment before v8 instruments), so they remain visibly
 * uncovered rather than dishonestly suppressed.
 *
 * Behaviour-asserting per AGENTS.md gotcha #3. Separate file from the existing
 * *.coverage.test.* to avoid shared-worker mock leakage.
 */
import { describe, it, expect } from "vitest";
import { summarizeHoldings } from "@/lib/holdings-summary";
import type { EnrichedHolding } from "@/components/ui/holding-row";
import type { SummarizeOptions } from "@/lib/holdings-summary";

const mkHolding = (over: Partial<EnrichedHolding>): EnrichedHolding => ({
  account: "Brokerage Alpha",
  ticker: "TEST",
  name: "Test Co",
  currency: "USD",
  pnlPct: 5,
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
});

const baseOpts: SummarizeOptions = { totalPortfolioUsd: 100000 };

describe("holdings-summary branch coverage top-up", () => {
  it("visibleWeight uses the ?? 0 fallback for a null-positionPct holding (line 177)", () => {
    // One holding has positionPct === null, a sibling keeps visiblePctSum > 0.
    // The null holding's visibleWeight() must resolve to 0 (its (??0) arm),
    // contributing nothing to HHI / sectors / tickers — so HHI == (1.0)^2.
    const holdings: EnrichedHolding[] = [
      mkHolding({ ticker: "WITHPCT", positionPct: 20, sector: "Tech" }),
      mkHolding({ ticker: "NULLPCT", positionPct: null, sector: "Energy" }),
    ];
    const summary = summarizeHoldings(holdings, baseOpts);

    // Only the non-null holding is visible → it owns 100% of visible weight.
    expect(summary.concentration.topHolding).not.toBeNull();
    expect(summary.concentration.topHolding!.ticker).toBe("WITHPCT");
    expect(summary.concentration.topHolding!.weight).toBeCloseTo(100, 6);
    // HHI = (1.0)^2 = 1.0 → "high" level.
    expect(summary.concentration.herfindahl).toBeCloseTo(1, 6);
    expect(summary.concentration.level).toBe("high");

    // The null-positionPct holding produced no sector or ticker slice.
    expect(summary.sectors).toHaveLength(1);
    expect(summary.sectors[0].name).toBe("Tech");
    expect(summary.byTicker.map((t) => t.ticker)).toEqual(["WITHPCT"]);
    expect(summary.byTicker).toHaveLength(1);
  });

  it("byAccount falls back to OTHER_COLOR for the 6th account (line 280)", () => {
    // SECTOR_COLORS has 5 entries (i 0..4). The 6th account (i === 5) must use
    // OTHER_COLOR via the `?? OTHER_COLOR` fallback.
    const OTHER_COLOR = "#71717a"; // zinc-500 (mirrors source constant)
    const SECTOR_COLORS = ["#34d399", "#60a5fa", "#f472b6", "#fbbf24", "#a78bfa"];

    const accountValues = [
      { account: "Acct-A", value: 60000 },
      { account: "Acct-B", value: 50000 },
      { account: "Acct-C", value: 40000 },
      { account: "Acct-D", value: 30000 },
      { account: "Acct-E", value: 20000 },
      { account: "Acct-F", value: 10000 }, // 6th → OTHER_COLOR
    ];
    const summary = summarizeHoldings([], { ...baseOpts, accountValues });

    expect(summary.byAccount).toHaveLength(6);
    // Sorted descending by value, so colors map by rank.
    summary.byAccount.slice(0, 5).forEach((slice, i) => {
      expect(slice.color).toBe(SECTOR_COLORS[i]);
    });
    // The 6th slice (lowest value) takes the fallback color.
    expect(summary.byAccount[5].account).toBe("Acct-F");
    expect(summary.byAccount[5].color).toBe(OTHER_COLOR);
  });

  it("sector slice dailyDeltaPct is null when the sector has no usable daily delta (line 309 :null arm)", () => {
    // The sector's only holding has dailyDeltaPct === null → deltaW stays 0 →
    // `agg.deltaW > 0 ? agg.deltaSum / agg.deltaW : null` takes the :null arm.
    const holdings: EnrichedHolding[] = [
      mkHolding({ ticker: "NODELTA", sector: "Energy", positionPct: 30, dailyDeltaPct: null }),
    ];
    const summary = summarizeHoldings(holdings, baseOpts);

    expect(summary.sectors).toHaveLength(1);
    expect(summary.sectors[0].name).toBe("Energy");
    // valueUsd still aggregates (positionPct present) but the delta is null.
    expect(summary.sectors[0].valueUsd).toBeGreaterThan(0);
    expect(summary.sectors[0].dailyDeltaPct).toBeNull();
  });

  it("byTicker displayName falls back to ticker.replace when name is empty (line 349 || right arm)", () => {
    // name === "" is falsy → `h.name || h.ticker.replace(/\.KS$/, "")` takes the
    // right arm, stripping the .KS suffix from the Korean ticker.
    const holdings: EnrichedHolding[] = [
      mkHolding({ ticker: "005930.KS", name: "", sector: "Tech", positionPct: 40 }),
    ];
    const summary = summarizeHoldings(holdings, baseOpts);

    const slice = summary.byTicker.find((t) => t.ticker === "005930.KS");
    expect(slice).toBeDefined();
    expect(slice!.displayName).toBe("005930"); // .KS stripped via the || fallback
  });
});
