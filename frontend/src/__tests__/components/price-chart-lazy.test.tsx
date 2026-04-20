/**
 * PriceChartLazy smoke — next/dynamic identity mock.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/dynamic", () => ({
  default: () => {
    const Stub = (props: Record<string, unknown>) => (
      <div data-testid="dynamic-stub">
        <span data-testid="ticker">{String(props.ticker ?? "")}</span>
        <span data-testid="data-len">{String((props.data as unknown[])?.length ?? 0)}</span>
      </div>
    );
    return Stub;
  },
}));

import { PriceChartLazy } from "@/components/ui/price-chart-lazy";

describe("PriceChartLazy", () => {
  it("exports a component function", () => {
    expect(typeof PriceChartLazy).toBe("function");
  });

  it("passes ticker + data to inner", () => {
    render(
      <PriceChartLazy
        ticker="AAPL"
        data={[
          { date: "2026-01-01", open: 1, high: 2, low: 0, close: 1.5, volume: 100 },
        ]}
      />,
    );
    expect(screen.getByTestId("dynamic-stub")).toBeInTheDocument();
    expect(screen.getByTestId("ticker").textContent).toBe("AAPL");
    expect(screen.getByTestId("data-len").textContent).toBe("1");
  });
});
