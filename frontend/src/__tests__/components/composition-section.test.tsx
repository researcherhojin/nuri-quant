import { describe, it, expect, vi } from "vitest";
import type { ReactNode, AnchorHTMLAttributes } from "react";
import { render, screen } from "@testing-library/react";

// #1210: 도넛(recharts) → 순수 server 스택 바 — recharts mock 불필요.
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
import { OTHER_COLOR } from "@/lib/holdings-summary";

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
  it("renders the section + tabs + bar + legend", () => {
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
    expect(screen.getByTestId("composition-bar")).toBeInTheDocument();
    expect(screen.getByTestId("composition-legend")).toBeInTheDocument();
  });

  // #1210 색 예산 잠금: holdings-summary 의 캔디 팔레트를 무시하고
  // 상위 5 = 차트 카테고리색(--chart-1..5 미러) + 나머지 = 무채로 재매핑한다.
  it("remaps legend/bar colors to the categorical chart tokens, ignoring summary colors", () => {
    render(
      <CompositionSection summary={summary()} totalUsd={12500} activeTab="ticker" />,
    );
    const firstDot = screen
      .getByTestId("composition-legend-TSLA")
      .querySelector("span[style]") as HTMLElement;
    // summary fixture 는 #34d399 (candy) 를 주지만 렌더는 --chart-1 값이어야 한다
    expect(firstDot.getAttribute("style")).toContain("rgb(76, 144, 240)"); // #4C90F0
    const segments = screen.getAllByTestId("composition-bar-segment");
    expect(segments[0].getAttribute("style")).toContain("rgb(76, 144, 240)");
    expect(segments.length).toBe(3); // 5개 이하 → 기타 세그먼트 없음
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

  // #1210: summary 자체 Other 버킷(섹터 top-4 병합 잔여, 항상 마지막)은 순번과
  // 무관하게 무채 — 섹터 탭에서 5번째 "Other" 가 카테고리색을 받으면 회귀다.
  it("colors the summary's own Other bucket neutral, never categorical", () => {
    render(
      <CompositionSection
        summary={summary({
          sectors: [
            { name: "EV/AI", weight: 40, valueUsd: 5000, dailyDeltaPct: 1.5, color: "#34d399" },
            { name: "Semi", weight: 25, valueUsd: 3000, dailyDeltaPct: -0.5, color: "#60a5fa" },
            { name: "ETF", weight: 15, valueUsd: 2000, dailyDeltaPct: null, color: "#f472b6" },
            { name: "Bio", weight: 12, valueUsd: 1500, dailyDeltaPct: 0.2, color: "#a78bfa" },
            { name: "Other", weight: 8, valueUsd: 1000, dailyDeltaPct: null, color: OTHER_COLOR },
          ],
        })}
        totalUsd={12500}
        activeTab="sector"
      />,
    );
    const otherDot = screen
      .getByTestId("composition-legend-Other")
      .querySelector("span[style]") as HTMLElement;
    expect(otherDot.getAttribute("style")).toContain("rgb(64, 72, 84)"); // #404854
    const segments = screen.getAllByTestId("composition-bar-segment");
    expect(segments[4].getAttribute("style")).toContain("rgb(64, 72, 84)");
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

  it("renders mini cards strip below the legend", () => {
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
    // 빈 상태: 바도 레전드도 없이 한 줄 안내만 (#1210 empty-state 규칙)
    expect(screen.queryByTestId("composition-bar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("composition-legend")).not.toBeInTheDocument();
    expect(screen.getByText("표시할 데이터가 없습니다.")).toBeInTheDocument();
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
