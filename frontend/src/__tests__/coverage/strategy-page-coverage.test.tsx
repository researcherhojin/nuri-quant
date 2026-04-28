/**
 * Strategy page — null regime, negative returns, empty arrays + with-data branches.
 * Split from coverage-push-5.test.tsx (lines 126-188).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

vi.mock("@/components/ui/equity-curve-chart", () => ({
  EquityCurveChart: ({ data }: { data: unknown[] }) => (
    <div data-testid="equity-curve-chart">{data.length} points</div>
  ),
}));

vi.mock("@/components/ui/price-chart", () => ({
  PriceChart: () => <div data-testid="price-chart" />,
  sma: (data: number[], _period: number) => data.map(() => null),
  formatVolume: (v: number) => String(v),
}));

vi.mock("@/components/ui/interactive-backtest-lazy", () => ({
  InteractiveBacktestLazy: ({ initialData }: { initialData: unknown[] }) => (
    <div data-testid="equity-curve-chart">{initialData.length} points</div>
  ),
}));

vi.mock("@/components/ui/price-chart-lazy", () => ({
  PriceChartLazy: () => <div data-testid="price-chart" />,
}));

const mockFetchAPI = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

describe("Strategy page branches", () => {
  beforeEach(() => { mockFetchAPI.mockReset(); });

  it("null regime, zero allocation, negative returns", async () => {
    mockFetchAPI.mockImplementation((path: string) => {
      if (path.includes("/api/strategy/status")) return {
        regime: null, allocation: { long_pct: 0, short_pct: 0, cash_pct: 0 },
        actions: [], positions: { positions: [] },
      };
      if (path.includes("/api/backtest")) return {
        result: { total_return: -2.5, sharpe: 0.3, spy_sharpe: 0.8,
          max_drawdown: -10, spy_max_drawdown: -15, spy_total_return: 8,
          transaction_costs: 0.3, total_days: 100, regime_changes: 2 },
        timing: null, stress: [],
      };
      return {};
    });

    const Page = await import("@/app/strategy/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => { expect(screen.getByText("Strategy")).toBeInTheDocument(); });
    expect(screen.queryByText(/confidence/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Long \d/)).not.toBeInTheDocument();
  });

  it("with timing, positions, actions, equity curve", async () => {
    mockFetchAPI.mockImplementation((path: string) => {
      if (path.includes("/api/strategy/status")) return {
        regime: { regime: "bear_high_vol", confidence: 0.65 },
        allocation: { long_pct: 30, short_pct: 20, cash_pct: 50 },
        actions: [{ action: "open_long", ticker: "AAPL", reason: "Momentum" }],
        positions: { positions: [
          { ticker: "MSFT", direction: "long", return_pct: -3.5 },
        ] },
      };
      if (path.includes("/api/backtest")) return {
        result: { total_return: 12.5, sharpe: 1.2, spy_sharpe: 0.8,
          max_drawdown: -8, spy_max_drawdown: -15, spy_total_return: 8,
          transaction_costs: 0.5, total_days: 365, regime_changes: 4,
          equity_curve: [{ date: "2024-01-01", value: 100000 }] },
        timing: { current_regime: "bear_high_vol",
          avg_forward_30d: -2.5, avg_forward_60d: -1.0, avg_forward_90d: 3.5,
          pct_to_bull: 0.3, pct_to_bear: 0.7 },
        stress: [
          { name: "2008", spy_return: -37, strategy_return: -12, protected: true },
        ],
      };
      return {};
    });

    const Page = await import("@/app/strategy/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("Long 30%")).toBeInTheDocument();
    });
    expect(screen.getByText("Short 20%")).toBeInTheDocument();
    expect(screen.getByText("Cash 50%")).toBeInTheDocument();
    expect(screen.getByText("65% confidence")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByTestId("equity-curve-chart")).toBeInTheDocument();
  });
});
