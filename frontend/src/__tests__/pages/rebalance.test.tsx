import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, act } from "@testing-library/react";

import { REBALANCE as R } from "@/lib/strings";

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

let mockFetchAPI: Mock;

vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

// #1227: 페이지가 /api/rebalance-advisor(위반 섹션)도 fetch — 경로로 라우팅
const mockAdvisorEmpty = {
  actions: [], total_violations: 0, total_recovery_usd: 0,
  violations_by_type: {}, violations_by_severity: {}, has_critical: false,
};

function setupFetchAPI(overrides: { rebalance?: unknown; advisor?: unknown } = {}) {
  mockFetchAPI = vi.fn().mockImplementation((path: string) => {
    if (path.includes("rebalance-advisor")) return Promise.resolve(overrides.advisor ?? mockAdvisorEmpty);
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
    expect(screen.getByText(/투자 규칙 위반 감지/)).toBeInTheDocument();
    // #1227: 두 섹션 — 룰 위반이 먼저, 비중 리밸런싱이 다음
    expect(screen.getByRole("heading", { name: R.SECTION_VIOLATIONS })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: R.SECTION_WEIGHTS })).toBeInTheDocument();
  });

  it("renders the advisor (violations) section inside the page", async () => {
    setupFetchAPI({
      advisor: {
        actions: [], total_violations: 3, total_recovery_usd: 1200,
        violations_by_type: { stop_loss: 3 }, violations_by_severity: { critical: 1, high: 2 }, has_critical: true,
      },
    });
    const { default: RebalancePage } = await import("@/app/rebalance/page");
    await act(async () => {
      render(<RebalancePage />);
    });
    expect(mockFetchAPI).toHaveBeenCalledWith("/api/rebalance-advisor");
    expect(screen.getByText("3건")).toBeInTheDocument();
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
