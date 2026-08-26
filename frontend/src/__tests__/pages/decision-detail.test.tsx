import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, act, within } from "@testing-library/react";

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

  it("shows a settled verdict and sources that lack a key", async () => {
    // 앞 테스트의 반대편 조합 — verdict 존재, 링크에 source_key 없음, 평문에 source_key 있음.
    mockFetchAPI = vi.fn().mockResolvedValue({
      ...mockDetail,
      thesis: {
        id: 8,
        ticker: "AAA",
        version: 1,
        author: "user",
        stance: "bearish",
        bull_case: "재고 사이클 저점 통과",
        bear_case: "가격 경쟁이 마진을 깎는다",
        effective_date: "2026-04-01",
        status: "superseded",
        verdict: "held",
        evidence: [
          {
            id: 21,
            side: "bull",
            claim: "재고 회전일수 개선",
            source_type: "filing",
            source_key: null,
            source_url: "https://example.invalid/k",
            as_of: null,
            quote: null,
          },
          {
            id: 22,
            side: "bear",
            claim: "ASP 하락",
            source_type: "analyst",
            source_key: "note-4",
            source_url: null,
            as_of: "2026-03-20",
            quote: null,
          },
        ],
      },
    });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    expect(screen.getByText(/v1 · 2026-04-01 · user · superseded/)).toBeInTheDocument();
    expect(screen.getByText("지켜짐").className).toContain("emerald");
    expect(screen.getByRole("link", { name: /^filing$/ })).toHaveAttribute("href", "https://example.invalid/k");
    expect(screen.getByText(/analyst\/note-4/)).toBeInTheDocument();
  });

  // verdict 뱃지만 보는 최소 논지 — 근거·기준은 다른 테스트가 덮는다.
  const baseThesis = {
    id: 9,
    ticker: "AAA",
    version: 1,
    author: "user",
    stance: "bullish",
    bull_case: "수요 우위",
    bear_case: "점유율 하락",
    effective_date: "2026-04-01",
    status: "active",
    verdict: null as string | null,
    evidence: [],
    criteria: [],
  };

  it("never paints an unevaluable verdict as a survived thesis", async () => {
    // 논지 층에서도 같은 규율 — 측정 못 한 것을 초록으로 칠하면 채점이 자기 편이 된다.
    mockFetchAPI = vi.fn().mockResolvedValue({
      ...mockDetail,
      thesis: { ...baseThesis, verdict: "unevaluable" },
    });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    const badge = screen.getByText("측정 불가");
    expect(badge.className).toContain("text-muted-foreground");
    expect(badge.className).not.toContain("emerald");
  });

  it("shows a blank verdict as in-progress, not as a pass", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({
      ...mockDetail,
      thesis: { ...baseThesis, verdict: null },
    });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    const badge = screen.getByText("진행 중");
    expect(badge.className).toContain("text-muted-foreground");
    expect(badge.className).not.toContain("emerald");
  });

  it("renders falsification criteria and never paints unevaluable as passing", async () => {
    // `unevaluable` 이 초록(유지)으로 보이면 "측정 못 했다" 가 "지켜졌다" 로 읽힌다 —
    // 그게 이 기능이 막으려는 것 자체다 (#1092).
    mockFetchAPI = vi.fn().mockResolvedValue({
      ...mockDetail,
      thesis: {
        id: 9,
        ticker: "AAA",
        version: 1,
        author: "user",
        stance: "bullish",
        bull_case: "수요가 공급을 앞선다",
        bear_case: "자체 칩 전환이 점유율을 깎는다",
        effective_date: "2026-04-01",
        status: "active",
        verdict: null,
        evidence: [],
        criteria: [
          {
            id: 1,
            kind: "machine",
            statement: "50일선 아래로 이탈하면 추세 전제가 깨진다",
            metric: "close",
            op: "<",
            threshold: 90,
            deadline_date: null,
            last_result: "breached",
            last_checked: "2026-08-18",
          },
          {
            id: 2,
            kind: "machine",
            statement: "팩터 점수가 하위권으로 내려가면",
            metric: "composite_score",
            op: "<",
            threshold: 0.3,
            deadline_date: null,
            last_result: "unevaluable",
            last_checked: "2026-08-18",
          },
          {
            id: 3,
            kind: "human",
            statement: "경영진이 capex 가이던스를 하향하면",
            metric: null,
            op: null,
            threshold: null,
            deadline_date: null,
            last_result: null,
            last_checked: null,
          },
        ],
      },
    });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    expect(screen.getByText(/반증 기준 \(3\)/)).toBeInTheDocument();
    expect(screen.getByText("반증됨")).toBeInTheDocument();
    expect(screen.getByText("사람 판정")).toBeInTheDocument();
    expect(screen.getByText("close < 90 · 2026-08-18")).toBeInTheDocument();

    // 측정 불가는 회색이어야 한다 — 유지(emerald)와 같은 색이면 안 된다.
    const unevaluable = screen.getByText("측정 불가");
    expect(unevaluable.className).toContain("text-muted-foreground");
    expect(unevaluable.className).not.toContain("emerald");
    expect(screen.queryByText("유지")).not.toBeInTheDocument();
    // 미점검(한 번도 안 돈 기준)도 통과처럼 보이면 안 된다.
    expect(screen.getByText("미점검").className).toContain("text-muted-foreground");
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

// #1216 U3 잠금: 2컬럼 골격 · 증거 key-value · raw float 종결 · 판정 상태.
describe("DecisionProvenance — U3 Evidence Terminal (#1216)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockFetchAPI = vi.fn().mockResolvedValue(mockDetail);
    notFoundMock.mockClear();
  });

  it("renders the 2-column skeleton: rail beside a 2/3 main column", async () => {
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    let container!: HTMLElement;
    await act(async () => {
      ({ container } = render(await DecisionProvenance({ id: "531" })));
    });
    const rail = screen.getByTestId("decision-rail");
    // #1257: 모바일에서도 본문 우선 — 레일은 모든 브레이크포인트에서 order-2
    expect(rail.className).toContain("order-2");
    const grid = rail.parentElement!;
    expect(grid.className).toContain("lg:grid-cols-3");
    expect(grid.querySelector(".lg\\:col-span-2")).not.toBeNull();
    expect(container).toBeTruthy();
  });

  it("renders evidence detail as key-value pairs, not raw JSON", async () => {
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    const kv = screen.getByTestId("evidence-kv");
    expect(kv.textContent).toContain("rsi");
    expect(kv.textContent).toContain("49");
    // raw JSON 문자열이 그대로 보이면 실패 (#1216 raw JSON 폐지)
    expect(screen.queryByText('{"rsi": 49}')).not.toBeInTheDocument();
  });

  it("falls back to raw detail when it is not a JSON object", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({
      ...mockDetail,
      evidence: [{ id: 1, decision_id: 531, source_type: "macro", source_key: "note", action: null, confidence: null, detail: "plain text detail" }],
    });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    expect(screen.queryByTestId("evidence-kv")).not.toBeInTheDocument();
    expect(screen.getByText("plain text detail")).toBeInTheDocument();
  });

  it("terminates raw floats: fixed VIX, currency prices, signed pnl", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({
      ...mockDetail,
      ticker: "005930.KS",
      vix: 21.040000915527344,
      entry_price: 204000,
      pnl_7d: 5.2,
      pnl_30d: -3.1,
    });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    // codex R1 P3: 값이 레일의 올바른 카드 안에 있는지까지 잠근다 (충돌 방지 스코프)
    const rail = screen.getByTestId("decision-rail");
    expect(within(rail).getByText("VIX").parentElement?.textContent).toContain("21.0"); // not 21.040000915…
    expect(within(rail).getByText("Entry").parentElement?.textContent).toContain("₩204,000"); // .KS → ₩
    expect(within(rail).getByText("7d").parentElement?.textContent).toContain("+5.2%");
    expect(within(rail).getByText("30d").parentElement?.textContent).toContain("-3.1%");
  });

  it("dashes a null confidence in the frozen context", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({ ...mockDetail, confidence: null });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    const rail = screen.getByTestId("decision-rail");
    expect(within(rail).getByText("Confidence").parentElement?.textContent).toContain("—");
  });

  it("shows 판정 D-n in the header for a recent pending decision", async () => {
    const recent = new Date(Date.now() - 10 * 86_400_000).toISOString().slice(0, 10);
    mockFetchAPI = vi.fn().mockResolvedValue({ ...mockDetail, date: recent });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    expect(screen.getByTestId("decision-outcome").textContent).toMatch(/D-\d+/);
  });

  it("shows the outcome intent tag with adjudication status in the header", async () => {
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    const outcome = screen.getByTestId("decision-outcome");
    // 2026-04-13 + 90d < 오늘 → pending 은 판정일 도래·미판정으로 드러난다
    expect(outcome.textContent).toContain("대기");
    expect(outcome.textContent).toContain("판정일 도래 · 미판정");
  });
});

// ═══════════════════════════════════════════════════════
// #1257 — 판정 경로 히어로 + 액션별 템플릿 + 에이전트 2단
// ═══════════════════════════════════════════════════════

describe("DecisionProvenance — 판정 경로 (#1257)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    notFoundMock.mockClear();
  });

  const vetoDetail = {
    ...mockDetail,
    action: "SELL",
    confidence: 100,
    agreement_rate: 0.2,
    reasoning: "리스크 에이전트 거부권 발동: 손절선 돌파 (-11.0% < -7%)",
    agent_verdicts: JSON.stringify([
      { agent_name: "risk", action: "SELL", confidence: 100, reasoning: "손절선 돌파" },
      { agent_name: "technical", action: "SELL", confidence: 100, reasoning: "MACD<Signal" },
      { agent_name: "options", action: "BUY", confidence: 86, reasoning: "PCR 약한 공포" },
      { agent_name: "smart_money", action: "HOLD", confidence: 30, reasoning: "스마트머니 데이터 없음" },
    ]),
    scoring_detail: JSON.stringify({
      final_action_source: "risk_veto",
      degraded_agents: ["smart_money"],
      panel_coverage: 0.75,
      risk_veto_fired: true,
    }),
    thesis: null,
  };

  it("risk_veto: 대차대조 히어로 — 합의 참고 vs 판정을 확정한 규칙", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue(vetoDetail);
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    const hero = screen.getByTestId("verdict-hero");
    expect(hero.dataset.source).toBe("risk_veto");
    expect(within(hero).getByText(/손실 관리 규칙이 이 판정을 자동 확정/)).toBeInTheDocument();
    expect(within(hero).getByText(/최종 판정을 확정한 것/)).toBeInTheDocument();
    // veto 사유는 히어로가 전문 표시 — 별도 "근거" 카드는 중복이라 사라진다
    expect(within(hero).getByText(/거부권 발동: 손절선 돌파/)).toBeInTheDocument();
    expect(screen.queryByText("근거")).not.toBeInTheDocument();
  });

  it("과거 행 fallback: scoring_detail 없이 reasoning 프리픽스만으로 veto 히어로", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({ ...vetoDetail, scoring_detail: null });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    expect(screen.getByTestId("verdict-hero").dataset.source).toBe("risk_veto");
  });

  it("weighted_sum(기본): 단일 히어로 + 합의 분포", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue(mockDetail);
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    const hero = screen.getByTestId("verdict-hero");
    expect(hero.dataset.source).toBe("weighted_sum");
    expect(within(hero).getByText(/가중 합의가 이 판정을 만들었습니다/)).toBeInTheDocument();
    // weighted_sum 은 근거 카드 유지
    expect(screen.getByText("근거")).toBeInTheDocument();
  });

  it("divergence_penalty: 강등 사유가 히어로에 표시", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({
      ...mockDetail,
      reasoning: "의견 분산 페널티로 HOLD 강등",
      scoring_detail: JSON.stringify({ final_action_source: "divergence_penalty" }),
    });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    const hero = screen.getByTestId("verdict-hero");
    expect(hero.dataset.source).toBe("divergence_penalty");
    expect(within(hero).getByText(/판정을 보수적으로 강등했습니다/)).toBeInTheDocument();
    expect(within(hero).getByText(/의견 분산 페널티로 HOLD 강등/)).toBeInTheDocument();
  });

  it("SELL 은 매수 사다리를 렌더하지 않는다 — 결정 시점 가격 + Stop 만", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue(vetoDetail);
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    const card = screen.getByTestId("price-card");
    expect(within(card).queryByText("Target 1")).not.toBeInTheDocument();
    expect(within(card).queryByText("Entry")).not.toBeInTheDocument();
    expect(within(card).getByText("결정 시점 가격")).toBeInTheDocument();
    expect(within(card).getByText(/매수 사다리.*적용되지 않습니다/)).toBeInTheDocument();
  });

  it("에이전트 2단: degraded 는 접힘 + 유효 의견만 본문 + 커버리지 표기", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue(vetoDetail);
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    expect(screen.getByText(/에이전트 판정 — 유효 의견 3/)).toBeInTheDocument();
    expect(screen.getByText(/패널 커버리지 75%/)).toBeInTheDocument();
    const degraded = screen.getByTestId("degraded-agents");
    expect(within(degraded).getByText(/의견 미산출 1/)).toBeInTheDocument();
    expect(within(degraded).getAllByText(/smart_money/).length).toBeGreaterThan(0);
  });

  it("scoring_detail 없는 과거 행은 평면 리스트 유지 — degraded 를 지어내지 않는다", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({ ...vetoDetail, scoring_detail: null });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    expect(screen.getByText(/에이전트 판정 \(4\)/)).toBeInTheDocument();
    expect(screen.queryByTestId("degraded-agents")).not.toBeInTheDocument();
  });

  it("veto + 논지 없음 → 자동 논지 렌더 (채점 기준 공백 방지)", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue(vetoDetail);
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    const auto = screen.getByTestId("auto-thesis");
    expect(within(auto).getByText(/자동 논지/)).toBeInTheDocument();
    expect(within(auto).getByText(/판정일에 실현 결과로 채점/)).toBeInTheDocument();
  });

  it("비-veto + 논지 없음 → 기존 부재 문구 유지 (자동 논지 남발 금지)", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({ ...mockDetail, thesis: null });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    expect(screen.queryByTestId("auto-thesis")).not.toBeInTheDocument();
    expect(screen.getByText(/기록된 논지 없음/)).toBeInTheDocument();
  });

  it("판정 후 새 사실 + 재검토 체크가 항상 렌더 — 부재도 정직하게 표시", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue(mockDetail);
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    const facts = screen.getByTestId("post-decision-facts");
    expect(within(facts).getByText(/자동 반영은 아직 없습니다/)).toBeInTheDocument();
    const recheck = screen.getByTestId("recheck-list");
    expect(within(recheck).getByText(/매매 권고 아님/)).toBeInTheDocument();
    expect(within(recheck).getByText(/현재 규칙 기준 재구성/)).toBeInTheDocument();
  });
});

describe("verdict-path helpers (#1257)", () => {
  it("parseScoringDetail: 깨진 JSON·배열·null 은 null", async () => {
    const { parseScoringDetail } = await import("@/app/decisions/verdict-path");
    expect(parseScoringDetail("not-json{")).toBeNull();
    expect(parseScoringDetail(null)).toBeNull();
    expect(parseScoringDetail(JSON.stringify([1, 2]))).toBeNull();
    expect(parseScoringDetail({ final_action_source: "weighted_sum" })).toEqual({
      final_action_source: "weighted_sum",
    });
  });

  it("deriveActionSource: 미지의 소스는 unknown — 가중 합의로 둔갑 금지 (codex P2)", async () => {
    const { deriveActionSource } = await import("@/app/decisions/verdict-path");
    expect(deriveActionSource({ final_action_source: "future_mechanism" }, "일반 합의")).toBe("unknown");
    expect(deriveActionSource(null, "리스크 에이전트 거부권 발동: x")).toBe("risk_veto");
    expect(deriveActionSource(null, null)).toBe("weighted_sum");
  });

  it("verdictSplit + 히어로 분포는 live 패널 기준 (codex P1)", async () => {
    const { verdictSplit } = await import("@/app/decisions/verdict-path");
    expect(verdictSplit([{ action: "SELL" }, { action: "BUY" }, { action: "HOLD" }])).toEqual({
      buy: 1,
      sell: 1,
      rest: 1,
    });
  });
});

describe("DecisionProvenance — codex ship-review 수정 잠금 (#1257)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    notFoundMock.mockClear();
  });

  it("P1: 히어로 분포가 degraded 를 세지 않는다 — live 패널 기준", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({
      ...mockDetail,
      action: "SELL",
      reasoning: "리스크 에이전트 거부권 발동: 손절선 돌파",
      agent_verdicts: JSON.stringify([
        { agent_name: "risk", action: "SELL", confidence: 100, reasoning: "손절선 돌파" },
        { agent_name: "options", action: "BUY", confidence: 86, reasoning: "PCR" },
        { agent_name: "smart_money", action: "HOLD", confidence: 30, reasoning: "데이터 없음" },
        { agent_name: "crypto", action: "HOLD", confidence: 0, reasoning: "무관" },
      ]),
      scoring_detail: JSON.stringify({
        final_action_source: "risk_veto",
        degraded_agents: ["smart_money", "crypto"],
        panel_coverage: 0.5,
      }),
      thesis: null,
    });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    const hero = screen.getByTestId("verdict-hero");
    // degraded 2명(HOLD 자리표시자)이 빠져야 함: live = SELL 1 · BUY 1 · 중립 0
    expect(within(hero).getByText(/SELL 1 · BUY 1 · 중립 0/)).toBeInTheDocument();
  });

  it("P2: 백엔드가 모르는 판정 소스 → unknown 히어로 (가중 합의로 오표기 금지)", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({
      ...mockDetail,
      scoring_detail: JSON.stringify({ final_action_source: "quantum_override" }),
    });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    const hero = screen.getByTestId("verdict-hero");
    expect(hero.dataset.source).toBe("unknown");
    expect(within(hero).getByText(/판정 경로를 해석할 수 없습니다/)).toBeInTheDocument();
    expect(within(hero).getByText(/quantum_override/)).toBeInTheDocument();
  });
});

describe("DecisionProvenance — null-필드 분기 커버 (#1257 codecov patch)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    notFoundMock.mockClear();
  });

  it("veto 히어로: confidence·agreement·reasoning null + 빈 verdicts 도 안전 렌더", async () => {
    mockFetchAPI = vi.fn().mockResolvedValue({
      ...mockDetail,
      action: "SELL",
      confidence: null,
      agreement_rate: null,
      reasoning: null,
      agent_verdicts: JSON.stringify([]),
      scoring_detail: JSON.stringify({ final_action_source: "risk_veto" }),
      thesis: null,
    });
    const { DecisionProvenance } = await import("@/app/decisions/[id]/page");
    await act(async () => {
      render(await DecisionProvenance({ id: "531" }));
    });
    const hero = screen.getByTestId("verdict-hero");
    expect(hero.dataset.source).toBe("risk_veto");
    // confidence null → "—", 분포 바는 0명이라 비어 있고, 일치율 표기는 생략
    expect(within(hero).getByText(/SELL · —/)).toBeInTheDocument();
    expect(within(hero).queryByText(/일치율 \d/)).not.toBeInTheDocument();
  });
});
