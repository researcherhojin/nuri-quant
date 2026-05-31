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

  // L113: decisions.length === 0 → 빈 상태 카드 (table-row 분기 우회).
  // SummaryCards: L65 binary/cond truthy(total-pending>0) + L95 truthy(%) + L96 arm0(green, >=50).
  it("renders empty table + green Hit Rate (successRate >= 50)", async () => {
    mockFetchAPI.mockResolvedValue({
      decisions: [],
      count: 0,
      // total-pending=8>0, round(5/(5+3)*100)=63 → >=50 → green, value="63%"
      summary: { total: 10, pending: 2, success: 5, failure: 3, neutral: 0 },
    });
    const jsx = await DecisionsSection();
    const { getByText } = render(jsx);
    expect(getByText("63%")).toBeInTheDocument();
  });

  // L96 arm1 (red): successRate>0 && <50. round(1/(1+9)*100)=10.
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

  // L95 falsy ("—") + L96 arm2 (default): successRate === 0 (success=0, failure>0).
  it("renders em-dash + default Hit Rate (successRate === 0)", async () => {
    mockFetchAPI.mockResolvedValue({
      decisions: [],
      count: 0,
      summary: { total: 5, pending: 0, success: 0, failure: 3, neutral: 2 },
    });
    const jsx = await DecisionsSection();
    const { getByText } = render(jsx);
    expect(getByText("—")).toBeInTheDocument();
  });

  // L65 binary/cond falsy arm: total - pending <= 0 → successRate = 0 (else branch).
  it("hits the L65 false arm when total - pending <= 0", async () => {
    mockFetchAPI.mockResolvedValue({
      decisions: [],
      count: 0,
      // total-pending = 3-3 = 0 → not >0 → successRate=0 (no division)
      summary: { total: 3, pending: 3, success: 0, failure: 0, neutral: 0 },
    });
    const jsx = await DecisionsSection();
    const { getByText } = render(jsx);
    expect(getByText("—")).toBeInTheDocument();
  });

  // 테이블 본문 분기 (L159/161/163/171/107/108) — 3개 행으로 모든 arm 커버.
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
    const { container, getAllByText } = render(jsx);

    const rows = container.querySelectorAll("tbody tr");
    expect(rows.length).toBe(3);

    // 행1: confidence "85" 렌더 (L159 truthy arm).
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

    // outcome 라벨들이 3행에 걸쳐 존재 (success/failure/neutral → L171 3 arms).
    expect(getAllByText("success").length).toBeGreaterThan(0);
    expect(getAllByText("failure").length).toBeGreaterThan(0);
    expect(getAllByText("neutral").length).toBeGreaterThan(0);
  });
});
