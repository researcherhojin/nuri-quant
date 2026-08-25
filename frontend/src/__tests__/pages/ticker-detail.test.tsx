/**
 * Ticker detail page coverage — renders the async TickerDetail component
 * by mocking fetchAPI and calling the default export with a mock params Promise.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Mock PriceChart (recharts doesn't render in jsdom)
vi.mock("@/components/ui/price-chart", () => ({
  PriceChart: ({ ticker }: { ticker: string }) => <div data-testid="price-chart">{ticker}</div>,
}));

// Mock fetchAPI at module level
const mockFetchAPI = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

const fullData = {
  ticker: "AAPL",
  price: { close: 185.5 },
  consensus: {
    final_action: "BUY",
    final_confidence: 75.3,
    agreement_rate: 0.8,
    verdicts: [
      { agent_name: "technical", action: "BUY", confidence: 80 },
      { agent_name: "risk", action: "HOLD", confidence: 60 },
    ],
    dissent: ["risk(HOLD, 60): moderate risk"],
  },
  analyst_ratings: [
    { firm: "Goldman", date: "2026-03-15", action: "upgrade", target_price: 200 },
    { firm: "JPM", date: "2026-03-10", action: "down", target_price: 170 },
  ],
  earnings: [
    { quarter: "2026-Q1", eps_actual: 2.1, eps_estimate: 1.9, surprise_pct: 0.105 },
    { quarter: "2025-Q4", eps_actual: 1.8, eps_estimate: 2.0, surprise_pct: -0.1 },
  ],
  insider_trades: [
    { insider_name: "Tim Cook CEO", transaction_type: "sale", value: 5000000, shares: 25000 },
    { insider_name: "Jeff Williams COO", transaction_type: "purchase", value: null, shares: 10000 },
  ],
  superinvestors: [
    { investor: "Buffett", portfolio_pct: 48.5 },
    { investor: "Dalio", portfolio_pct: 2.1 },
  ],
  fundamentals: {
    pe_ratio: 28.5,
    roe: 0.175,
    revenue_growth: 0.08,
    debt_to_equity: 1.5,
    profit_margin: 0.25,
    beta: 1.2,
  },
};

const priceData = {
  prices: Array.from({ length: 10 }, (_, i) => ({
    date: `2026-03-${String(i + 1).padStart(2, "0")}`,
    open: 180 + i, high: 186 + i, low: 179 + i, close: 185 + i, volume: 1000000,
  })),
};

const targets = {
  stock_type: "growth",
  stop_loss: 172.52, stop_loss_pct: -7,
  target_1: 222.6, target_1_pct: 20,
  target_2: 259.7, target_2_pct: 40,
  trailing_stop_pct: -15,
  analyst_target: 200, analyst_upside_pct: 8,
};

const external = {
  count: 2,
  data: [
    { source: "TipRanks", data_type: "consensus", value: "Strong Buy" },
    { source: "Dataroma", data_type: "holders", value: "5 holders" },
  ],
};

describe("TickerPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchAPI.mockImplementation((url: string) => {
      if (url.includes("/prices")) return Promise.resolve(priceData);
      if (url.includes("/targets/")) return Promise.resolve(targets);
      if (url.includes("/external/")) return Promise.resolve(external);
      if (url.includes("/ticker/")) return Promise.resolve(fullData);
      return Promise.resolve({});
    });
  });

  it("renders full ticker detail with all sections", async () => {
    const mod = await import("@/app/ticker/[symbol]/page");
    const element = await mod.default({ params: Promise.resolve({ symbol: "AAPL" }) });
    await act(async () => { render(element); });

    // Header
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    expect(screen.getAllByText("BUY").length).toBeGreaterThan(0);
    expect(screen.getByText("80% agree")).toBeInTheDocument();

    // Agent verdicts
    expect(screen.getByText("technical")).toBeInTheDocument();
    expect(screen.getByText("risk")).toBeInTheDocument();
    expect(screen.getByText("10-Agent Analysis")).toBeInTheDocument();

    // Dissent
    expect(screen.getByText(/risk\(HOLD/)).toBeInTheDocument();
  });

  it("renders analyst ratings with upgrade/downgrade", async () => {
    const mod = await import("@/app/ticker/[symbol]/page");
    const element = await mod.default({ params: Promise.resolve({ symbol: "AAPL" }) });
    await act(async () => { render(element); });

    expect(screen.getByText("Goldman")).toBeInTheDocument();
    expect(screen.getByText("$200")).toBeInTheDocument();
    expect(screen.getByText("JPM")).toBeInTheDocument();
  });

  it("renders earnings with surprise percentages", async () => {
    const mod = await import("@/app/ticker/[symbol]/page");
    const element = await mod.default({ params: Promise.resolve({ symbol: "AAPL" }) });
    await act(async () => { render(element); });

    expect(screen.getByText("2.10")).toBeInTheDocument();
    expect(screen.getByText("11%")).toBeInTheDocument();
  });

  it("renders insider trades with value and shares", async () => {
    const mod = await import("@/app/ticker/[symbol]/page");
    const element = await mod.default({ params: Promise.resolve({ symbol: "AAPL" }) });
    await act(async () => { render(element); });

    expect(screen.getByText("Tim Cook")).toBeInTheDocument();
    expect(screen.getByText("$5.0M")).toBeInTheDocument();
    expect(screen.getByText("10,000 sh")).toBeInTheDocument();
  });

  it("renders fundamentals metrics", async () => {
    const mod = await import("@/app/ticker/[symbol]/page");
    const element = await mod.default({ params: Promise.resolve({ symbol: "AAPL" }) });
    await act(async () => { render(element); });

    expect(screen.getByText("PE")).toBeInTheDocument();
    expect(screen.getByText("28.5")).toBeInTheDocument();
    expect(screen.getByText("ROE")).toBeInTheDocument();
    expect(screen.getByText("17.5%")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });

  it("renders superinvestors", async () => {
    const mod = await import("@/app/ticker/[symbol]/page");
    const element = await mod.default({ params: Promise.resolve({ symbol: "AAPL" }) });
    await act(async () => { render(element); });

    expect(screen.getByText("Buffett")).toBeInTheDocument();
    expect(screen.getByText("48.5%")).toBeInTheDocument();
    expect(screen.getByText("Dalio")).toBeInTheDocument();
  });

  it("renders price targets", async () => {
    const mod = await import("@/app/ticker/[symbol]/page");
    const element = await mod.default({ params: Promise.resolve({ symbol: "AAPL" }) });
    await act(async () => { render(element); });

    expect(screen.getByText("Price Targets (growth)")).toBeInTheDocument();
    expect(screen.getByText(/\$172\.52/)).toBeInTheDocument();
  });

  it("renders external data", async () => {
    const mod = await import("@/app/ticker/[symbol]/page");
    const element = await mod.default({ params: Promise.resolve({ symbol: "AAPL" }) });
    await act(async () => { render(element); });

    expect(screen.getByText("TipRanks/consensus")).toBeInTheDocument();
    expect(screen.getByText("Strong Buy")).toBeInTheDocument();
  });

  it("renders price chart", async () => {
    const mod = await import("@/app/ticker/[symbol]/page");
    const element = await mod.default({ params: Promise.resolve({ symbol: "AAPL" }) });
    await act(async () => { render(element); });

    expect(screen.getByTestId("price-chart")).toBeInTheDocument();
  });

  it("handles empty data gracefully", async () => {
    mockFetchAPI.mockImplementation((url: string) => {
      if (url.includes("/prices")) return Promise.resolve({ prices: [] });
      if (url.includes("/targets/")) return Promise.reject(new Error("404"));
      if (url.includes("/external/")) return Promise.reject(new Error("404"));
      return Promise.resolve({
        ticker: "NEW", price: {}, consensus: {},
        analyst_ratings: [], earnings: [], insider_trades: [],
        superinvestors: [], fundamentals: null,
      });
    });

    const mod = await import("@/app/ticker/[symbol]/page");
    const element = await mod.default({ params: Promise.resolve({ symbol: "NEW" }) });
    await act(async () => { render(element); });

    expect(screen.getAllByText("NEW").length).toBeGreaterThan(0);
    expect(screen.getByText("No rating data")).toBeInTheDocument();
    expect(screen.getByText("No earnings data")).toBeInTheDocument();
    expect(screen.getByText("No insider data")).toBeInTheDocument();
  });

  it("handles null earnings fields (partial branch coverage)", async () => {
    mockFetchAPI.mockImplementation((url: string) => {
      if (url.includes("/prices")) return Promise.resolve({ prices: [] });
      if (url.includes("/targets/")) return Promise.reject(new Error("404"));
      if (url.includes("/external/")) return Promise.reject(new Error("404"));
      return Promise.resolve({
        ticker: "NULL", price: { close: 50 }, consensus: { verdicts: [] },
        analyst_ratings: [],
        earnings: [
          { quarter: null, eps_actual: null, eps_estimate: null, surprise_pct: null },
          { quarter: "2026-Q1", eps_actual: 1.5, eps_estimate: 1.3, surprise_pct: 0 },
        ],
        insider_trades: [], superinvestors: [], fundamentals: null,
      });
    });

    const mod = await import("@/app/ticker/[symbol]/page");
    const element = await mod.default({ params: Promise.resolve({ symbol: "NULL" }) });
    await act(async () => { render(element); });

    // Null fields should render as "—"
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(3);
  });

  it("handles no consensus data", async () => {
    mockFetchAPI.mockImplementation((url: string) => {
      if (url.includes("/prices")) return Promise.resolve({ prices: [] });
      if (url.includes("/targets/")) return Promise.reject(new Error("404"));
      if (url.includes("/external/")) return Promise.resolve({ count: 0, data: [] });
      return Promise.resolve({
        ticker: "TEST", price: { close: 100 }, consensus: { verdicts: [] },
        analyst_ratings: [], earnings: [], insider_trades: [],
        superinvestors: [], fundamentals: null,
      });
    });

    const mod = await import("@/app/ticker/[symbol]/page");
    const element = await mod.default({ params: Promise.resolve({ symbol: "TEST" }) });
    await act(async () => { render(element); });

    // formatMoney (#1197): USD 는 소수 2자리 고정
    expect(screen.getByText("$100.00")).toBeInTheDocument();
  });
});
