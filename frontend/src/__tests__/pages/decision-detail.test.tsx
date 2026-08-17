import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, act } from "@testing-library/react";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const notFoundMock = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});
vi.mock("next/navigation", () => ({ notFound: () => notFoundMock() }));

let mockFetchAPI: Mock;
vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

const mockDetail = {
  id: 531,
  date: "2026-04-13",
  ticker: "AAA",
  action: "BUY",
  confidence: 75,
  regime: "bull_low_vol",
  macro_score: 72,
  vix: 15,
  fear_greed: 65,
  agreement_rate: 0.8,
  // 생산자처럼 JSON 문자열로 저장
  agent_verdicts: JSON.stringify([
    { agent_name: "technical", action: "BUY", confidence: 80, reasoning: "MACD>Signal" },
  ]),
  entry_price: 120,
  stop_loss: 111.6,
  target_1: 144,
  target_2: 168,
  pnl_7d: 5.2,
  pnl_30d: -3.1,
  pnl_60d: null,
  pnl_90d: null,
  outcome: "pending",
  reasoning: "Consensus reached",
  evidence: [
    { id: 1, decision_id: 531, source_type: "agent", source_key: "technical", action: "BUY", confidence: 80, detail: '{"rsi": 49}' },
  ],
};

describe("DecisionProvenance", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockFetchAPI = vi.fn().mockResolvedValue(mockDetail);
    notFoundMock.mockClear();
  });

  it("renders frozen context + price ladder + outcome", async () => {
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    expect(screen.getByText("AAA")).toBeInTheDocument();
    expect(screen.getByText(/결정 시점 컨텍스트/)).toBeInTheDocument();
    expect(screen.getByText("Entry")).toBeInTheDocument();
    expect(screen.getByText("Stop")).toBeInTheDocument();
    expect(screen.getByText(/실현 결과/)).toBeInTheDocument();
    expect(screen.getByText("#531 · 2026-04-13")).toBeInTheDocument();
  });

  it("renders parsed agent verdicts and evidence chain", async () => {
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    expect(screen.getByText("technical")).toBeInTheDocument();
    expect(screen.getByText(/증거 체인/)).toBeInTheDocument();
    expect(screen.getByText("agent/technical")).toBeInTheDocument();
  });

  it("calls notFound when the decision fetch fails (404)", async () => {
    mockFetchAPI = vi.fn().mockRejectedValue(new Error("API /api/decisions/999: 404"));
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await expect(DecisionProvenance({ id: "999" })).rejects.toThrow();
    expect(notFoundMock).toHaveBeenCalled();
  });

  it("calls notFound when the API returns null", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue(null);
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await expect(DecisionProvenance({ id: "0" })).rejects.toThrow();
    expect(notFoundMock).toHaveBeenCalled();
  });

  it("handles minimal decision: null fields, empty evidence, array verdicts, zero pnl", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({
      id: 1, date: "2026-04-01", ticker: "BBB", action: "HOLD", confidence: 50,
      regime: null, macro_score: null, vix: null, fear_greed: null, agreement_rate: null,
      agent_verdicts: [], // 직접 배열 (parse 분기 우회)
      entry_price: null, stop_loss: null, target_1: null, target_2: null,
      pnl_7d: 0, pnl_30d: null, pnl_60d: null, pnl_90d: null,
      outcome: "", reasoning: null, evidence: [],
    });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "1" }));
    });
    expect(screen.getByText("BBB")).toBeInTheDocument();
    expect(screen.getByText("증거 없음")).toBeInTheDocument();
    // reasoning null → 근거 카드 없음, verdicts 빈 배열 → 에이전트 카드 없음
    expect(screen.queryByText(/에이전트 판정/)).not.toBeInTheDocument();
  });

  it("falls back to [] when evidence is null (page.tsx:96 ?? branch)", async () => {
    // 기존 테스트는 항상 evidence 배열을 줘서 `d.evidence ?? []` 의 left 분기만 탐.
    // evidence=null → right(`[]`) fallback 분기 커버 (codecov partial 해소).
    mockFetchAPI = vi.fn().mockResolvedValue({ ...mockDetail, evidence: null });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    expect(screen.getByText("증거 없음")).toBeInTheDocument();
  });

  it("falls back to empty verdicts on malformed JSON + renders evidence with null fields", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({
      ...mockDetail,
      agent_verdicts: "not-json{", // parse 실패 → []
      reasoning: null,
      evidence: [
        { id: 9, decision_id: 531, source_type: "data", source_key: "vix", action: null, confidence: null, detail: null },
      ],
    });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    expect(screen.getByText("data/vix")).toBeInTheDocument();
    expect(screen.queryByText(/에이전트 판정/)).not.toBeInTheDocument();
  });

  it("parseVerdicts handles null and non-array JSON gracefully", async () => {
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    for (const av of [null, "{}"]) {
      mockFetchAPI = vi.fn().mockResolvedValue({ ...mockDetail, agent_verdicts: av, evidence: [] });
      await act(async () => {
        render(await DecisionProvenance({ id: "531" }));
      });
    }
    expect(mockFetchAPI).toHaveBeenCalled();
  });

  it("filters malformed verdict entries and guards missing confidence/reasoning", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({
      ...mockDetail,
      agent_verdicts: JSON.stringify([
        null,
        {},
        { agent_name: "risk", action: "HOLD" }, // confidence/reasoning 누락
        { agent_name: "macro", action: "BUY", confidence: 70, reasoning: "neutral" },
      ]),
      evidence: [],
    });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    // null/{} 제거 → valid 2개만
    expect(screen.getByText("에이전트 판정 (2)")).toBeInTheDocument();
    expect(screen.getByText("risk")).toBeInTheDocument();
    expect(screen.getByText("macro")).toBeInTheDocument();
  });

  it("renders bull and bear cases side by side with sourced evidence", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({
      ...mockDetail,
      thesis: {
        id: 7,
        ticker: "AAA",
        version: 2,
        author: "user",
        stance: "bullish",
        bull_case: "가속기 수요가 공급을 앞선다",
        bear_case: "고객사 자체 칩 전환이 점유율을 깎는다",
        effective_date: "2026-04-01",
        status: "active",
        verdict: null,
        evidence: [
          {
            id: 11,
            side: "bull",
            claim: "데이터센터 매출 4분기 연속 증가",
            source_type: "filing",
            source_key: "10-Q",
            source_url: "https://example.invalid/q",
            as_of: "2026-03-31",
            quote: null,
          },
          {
            id: 12,
            side: "bear",
            claim: "상위 고객 2곳이 자체 칩을 발표",
            source_type: "analyst",
            source_key: null,
            source_url: null,
            as_of: null,
            quote: null,
          },
        ],
      },
    });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    expect(screen.getByText("상승 논리")).toBeInTheDocument();
    expect(screen.getByText("하락 논리")).toBeInTheDocument();
    expect(screen.getByText("가속기 수요가 공급을 앞선다")).toBeInTheDocument();
    expect(screen.getByText("고객사 자체 칩 전환이 점유율을 깎는다")).toBeInTheDocument();
    expect(screen.getByText("논지 근거 (2)")).toBeInTheDocument();
    // 출처 역추적 — url 이 있으면 링크, 없으면 평문
    expect(screen.getByRole("link", { name: /filing\/10-Q/ })).toHaveAttribute(
      "href",
      "https://example.invalid/q",
    );
    expect(screen.getByText("analyst")).toBeInTheDocument();
    expect(screen.getByText(/v2 · 2026-04-01 · user · active/)).toBeInTheDocument();
  });

  it("says the thesis is missing instead of hiding the card", async () => {
    // 논지가 비어 있다는 사실이 곧 판단 근거의 부재다 — 카드가 사라지면 그 부재가 안 보인다.
    mockFetchAPI = vi.fn().mockResolvedValue({ ...mockDetail, thesis: null });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    expect(screen.getByText("투자 논지")).toBeInTheDocument();
    expect(screen.getByText(/이 시점에 기록된 논지 없음/)).toBeInTheDocument();
  });

  it("default export awaits params; Loading skeleton shows while child suspends", async () => {
    mockFetchAPI = vi.fn(() => new Promise(() => {})); // never resolve → child suspends → fallback
    const mod = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await mod.default({ params: Promise.resolve({ id: "531" }) }));
    });
    expect(document.querySelector(".animate-pulse")).toBeTruthy();
  });
});
