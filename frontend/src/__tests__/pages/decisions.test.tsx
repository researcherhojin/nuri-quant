import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
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

let mockFetchAPI: Mock;

vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

function setupFetchAPI(response: unknown = mockDecisionsResponse) {
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

  it("renders ticker links to the frozen decision provenance page", async () => {
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    const link = screen.getByRole("link", { name: "AAA" });
    expect(link).toHaveAttribute("href", "/decisions/1");
  });

  it("renders action badges in rows (filter chips also carry BUY/SELL)", async () => {
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    // #1216: 필터 칩에도 BUY/SELL 텍스트가 있으므로 행 범위로 좁혀 단정한다
    const rows = screen.getAllByTestId("decisions-row");
    expect(rows[0].textContent).toContain("BUY");
    expect(rows[1].textContent).toContain("SELL");
  });

  // #1216: 필터 바 — outcome/action 칩과 초기화 링크가 URL 기반으로 렌더된다.
  it("renders URL-driven filter chips", async () => {
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    const bar = screen.getByTestId("decisions-filters");
    expect(bar.textContent).toContain("대기");
    expect(bar.textContent).toContain("성공");
    expect(bar.textContent).toContain("HOLD");
    const pendingChip = Array.from(bar.querySelectorAll("a")).find((a) => a.textContent === "대기");
    expect(pendingChip).toHaveAttribute("href", "/decisions?outcome=pending");
  });

  // #1216: 날짜 그룹 헤더 — 서로 다른 두 날짜의 행이 각자의 헤더 아래 묶인다.
  it("groups rows under date headers with counts", async () => {
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    const headers = screen.getAllByTestId("decisions-date-header");
    expect(headers).toHaveLength(2);
    expect(headers[0].textContent).toContain("2026-04-10");
    expect(headers[0].textContent).toContain("1건");
  });

  // #1216: 판정일 명시 — 판정일이 지난 pending 은 "판정일 도래 · 미판정"으로 드러난다.
  it("marks past-due pending rows as 판정일 도래", async () => {
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    // fixture date 2026-04-10/09 + 90d < 오늘 → due 라벨 (달력 진행에 무관하게 유지)
    expect(screen.getAllByText("판정일 도래 · 미판정").length).toBe(2);
  });

  // waiting arm: 최근 결정은 D-n 으로 렌더 (판정일 전) — 날짜는 실행 시점 기준 동적 생성.
  it("renders D-n for a recent pending decision", async () => {
    const recent = new Date(Date.now() - 10 * 86_400_000).toISOString().slice(0, 10);
    setupFetchAPI({
      decisions: [{ ...mockDecisionsResponse.decisions[0], id: 9, date: recent }],
      count: 1,
      summary: { total: 1, pending: 1, success: 0, failure: 0, neutral: 0 },
    });
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    const row = screen.getByTestId("decisions-row");
    expect(row.textContent).toMatch(/D-\d+/);
  });

  // 미지의 outcome 값은 pending 태그로 폴백한다 (OUTCOME_TAG ?? 가드).
  it("falls back to the pending tag for an unknown outcome value", async () => {
    setupFetchAPI({
      decisions: [{ ...mockDecisionsResponse.decisions[0], id: 9, outcome: "weird" }],
      count: 1,
      summary: { total: 1, pending: 1, success: 0, failure: 0, neutral: 0 },
    });
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    expect(screen.getByTestId("decisions-row").textContent).toContain("대기");
  });

  // searchParams 경로: outcome 은 API 로, action 은 RSC 로 — 필터 노트 병기 (codex R1 P2).
  it("applies searchParams filters and shows the global-summary note", async () => {
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => {
      render(await DecisionsPage({ searchParams: Promise.resolve({ outcome: "pending", action: "SELL" }) }));
    });
    expect(mockFetchAPI).toHaveBeenCalledWith("/api/decisions?limit=100&outcome=pending");
    const note = screen.getByTestId("decisions-filtered-note");
    expect(note.textContent).toContain("요약 카드는 전체 기준");
    // action=SELL → BBB 행만
    expect(screen.getAllByTestId("decisions-row")).toHaveLength(1);
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

  it("shows green hit rate when success >= 50%", async () => {
    setupFetchAPI({
      decisions: [
        { id: 1, date: "2026-01-01", ticker: "WIN", action: "BUY", confidence: 80,
          regime: null, macro_score: null, vix: null, fear_greed: null,
          agreement_rate: 0.9, entry_price: null, stop_loss: null,
          target_1: null, target_2: null, pnl_7d: null, pnl_30d: 15.0,
          pnl_60d: null, pnl_90d: 25.0, outcome: "success", reasoning: "test" },
      ],
      count: 1,
      summary: { total: 1, pending: 0, success: 1, failure: 0, neutral: 0 },
    });
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  it("shows red hit rate when success < 50%", async () => {
    setupFetchAPI({
      decisions: [
        { id: 1, date: "2026-01-01", ticker: "LOSE", action: "BUY", confidence: 40,
          regime: "bear_high_vol", macro_score: 30, vix: 35, fear_greed: 20,
          agreement_rate: 0.3, entry_price: 100, stop_loss: 93,
          target_1: 120, target_2: 140, pnl_7d: -5.0, pnl_30d: -15.0,
          pnl_60d: -20.0, pnl_90d: -25.0, outcome: "failure", reasoning: "bad" },
        { id: 2, date: "2026-01-02", ticker: "WIN2", action: "SELL", confidence: 70,
          regime: null, macro_score: null, vix: null, fear_greed: null,
          agreement_rate: null, entry_price: null, stop_loss: null,
          target_1: null, target_2: null, pnl_7d: 0, pnl_30d: null,
          pnl_60d: null, pnl_90d: null, outcome: "success", reasoning: null },
      ],
      count: 2,
      summary: { total: 3, pending: 1, success: 1, failure: 1, neutral: 0 },
    });
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    await act(async () => { render(await DecisionsPage()); });
    // 1 success / 2 completed = 50% → green
    expect(screen.getByText("50%")).toBeInTheDocument();
    // #1216: outcome 은 intent 태그 (성공/실패) + 판정 기준일 — BUY/SELL 배지 오매핑 폐지.
    // 필터 칩에도 "성공" 텍스트가 있으므로 행 범위로 단정한다.
    const rows = screen.getAllByTestId("decisions-row");
    const rowText = rows.map((r) => r.textContent).join(" ");
    expect(rowText).toContain("성공");
    expect(rowText).toContain("실패");
    expect(rowText).toContain("2026-04-01"); // 2026-01-01 + 90d
  });

  it("renders loading skeleton", async () => {
    const { default: DecisionsPage } = await import("@/app/decisions/page");
    // 페이지 JSX 는 await, Suspense 자식 promise 는 미해결 상태로 렌더 → fallback
    const { container } = render(await DecisionsPage());
    const pulses = container.querySelectorAll(".animate-pulse");
    expect(pulses.length).toBeGreaterThan(0);
  });
});
