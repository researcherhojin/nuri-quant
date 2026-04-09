import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockDecisionsResponse = {
  decisions: [
    {
      id: 1, date: "2026-04-10", ticker: "AAA", action: "BUY", confidence: 75,
      regime: "bull_low_vol", macro_score: 72, vix: 15, fear_greed: 65,
      agreement_rate: 0.8, entry_price: 120.0, stop_loss: 111.6,
      target_1: 144.0, target_2: 168.0, pnl_7d: 5.2, pnl_30d: null,
      pnl_60d: null, pnl_90d: null, outcome: "pending", reasoning: "Consensus",
    },
    {
      id: 2, date: "2026-04-09", ticker: "BBB", action: "SELL", confidence: 60,
      regime: "bull_low_vol", macro_score: 72, vix: 15, fear_greed: 65,
      agreement_rate: 0.6, entry_price: 250.0, stop_loss: null,
      target_1: null, target_2: null, pnl_7d: -3.1, pnl_30d: -8.5,
      pnl_60d: null, pnl_90d: null, outcome: "pending", reasoning: "Risk veto",
    },
  ],
  count: 2,
  summary: { total: 2, pending: 2, success: 0, failure: 0, neutral: 0 },
};

const mockEmptyResponse = {
  decisions: [],
  count: 0,
  summary: { total: 0, pending: 0, success: 0, failure: 0, neutral: 0 },
};

let mockFetchAPI: any;

vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: any[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

function setupFetchAPI(response: any = mockDecisionsResponse) {
  mockFetchAPI = vi.fn().mockResolvedValue(response);
}

describe("DecisionsPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setupFetchAPI();
  });

  it("renders page heading and description", async () => {
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    expect(screen.getByText("Decision Intelligence")).toBeInTheDocument();
    expect(screen.getByText(/의사결정 저널/)).toBeInTheDocument();
  });

  it("renders summary cards with correct labels", async () => {
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("Success")).toBeInTheDocument();
    expect(screen.getByText("Failure")).toBeInTheDocument();
    expect(screen.getByText("Hit Rate")).toBeInTheDocument();
  });

  it("renders decision table with tickers", async () => {
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    expect(screen.getByText("AAA")).toBeInTheDocument();
    expect(screen.getByText("BBB")).toBeInTheDocument();
  });

  it("renders PnL values with formatting", async () => {
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    expect(screen.getByText("+5.2%")).toBeInTheDocument();
    expect(screen.getByText("-8.5%")).toBeInTheDocument();
  });

  it("renders ticker links to detail page", async () => {
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    const link = screen.getByRole("link", { name: "AAA" });
    expect(link).toHaveAttribute("href", "/ticker/AAA");
  });

  it("renders action badges", async () => {
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("SELL")).toBeInTheDocument();
  });

  it("shows empty state when no decisions", async () => {
    setupFetchAPI(mockEmptyResponse);
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    expect(screen.getByText(/make consensus/)).toBeInTheDocument();
  });

  it("shows hit rate dash when no completed decisions", async () => {
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    // summary: 0 success, 0 failure → hit rate = "—"
    const hitRateCard = screen.getByText("Hit Rate").closest("div");
    expect(hitRateCard?.textContent).toContain("—");
  });

  it("handles API failure gracefully", async () => {
    mockFetchAPI = vi.fn().mockRejectedValue(new Error("API error"));
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    expect(screen.getByText(/API 연결 실패/)).toBeInTheDocument();
  });
});
