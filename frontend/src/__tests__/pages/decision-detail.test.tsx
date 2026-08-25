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
    expect(rail.className).toContain("lg:order-2");
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
