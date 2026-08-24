import { describe, it, expect, vi } from "vitest";
import type { ReactNode, AnchorHTMLAttributes } from "react";
import { render, screen } from "@testing-library/react";

vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: ReactNode; href: string } & AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

import { HeroStats } from "@/components/ui/hero-stats";
import type { HoldingsSummary } from "@/lib/holdings-summary";
import { HERO } from "@/lib/strings";

function summary(over: Partial<HoldingsSummary> = {}): HoldingsSummary {
  return {
    today: { totalUsd: 495, totalPct: 2.44, upCount: 13, downCount: 3 },
    cumulative: { totalUsd: 2427, totalPct: 13.6 },
    winRate: { winners: 15, losers: 1, flat: 0, winRatePct: 93.75 },
    byTicker: [],
    byAccount: [],
    sectors: [],
    topMovers: { winners: [], losers: [] },
    concentration: { herfindahl: 0, topHolding: null, level: "low" },
    ...over,
  };
}

describe("HeroStats", () => {
  it("renders all four hero cells with testids", () => {
    render(
      <HeroStats
        totalUsd={74237}
        cashTotalUsd={40240}
        holdingsValueUsd={33996}
        summary={summary()}
        verdictLabel="관망"
      />,
    );
    expect(screen.getByTestId("hero-stats")).toBeInTheDocument();
    expect(screen.getByTestId("hero-total")).toBeInTheDocument();
    expect(screen.getByTestId("hero-today")).toBeInTheDocument();
    expect(screen.getByTestId("hero-cumulative")).toBeInTheDocument();
    expect(screen.getByTestId("hero-winrate")).toBeInTheDocument();
  });

  it("renders 총 자산 with formatted USD + verdict badge", () => {
    render(
      <HeroStats
        totalUsd={74237}
        cashTotalUsd={40240}
        holdingsValueUsd={33996}
        summary={summary()}
        verdictLabel="관망"
      />,
    );
    const total = screen.getByTestId("hero-total");
    expect(total.textContent).toContain("총 자산");
    expect(total.textContent).toContain("$74,237");
    expect(total.textContent).toContain("관망");
    // sub-line shows holdings + cash
    expect(total.textContent).toContain("보유");
    expect(total.textContent).toContain("$33,996");
    expect(total.textContent).toContain("$40,240");
  });

  it("renders today P&L positive in emerald with up arrow", () => {
    render(
      <HeroStats
        totalUsd={74237}
        cashTotalUsd={0}
        holdingsValueUsd={74237}
        summary={summary()}
        verdictLabel="관망"
      />,
    );
    const today = screen.getByTestId("hero-today");
    expect(today.textContent).toContain("$495");
    expect(today.textContent).toContain("+2.44%");
    expect(today.textContent).toContain("\u25B2"); // ▲
    expect(today.innerHTML).toMatch(/text-emerald-400/);
  });

  it("renders today P&L negative in red with down arrow", () => {
    render(
      <HeroStats
        totalUsd={74237}
        cashTotalUsd={0}
        holdingsValueUsd={74237}
        summary={summary({
          today: { totalUsd: -300, totalPct: -1.2, upCount: 2, downCount: 8 },
        })}
        verdictLabel="주의"
      />,
    );
    const today = screen.getByTestId("hero-today");
    expect(today.textContent).toContain("$300");
    expect(today.textContent).toContain("-1.20%");
    expect(today.textContent).toContain("\u25BC"); // ▼
    expect(today.innerHTML).toMatch(/text-red-400/);
  });

  it("renders cumulative P&L with both $ and %", () => {
    render(
      <HeroStats
        totalUsd={74237}
        cashTotalUsd={0}
        holdingsValueUsd={74237}
        summary={summary()}
        verdictLabel="관망"
      />,
    );
    const cum = screen.getByTestId("hero-cumulative");
    expect(cum.textContent).toContain("$2,427");
    expect(cum.textContent).toContain("+13.6%");
  });

  it("renders winrate emerald when ≥60%", () => {
    render(
      <HeroStats
        totalUsd={74237}
        cashTotalUsd={0}
        holdingsValueUsd={74237}
        summary={summary({
          winRate: { winners: 9, losers: 1, flat: 0, winRatePct: 90 },
        })}
        verdictLabel="관망"
      />,
    );
    const wr = screen.getByTestId("hero-winrate");
    expect(wr.textContent).toContain("90%");
    expect(wr.textContent).toContain("9W / 1L");
    expect(wr.innerHTML).toMatch(/text-emerald-400/);
  });

  it("renders winrate amber for 40-60%", () => {
    render(
      <HeroStats
        totalUsd={74237}
        cashTotalUsd={0}
        holdingsValueUsd={74237}
        summary={summary({
          winRate: { winners: 5, losers: 5, flat: 0, winRatePct: 50 },
        })}
        verdictLabel="관망"
      />,
    );
    const wr = screen.getByTestId("hero-winrate");
    expect(wr.innerHTML).toMatch(/text-amber-400/);
  });

  it("renders winrate red below 40%", () => {
    render(
      <HeroStats
        totalUsd={74237}
        cashTotalUsd={0}
        holdingsValueUsd={74237}
        summary={summary({
          winRate: { winners: 2, losers: 8, flat: 0, winRatePct: 20 },
        })}
        verdictLabel="주의"
      />,
    );
    const wr = screen.getByTestId("hero-winrate");
    expect(wr.innerHTML).toMatch(/text-red-400/);
  });

  it("renders winrate em dash when no movers (zinc-600)", () => {
    render(
      <HeroStats
        totalUsd={74237}
        cashTotalUsd={0}
        holdingsValueUsd={74237}
        summary={summary({
          winRate: { winners: 0, losers: 0, flat: 5, winRatePct: 0 },
        })}
        verdictLabel="관망"
      />,
    );
    const wr = screen.getByTestId("hero-winrate");
    expect(wr.textContent).toContain("—");
    expect(wr.textContent).toContain("보합 5");
  });

  it("hides holdings/cash sub-line when both are zero", () => {
    render(
      <HeroStats
        totalUsd={0}
        cashTotalUsd={0}
        holdingsValueUsd={0}
        summary={summary()}
        verdictLabel="관망"
      />,
    );
    const total = screen.getByTestId("hero-total");
    expect(total.textContent).not.toContain("보유 $");
  });
});

// #1185: 출처 분리 — 히어로 지표는 스냅샷, 판정 성과는 원장(/decisions)
describe("HeroStats provenance (#1185)", () => {
  it("always renders the snapshot provenance strip with a ledger link", () => {
    render(
      <HeroStats
        totalUsd={10000}
        cashTotalUsd={2000}
        holdingsValueUsd={8000}
        summary={summary()}
        verdictLabel="관망"
      />,
    );
    const strip = screen.getByTestId("hero-provenance");
    expect(strip.textContent).toContain(HERO.PROVENANCE_SNAPSHOT);
    expect(strip.textContent).toContain(HERO.PROVENANCE_SCOPE);
    expect(strip.textContent).toContain(HERO.PROVENANCE_LEDGER_LINK);
    const link = strip.querySelector("a");
    expect(link?.getAttribute("href")).toBe("/decisions");
  });

  it("marks the win-rate stat as unrealized-snapshot, not system performance", () => {
    render(
      <HeroStats
        totalUsd={10000}
        cashTotalUsd={2000}
        holdingsValueUsd={8000}
        summary={summary({ winRate: { winners: 3, losers: 7, flat: 0, winRatePct: 30 } })}
        verdictLabel="관망"
      />,
    );
    const winrate = screen.getByTestId("hero-winrate");
    expect(winrate.textContent).toContain(HERO.WIN_RATE_SCOPE);
  });

  it("keeps the flat count alongside the win-rate scope note", () => {
    render(
      <HeroStats
        totalUsd={10000}
        cashTotalUsd={2000}
        holdingsValueUsd={8000}
        summary={summary({ winRate: { winners: 2, losers: 2, flat: 3, winRatePct: 50 } })}
        verdictLabel="관망"
      />,
    );
    const winrate = screen.getByTestId("hero-winrate");
    expect(winrate.textContent).toContain(`${HERO.FLAT} 3`);
    expect(winrate.textContent).toContain(HERO.WIN_RATE_SCOPE);
  });
});
