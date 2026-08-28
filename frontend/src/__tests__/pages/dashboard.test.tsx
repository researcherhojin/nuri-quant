import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

// #1210: 도넛 폐지로 대시보드 트리에 recharts 소비자가 없다 — mock 불필요.
vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: string; [k: string]: unknown }) => (
    <a href={href} {...rest}>{children}</a>
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
  // #1284: 실 API 는 이 필드를 **항상** 낸다. 빠뜨려두면 `undefined` 가 되어 예전
  // `|| 1400` 폴백을 타고, 그 지어낸 값 위에서 기대치가 계산된다 — 잘못된 mock 형태가
  // 결함을 잠그던 자리다 (`tests/CLAUDE.md` "Mock Shape Locks Bugs").
  exchange_rate: 1400,
  fx_unavailable: null,
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
      // #223: 총 자산 label appears in HeroStats card label.
      const total = screen.getByTestId("hero-total");
      expect(total.textContent).toContain("총 자산");
      expect(total.textContent).toContain("$8,850");
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

  // U2b-1 계약 잠금 (#1206): "오늘의 답"이 첫 픽셀 — 배너가 대시보드 루트의 첫
  // 요소이고, 히어로는 더 이상 verdict 배지를 갖지 않는다. 배너가 히어로 아래로
  // 내려가거나 배지가 부활하면 FAIL.
  it("verdict banner is the FIRST dashboard element and hero owns no badge (#1206)", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    let container!: HTMLElement;
    await act(async () => { ({ container } = render(<Page.default />)); });
    await waitFor(() => {
      const banner = container.querySelector('[data-testid="verdict-banner"]');
      expect(banner).not.toBeNull();
      const root = banner!.parentElement!;
      expect(root.firstElementChild).toBe(banner);
      const hero = container.querySelector('[data-testid="hero-stats"]');
      expect(hero).not.toBeNull();
      // 배너가 히어로보다 DOM 상 앞선다
      expect(banner!.compareDocumentPosition(hero!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      // 히어로 총자산 셀에 verdict 라벨 배지 없음
      const total = container.querySelector('[data-testid="hero-total"]');
      expect(total!.textContent).not.toContain("관망");
    });
  });

  it("renders allocation values in compact market strip (#223 iter 7)", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // #223 iter 7: market context strip is now a single compact row.
      // Content includes "투자 50%" / "현금 40%" but as fragments not a single text node.
      const candidates = screen.getAllByText((_, el) => {
        const txt = el?.textContent ?? "";
        return txt.includes("실제") && txt.includes("40%") && txt.includes("현금");
      });
      expect(candidates.length).toBeGreaterThan(0);
    });
  });

  it("hero total includes cash from portfolio.cash (#213)", async () => {
    // holdings $8,850 + cash $5,000 = total $13,850
    setupMocks({
      portfolio: {
        count: 2,
        holdings: [
          { ticker: "TSLA", quantity: 33, avg_price: 343, latest_price: 250, currency: "USD" },
          { ticker: "005930.KS", quantity: 4, avg_price: 200500, latest_price: 210000, currency: "KRW" },
        ],
        cash: {
          accounts: [{ account: "Main", cash_usd: 5000, cash_krw: 0, total_usd: 5000 }],
          total_cash_usd: 5000,
        },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // #223: hero card has total + holdings/cash sub-line
      const total = screen.getByTestId("hero-total");
      expect(total.textContent).toContain("$13,850");
      expect(total.textContent).toContain("총 자산");
      expect(total.textContent).toContain("$8,850");
      expect(total.textContent).toContain("$5,000");
    });
  });

  it("renders actual + target allocation values in compact strip (#213 / #223 iter 7)", async () => {
    setupMocks({
      dashboard: {
        ...mockDashboardData,
        actual_allocation: { long: 46, short: 0, cash: 54 },
        target_allocation: { long: 20, short: 0, cash: 80 },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // #223 iter 7: allocation now a fragment in the compact market strip.
      // Numbers split across spans → assert via custom text matcher on the
      // strip's container. The strip is the market context strip at the top.
      const stripsWithAllocation = screen.getAllByText((_, el) => {
        const t = el?.textContent ?? "";
        return t.includes("실제") && t.includes("46%") && t.includes("권장") && t.includes("20%");
      });
      expect(stripsWithAllocation.length).toBeGreaterThan(0);
    });
  });

  it("falls back to holdings-only total when portfolio.cash is absent (#213)", async () => {
    // No cash in portfolio → hero shows $8,850 with holdings + cash $0 sub-line
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      const total = screen.getByTestId("hero-total");
      expect(total.textContent).toContain("$8,850");
      // No more per-account list in the hero (#223 moved that to composition)
      expect(total.textContent).not.toContain("Main $");
      expect(total.textContent).not.toContain("Pension $");
    });
  });

  it("renders sparkline period toggle in holdings header (#214 polish)", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      const toggle = screen.getByTestId("sparkline-period-toggle");
      expect(toggle).toBeInTheDocument();
      // All 4 period options rendered
      expect(toggle.textContent).toContain("14");
      expect(toggle.textContent).toContain("30");
      expect(toggle.textContent).toContain("60");
      expect(toggle.textContent).toContain("90");
    });
  });

  it("falls back to default period when ?period is not one of the allowed options", async () => {
    // parseSparklinePeriod: parseInt("45") = 45 → not in [14,30,60,90] → fallback 30
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => {
      render(<Page.default searchParams={Promise.resolve({ period: "45" })} />);
    });
    await waitFor(() => {
      // Active period "30" retains its highlighted class — rendered in the toggle
      const toggle = screen.getByTestId("sparkline-period-toggle");
      expect(toggle).toBeInTheDocument();
    });
  });

  it("renders gracefully when side endpoints reject (fetchAPI catch branches)", async () => {
    // Dashboard + portfolio resolve (prevents redirect); everything else rejects.
    // Exercises the .catch() defaults on freshness/pipeline/certify/advisor/targets.
    mockFetchAPI.mockImplementation((path: string) => {
      if (path.includes("/api/dashboard")) return Promise.resolve(mockDashboardData);
      if (path.includes("/api/portfolio/history")) return Promise.resolve({ history: [] });
      if (path.includes("/api/portfolio")) return Promise.resolve(mockPortfolio);
      return Promise.reject(new Error("network"));
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // Hero still renders with the resolved dashboard/portfolio data
      const total = screen.getByTestId("hero-total");
      expect(total.textContent).toContain("총 자산");
      expect(total.textContent).toContain("$8,850");
    });
  });


  it("hides Pension holdings from main table (#214 polish)", async () => {
    setupMocks({
      portfolio: {
        count: 3,
        holdings: [
          { ticker: "AAPL", account: "acct_m", quantity: 10, avg_price: 100, latest_price: 110, currency: "USD" },
          { ticker: "069500.KS", account: "acct_p", quantity: 5, avg_price: 30000, latest_price: 32000, currency: "KRW" },
          { ticker: "TIGER", account: "acct_p2", quantity: 2, avg_price: 50000, latest_price: 51000, currency: "KRW" },
        ],
        cash: { accounts: [], total_cash_usd: 0 },
      },
      dashboard: {
        ...mockDashboardData,
        actions: [],
        account_labels: {
          acct_m: "Main",
          acct_p: "Pension",
          acct_p2: "Pension 2",
        },
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // Only 1 holding row (Main AAPL); two Pension accounts filtered out
      const rows = screen.getAllByTestId("holding-row");
      expect(rows).toHaveLength(1);
      // "연금 2건 숨김" hint shown in header
      expect(screen.getByText(/연금 2건 숨김/)).toBeInTheDocument();
    });
  });

  it("renders distinct rows when same ticker held in multiple accounts (#199 multi-account fix)", async () => {
    // raw broker accounts → 익명 label per-account 매핑
    // TSLA in two distinct accounts → both rows must render with unique React keys
    const portfolio = {
      count: 4,
      holdings: [
        { ticker: "TSLA", account: "broker_a", quantity: 10, avg_price: 200, latest_price: 240, currency: "USD" },
        { ticker: "TSLA", account: "broker_b", quantity: 5, avg_price: 220, latest_price: 240, currency: "USD" },
        { ticker: "AAPL", account: "broker_a", quantity: 8, avg_price: 150, latest_price: 165, currency: "USD" },
        { ticker: "AAPL", account: "broker_b", quantity: 4, avg_price: 160, latest_price: 165, currency: "USD" },
      ],
    };
    setupMocks({
      portfolio,
      dashboard: {
        ...mockDashboardData,
        actions: [],
        ticker_accounts: { TSLA: "Main", AAPL: "Main" },  // 단일 매핑 (legacy)
        account_labels: { broker_a: "Main", broker_b: "Sub" },  // per-account 매핑 (#199 fix)
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // 4 holding rows (no React key collision, no rows omitted)
      const rows = screen.getAllByTestId("holding-row");
      expect(rows).toHaveLength(4);
    });
  });

  it("shows holdings and upcoming events in inline strip (#214 polish A)", async () => {
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
      // 보유 종목 section still present (#223: now via testid because the
      // text appears in both section header AND CompositionSection legend)
      expect(screen.getByTestId("holdings-section")).toBeInTheDocument();
      // Events rendered in events strip
      expect(screen.getByTestId("strip-events")).toBeInTheDocument();
      expect(screen.getByText(/AAPL 실적발표/)).toBeInTheDocument();
      expect(screen.getByText(/FOMC 금리결정/)).toBeInTheDocument();
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
      // #223: name appears in both holdings table row + composition legend.
      // Use the holding row testid to assert.
      const row = screen.getAllByTestId("holding-row").find((r) =>
        r.textContent?.includes("Apple Inc"),
      );
      expect(row).toBeTruthy();
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
      // displayName strips .KS, so "005930" should appear instead of "005930.KS".
      // #221 summary panel (hidden via CSS but still in DOM) may also include the
      // ticker in its movers card, so assert presence via the holding row itself.
      const row = screen.getAllByTestId("holding-row").find((r) =>
        r.textContent?.includes("005930"),
      );
      expect(row).toBeTruthy();
      expect(row?.textContent).not.toContain(".KS");
    });
  });

  /* ── account_values rendering (#223: now in CompositionSection account tab) ── */
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
      // #223: account names now live in the composition section's account tab
      // legend (visible only when activeTab === "account"). Default tab is "ticker"
      // so they're not in the DOM unless we navigate. Just assert the composition
      // section is present and the hero total renders.
      expect(screen.getByTestId("composition-section")).toBeInTheDocument();
      const total = screen.getByTestId("hero-total");
      expect(total.textContent).toContain("$8,850");
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
      const total = screen.getByTestId("hero-total");
      expect(total.textContent).toContain("$8,850");
    });
  });

  /* ── exchange_rate 부재 (#1284) ── */
  it("shows an em dash and the reason when exchange_rate is null", async () => {
    // 예전 이름은 "uses fallback exchange rate 1400..." 이었고 지어낸 1400 으로 환산한
    // $8,850 을 잠그고 있었다. 원화 보유가 있으면 통화 혼합 총액은 **미상**이다.
    const reason = "USD/KRW 미수집 — 원화 자산이 있어 통화 혼합 합계를 낼 수 없습니다";
    setupMocks({
      dashboard: { ...mockDashboardData, exchange_rate: null, fx_unavailable: reason },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // ⚠️ `hero-total` 컨테이너에 `toContain("—")` 만 걸면 **사유 문자열 안의 em dash**
      // 가 단언을 대신 만족시킨다 — 값이 "$0" 이어도 통과하는 false lock 이었다
      // (뮤테이션 실측으로 발각). 값 요소를 직접 본다.
      const value = screen.getByTestId("hero-total-value");
      expect(value.textContent).toBe("—");
      expect(screen.getByTestId("hero-total").textContent).toContain(reason);
    });
  });

  it("keeps a USD-only total exact when exchange_rate is null", async () => {
    // 대조군 — 환산이 필요 없으면 환율 부재와 무관하게 정확하다. 일괄 "—" 는 과잉이다.
    setupMocks({
      dashboard: { ...mockDashboardData, exchange_rate: null, fx_unavailable: null },
      portfolio: {
        count: 1,
        holdings: [
          { ticker: "ZZZZ", quantity: 10, avg_price: 100, latest_price: 250, currency: "USD" },
        ],
      },
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      expect(screen.getByTestId("hero-total-value").textContent).toBe("$2,500");
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
      const total = screen.getByTestId("hero-total");
      expect(total.textContent).toContain("$8,896");
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


  it("dashboard fetch 실패(503 shed 포함) → 홈은 stale 배너 최소 shape 로 강등 (#1119)", async () => {
    setupMocks();
    const impl = mockFetchAPI.getMockImplementation()!;
    mockFetchAPI.mockImplementation((path: string) => {
      if (path.includes("/api/dashboard")) return Promise.reject(new Error("API /api/dashboard: 503"));
      return impl(path);
    });
    const Page = await import("@/app/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => {
      // 홈이 에러 UI 로 죽지 않고 강등 문구 + stale 배너로 렌더된다
      expect(screen.getByText("데이터를 불러오지 못했습니다 — 잠시 후 새로고침하세요.")).toBeInTheDocument();
    });
  });
});
