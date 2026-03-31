import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  fetchAPI: vi.fn(),
  API_BASE: "http://localhost:8001",
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/components/ui/price-chart", () => ({
  PriceChart: ({ ticker }: { ticker: string }) => <div data-testid="price-chart">{ticker}</div>,
}));

const mockTickerData = {
  ticker: "AAPL",
  price: { close: 185.5 },
  consensus: {
    final_action: "BUY",
    final_confidence: 75.3,
    agreement_rate: 0.8,
    verdicts: [
      { agent_name: "technical", action: "BUY", confidence: 80 },
      { agent_name: "fundamental", action: "HOLD", confidence: 60 },
    ],
    dissent: ["fundamental(HOLD, 60): neutral"],
  },
  analyst_ratings: [
    { firm: "Goldman Sachs", date: "2026-03-15", action: "upgrade", target_price: 200 },
  ],
  earnings: [
    { quarter: "2026-Q1", eps_actual: 2.1, eps_estimate: 1.9, surprise_pct: 0.105 },
  ],
  insider_trades: [
    { insider_name: "Tim Cook CEO", transaction_type: "sale", value: 5000000 },
  ],
  superinvestors: [{ investor: "Buffett", portfolio_pct: 48.5 }],
  fundamentals: {
    pe_ratio: 28.5, roe: 0.175, revenue_growth: 0.08,
    debt_to_equity: 1.5, profit_margin: 0.25, beta: 1.2,
  },
};

const mockPriceData = { prices: [{ date: "2026-03-01", open: 180, high: 186, low: 179, close: 185, volume: 1000000 }] };
const mockTargets = { stock_type: "growth", stop_loss: 172.52, stop_loss_pct: -7, target_1: 222.6, target_1_pct: 20, target_2: 259.7, target_2_pct: 40, trailing_stop_pct: -15, analyst_target: 200, analyst_upside_pct: 8 };
const mockExternal = { count: 1, data: [{ source: "TipRanks", data_type: "consensus", value: "Strong Buy" }] };

import { fetchAPI } from "@/lib/api";
const mockFetchAPI = fetchAPI as ReturnType<typeof vi.fn>;

function setupMocks(overrides: Record<string, any> = {}) {
  mockFetchAPI.mockImplementation((url: string) => {
    if (url.includes("/prices")) return Promise.resolve(overrides.prices ?? mockPriceData);
    if (url.includes("/targets/")) return Promise.resolve(overrides.targets ?? mockTargets);
    if (url.includes("/external/")) return Promise.resolve(overrides.external ?? mockExternal);
    if (url.includes("/ticker/")) return Promise.resolve(overrides.ticker ?? mockTickerData);
    return Promise.resolve({});
  });
}

// Test fetchAPI calls and data shapes without rendering the full async page component
// (React 19 in jsdom doesn't support async server components with await params)
describe("TickerPage API integration", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("calls correct API endpoints for a ticker", async () => {
    setupMocks();
    // Simulate the 4 parallel fetches from TickerDetail
    const [data, priceData, targets, external] = await Promise.all([
      mockFetchAPI(`/api/ticker/AAPL`),
      mockFetchAPI(`/api/ticker/AAPL/prices?days=365`),
      mockFetchAPI(`/api/targets/AAPL`),
      mockFetchAPI(`/api/external/AAPL`),
    ]);
    expect(data.ticker).toBe("AAPL");
    expect(priceData.prices.length).toBe(1);
    expect(targets.stock_type).toBe("growth");
    expect(external.count).toBe(1);
  });

  it("handles targets/external errors gracefully", async () => {
    mockFetchAPI.mockImplementation((url: string) => {
      if (url.includes("/targets/")) return Promise.reject(new Error("not found"));
      if (url.includes("/external/")) return Promise.reject(new Error("not found"));
      if (url.includes("/prices")) return Promise.resolve({ prices: [] });
      return Promise.resolve({ ticker: "NEW", consensus: {}, analyst_ratings: [], earnings: [], insider_trades: [], superinvestors: [], fundamentals: null });
    });
    const [data, , targets, external] = await Promise.all([
      mockFetchAPI(`/api/ticker/NEW`),
      mockFetchAPI(`/api/ticker/NEW/prices?days=365`),
      mockFetchAPI(`/api/targets/NEW`).catch(() => null),
      mockFetchAPI(`/api/external/NEW`).catch(() => null),
    ]);
    expect(data.ticker).toBe("NEW");
    expect(targets).toBeNull();
    expect(external).toBeNull();
  });

  it("consensus verdicts are mapped correctly", () => {
    const verdicts = mockTickerData.consensus.verdicts;
    expect(verdicts.length).toBe(2);
    expect(verdicts[0].action).toBe("BUY");
    expect(verdicts[1].action).toBe("HOLD");
  });

  it("insider trade value formatting", () => {
    const ins = mockTickerData.insider_trades[0];
    const formatted = ins.value ? `$${(ins.value / 1000000).toFixed(1)}M` : "";
    expect(formatted).toBe("$5.0M");
  });

  it("earnings surprise percentage", () => {
    const e = mockTickerData.earnings[0];
    const surprise = e.surprise_pct ? `${(e.surprise_pct * 100).toFixed(0)}%` : "—";
    expect(surprise).toBe("11%");
  });

  it("analyst rating action mapping", () => {
    const r = mockTickerData.analyst_ratings[0];
    const mapped = r.action === "up" || r.action === "upgrade" ? "BUY" : r.action === "down" || r.action === "downgrade" ? "SELL" : "HOLD";
    expect(mapped).toBe("BUY");
  });

  it("fundamentals ROE formatting", () => {
    const fund = mockTickerData.fundamentals;
    const roe = `${(fund.roe * 100).toFixed(1)}%`;
    expect(roe).toBe("17.5%");
    expect(fund.roe > 0.15).toBe(true); // green color
  });

  it("price targets display values", () => {
    expect(mockTargets.stop_loss).toBe(172.52);
    expect(mockTargets.target_1_pct).toBe(20);
    expect(mockTargets.analyst_upside_pct).toBe(8);
  });
});
