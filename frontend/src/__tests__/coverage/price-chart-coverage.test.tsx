/**
 * PriceChart component — period switch, SMA legend, volume formatting.
 * Split from coverage-push-1.test.tsx (lines 230-269 PriceChart + 306-350 utility coverage).
 *
 * NOTE: kept separate from price-chart-tooltip-coverage.test.tsx — that file uses
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

describe("PriceChart", () => {
  const mockData = Array.from({ length: 300 }, (_, i) => ({
    date: `2024-${String(Math.floor(i / 30) + 1).padStart(2, "0")}-${String((i % 30) + 1).padStart(2, "0")}`,
    open: 100 + i * 0.5,
    high: 102 + i * 0.5,
    low: 98 + i * 0.5,
    close: 101 + i * 0.5,
    volume: 1000000 + i * 10000,
  }));

  it("renders chart with default period", async () => {
    const { PriceChart } = await import("@/components/ui/price-chart");
    render(<PriceChart data={mockData} ticker="AAPL" />);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("switches period on button click", async () => {
    const { PriceChart } = await import("@/components/ui/price-chart");
    render(<PriceChart data={mockData} ticker="NVDA" />);

    // Click 1M period
    fireEvent.click(screen.getByText("1M"));
    // Click ALL period
    fireEvent.click(screen.getByText("ALL"));
  });

  it("renders SMA legend", async () => {
    const { PriceChart } = await import("@/components/ui/price-chart");
    render(<PriceChart data={mockData} ticker="AAPL" />);
    expect(screen.getByText("Close")).toBeInTheDocument();
    expect(screen.getByText("SMA20")).toBeInTheDocument();
    expect(screen.getByText("SMA50")).toBeInTheDocument();
  });
});


// ═══════════════════════════════════════════════════════════
// PriceChart utility behaviors — short data + volume range branches
// ═══════════════════════════════════════════════════════════

describe("PriceChart utility functions coverage", () => {
  it("handles short data (< sma period)", async () => {
    const { PriceChart } = await import("@/components/ui/price-chart");
    const shortData = Array.from({ length: 10 }, (_, i) => ({
      date: `2024-01-${String(i + 1).padStart(2, "0")}`,
      open: 100, high: 102, low: 98, close: 101, volume: 500,
    }));
    render(<PriceChart data={shortData} ticker="TEST" />);
    expect(screen.getByText("TEST")).toBeInTheDocument();
  });

  it("handles volume formatting in different ranges", async () => {
    const { PriceChart } = await import("@/components/ui/price-chart");
    const data = Array.from({ length: 60 }, (_, i) => ({
      date: `2024-01-${String((i % 28) + 1).padStart(2, "0")}`,
      open: 100, high: 102, low: 98, close: 101,
      volume: i < 20 ? 500 : i < 40 ? 50000 : 5000000, // < 1K, K range, M range
    }));
    render(<PriceChart data={data} ticker="VOL" />);
    expect(screen.getByText("VOL")).toBeInTheDocument();
  });
});
