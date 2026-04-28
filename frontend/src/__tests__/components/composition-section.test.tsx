import { describe, it, expect, vi } from "vitest";
import type { ReactNode, AnchorHTMLAttributes } from "react";
import { render, screen } from "@testing-library/react";

// jsdom can't render Recharts; mock the chart primitives so the
// CompositionSection's child donut renders as a stub container.
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  PieChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Pie: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Cell: () => <div />,
  Tooltip: () => <div />,
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: ReactNode; href: string } & AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

import {
  CompositionSection,
  parseCompositionTab,
} from "@/components/ui/composition-section";
import type { HoldingsSummary } from "@/lib/holdings-summary";

function summary(over: Partial<HoldingsSummary> = {}): HoldingsSummary {
  return {
    today: { totalUsd: 100, totalPct: 0.5, upCount: 5, downCount: 1 },
    cumulative: { totalUsd: 1000, totalPct: 5 },
    winRate: { winners: 5, losers: 1, flat: 0, winRatePct: 83.3 },
    byTicker: [
      { ticker: "TSLA", displayName: "TSLA", weight: 40, valueUsd: 5000, sector: "EV/AI", dailyDeltaPct: 1.5, color: "#34d399" },
      { ticker: "NVDA", displayName: "NVDA", weight: 30, valueUsd: 3750, sector: "Semi", dailyDeltaPct: -0.5, color: "#60a5fa" },
      { ticker: "VOO", displayName: "VOO", weight: 30, valueUsd: 3750, sector: "ETF", dailyDeltaPct: null, color: "#f472b6" },
    ],
    byAccount: [
      { account: "Main", valueUsd: 8000, weight: 60, dailyDeltaPct: 0.8, color: "#34d399" },
      { account: "Sub", valueUsd: 5000, weight: 40, dailyDeltaPct: -0.2, color: "#60a5fa" },
    ],
    sectors: [
      { name: "EV/AI", weight: 40, valueUsd: 5000, dailyDeltaPct: 1.5, color: "#34d399" },
      { name: "Semi", weight: 30, valueUsd: 3750, dailyDeltaPct: -0.5, color: "#60a5fa" },
      { name: "ETF", weight: 30, valueUsd: 3750, dailyDeltaPct: null, color: "#f472b6" },
    ],
    topMovers: {
      winners: [
        { account: "Main", ticker: "TSLA", pnlPct: 15 },
        { account: "Main", ticker: "NVDA", pnlPct: 10 },
      ],
      losers: [{ account: "Sub", ticker: "VOO", pnlPct: -2 }],
    },
    concentration: {
      herfindahl: 0.34,
      topHolding: { ticker: "TSLA", weight: 40 },
      level: "high",
    },
    ...over,
  };
}

describe("parseCompositionTab", () => {
  it("returns ticker for unknown values", () => {
    expect(parseCompositionTab(undefined)).toBe("ticker");
    expect(parseCompositionTab("invalid")).toBe("ticker");
    expect(parseCompositionTab("")).toBe("ticker");
  });

  it("returns sector / account / ticker exactly", () => {
    expect(parseCompositionTab("sector")).toBe("sector");
    expect(parseCompositionTab("account")).toBe("account");
    expect(parseCompositionTab("ticker")).toBe("ticker");
  });
});

describe("CompositionSection", () => {
  it("renders the section + tabs + donut + legend", () => {
    render(
      <CompositionSection summary={summary()} totalUsd={12500} activeTab="ticker" />,
    );
    expect(screen.getByTestId("composition-section")).toBeInTheDocument();
    expect(screen.getByTestId("composition-tabs")).toBeInTheDocument();
    expect(screen.getByTestId("composition-tab-ticker")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByTestId("composition-tab-sector")).toHaveAttribute(
      "aria-selected",
      "false",
    );
    expect(screen.getByTestId("composition-donut")).toBeInTheDocument();
    expect(screen.getByTestId("composition-legend")).toBeInTheDocument();
  });

  it("ticker tab renders one legend row per ticker with rich info", () => {
    render(
      <CompositionSection summary={summary()} totalUsd={12500} activeTab="ticker" />,
    );
    const legend = screen.getByTestId("composition-legend");
    // 3 ticker rows
    expect(screen.getByTestId("composition-legend-TSLA")).toBeInTheDocument();
    expect(screen.getByTestId("composition-legend-NVDA")).toBeInTheDocument();
    expect(screen.getByTestId("composition-legend-VOO")).toBeInTheDocument();
    // sector meta + value + weight + delta
    expect(legend.textContent).toContain("EV/AI");
    expect(legend.textContent).toContain("$5,000");
    expect(legend.textContent).toContain("40.0%");
    expect(legend.textContent).toContain("+1.50%");
    expect(legend.textContent).toContain("-0.50%");
    // null delta → em dash
    expect(legend.textContent).toContain("—");
  });

  it("sector tab renders sector slices in legend", () => {
    render(
      <CompositionSection summary={summary()} totalUsd={12500} activeTab="sector" />,
    );
    expect(screen.getByTestId("composition-tab-sector")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByTestId("composition-legend-EV/AI")).toBeInTheDocument();
    expect(screen.getByTestId("composition-legend-Semi")).toBeInTheDocument();
    expect(screen.getByTestId("composition-legend-ETF")).toBeInTheDocument();
  });

  it("account tab renders account slices in legend", () => {
    render(
      <CompositionSection summary={summary()} totalUsd={12500} activeTab="account" />,
    );
    expect(screen.getByTestId("composition-tab-account")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByTestId("composition-legend-Main")).toBeInTheDocument();
    expect(screen.getByTestId("composition-legend-Sub")).toBeInTheDocument();
  });

  it("renders mini cards strip below the donut", () => {
    render(
      <CompositionSection summary={summary()} totalUsd={12500} activeTab="ticker" />,
    );
    expect(screen.getByTestId("composition-side-cards")).toBeInTheDocument();
    expect(screen.getByTestId("side-movers")).toBeInTheDocument();
    expect(screen.getByTestId("side-concentration")).toBeInTheDocument();
    // Movers content
    const movers = screen.getByTestId("side-movers");
    expect(movers.textContent).toContain("TSLA");
    expect(movers.textContent).toContain("VOO");
    // Concentration colored amber for "high" level
    const conc = screen.getByTestId("side-concentration");
    expect(conc.textContent).toContain("0.34");
    expect(conc.textContent).toContain("high");
    expect(conc.innerHTML).toMatch(/text-amber-400/);
  });

  it("renders 손실 없음 fallback when there are no losers", () => {
    render(
      <CompositionSection
        summary={summary({
          topMovers: {
            winners: [{ account: "Main", ticker: "TSLA", pnlPct: 15 }],
            losers: [],
          },
        })}
        totalUsd={12500}
        activeTab="ticker"
      />,
    );
    expect(screen.getByTestId("side-movers").textContent).toContain("손실 없음");
  });

  it("renders empty state when summary has no slices for the tab", () => {
    render(
      <CompositionSection
        summary={summary({ byTicker: [], sectors: [], byAccount: [] })}
        totalUsd={0}
        activeTab="ticker"
      />,
    );
    // Donut shows the empty placeholder, and legend gracefully omits
    expect(screen.getByTestId("composition-donut-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("composition-legend")).not.toBeInTheDocument();
  });

  it("hides Movers card when both winners and losers are empty", () => {
    render(
      <CompositionSection
        summary={summary({ topMovers: { winners: [], losers: [] } })}
        totalUsd={12500}
        activeTab="ticker"
      />,
    );
    expect(screen.queryByTestId("side-movers")).not.toBeInTheDocument();
  });

  it("hides Concentration card when topHolding is null", () => {
    render(
      <CompositionSection
        summary={summary({
          concentration: { herfindahl: 0, topHolding: null, level: "low" },
        })}
        totalUsd={12500}
        activeTab="ticker"
      />,
    );
    expect(screen.queryByTestId("side-concentration")).not.toBeInTheDocument();
  });
});
