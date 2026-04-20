/**
 * InteractiveBacktestLazy smoke — next/dynamic identity mock.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/dynamic", () => ({
  default: () => {
    const Stub = (props: Record<string, unknown>) => (
      <div data-testid="dynamic-stub">
        <span data-testid="has-initial-data">{String(Boolean(props.initialData))}</span>
        <span data-testid="has-metrics">{String(Boolean(props.initialMetrics))}</span>
        <span data-testid="data-len">
          {String((props.initialData as unknown[])?.length ?? 0)}
        </span>
      </div>
    );
    return Stub;
  },
}));

import { InteractiveBacktestLazy } from "@/components/ui/interactive-backtest-lazy";

describe("InteractiveBacktestLazy", () => {
  it("exports a component function", () => {
    expect(typeof InteractiveBacktestLazy).toBe("function");
  });

  it("passes initialData + initialMetrics to inner", () => {
    render(
      <InteractiveBacktestLazy
        initialData={[
          { date: "2026-01-01", strategy: 100, spy: 100, drawdown: 0 },
          { date: "2026-01-02", strategy: 102, spy: 101, drawdown: -1 },
        ]}
        initialMetrics={{
          total_return: 5.0, sharpe: 1.2, max_drawdown: -3.0,
          win_rate: 60, spy_total_return: 3.0, excess_return: 2.0,
        }}
      />,
    );
    expect(screen.getByTestId("dynamic-stub")).toBeInTheDocument();
    expect(screen.getByTestId("has-initial-data").textContent).toBe("true");
    expect(screen.getByTestId("has-metrics").textContent).toBe("true");
    expect(screen.getByTestId("data-len").textContent).toBe("2");
  });

  it("works without initialMetrics (optional)", () => {
    render(<InteractiveBacktestLazy initialData={[]} />);
    expect(screen.getByTestId("has-metrics").textContent).toBe("false");
  });
});
