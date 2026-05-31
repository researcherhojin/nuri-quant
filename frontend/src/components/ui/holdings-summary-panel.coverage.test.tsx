/**
 * Coverage top-up for HoldingsSummaryPanel (#221).
 *
 * The base suite (src/__tests__/components/holdings-summary-panel.test.tsx)
 * never feeds today.totalUsd with |value| >= 1000, so the thousands-grouping
 * branch of formatUsd() (source line 32) stays uncovered. These tests render
 * a fully-populated panel (every card + barlist) AND drive both formatUsd
 * branches so this file alone reaches 100% statements:
 *   - large positive total  -> "$1,250" (Math.round + toLocaleString, line 32)
 *   - large negative total  -> abs grouped, down-arrow color path (line 32)
 *   - small total           -> "$340" (toFixed fallback, line 33)
 *
 * HoldingsSummaryPanel is a pure prop-driven Server Component (no fetch, no
 * recharts), so no network/recharts mocking is needed and the recharts-hoist
 * gotcha does not apply. Data shape mirrors the base suite's baseSummary().
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { HoldingsSummaryPanel } from "@/components/ui/holdings-summary-panel";
import type { HoldingsSummary } from "@/lib/holdings-summary";

function baseSummary(over: Partial<HoldingsSummary> = {}): HoldingsSummary {
  return {
    today: { totalUsd: 340, totalPct: 0.46, upCount: 6, downCount: 4 },
    cumulative: { totalUsd: 8500, totalPct: 12.5 },
    winRate: { winners: 8, losers: 2, flat: 0, winRatePct: 80 },
    byTicker: [
      { ticker: "AAPL", displayName: "AAPL", weight: 28, valueUsd: 21000, sector: "BigTech", dailyDeltaPct: 1.2, color: "#34d399" },
      { ticker: "MSFT", displayName: "MSFT", weight: 19, valueUsd: 14000, sector: "BigTech", dailyDeltaPct: -0.5, color: "#60a5fa" },
    ],
    byAccount: [
      { account: "Brokerage Alpha", valueUsd: 36000, weight: 50.0, dailyDeltaPct: 0.8, color: "#34d399" },
      { account: "Brokerage Beta", valueUsd: 20000, weight: 27.0, dailyDeltaPct: 0.4, color: "#60a5fa" },
    ],
    sectors: [
      { name: "BigTech", weight: 47, valueUsd: 35000, dailyDeltaPct: 0.9, color: "#34d399" },
      { name: "ETF", weight: 12, valueUsd: 9000, dailyDeltaPct: -0.1, color: "#f472b6" },
    ],
    topMovers: {
      winners: [{ account: "Brokerage Alpha", ticker: "AAPL", pnlPct: 5.6 }],
      losers: [{ account: "Brokerage Beta", ticker: "MSFT", pnlPct: -1.0 }],
    },
    concentration: {
      herfindahl: 0.18,
      topHolding: { ticker: "AAPL", weight: 18.5 },
      level: "medium",
    },
    ...over,
  };
}

describe("HoldingsSummaryPanel formatUsd thousands branch", () => {
  it("groups a large positive daily total with thousands separators", () => {
    render(
      <HoldingsSummaryPanel
        summary={baseSummary({
          today: { totalUsd: 1250.4, totalPct: 1.23, upCount: 5, downCount: 2 },
        })}
      />,
    );

    const today = screen.getByTestId("summary-today");
    // Math.round(1250.4) = 1250 -> "$1,250" (NOT the "$1250.40" toFixed path)
    expect(today.textContent).toContain("$1,250");
    expect(today.textContent).not.toContain("1250.40");
  });

  it("groups a large negative daily total using the absolute value", () => {
    render(
      <HoldingsSummaryPanel
        summary={baseSummary({
          today: { totalUsd: -2500.9, totalPct: -3.1, upCount: 1, downCount: 9 },
        })}
      />,
    );

    const today = screen.getByTestId("summary-today");
    // abs(-2500.9) = 2500.9 -> round 2501 -> "$2,501"
    expect(today.textContent).toContain("$2,501");
    expect(today.textContent).toContain("▼"); // down arrow (negative)
  });

  it("uses the toFixed fallback for sub-1000 totals", () => {
    render(<HoldingsSummaryPanel summary={baseSummary()} />);
    const today = screen.getByTestId("summary-today");
    // abs(340) < 1000 -> "$340.00"
    expect(today.textContent).toContain("$340.00");
  });
});
