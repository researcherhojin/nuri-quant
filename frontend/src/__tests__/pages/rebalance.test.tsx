import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockRebalance = {
  actions: [
    {
      ticker: "NVDA", sector: "Semiconductor", action: "BUY",
      current_weight: 8.5, target_weight: 12.0, trade_value: 3500,
      signals: ["rsi_oversold", "macd_golden"], regime_note: "bull_low_vol favorable",
    },
    {
      ticker: "TSLA", sector: "SectorA", action: "SELL",
      current_weight: 18.0, target_weight: 10.0, trade_value: -8000,
      signals: ["sma_dead"], regime_note: "overweight in current regime",
    },
    {
      ticker: "AAPL", sector: "Tech", action: "HOLD",
      current_weight: 10.0, target_weight: 10.0, trade_value: 0,
      signals: [], regime_note: "on target",
    },
    {
      ticker: "MSFT", sector: "Tech", action: "HOLD",
      current_weight: 9.0, target_weight: 9.0, trade_value: 0,
      signals: [], regime_note: "on target",
    },
  ],
  method: "rp",
  actionable: 2,
};

let mockFetchAPI: any;

vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: any[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

function setupFetchAPI(overrides: { rebalance?: any } = {}) {
  mockFetchAPI = vi.fn().mockImplementation((_path: string) => {
    return Promise.resolve(overrides.rebalance ?? mockRebalance);
  });
}

describe("RebalancePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setupFetchAPI();
  });

  it("renders the page heading", async () => {
    const { default: RebalancePage } = await import("@/app/rebalance/page");
    await act(async () => {
      render(<RebalancePage />);
    });

    expect(screen.getByText("Rebalancing")).toBeInTheDocument();
  });

  it("renders Risk Parity method description with action count", async () => {
    const { default: RebalancePage } = await import("@/app/rebalance/page");
    await act(async () => {
      render(<RebalancePage />);
    });

    expect(screen.getByText(/Regime-Aware Rebalancing — Risk Parity \(2 actions\)/)).toBeInTheDocument();
  });

  it("renders HOLD tickers in footnote", async () => {
    const { default: RebalancePage } = await import("@/app/rebalance/page");
    await act(async () => {
      render(<RebalancePage />);
    });

    expect(screen.getByText(/HOLD: AAPL, MSFT/)).toBeInTheDocument();
  });

  it("calls fetchAPI with correct path", async () => {
    const { default: RebalancePage } = await import("@/app/rebalance/page");
    await act(async () => {
      render(<RebalancePage />);
    });

    expect(mockFetchAPI).toHaveBeenCalledWith("/api/rebalance?method=rp");
  });

  it("shows error message when API returns error field", async () => {
    setupFetchAPI({
      rebalance: { error: "No portfolio data" },
    });

    const { default: RebalancePage } = await import("@/app/rebalance/page");
    await act(async () => {
      render(<RebalancePage />);
    });

    expect(screen.getByText("No portfolio data")).toBeInTheDocument();
  });

  it("renders with no HOLD tickers", async () => {
    setupFetchAPI({
      rebalance: {
        actions: [mockRebalance.actions[0], mockRebalance.actions[1]],
        method: "rp",
        actionable: 2,
      },
    });

    const { default: RebalancePage } = await import("@/app/rebalance/page");
    await act(async () => {
      render(<RebalancePage />);
    });

    // No HOLD footnote
    expect(screen.queryByText(/HOLD:/)).not.toBeInTheDocument();
  });

  it("renders with all HOLD actions (empty actionable table)", async () => {
    setupFetchAPI({
      rebalance: {
        actions: [
          { ticker: "AAPL", sector: "Tech", action: "HOLD", current_weight: 10, target_weight: 10, trade_value: 0, signals: [], regime_note: "" },
        ],
        method: "rp",
        actionable: 0,
      },
    });

    const { default: RebalancePage } = await import("@/app/rebalance/page");
    await act(async () => {
      render(<RebalancePage />);
    });

    expect(screen.getByText(/0 actions/)).toBeInTheDocument();
    expect(screen.getByText(/HOLD: AAPL/)).toBeInTheDocument();
  });
});
