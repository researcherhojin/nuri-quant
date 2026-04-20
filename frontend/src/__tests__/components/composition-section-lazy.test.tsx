/**
 * CompositionSectionLazy smoke — next/dynamic identity mock.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/dynamic", () => ({
  default: () => {
    const Stub = (props: Record<string, unknown>) => (
      <div data-testid="dynamic-stub">
        <span data-testid="total-usd">{String(props.totalUsd ?? "")}</span>
        <span data-testid="tab">{String(props.activeTab ?? "")}</span>
        <span data-testid="has-summary">{String(Boolean(props.summary))}</span>
      </div>
    );
    return Stub;
  },
}));

import { CompositionSectionLazy, parseCompositionTab } from "@/components/ui/composition-section-lazy";
import type { HoldingsSummary } from "@/lib/holdings-summary";

function makeSummary(): HoldingsSummary {
  return {
    today: { totalUsd: 100, totalPct: 0.5, upCount: 5, downCount: 1 },
    cumulative: { totalUsd: 1000, totalPct: 5 },
    winRate: { winners: 5, losers: 1, flat: 0, winRatePct: 83.3 },
    holdings: [],
    rowsByTicker: [],
    rowsBySector: [],
    rowsByAccount: [],
  } as unknown as HoldingsSummary;
}

describe("CompositionSectionLazy", () => {
  it("exports a component function", () => {
    expect(typeof CompositionSectionLazy).toBe("function");
  });

  it("re-exports parseCompositionTab", () => {
    expect(parseCompositionTab("sector")).toBe("sector");
    expect(parseCompositionTab("ticker")).toBe("ticker");
    expect(parseCompositionTab(undefined)).toBe("ticker");
  });

  it("passes summary + totalUsd + activeTab through to inner", () => {
    render(
      <CompositionSectionLazy
        summary={makeSummary()}
        totalUsd={12345}
        activeTab="sector"
      />,
    );
    expect(screen.getByTestId("dynamic-stub")).toBeInTheDocument();
    expect(screen.getByTestId("total-usd").textContent).toBe("12345");
    expect(screen.getByTestId("tab").textContent).toBe("sector");
    expect(screen.getByTestId("has-summary").textContent).toBe("true");
  });
});
