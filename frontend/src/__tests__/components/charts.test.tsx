import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// Mock recharts — jsdom can't render SVG charts
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: any) => <div data-testid="responsive-container">{children}</div>,
  ComposedChart: ({ children }: any) => <div data-testid="composed-chart">{children}</div>,
  Area: () => <div data-testid="area" />,
  Line: () => <div data-testid="line" />,
  Bar: () => <div data-testid="bar" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  Tooltip: () => <div data-testid="tooltip" />,
  CartesianGrid: () => <div data-testid="grid" />,
}));

describe("PriceChart", () => {
  const mockData = Array.from({ length: 60 }, (_, i) => ({
    date: `2026-01-${String(i + 1).padStart(2, "0")}`,
    open: 100 + i,
    high: 105 + i,
    low: 95 + i,
    close: 102 + i,
    volume: 1000000 + i * 10000,
  }));

  it("renders period selector buttons", async () => {
    const { PriceChart } = await import("@/components/ui/price-chart");
    render(<PriceChart data={mockData} ticker="AAPL" />);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("1M")).toBeInTheDocument();
    expect(screen.getByText("3M")).toBeInTheDocument();
    expect(screen.getByText("6M")).toBeInTheDocument();
    expect(screen.getByText("1Y")).toBeInTheDocument();
    expect(screen.getByText("ALL")).toBeInTheDocument();
  });

  it("renders chart container", async () => {
    const { PriceChart } = await import("@/components/ui/price-chart");
    render(<PriceChart data={mockData} ticker="AAPL" />);
    expect(screen.getAllByTestId("responsive-container").length).toBeGreaterThan(0);
  });

  it("renders legend items", async () => {
    const { PriceChart } = await import("@/components/ui/price-chart");
    render(<PriceChart data={mockData} ticker="AAPL" />);
    expect(screen.getByText("Close")).toBeInTheDocument();
    expect(screen.getByText("SMA20")).toBeInTheDocument();
    expect(screen.getByText("SMA50")).toBeInTheDocument();
  });

  it("switches period on button click", async () => {
    const { PriceChart } = await import("@/components/ui/price-chart");
    render(<PriceChart data={mockData} ticker="AAPL" />);
    const btn1M = screen.getByText("1M");
    fireEvent.click(btn1M);
    // After clicking 1M, the button should have active style
    expect(btn1M.className).toContain("bg-muted");
  });

  it("handles small dataset", async () => {
    const { PriceChart } = await import("@/components/ui/price-chart");
    const smallData = mockData.slice(0, 5);
    render(<PriceChart data={smallData} ticker="TEST" />);
    expect(screen.getByText("TEST")).toBeInTheDocument();
  });
});

describe("EquityCurveChart", () => {
  const mockData = Array.from({ length: 30 }, (_, i) => ({
    date: `2026-01-${String(i + 1).padStart(2, "0")}`,
    strategy: i * 0.5,
    spy: i * 0.3,
    drawdown: -Math.random() * 5,
  }));

  it("renders period selector and legend", async () => {
    const { EquityCurveChart } = await import("@/components/ui/equity-curve-chart");
    render(<EquityCurveChart data={mockData} />);
    expect(screen.getByText("Equity Curve")).toBeInTheDocument();
    expect(screen.getByText("1Y")).toBeInTheDocument();
    expect(screen.getByText("ALL")).toBeInTheDocument();
    expect(screen.getByText("Strategy")).toBeInTheDocument();
    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.getByText("Drawdown")).toBeInTheDocument();
  });

  it("renders chart containers", async () => {
    const { EquityCurveChart } = await import("@/components/ui/equity-curve-chart");
    render(<EquityCurveChart data={mockData} />);
    // Two charts: equity + drawdown
    expect(screen.getAllByTestId("responsive-container").length).toBe(2);
  });

  it("returns null for empty data", async () => {
    const { EquityCurveChart } = await import("@/components/ui/equity-curve-chart");
    const { container } = render(<EquityCurveChart data={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("switches period on click", async () => {
    const { EquityCurveChart } = await import("@/components/ui/equity-curve-chart");
    render(<EquityCurveChart data={mockData} />);
    const btn1Y = screen.getByText("1Y");
    fireEvent.click(btn1Y);
    expect(btn1Y.className).toContain("bg-muted");
  });
});
