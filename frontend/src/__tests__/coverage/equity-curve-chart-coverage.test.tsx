/**
 * EquityCurveChart — period switch, empty data branch.
 * Split from coverage-push-1.test.tsx (lines 270-294).
 *
 * NOTE: kept separate from equity-curve-tooltip-coverage.test.tsx — that file uses
 * vi.doMock("recharts") to capture tooltip formatters, while this file uses static
 * vi.mock("recharts"). vi.mock hoist scope per file (frontend/CLAUDE.md gotcha).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children?: ReactNode }) => <div data-testid="responsive-container">{children}</div>,
  ComposedChart: ({ children }: { children?: ReactNode }) => <div data-testid="composed-chart">{children}</div>,
  Area: () => <div data-testid="area" />,
  Line: () => <div data-testid="line" />,
  Bar: () => <div data-testid="bar" />,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  CartesianGrid: () => null,
}));

describe("EquityCurveChart", () => {
  it("returns null for empty data", async () => {
    const { EquityCurveChart } = await import("@/components/ui/equity-curve-chart");
    const { container } = render(<EquityCurveChart data={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders with data and period switch", async () => {
    const { EquityCurveChart } = await import("@/components/ui/equity-curve-chart");
    const data = Array.from({ length: 500 }, (_, i) => ({
      date: `2024-${String(Math.floor(i / 30) + 1).padStart(2, "0")}-${String((i % 30) + 1).padStart(2, "0")}`,
      strategy: i * 0.1,
      spy: i * 0.08,
      drawdown: -(i % 10) * 0.5,
    }));
    render(<EquityCurveChart data={data} />);
    expect(screen.getByText("Equity Curve")).toBeInTheDocument();
    expect(screen.getByText("Strategy")).toBeInTheDocument();
    expect(screen.getByText("Drawdown")).toBeInTheDocument();

    // Switch period
    fireEvent.click(screen.getByText("1Y"));
    fireEvent.click(screen.getByText("3Y"));
  });
});
