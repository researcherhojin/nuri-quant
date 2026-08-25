import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Mock fetchAPI
const mockFetchAPI = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

// Mock EquityCurveChart (recharts does not render in jsdom)
vi.mock("@/components/ui/equity-curve-chart", () => ({
  EquityCurveChart: ({ data }: { data: unknown[] }) => (
    <div data-testid="equity-curve-chart">{data.length} points</div>
  ),
}));

const mockStrategyStatus = {
  regime: {
    regime: "bull_low_vol",
    trend: "bull",
    volatility: "low",
    confidence: 0.82,
  },
  allocation: {
    long_pct: 60,
    short_pct: 10,
    cash_pct: 30,
  },
  actions: [
    { action: "open_long", ticker: "NVDA", reason: "Strong momentum + factor score" },
    { action: "close_short", ticker: "TSLA", reason: "Regime shifted to bull" },
  ],
  positions: {
    positions: [
      { ticker: "AAPL", direction: "long", return_pct: 5.2 },
      { ticker: "NVDA", direction: "long", return_pct: -2.1 },
      { ticker: "TSLA", direction: "short", return_pct: 3.8 },
    ],
  },
};

const mockBacktest = {
  result: {
    total_return: 25.3,
    spy_total_return: 18.5,
    sharpe: 1.42,
    spy_sharpe: 1.1,
    max_drawdown: -8.5,
    spy_max_drawdown: -12.3,
    transaction_costs: 0.8,
    total_days: 1260,
    regime_changes: 15,
    equity_curve: [],
  },
  timing: {
    current_regime: "bull_low_vol",
    avg_forward_30d: 2.5,
    avg_forward_60d: 5.1,
    avg_forward_90d: 8.2,
    pct_to_bull: 0.65,
    pct_to_bear: 0.15,
  },
  stress: [
    { name: "COVID-19", spy_return: -33.9, strategy_return: -18.2, protected: true },
    { name: "2022 Bear", spy_return: -25.4, strategy_return: -12.1, protected: true },
    { name: "Flash Crash", spy_return: -9.0, strategy_return: -5.5, protected: true },
  ],
};

function setupMocks(overrides: Record<string, unknown> = {}) {
  mockFetchAPI.mockImplementation((path: string) => {
    if (path.includes("/api/strategy/status")) return Promise.resolve(overrides.status ?? mockStrategyStatus);
    if (path.includes("/api/backtest")) return Promise.resolve(overrides.backtest ?? mockBacktest);
    return Promise.resolve({});
  });
}

describe("StrategyPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockFetchAPI.mockReset();
  });

  it("renders page title after data loads", async () => {
    setupMocks();
    const Page = await import("@/app/strategy/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("Strategy")).toBeInTheDocument();
    });
  });

  it("renders regime status badge", async () => {
    setupMocks();
    const Page = await import("@/app/strategy/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("BULL_LOW_VOL")).toBeInTheDocument();
      expect(screen.getByText("82% confidence")).toBeInTheDocument();
    });
  });

  it("renders allocation bar with long/short/cash percentages", async () => {
    setupMocks();
    const Page = await import("@/app/strategy/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("Long 60%")).toBeInTheDocument();
      expect(screen.getByText("Short 10%")).toBeInTheDocument();
      expect(screen.getByText("Cash 30%")).toBeInTheDocument();
    });
  });

  it("renders backtest metrics", async () => {
    setupMocks();
    const Page = await import("@/app/strategy/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("+25.3%")).toBeInTheDocument();
      expect(screen.getByText("1.42")).toBeInTheDocument();
      expect(screen.getByText("-8.5%")).toBeInTheDocument();
      expect(screen.getByText("Return")).toBeInTheDocument();
      expect(screen.getByText("Sharpe")).toBeInTheDocument();
    });
  });

  it("renders stress test scenarios", async () => {
    setupMocks();
    const Page = await import("@/app/strategy/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("Crisis Protection")).toBeInTheDocument();
      expect(screen.getByText("COVID-19")).toBeInTheDocument();
      expect(screen.getByText("2022 Bear")).toBeInTheDocument();
    });
  });

  it("renders open positions", async () => {
    setupMocks();
    const Page = await import("@/app/strategy/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("Open Positions")).toBeInTheDocument();
      expect(screen.getByText("AAPL")).toBeInTheDocument();
      // NVDA and TSLA appear in both actions and positions sections
      expect(screen.getAllByText("NVDA").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("TSLA").length).toBeGreaterThanOrEqual(1);
      // Check position return values to confirm position section renders
      expect(screen.getByText("5.2%")).toBeInTheDocument();
      expect(screen.getByText("-2.1%")).toBeInTheDocument();
      expect(screen.getByText("3.8%")).toBeInTheDocument();
    });
  });

  it("renders entry timing forward returns", async () => {
    setupMocks();
    const Page = await import("@/app/strategy/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("+2.5%")).toBeInTheDocument();
      expect(screen.getByText("+5.1%")).toBeInTheDocument();
      expect(screen.getByText("+8.2%")).toBeInTheDocument();
      expect(screen.getByText("30d")).toBeInTheDocument();
      expect(screen.getByText("60d")).toBeInTheDocument();
      expect(screen.getByText("90d")).toBeInTheDocument();
    });
  });

  it("hides positions section when no positions", async () => {
    setupMocks({
      status: { ...mockStrategyStatus, positions: { positions: [] } },
    });
    const Page = await import("@/app/strategy/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("Strategy")).toBeInTheDocument();
    });

    expect(screen.queryByText("Open Positions")).not.toBeInTheDocument();
  });

  it("renders positions count in header", async () => {
    setupMocks();
    const Page = await import("@/app/strategy/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("3 positions open")).toBeInTheDocument();
    });
  });

  it("renders loading skeleton initially", async () => {
    // Make fetchAPI never resolve to test the Suspense fallback
    mockFetchAPI.mockReturnValue(new Promise(() => {}));
    const Page = await import("@/app/strategy/page");
    const { container } = render(<Page.default />);

    // Suspense fallback shows animate-pulse skeletons
    const pulseElements = container.querySelectorAll(".animate-pulse");
    expect(pulseElements.length).toBeGreaterThan(0);
  });

  it("gated fetch 실패(503 shed 포함) → 섹션만 강등 (#1119)", async () => {
    mockFetchAPI.mockImplementation(() => Promise.reject(new Error("API /api/backtest: 503")));
    const { StrategyDashboard } = await import("@/app/strategy/page");
    const ui = await StrategyDashboard();
    render(ui);
    expect(screen.getByText("데이터를 불러오지 못했습니다 — 잠시 후 새로고침하세요.")).toBeInTheDocument();
  });
});
