/**
 * Advisor page — zero critical, missing severity keys, zero violations,
 * Ticker page null/empty + full-data branches.
 *
 * Split from coverage-push-5.test.tsx (lines 244-352). Includes Ticker page tests
 * because they share identical mock setup (chart-lazy mocks etc).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
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


// ═══════════════════════════════════════════════════════════
// Ticker — null/empty + full-data branches
// (cohabits because of shared chart-lazy mocks)
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
