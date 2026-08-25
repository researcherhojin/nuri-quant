import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, within } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  fetchAPI: vi.fn(),
}));

import { fetchAPI } from "@/lib/api";
import { DecisionsSection } from "./page";

const mockFetchAPI = vi.mocked(fetchAPI);

// 모든 행 필드를 채운 기본 decision. over 로 분기별 변형.
function makeDecision(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    date: "2026-01-15",
    ticker: "NVDA",
    action: "BUY",
    confidence: 85,
    regime: "RISK_ON",
    macro_score: 60,
    vix: 18,
    fear_greed: 55,
    agreement_rate: 0.8,
    entry_price: 800,
    stop_loss: 750,
    target_1: 880,
    target_2: 960,
    pnl_7d: 2.5,
    pnl_30d: 5.0,
    pnl_60d: 8.0,
    pnl_90d: 12.0,
    outcome: "success",
    reasoning: "Strong momentum",
    ...over,
  };
}

// async Server Component 의 nested Suspense child 는 jsdom 이 commit 하지 않으므로
// export 한 DecisionsSection 을 직접 await 후 반환 JSX 를 render 한다 (mandatory gotcha).
describe("DecisionsSection — exhaustive branch coverage", () => {
  beforeEach(() => {
    mockFetchAPI.mockReset();
  });

  // catch 분기 (L190): fetchAPI 가 throw → API_ERROR 메시지 반환.
  it("renders API error when fetchAPI throws", async () => {
    mockFetchAPI.mockRejectedValue(new Error("boom"));
    const jsx = await DecisionsSection();
    const { container } = render(jsx);
    expect(container.querySelector("p")?.className).toContain("text-red-400");
  });

  // decisions.length === 0 → 빈 상태 카드 (table-row 분기 우회).
  // SummaryCards: adjudicated>0 truthy + >=50 green arm.
  it("renders empty table + green Hit Rate (successRate >= 50)", async () => {
    mockFetchAPI.mockResolvedValue({
      decisions: [],
      count: 0,
      // adjudicated=8>0, round(5/8*100)=63 → >=50 → green, value="63%"
      summary: { total: 10, pending: 2, success: 5, failure: 3, neutral: 0 },
    });
    const jsx = await DecisionsSection();
    const { getByText } = render(jsx);
    expect(getByText("63%")).toBeInTheDocument();
  });

  // red arm: successRate < 50. round(1/10*100)=10.
  it("renders red Hit Rate (0 < successRate < 50)", async () => {
    mockFetchAPI.mockResolvedValue({
      decisions: [],
      count: 0,
      summary: { total: 12, pending: 2, success: 1, failure: 9, neutral: 0 },
    });
    const jsx = await DecisionsSection();
    const { getByText } = render(jsx);
    expect(getByText("10%")).toBeInTheDocument();
  });

  // #1216 의미 변경: 판정 3건 전패 → 0% 는 실측이다 ("—" 로 숨기지 않는다).
  it("renders 0% (red) when all adjudicated decisions failed", async () => {
    mockFetchAPI.mockResolvedValue({
      decisions: [],
      count: 0,
      summary: { total: 5, pending: 0, success: 0, failure: 3, neutral: 2 },
    });
    const jsx = await DecisionsSection();
    const { getByText } = render(jsx);
    expect(getByText("0%")).toBeInTheDocument();
  });

  // adjudicated === 0 (전부 pending) → 나눗셈 없이 "—" (NaN 가드, #1216).
  it("renders em-dash when nothing is adjudicated yet", async () => {
    mockFetchAPI.mockResolvedValue({
      decisions: [],
      count: 0,
      summary: { total: 3, pending: 3, success: 0, failure: 0, neutral: 0 },
    });
    const jsx = await DecisionsSection();
    const { getByText } = render(jsx);
    expect(getByText("—")).toBeInTheDocument();
  });

  // 테이블 본문 분기 — 3개 행으로 모든 arm 커버 (+#1216: 날짜 그룹 헤더 1행 추가).
  it("renders table rows covering all per-row ternary arms", async () => {
    mockFetchAPI.mockResolvedValue({
      decisions: [
        // 행1: 모든 truthy/positive arm.
        //  L159 confidence!=null, L161 regime present, L163 entry_price truthy,
        //  L171 arm0 (outcome==="success" → BUY),
        //  PnlCell value>0 → L107 arm0, L108 "+"(arm0).
        makeDecision({
          id: 1,
          confidence: 85,
          regime: "RISK_ON",
          entry_price: 800,
          outcome: "success",
          pnl_7d: 2.5,
          pnl_30d: 5.0,
          pnl_90d: 12.0,
        }),
        // 행2: falsy/negative arm.
        //  L159 confidence null (?. short-circuit), L161 regime null → "—",
        //  L163 entry_price null → "—", L171 arm1 (outcome==="failure" → SELL),
        //  PnlCell value<0 → L107 arm1, L108 ""(arm1).
        makeDecision({
          id: 2,
          confidence: null,
          regime: null,
          entry_price: null,
          outcome: "failure",
          pnl_7d: -1.5,
          pnl_30d: -3.0,
          pnl_90d: -7.0,
        }),
        // 행3: zero / null / 나머지 arm.
        //  L171 arm2 (outcome neither success/failure → HOLD),
        //  PnlCell value===0 → L106 false arm, L107 arm2 (muted), L108 arm1 + toFixed,
        //  PnlCell value===null (pnl_90d) → L106 TRUE arm → "—" 반환 (early return).
        makeDecision({
          id: 3,
          confidence: 50,
          regime: "NEUTRAL",
          entry_price: 100,
          outcome: "neutral",
          pnl_7d: 0,
          pnl_30d: 0,
          pnl_90d: null,
        }),
      ],
      count: 3,
      summary: { total: 10, pending: 2, success: 5, failure: 3, neutral: 0 },
    });
    const jsx = await DecisionsSection();
    const { container, getAllByText, getAllByTestId } = render(jsx);

    // 같은 날짜 3행 → 날짜 그룹 헤더 1 + 데이터 행 3 (#1216)
    expect(container.querySelectorAll("tbody tr").length).toBe(4);
    expect(getAllByTestId("decisions-date-header")).toHaveLength(1);
    const rows = getAllByTestId("decisions-row");
    expect(rows.length).toBe(3);

    // 행1: confidence "85" — micro-bar 숫자 (#1216).
    expect(within(rows[0] as HTMLElement).getByText("85")).toBeInTheDocument();
    // 행1: regime "RISK_ON" (L161 truthy arm).
    expect(within(rows[0] as HTMLElement).getByText("RISK_ON")).toBeInTheDocument();
    // 행1: entry "$800.00" (L163 truthy arm).
    expect(within(rows[0] as HTMLElement).getByText("$800.00")).toBeInTheDocument();
    // 행1: positive pnl "+2.5%" (L107 arm0 / L108 "+").
    expect(within(rows[0] as HTMLElement).getByText("+2.5%")).toBeInTheDocument();

    // 행2: regime null + entry_price null → "—" placeholder (L161/L163 falsy arms).
    const dashes = within(rows[1] as HTMLElement).getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(2);
    // 행2: negative pnl "-1.5%" (L107 arm1 / L108 "").
    expect(within(rows[1] as HTMLElement).getByText("-1.5%")).toBeInTheDocument();

    // 행3: zero pnl "0.0%" (L106 false arm / L107 arm2 / L108 "").
    expect(within(rows[2] as HTMLElement).getAllByText("0.0%").length).toBeGreaterThan(0);
    // 행3: pnl_90d=null → PnlCell L106 TRUE arm → "—" early return.
    expect(within(rows[2] as HTMLElement).getAllByText("—").length).toBeGreaterThan(0);

    // outcome intent 태그 (#1216: 성공→BUY 배지 오매핑 제거) + 판정 기준일 병기.
    // 세 행 모두 adjudicated (success/failure/neutral) → 2026-01-15+90d.
    expect(getAllByText("성공").length).toBeGreaterThan(0);
    expect(getAllByText("실패").length).toBeGreaterThan(0);
    expect(getAllByText("중립").length).toBeGreaterThan(0);
    expect(getAllByText("2026-04-15").length).toBe(3);
  });

  // #1216: action 필터는 RSC 측 필터 (API 미지원 파라미터).
  it("filters rows by action in the RSC when ?action= is set", async () => {
    mockFetchAPI.mockResolvedValue({
      decisions: [
        makeDecision({ id: 1, ticker: "AAA", action: "BUY" }),
        makeDecision({ id: 2, ticker: "BBB", action: "SELL" }),
      ],
      count: 2,
      summary: { total: 2, pending: 0, success: 2, failure: 0, neutral: 0 },
    });
    const jsx = await DecisionsSection({ action: "SELL" });
    const { getAllByTestId, queryByText } = render(jsx);
    expect(getAllByTestId("decisions-row")).toHaveLength(1);
    expect(queryByText("AAA")).not.toBeInTheDocument();
  });

  // #1216: outcome 필터는 API 파라미터로 전달된다.
  it("passes ?outcome= through to the API query", async () => {
    mockFetchAPI.mockResolvedValue({
      decisions: [],
      count: 0,
      summary: { total: 0, pending: 0, success: 0, failure: 0, neutral: 0 },
    });
    await DecisionsSection({ outcome: "failure" });
    expect(mockFetchAPI).toHaveBeenCalledWith("/api/decisions?limit=100&outcome=failure");
  });

  // #1216: 필터 중 0건은 데이터 부재 문구와 다른 전용 문구.
  it("shows the filtered-empty copy when a filter yields nothing", async () => {
    mockFetchAPI.mockResolvedValue({
      decisions: [makeDecision({ id: 1, action: "BUY" })],
      count: 1,
      summary: { total: 1, pending: 0, success: 1, failure: 0, neutral: 0 },
    });
    const jsx = await DecisionsSection({ action: "HOLD" });
    const { getByText, queryByText } = render(jsx);
    expect(getByText("필터에 해당하는 의사결정 없음.")).toBeInTheDocument();
    expect(queryByText(/make consensus/)).not.toBeInTheDocument();
  });
});
