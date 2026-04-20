/**
 * Coverage push 5: branch coverage for client-table, strategy, ticker,
 * consensus, signals, engine, advisor pages.
 * Follows established test patterns — mockImplementation with URL matching.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: any) => <a href={href}>{children}</a>,
}));

vi.mock("@/components/ui/equity-curve-chart", () => ({
  EquityCurveChart: ({ data }: { data: unknown[] }) => (
    <div data-testid="equity-curve-chart">{data.length} points</div>
  ),
}));

vi.mock("@/components/ui/price-chart", () => ({
  PriceChart: () => <div data-testid="price-chart" />,
  sma: (data: number[], period: number) => data.map(() => null),
  formatVolume: (v: number) => String(v),
}));

// InteractiveBacktestLazy / PriceChartLazy / CompositionSectionLazy 의 lazy wrapper
// 우회 — 각 모듈을 inner sync stub 으로 직접 mock. next/dynamic 의 async 성격을
// 테스트에서 재현하면 unstable 해서 lazy wrapper 자체를 identity 로 대체.

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
  fetchAPI: (...args: any[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

// ═══════════════════════════════════════════════════════════
// ClientTable — branch coverage 80% → higher
// ═══════════════════════════════════════════════════════════

describe("ClientTable branches", () => {
  it("renders targets with signal types and price formats", async () => {
    const { ClientTable } = await import("@/components/ui/client-table");
    const data = [
      { ticker: "AAPL", stock_type: "growth", current_price: 195.50,
        stop_loss: 181.82, target_1: 234.60, target_2: 273.70, analyst_target: 220.0,
        take_profit_triggered: "target_1", trailing_stop_triggered: false, take_profit_sell_pct: 50 },
      { ticker: "MSFT", stock_type: "value", current_price: 380.00,
        stop_loss: 342.00, target_1: 437.00, target_2: 494.00, analyst_target: null,
        take_profit_triggered: "target_2", trailing_stop_triggered: false, take_profit_sell_pct: 25 },
      { ticker: "005930.KS", stock_type: "value", current_price: 65000,
        stop_loss: 58500, target_1: 74750, target_2: 84500, analyst_target: 80000,
        take_profit_triggered: null, trailing_stop_triggered: true, take_profit_sell_pct: 0 },
      { ticker: "TSLA", stock_type: "growth", current_price: 0,
        stop_loss: 0, target_1: 0, target_2: 0, analyst_target: 0,
        take_profit_triggered: null, trailing_stop_triggered: false, take_profit_sell_pct: 0 },
    ];
    render(<ClientTable variant="targets" data={data} />);
    expect(screen.getByText("TP1 (50%)")).toBeInTheDocument();
    expect(screen.getByText("TP2 (25%)")).toBeInTheDocument();
    expect(screen.getByText("TRAIL STOP")).toBeInTheDocument();
    expect(screen.getByText("₩65,000")).toBeInTheDocument();
    expect(screen.getByText("$195.50")).toBeInTheDocument();
  });

  it("renders scorecard with negative/zero pct", async () => {
    const { ClientTable } = await import("@/components/ui/client-table");
    const data = [
      { signal_id: "rsi_oversold", total_trades: 100, win_rate: 0.65, profit_factor: 2.1, avg_return: 5.0 },
      { signal_id: "gap_down", total_trades: 50, win_rate: 0.45, profit_factor: 0.8, avg_return: -3.2 },
      { signal_id: "bb_bounce", total_trades: 30, win_rate: 0.50, profit_factor: 1.0, avg_return: 0.0 },
    ];
    const { container } = render(<ClientTable variant="scorecard" data={data} />);
    expect(container.querySelector(".text-emerald-400")).not.toBeNull();
    expect(container.querySelector(".text-red-400")).not.toBeNull();
  });

  it("renders unknown variant error", async () => {
    const { ClientTable } = await import("@/components/ui/client-table");
    render(<ClientTable variant="nonexistent" data={[]} />);
    expect(screen.getByText("Unknown variant: nonexistent")).toBeInTheDocument();
  });

  it("renders advisor variant with severity levels", async () => {
    const { ClientTable } = await import("@/components/ui/client-table");
    render(<ClientTable variant="advisor" data={[
      { priority: 1, ticker: "BBB", severity: "critical", action: "SELL_ALL", sell_shares: 100, sell_value_usd: 5000, reason: "Leveraged ETF" },
      { priority: 2, ticker: "AAPL", severity: "high", action: "SELL_PARTIAL", sell_shares: 5, sell_value_usd: 900, reason: "Sector limit" },
    ]} />);
    expect(screen.getByText("전량 매도")).toBeInTheDocument();
    expect(screen.getByText("일부 매도")).toBeInTheDocument();
  });

  it("renders gate with title and passed/failed", async () => {
    const { ClientTable } = await import("@/components/ui/client-table");
    render(<ClientTable variant="gate" data={[
      { description: "VIX", phase: "collect", passed: true, detail: "OK" },
      { description: "Fresh", phase: "validate", passed: false, detail: "Stale" },
    ]} compact title="Gate" />);
    expect(screen.getByText("Gate")).toBeInTheDocument();
    expect(screen.getByText("✅")).toBeInTheDocument();
    expect(screen.getByText("❌")).toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════
// Strategy — null regime, negative returns, empty arrays
// ═══════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════
// Consensus — VIX branches
// ═══════════════════════════════════════════════════════════

describe("Consensus page VIX branches", () => {
  beforeEach(() => { mockFetchAPI.mockReset(); });

  it("VIX < 25 → no banner", async () => {
    mockFetchAPI.mockImplementation(() => ({
      regime: { vix: 18, regime: "bull_low_vol" },
      results: [{ ticker: "AAPL", final_action: "BUY", final_confidence: 85,
        agreement_rate: 0.8, dissent: [], verdicts: [], reasoning: "" }],
      count: 1,
    }));

    const Page = await import("@/app/consensus/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => { expect(screen.getByText("AAPL")).toBeInTheDocument(); });
    expect(screen.queryByText(/신규 매수/)).not.toBeInTheDocument();
  });

  it("VIX 25-30 → warning banner", async () => {
    mockFetchAPI.mockImplementation(() => ({
      regime: { vix: 27.5, regime: "bear" },
      results: [{ ticker: "AAPL", final_action: "HOLD", final_confidence: 50,
        agreement_rate: 0.5, dissent: ["Risk high"], verdicts: [], reasoning: "" }],
      count: 1,
    }));

    const Page = await import("@/app/consensus/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => { expect(screen.getByText(/VIX/)).toBeInTheDocument(); });
  });
});

// ═══════════════════════════════════════════════════════════
// Signals — error branch
// ═══════════════════════════════════════════════════════════

describe("Signals page error", () => {
  beforeEach(() => { mockFetchAPI.mockReset(); });

  it("API error object → error display", async () => {
    mockFetchAPI.mockImplementation(() => ({ error: "CSV not found" }));
    const Page = await import("@/app/signals/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => { expect(screen.getByText("CSV not found")).toBeInTheDocument(); });
  });
});

// ═══════════════════════════════════════════════════════════
// Advisor — zero critical, missing severity keys
// ═══════════════════════════════════════════════════════════

describe("Advisor page branches", () => {
  beforeEach(() => { mockFetchAPI.mockReset(); });

  it("zero critical → default color", async () => {
    mockFetchAPI.mockImplementation(() => Promise.resolve({
      total_violations: 3, violations_by_severity: { critical: 0, high: 2, medium: 1 },
      actions: [], total_recovery_usd: 0, violations_by_type: {}, has_critical: false,
    }));
    const { default: AdvisorPage } = await import("@/app/advisor/page");
    await act(async () => { render(<AdvisorPage />); });
    expect(screen.getByText("3건")).toBeInTheDocument();
  });

  it("zero violations → early return with READY badge", async () => {
    mockFetchAPI.mockImplementation(() => Promise.resolve({
      total_violations: 0, violations_by_severity: {},
      actions: [], total_recovery_usd: 0, violations_by_type: {}, has_critical: false,
    }));
    const { default: AdvisorPage } = await import("@/app/advisor/page");
    await act(async () => { render(<AdvisorPage />); });
    expect(screen.getByText("모든 투자 규칙 준수 중. 위반 사항 없음.")).toBeInTheDocument();
  });
});

// Engine page severity branches are covered by
// src/__tests__/pages/engine.test.tsx

// ═══════════════════════════════════════════════════════════
// Ticker — null/empty branches
// ═══════════════════════════════════════════════════════════

describe("Ticker page branches", () => {
  beforeEach(() => { mockFetchAPI.mockReset(); });

  it("null consensus, no fund/targets/external", async () => {
    mockFetchAPI.mockImplementation((url: string) => {
      if (url.includes("/prices")) return Promise.resolve({ prices: [] });
      if (url.includes("/targets/")) return Promise.reject(new Error("not found"));
      if (url.includes("/external/")) return Promise.reject(new Error("not found"));
      if (url.includes("/ticker/")) return Promise.resolve({
        ticker: "ZZZZ", price: { close: null },
        consensus: { final_action: null, final_confidence: null,
          agreement_rate: null, verdicts: [], dissent: [] },
        analyst_ratings: [], earnings: [], insider_trades: [],
        superinvestors: [], fundamentals: null,
      });
      return Promise.resolve({});
    });
    const mod = await import("@/app/ticker/[symbol]/page");
    const element = await mod.default({ params: Promise.resolve({ symbol: "ZZZZ" }) });
    await act(async () => { render(element); });
    expect(screen.getByText("ZZZZ")).toBeInTheDocument();
    expect(screen.getByText("No rating data")).toBeInTheDocument();
    expect(screen.queryByText("Fundamentals")).not.toBeInTheDocument();
  });

  it("full data — fund, targets, external, insiders", async () => {
    mockFetchAPI.mockImplementation((url: string) => {
      if (url.includes("/prices")) return Promise.resolve({
        prices: [{ date: "2025-01-01", close: 190, open: 188, high: 192, low: 187, volume: 1000000 }],
      });
      if (url.includes("/targets/")) return Promise.resolve({
        stock_type: "growth", stop_loss: 181.82, stop_loss_pct: -7,
        target_1: 234.60, target_1_pct: 20, target_2: 273.70, target_2_pct: 40,
        trailing_stop_pct: 15, analyst_target: 220.0, analyst_upside_pct: 12.5,
      });
      if (url.includes("/external/")) return Promise.resolve({
        count: 2, data: [
          { source: "tipranks", data_type: "consensus", value: "Strong Buy" },
          { source: "dataroma", data_type: "holders", value: "3 supers" },
        ],
      });
      if (url.includes("/ticker/")) return Promise.resolve({
        ticker: "AAPL", price: { close: 195.50 },
        consensus: { final_action: "BUY", final_confidence: 85,
          agreement_rate: 0.8,
          verdicts: [{ agent_name: "technical", action: "BUY", confidence: 90 }],
          dissent: ["Risk: high vol"] },
        analyst_ratings: [
          { firm: "GS", date: "2025-03-01", action: "upgrade", target_price: 220 },
          { firm: "MS", date: "2025-03-02", action: "downgrade", target_price: 180 },
        ],
        earnings: [
          { quarter: "2025-Q1", eps_actual: 2.5, eps_estimate: 2.3, surprise_pct: 0.087 },
          { quarter: "2024-Q4", eps_actual: 1.8, eps_estimate: 2.0, surprise_pct: -0.1 },
        ],
        insider_trades: [
          { transaction_type: "purchase", insider_name: "Tim Cook", value: 5000000 },
          { transaction_type: "sale", insider_name: "Jeff W", value: null, shares: 50000 },
        ],
        superinvestors: [{ investor: "Berkshire", portfolio_pct: 2.5 }],
        fundamentals: { pe_ratio: 28.5, roe: 0.45, revenue_growth: 0.08,
          debt_to_equity: 1.2, profit_margin: 0.25, beta: 1.15 },
      });
      return Promise.resolve({});
    });
    const mod = await import("@/app/ticker/[symbol]/page");
    const element = await mod.default({ params: Promise.resolve({ symbol: "AAPL" }) });
    await act(async () => { render(element); });
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("85")).toBeInTheDocument();
    expect(screen.getByText("80% agree")).toBeInTheDocument();
    expect(screen.getByText("Fundamentals")).toBeInTheDocument();
    expect(screen.getByText("Price Targets (growth)")).toBeInTheDocument();
    expect(screen.getByText("External Data (2)")).toBeInTheDocument();
    expect(screen.getByText("$5.0M")).toBeInTheDocument();
    expect(screen.getByText("50,000 sh")).toBeInTheDocument();
  });
});
