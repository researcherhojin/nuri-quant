import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

// #221 iter-3: panel no longer uses Recharts (donut replaced with a CSS
// barlist) so this test file doesn't need any chart mocks anymore.
import { HoldingsSummaryPanel } from "@/components/ui/holdings-summary-panel";
import type { HoldingsSummary } from "@/lib/holdings-summary";

function baseSummary(over: Partial<HoldingsSummary> = {}): HoldingsSummary {
  return {
    today: { totalUsd: 340, totalPct: 0.46, upCount: 6, downCount: 4 },
    cumulative: { totalUsd: 8500, totalPct: 12.5 },
    winRate: { winners: 8, losers: 2, flat: 0, winRatePct: 80 },
    byTicker: [
      { ticker: "NVDA", displayName: "NVDA", weight: 28, valueUsd: 21000, sector: "Semi", color: "#34d399" },
      { ticker: "TSLA", displayName: "TSLA", weight: 19, valueUsd: 14000, sector: "EV/AI", color: "#60a5fa" },
    ],
    byAccount: [
      { account: "Main", valueUsd: 36700, weight: 49.4, color: "#34d399" },
      { account: "Active", valueUsd: 20356, weight: 27.4, color: "#60a5fa" },
      { account: "Pension", valueUsd: 13752, weight: 18.5, color: "#f472b6" },
      { account: "Toss", valueUsd: 2517, weight: 3.4, color: "#fbbf24" },
    ],
    sectors: [
      { name: "Semi", weight: 28, color: "#34d399" },
      { name: "BigTech", weight: 19, color: "#60a5fa" },
      { name: "ETF", weight: 12, color: "#f472b6" },
      { name: "Other", weight: 41, color: "#71717a" },
    ],
    topMovers: {
      winners: [
        { account: "Main", ticker: "NVDA", pnlPct: 5.6 },
        { account: "Main", ticker: "PL", pnlPct: 38.2 },
      ],
      losers: [
        { account: "Active", ticker: "VOO", pnlPct: -1.0 },
      ],
    },
    concentration: {
      herfindahl: 0.18,
      topHolding: { ticker: "TSLA", weight: 18.5 },
      level: "medium",
    },
    ...over,
  };
}

describe("HoldingsSummaryPanel", () => {
  it("renders all five cards with correct testids", () => {
    render(<HoldingsSummaryPanel summary={baseSummary()} />);
    expect(screen.getByTestId("holdings-summary-panel")).toBeInTheDocument();
    expect(screen.getByTestId("summary-today")).toBeInTheDocument();
    expect(screen.getByTestId("summary-accounts")).toBeInTheDocument();
    expect(screen.getByTestId("summary-sectors")).toBeInTheDocument();
    expect(screen.getByTestId("summary-movers")).toBeInTheDocument();
    expect(screen.getByTestId("summary-concentration")).toBeInTheDocument();
  });

  it("renders accounts barlist with one row per account + weight labels", () => {
    render(<HoldingsSummaryPanel summary={baseSummary()} />);
    const accounts = screen.getByTestId("summary-accounts");
    expect(accounts.textContent).toContain("Main");
    expect(accounts.textContent).toContain("49.4%");
    expect(accounts.textContent).toContain("Active");
    expect(accounts.textContent).toContain("27.4%");
    const barlist = screen.getByTestId("account-barlist");
    expect(barlist.children).toHaveLength(4);
    expect(screen.getByTestId("account-bar-Main")).toBeInTheDocument();
    expect(screen.getByTestId("account-bar-Active")).toBeInTheDocument();
    expect(screen.getByTestId("account-bar-Pension")).toBeInTheDocument();
    expect(screen.getByTestId("account-bar-Toss")).toBeInTheDocument();
  });

  it("hides accounts card when byAccount is empty", () => {
    render(<HoldingsSummaryPanel summary={baseSummary({ byAccount: [] })} />);
    expect(screen.queryByTestId("summary-accounts")).not.toBeInTheDocument();
  });

  it("renders today card with dollar + percent + up/down counts", () => {
    render(<HoldingsSummaryPanel summary={baseSummary()} />);
    const today = screen.getByTestId("summary-today");
    expect(today.textContent).toContain("$340");
    expect(today.textContent).toContain("+0.46%");
    expect(today.textContent).toContain("6");
    expect(today.textContent).toContain("4");
  });

  it("uses emerald styling for positive today and red for negative", () => {
    const { rerender } = render(
      <HoldingsSummaryPanel summary={baseSummary({ today: { totalUsd: 100, totalPct: 0.2, upCount: 1, downCount: 0 } })} />,
    );
    const today = screen.getByTestId("summary-today");
    expect(today.innerHTML).toMatch(/text-emerald-400/);
    // positive arrow (▲)
    expect(today.textContent).toContain("\u25B2");

    rerender(
      <HoldingsSummaryPanel summary={baseSummary({ today: { totalUsd: -100, totalPct: -0.2, upCount: 0, downCount: 1 } })} />,
    );
    const todayNeg = screen.getByTestId("summary-today");
    expect(todayNeg.innerHTML).toMatch(/text-red-400/);
    expect(todayNeg.textContent).toContain("\u25BC");
  });

  it("renders sector barlist with one row per slice + percent labels", () => {
    render(<HoldingsSummaryPanel summary={baseSummary()} />);
    const sectors = screen.getByTestId("summary-sectors");
    expect(sectors.textContent).toContain("Semi");
    expect(sectors.textContent).toContain("28.0%");
    expect(sectors.textContent).toContain("BigTech");
    expect(sectors.textContent).toContain("19.0%");
    // Barlist has one row per slice
    const barlist = screen.getByTestId("sector-barlist");
    expect(barlist.children).toHaveLength(4);
    expect(screen.getByTestId("sector-bar-Semi")).toBeInTheDocument();
    expect(screen.getByTestId("sector-bar-BigTech")).toBeInTheDocument();
    expect(screen.getByTestId("sector-bar-ETF")).toBeInTheDocument();
    expect(screen.getByTestId("sector-bar-Other")).toBeInTheDocument();
  });

  it("renders winner and loser movers", () => {
    render(<HoldingsSummaryPanel summary={baseSummary()} />);
    const movers = screen.getByTestId("summary-movers");
    expect(movers.textContent).toContain("NVDA");
    expect(movers.textContent).toContain("+5.6%");
    expect(movers.textContent).toContain("VOO");
    expect(movers.textContent).toContain("-1.0%");
  });

  it("renders concentration card with HHI + level + top holding", () => {
    render(<HoldingsSummaryPanel summary={baseSummary()} />);
    const conc = screen.getByTestId("summary-concentration");
    expect(conc.textContent).toContain("HHI 0.18");
    expect(conc.textContent).toContain("medium");
    expect(conc.textContent).toContain("TSLA");
    expect(conc.textContent).toContain("18.5%");
  });

  it("applies amber styling when concentration level is high", () => {
    render(
      <HoldingsSummaryPanel
        summary={baseSummary({
          concentration: {
            herfindahl: 0.25,
            topHolding: { ticker: "TSLA", weight: 45 },
            level: "high",
          },
        })}
      />,
    );
    const conc = screen.getByTestId("summary-concentration");
    expect(conc.innerHTML).toMatch(/text-amber-400/);
  });

  it("hides sectors card when slices array is empty", () => {
    render(
      <HoldingsSummaryPanel
        summary={baseSummary({ sectors: [] })}
      />,
    );
    expect(screen.queryByTestId("summary-sectors")).not.toBeInTheDocument();
  });

  it("hides movers card when no winners and no losers", () => {
    render(
      <HoldingsSummaryPanel
        summary={baseSummary({ topMovers: { winners: [], losers: [] } })}
      />,
    );
    expect(screen.queryByTestId("summary-movers")).not.toBeInTheDocument();
  });

  it("hides concentration card when topHolding is null", () => {
    render(
      <HoldingsSummaryPanel
        summary={baseSummary({
          concentration: { herfindahl: 0, topHolding: null, level: "low" },
        })}
      />,
    );
    expect(screen.queryByTestId("summary-concentration")).not.toBeInTheDocument();
  });
});
