import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CompositionSection } from "@/components/ui/composition-section";
import type { HoldingsSummary } from "@/lib/holdings-summary";

// next/link → plain anchor (no router needed)
vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function makeSummary(overrides?: Partial<HoldingsSummary>): HoldingsSummary {
  const base: HoldingsSummary = {
    today: { totalUsd: 0, totalPct: 0, upCount: 0, downCount: 0 },
    cumulative: { totalUsd: 0, totalPct: 0 },
    winRate: { winners: 0, losers: 0, flat: 0, winRatePct: 0 },
    byAccount: [],
    sectors: [],
    byTicker: [],
    topMovers: { winners: [], losers: [] },
    concentration: { herfindahl: 0, topHolding: null, level: "low" },
  };
  return { ...base, ...overrides };
}

describe("CompositionSection — branch coverage", () => {
  // Branch 14 arm 1 (line 207-209): valueUsd == null → renders "" instead of $value
  it("renders empty USD cell when a legend row has null valueUsd", () => {
    const summary = makeSummary({
      byTicker: [
        {
          ticker: "AAA",
          displayName: "AAA",
          weight: 100,
          valueUsd: null as unknown as number, // null branch → "" arm
          sector: null,
          dailyDeltaPct: null,
          color: "#34d399",
        },
      ],
    });
    render(<CompositionSection summary={summary} totalUsd={1000} activeTab="ticker" />);
    const row = screen.getByTestId("composition-legend-AAA");
    // The USD value span (w-20 cell) must be present but contain no "$"
    expect(row.textContent).not.toContain("$");
  });

  // Branch 21 arm 0 (line 286): concentration.level === "medium" → text-zinc-200
  it("colors herfindahl text-zinc-200 when concentration level is medium", () => {
    const summary = makeSummary({
      concentration: {
        herfindahl: 0.25,
        topHolding: { ticker: "MID", weight: 40 },
        level: "medium",
      },
    });
    render(<CompositionSection summary={summary} totalUsd={1000} activeTab="ticker" />);
    const card = screen.getByTestId("side-concentration");
    const herfindahlSpan = card.querySelector("span.text-sm")!;
    expect(herfindahlSpan.className).toContain("text-zinc-200");
    expect(herfindahlSpan.className).not.toContain("text-amber-400");
    expect(herfindahlSpan.className).not.toContain("text-emerald-400");
  });

  // Branch 21 arm 1 (line 287): level neither "high" nor "medium" (i.e. "low") → text-emerald-400
  it("colors herfindahl text-emerald-400 when concentration level is low", () => {
    const summary = makeSummary({
      concentration: {
        herfindahl: 0.1,
        topHolding: { ticker: "LOW", weight: 15 },
        level: "low",
      },
    });
    render(<CompositionSection summary={summary} totalUsd={1000} activeTab="ticker" />);
    const card = screen.getByTestId("side-concentration");
    const herfindahlSpan = card.querySelector("span.text-sm")!;
    expect(herfindahlSpan.className).toContain("text-emerald-400");
  });

  // Branch 20 arm 1 (line 285-287): the outer ternary false arm (level !== "high").
  // Also covers branch 20 arm 0 (high) for completeness so the card's amber path is exercised.
  it("colors herfindahl text-amber-400 when concentration level is high", () => {
    const summary = makeSummary({
      concentration: {
        herfindahl: 0.6,
        topHolding: { ticker: "HOT", weight: 70 },
        level: "high",
      },
    });
    render(<CompositionSection summary={summary} totalUsd={1000} activeTab="ticker" />);
    const card = screen.getByTestId("side-concentration");
    const herfindahlSpan = card.querySelector("span.text-sm")!;
    expect(herfindahlSpan.className).toContain("text-amber-400");
  });
});
