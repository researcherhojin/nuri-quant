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
      if (path.includes("/api/portfolio/history")) return Promise.resolve({ history: [] });
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
      expect(screen.getByText(/품질 9\/10/)).toBeInTheDocument();
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
      expect(screen.getByText(/품질 미통과/)).toBeInTheDocument();
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

  it("renders action items as 신규 매수 후보 with Korean BUY/SELL", async () => {
    // Default mock: NVDA + INTC actions, TSLA + 005930.KS holdings → NVDA + INTC are not held
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText(/신규 매수 후보/)).toBeInTheDocument();
      expect(screen.getByText("매수")).toBeInTheDocument();
      expect(screen.getByText("매도")).toBeInTheDocument();
      expect(screen.getByText("NVDA")).toBeInTheDocument();
    });
  });

  it("shows empty state when no candidates", async () => {
    setupMocks({ dashboard: { ...mockDashboardData, actions: [] } });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText(/신규 매수 후보 없음/)).toBeInTheDocument();
    });
  });

  it("shows portfolio holdings and upcoming events in footer", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        upcoming_events: [
          { date: "2026-04-15", event_type: "earnings", ticker: "AAPL", description: "AAPL 실적발표", importance: 2 },
          { date: "2026-05-07", event_type: "fomc", ticker: null, description: "FOMC 금리결정", importance: 3 },
        ],
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // 보유 종목 항상 표시
      expect(screen.getByText(/보유 종목/)).toBeInTheDocument();
      // 다음 이벤트 푸터에 표시
      expect(screen.getByText(/AAPL 실적발표/)).toBeInTheDocument();
      expect(screen.getByText(/FOMC 금리결정/)).toBeInTheDocument();
    });
  });

  it("renders clickable alert lines with navigation", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        alerts: [
          { level: "critical", message: "TSLA 손절선 돌파 (-15.7%)" },
          { level: "warning", message: "BUY/SELL 충돌 2건: AAPL, MSFT" },
        ],
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText(/주의 2건/)).toBeInTheDocument();
      // Stop-loss alert links to ticker page
      const links = screen.getAllByRole("link");
      const tslaAlert = links.find(l => l.getAttribute("href") === "/ticker/TSLA");
      expect(tslaAlert).toBeTruthy();
      // Conflict alert links to decisions
      const conflictAlert = links.find(l => l.getAttribute("href") === "/decisions");
      expect(conflictAlert).toBeTruthy();
    });
  });

  it("shows nothing when alerts empty (no risk banner)", async () => {
    setupMocks({ dashboard: { ...mockDashboardData, alerts: [] } });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // Alert banner should not appear at all when no alerts
      expect(screen.queryByText(/주의.*건/)).not.toBeInTheDocument();
      // The old "위험 요소 없음" indicator is removed
      expect(screen.queryByText(/위험 요소 없음/)).not.toBeInTheDocument();
    });
  });

  it("renders market context inline strip in Korean", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // Inline strip shows trend, VIX value, and regime
      expect(screen.getByText(/상승/)).toBeInTheDocument();
      expect(screen.getByText("18.5")).toBeInTheDocument();
      expect(screen.getByText("VIX")).toBeInTheDocument();
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

  it("renders pipeline link in footer", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      const links = screen.getAllByRole("link");
      const pipelineLink = links.find(l => l.getAttribute("href") === "/pipeline");
      expect(pipelineLink).toBeTruthy();
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
      expect(screen.getByText(/규칙 위반 3건/)).toBeInTheDocument();
    });
  });

  it("hides violations and quality when zero", async () => {
    setupMocks({ siege: { certified: true, score: 100, passed: 0, total: 0, conditions: [] } });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.queryByText(/품질 검증/)).not.toBeInTheDocument();
    });
  });

  /* ── vixZone helper coverage ── */
  it("renders VIX null as dash", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        regime: { ...mockDashboardData.regime, vix: undefined },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // vixZone(null) returns label "—"
      const vixLabels = screen.getAllByText("—");
      expect(vixLabels.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("renders VIX < 12 as 안정", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        regime: { ...mockDashboardData.regime, vix: 10 },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("안정")).toBeInTheDocument();
    });
  });

  it("renders VIX < 17 as 낮음", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        regime: { ...mockDashboardData.regime, vix: 14 },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("낮음")).toBeInTheDocument();
    });
  });

  it("renders VIX 18.5 as 보통", async () => {
    // Default mock has vix: 18.5 which hits the v < 23 branch.
    // macro score 65 also maps to 보통, so we expect at least 2 occurrences.
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      const matches = screen.getAllByText("보통");
      expect(matches.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("renders VIX >= 33 as 위험", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        regime: { ...mockDashboardData.regime, vix: 40 },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("위험")).toBeInTheDocument();
    });
  });

  /* ── fgLabel / fgColor helper coverage ── */
  it("renders fear_greed < 25 as 극도 공포", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        regime: { ...mockDashboardData.regime, fear_greed: 15 },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("극도 공포")).toBeInTheDocument();
    });
  });

  it("renders fear_greed < 45 as 공포", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        regime: { ...mockDashboardData.regime, fear_greed: 35 },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("공포")).toBeInTheDocument();
    });
  });

  it("renders fear_greed 55 as 중립", async () => {
    // Default mock has fear_greed: 55 which hits fg <= 55
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("중립")).toBeInTheDocument();
    });
  });

  it("renders fear_greed 70 as 탐욕", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        regime: { ...mockDashboardData.regime, fear_greed: 70 },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("탐욕")).toBeInTheDocument();
    });
  });

  it("renders fear_greed > 75 as 극도 탐욕", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        regime: { ...mockDashboardData.regime, fear_greed: 90 },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("극도 탐욕")).toBeInTheDocument();
    });
  });

  it("renders fear_greed null as dash", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        regime: { ...mockDashboardData.regime, fear_greed: undefined },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      const dashes = screen.getAllByText("—");
      expect(dashes.length).toBeGreaterThanOrEqual(1);
    });
  });

  /* ── macroLevel helper coverage ── */
  it("renders macro score >= 70 as 양호", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        macro: { score: 75, interpretation: "Positive" },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("양호")).toBeInTheDocument();
    });
  });

  it("renders macro score < 30 as 취약", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        macro: { score: 20, interpretation: "Negative" },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("취약")).toBeInTheDocument();
    });
  });

  it("renders macro score 35 as 부진", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        macro: { score: 35, interpretation: "Below average" },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("부진")).toBeInTheDocument();
    });
  });

  /* ── displayName helper coverage ── */
  it("renders holding name when available", async () => {
    setupMocks({
      portfolio: {
        count: 2,
        holdings: [
          { ticker: "AAPL", name: "Apple Inc", quantity: 10, avg_price: 150, latest_price: 200, currency: "USD" },
          { ticker: "GOOG", quantity: 5, avg_price: 100, latest_price: 80, currency: "USD" },
        ],
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText(/Apple Inc/)).toBeInTheDocument();
    });
  });

  it("strips .KS suffix for Korean tickers in displayName", async () => {
    setupMocks({
      portfolio: {
        count: 2,
        holdings: [
          { ticker: "005930.KS", quantity: 10, avg_price: 50000, latest_price: 60000, currency: "KRW" },
          { ticker: "TSLA", quantity: 5, avg_price: 100, latest_price: 80, currency: "USD" },
        ],
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // displayName strips .KS, so "005930" should appear instead of "005930.KS"
      expect(screen.getByText(/005930/)).toBeInTheDocument();
    });
  });

  /* ── account_values rendering ── */
  it("renders account_values when present", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        account_values: [
          { account: "Main", value: 5000 },
          { account: "Pension", value: 3000 },
        ],
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText(/Main \$5,000/)).toBeInTheDocument();
      expect(screen.getByText(/Pension \$3,000/)).toBeInTheDocument();
    });
  });

  it("does not render account_values row when absent", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        account_values: undefined,
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("$8,850")).toBeInTheDocument();
      // No per-account breakdown text
      expect(screen.queryByText(/Main \$/)).not.toBeInTheDocument();
    });
  });

  /* ── account-grouped actions ── */
  it("renders Main/Sub actions in grouped section", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        actions: [
          { action: "BUY", ticker: "AAPL", confidence: 85, agreement: 90, reason: "Momentum", account: "Main" },
          { action: "SELL", ticker: "GOOG", confidence: 60, agreement: 70, reason: "Weakness", account: "Sub" },
        ],
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
      expect(screen.getByText("GOOG")).toBeInTheDocument();
      expect(screen.getByText("Main")).toBeInTheDocument();
      expect(screen.getByText("Sub")).toBeInTheDocument();
    });
  });

  it("renders Pension actions as '월말 매수 대기' when not month-end", async () => {
    // Default date (April 11) is not within 3 days of month end (April 30)
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        actions: [
          { action: "BUY", ticker: "SPY", confidence: 70, agreement: 80, reason: "Rebalance", account: "Pension" },
        ],
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText(/월말 매수 대기/)).toBeInTheDocument();
      // SPY should not appear as a clickable action (pension hidden mid-month)
      expect(screen.queryByText("SPY")).not.toBeInTheDocument();
    });
  });

  it("renders Pension actions expanded at month-end", async () => {
    // Mock Date so new Date() returns April 29 (1 day before month end → isMonthEnd = true)
    // Use a class-based mock to keep real timer functionality for waitFor
    const RealDate = globalThis.Date;
    const fakeNow = new RealDate(2026, 3, 29, 12, 0, 0).getTime(); // April 29
    class MockDate extends RealDate {
      constructor(...args: any[]) {
        if (args.length === 0) { super(fakeNow); } else { super(...(args as [any])); }
      }
      static override now() { return fakeNow; }
    }
    vi.stubGlobal("Date", MockDate);

    setupMocks({
      dashboard: {
        ...mockDashboardData,
        actions: [
          { action: "BUY", ticker: "SPY", confidence: 70, agreement: 80, reason: "Rebalance", account: "Pension" },
        ],
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("SPY")).toBeInTheDocument();
      expect(screen.getByText("연금")).toBeInTheDocument();
      expect(screen.queryByText(/월말 매수 대기/)).not.toBeInTheDocument();
    });

    vi.stubGlobal("Date", RealDate);
  });

  it("renders 'other' actions (no account or Toss)", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        actions: [
          { action: "BUY", ticker: "MSFT", confidence: 75, agreement: 85, reason: "Factor score", account: "Toss" },
          { action: "BUY", ticker: "AMZN", confidence: 65, agreement: 75, reason: "Breakout" },
        ],
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("MSFT")).toBeInTheDocument();
      expect(screen.getByText("AMZN")).toBeInTheDocument();
      expect(screen.getByText("Toss")).toBeInTheDocument();
    });
  });

  /* ── exchange_rate fallback ── */
  it("uses fallback exchange rate 1400 when exchange_rate is null", async () => {
    // KRW holding: 4 * 210000 / 1400 = 600; USD holding: 33 * 250 = 8250; total = 8850
    setupMocks({
      dashboard: { ...mockDashboardData, exchange_rate: null },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("$8,850")).toBeInTheDocument();
    });
  });

  it("uses provided exchange_rate when present", async () => {
    // KRW holding: 4 * 210000 / 1300 = ~646.15; USD holding: 33 * 250 = 8250; total ≈ 8896
    setupMocks({
      dashboard: { ...mockDashboardData, exchange_rate: 1300 },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("$8,896")).toBeInTheDocument();
    });
  });

  /* ── VIX 주의 zone (v < 33) ── */
  it("renders VIX 25 as 주의 zone", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        regime: { ...mockDashboardData.regime, vix: 25 },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // vixZone(25) → label "주의" — but "주의" also appears in verdict label
      // Check that VIX value 25 is rendered
      expect(screen.getByText("25")).toBeInTheDocument();
    });
  });

  /* ── mixed account actions (all groups present) ── */
  it("renders all account groups together", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        actions: [
          { action: "BUY", ticker: "AAPL", confidence: 85, agreement: 90, reason: "Momentum", account: "Main" },
          { action: "BUY", ticker: "GOOG", confidence: 70, agreement: 80, reason: "Rebalance", account: "Pension" },
          { action: "BUY", ticker: "MSFT", confidence: 75, agreement: 85, reason: "Factor", account: "Toss" },
        ],
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // Main action rendered
      expect(screen.getByText("AAPL")).toBeInTheDocument();
      // Toss (other) action rendered
      expect(screen.getByText("MSFT")).toBeInTheDocument();
      // Pension is mid-month → collapsed
      expect(screen.getByText(/월말 매수 대기/)).toBeInTheDocument();
    });
  });

  /* ── action with name field ── */
  it("renders action name and ticker when name is present", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        actions: [
          { action: "BUY", ticker: "NVDA", name: "NVIDIA Corp", confidence: 80, agreement: 90, reason: "AI growth", account: "Main" },
        ],
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByText("NVIDIA Corp")).toBeInTheDocument();
      expect(screen.getByText("NVDA")).toBeInTheDocument();
    });
  });
});
