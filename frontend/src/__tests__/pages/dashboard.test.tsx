import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockRedirect = vi.fn().mockImplementation((path: string) => {
  throw new Error(`REDIRECT:${path}`);
});
vi.mock("next/navigation", () => ({
  redirect: (path: string) => mockRedirect(path),
}));

const mockFetchAPI = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

vi.mock("@/components/ui/freshness-bar", () => ({
  FreshnessBar: ({ items }: { items: unknown[] }) => (
    <div data-testid="freshness-bar">{items.length} items</div>
  ),
}));

const mockDashboardData = {
  verdict: "관망. 횡보 + 고변동 구간. 대기하며 레짐 전환을 주시하세요.",
  verdict_level: "cautious",
  regime: { regime: "bull_low_vol", trend: "bull", volatility: "low", confidence: 78, vix: 18.5, fear_greed: 55 },
  macro: { score: 65, interpretation: "Moderately positive" },
  allocation: { long: 50, short: 10, cash: 40 },
  actions: [
    { action: "BUY", ticker: "NVDA", confidence: 72, agreement: 80, reason: "Strong multi-factor score" },
    { action: "SELL", ticker: "INTC", confidence: 65, agreement: 70, reason: "Negative momentum" },
  ],
  alerts: [
    { level: "warning", message: "VIX approaching 25 threshold" },
    { level: "critical", message: "TSLA 손절선 돌파 (-8.1%)" },
  ],
  gate_score: 85,
  n_positions: 5,
};

const mockFreshness = {
  items: [
    { key: "prices", label: "Prices", status: "PASS", age_hours: 2, message: "OK" },
    { key: "vix", label: "VIX", status: "WARN", age_hours: 30, message: "Stale" },
  ],
  overall: "WARN", pass: 1, warn: 1, fail: 0,
};

const mockPipelineStatus = {
  steps: [
    { step: "collect", label: "Collect", status: "done", record_count: 25000, last_updated: "2026-03-31" },
    { step: "validate", label: "Validate", status: "done", record_count: 150, last_updated: "2026-03-31" },
  ],
};

const mockPortfolio = {
  count: 10,
  holdings: [
    { ticker: "TSLA", quantity: 33, avg_price: 343, latest_price: 250, currency: "USD" },
    { ticker: "005930.KS", quantity: 4, avg_price: 200500, latest_price: 210000, currency: "KRW" },
  ],
};

const mockSiege = { certified: true, score: 90, passed: 9, total: 10, conditions: [] };
const mockAdvisor = { has_critical: false, total_violations: 0, total_recovery_usd: 0 };

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockFetchAPI.mockReset();
    mockRedirect.mockClear();
    mockRedirect.mockImplementation((path: string) => { throw new Error(`REDIRECT:${path}`); });
  });

  function setupMocks(overrides: Record<string, unknown> = {}) {
    mockFetchAPI.mockImplementation((path: string) => {
      if (path.includes("/api/dashboard")) return Promise.resolve(overrides.dashboard ?? mockDashboardData);
      if (path.includes("/api/freshness")) return Promise.resolve(overrides.freshness ?? mockFreshness);
      if (path.includes("/api/pipeline/status")) return Promise.resolve(overrides.pipeline ?? mockPipelineStatus);
      if (path.includes("/api/portfolio")) return Promise.resolve(overrides.portfolio ?? mockPortfolio);
      if (path.includes("/api/certify")) return Promise.resolve(overrides.siege ?? mockSiege);
      if (path.includes("/api/rebalance-advisor")) return Promise.resolve(overrides.advisor ?? mockAdvisor);
      return Promise.resolve({});
    });
  }

  it("renders verdict with Korean label and portfolio value", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("주의")).toBeInTheDocument();
      expect(screen.getByText(/총 평가액/)).toBeInTheDocument();
      expect(screen.getByText("$8,850")).toBeInTheDocument();
    });
  });

  it("renders quality gate pass", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("통과")).toBeInTheDocument();
      expect(screen.getByText("9/10")).toBeInTheDocument();
    });
  });

  it("renders quality gate fail with conditions", async () => {
    setupMocks({
      siege: {
        certified: false, score: 40, passed: 4, total: 10,
        conditions: [{ passed: false, severity: "error", description: "포지션 한도 초과", detail: "TSLA > 15%" }],
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("미통과")).toBeInTheDocument();
      expect(screen.getByText("4/10")).toBeInTheDocument();
      expect(screen.getByText(/품질검증 미통과/)).toBeInTheDocument();
    });
  });

  it("renders verdict text", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText(/관망. 횡보/)).toBeInTheDocument();
    });
  });

  it("renders allocation bar with Korean labels", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText(/현금 40%/)).toBeInTheDocument();
    });
  });

  it("renders action items with Korean BUY/SELL", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText(/오늘의 매매/)).toBeInTheDocument();
      expect(screen.getByText("매수")).toBeInTheDocument();
      expect(screen.getByText("매도")).toBeInTheDocument();
      expect(screen.getByText("NVDA")).toBeInTheDocument();
    });
  });

  it("shows empty state for actions", async () => {
    setupMocks({ dashboard: { ...mockDashboardData, actions: [] } });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText(/매매 신호 없음/)).toBeInTheDocument();
    });
  });

  it("renders risk alerts with guidance", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText(/위험 관리/)).toBeInTheDocument();
      expect(screen.getByText(/TSLA 손절선 돌파/)).toBeInTheDocument();
      expect(screen.getByText(/매도 검토하여 손실 제한/)).toBeInTheDocument();
    });
  });

  it("shows no risk message when empty", async () => {
    setupMocks({ dashboard: { ...mockDashboardData, alerts: [] } });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText(/위험 요소 없음/)).toBeInTheDocument();
    });
  });

  it("renders market context in Korean", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("시장 현황")).toBeInTheDocument();
      expect(screen.getByText(/상승/)).toBeInTheDocument();
      expect(screen.getByText("18.5")).toBeInTheDocument();
    });
  });

  it("renders freshness bar", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByTestId("freshness-bar")).toBeInTheDocument();
    });
  });

  it("renders pipeline status", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getAllByText("Collect").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("renders loading skeleton", async () => {
    mockFetchAPI.mockReturnValue(new Promise(() => {}));
    const Page = await import("@/app/page");
    const { container } = render(<Page.default />);
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("shows rule violations when present", async () => {
    setupMocks({ advisor: { has_critical: true, total_violations: 3, total_recovery_usd: 500 } });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("3건")).toBeInTheDocument();
    });
  });

  it("hides violations and quality when zero", async () => {
    setupMocks({ siege: { certified: true, score: 100, passed: 0, total: 0, conditions: [] } });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.queryByText("품질검증")).not.toBeInTheDocument();
    });
  });
});
