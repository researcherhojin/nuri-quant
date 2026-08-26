import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConsensusTable, type ScoringDetail } from "@/components/ui/consensus-table";

const mockData = [
  {
    ticker: "TSLA",
    final_action: "BUY",
    final_confidence: 72.5,
    agreement_rate: 0.8,
    verdicts: [
      { agent_name: "technical", ticker: "TSLA", action: "BUY", confidence: 75, reasoning: "RSI oversold bounce", data_points: {} },
      { agent_name: "fundamental", ticker: "TSLA", action: "HOLD", confidence: 50, reasoning: "PE ratio elevated", data_points: {} },
      { agent_name: "risk", ticker: "TSLA", action: "BUY", confidence: 60, reasoning: "Volatility decreasing", data_points: {} },
      { agent_name: "macro", ticker: "TSLA", action: "BUY", confidence: 70, reasoning: "Bull regime favorable", data_points: {} },
    ],
    dissent: ["fundamental"],
    reasoning: "Majority BUY consensus",
  },
  {
    ticker: "NVDA",
    final_action: "SELL",
    final_confidence: 65.0,
    agreement_rate: 0.4,
    verdicts: [
      { agent_name: "technical", ticker: "NVDA", action: "SELL", confidence: 80, reasoning: "MACD dead cross", data_points: {} },
      { agent_name: "fundamental", ticker: "NVDA", action: "BUY", confidence: 70, reasoning: "Strong earnings growth", data_points: {} },
    ],
    dissent: ["fundamental"],
    reasoning: "Technical weakness overrides",
  },
  {
    ticker: "AAPL",
    final_action: "HOLD",
    final_confidence: 55.0,
    agreement_rate: 0.6,
    verdicts: [],
    dissent: [],
    reasoning: "No strong signal either way",
  },
];

describe("ConsensusTable", () => {
  it("renders all ticker rows", () => {
    render(<ConsensusTable data={mockData} />);
    expect(screen.getByText("TSLA")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("renders column headers", () => {
    render(<ConsensusTable data={mockData} />);
    expect(screen.getByText("Ticker")).toBeInTheDocument();
    expect(screen.getByText("Action")).toBeInTheDocument();
    expect(screen.getByText("Conf")).toBeInTheDocument();
  });

  it("renders confidence values", () => {
    render(<ConsensusTable data={mockData} />);
    expect(screen.getByText("72.5")).toBeInTheDocument();
    expect(screen.getByText("65.0")).toBeInTheDocument();
    expect(screen.getByText("55.0")).toBeInTheDocument();
  });

  it("renders action badges via StatusBadge", () => {
    render(<ConsensusTable data={mockData} />);
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("SELL")).toBeInTheDocument();
    expect(screen.getByText("HOLD")).toBeInTheDocument();
  });

  it("renders agreement percentages", () => {
    render(<ConsensusTable data={mockData} />);
    // 0.8 -> "80%", 0.4 -> "40%", 0.6 -> "60%"
    expect(screen.getByText("80%")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
  });

  it("renders agent cell abbreviations in header", () => {
    render(<ConsensusTable data={mockData} />);
    // Agent short labels from AGENT_ORDER
    expect(screen.getByText("Tech")).toBeInTheDocument();
    expect(screen.getByText("Fund")).toBeInTheDocument();
    expect(screen.getByText("Macro")).toBeInTheDocument();
    expect(screen.getByText("Risk")).toBeInTheDocument();
    expect(screen.getByText("Smart")).toBeInTheDocument();
    expect(screen.getByText("Wall")).toBeInTheDocument();
    expect(screen.getByText("KR")).toBeInTheDocument();
    expect(screen.getByText("Opt")).toBeInTheDocument();
    expect(screen.getByText("Cry")).toBeInTheDocument();
    expect(screen.getByText("Ret")).toBeInTheDocument();
  });

  it("expands agent details on row click", () => {
    render(<ConsensusTable data={mockData} />);

    // Click TSLA row
    fireEvent.click(screen.getByText("TSLA"));

    // Agent reasoning should be visible
    expect(screen.getByText("RSI oversold bounce")).toBeInTheDocument();
    expect(screen.getByText("PE ratio elevated")).toBeInTheDocument();
    expect(screen.getByText("Volatility decreasing")).toBeInTheDocument();
    expect(screen.getByText("Bull regime favorable")).toBeInTheDocument();
  });

  it("collapses details on second click", () => {
    render(<ConsensusTable data={mockData} />);

    // Click to expand
    fireEvent.click(screen.getByText("TSLA"));
    expect(screen.getByText("RSI oversold bounce")).toBeInTheDocument();

    // Click again to collapse
    fireEvent.click(screen.getByText("TSLA"));
    expect(screen.queryByText("RSI oversold bounce")).not.toBeInTheDocument();
  });

  it("only one row expanded at a time", () => {
    render(<ConsensusTable data={mockData} />);

    // Expand TSLA
    fireEvent.click(screen.getByText("TSLA"));
    expect(screen.getByText("RSI oversold bounce")).toBeInTheDocument();

    // Expand NVDA (should collapse TSLA)
    fireEvent.click(screen.getByText("NVDA"));
    expect(screen.queryByText("RSI oversold bounce")).not.toBeInTheDocument();
    expect(screen.getByText("MACD dead cross")).toBeInTheDocument();
  });

  it("renders empty table without crashing", () => {
    const { container } = render(<ConsensusTable data={[]} />);
    const tbody = container.querySelector("tbody");
    expect(tbody).not.toBeNull();
    expect(tbody!.children).toHaveLength(0);
  });

  it("renders agent cell with B/S/H prefix and confidence", () => {
    render(<ConsensusTable data={mockData} />);
    // Technical agent for TSLA: BUY confidence 75 → "B75"
    expect(screen.getByText("B75")).toBeInTheDocument();
    // Risk agent for TSLA: BUY confidence 60 → "B60"
    expect(screen.getByText("B60")).toBeInTheDocument();
  });

  it("applies green color for BUY agents", () => {
    render(<ConsensusTable data={mockData} />);
    const buyCell = screen.getByText("B75");
    expect(buyCell.className).toContain("text-emerald-400");
  });

  it("applies red color for SELL agents", () => {
    render(<ConsensusTable data={mockData} />);
    // NVDA technical agent: SELL 80 → "S80"
    const sellCell = screen.getByText("S80");
    expect(sellCell.className).toContain("text-red-400");
  });

  it("shows -- for missing agent verdicts", () => {
    render(<ConsensusTable data={mockData} />);
    // AAPL has no verdicts, so all agent columns should show --
    const dashes = screen.getAllByText("--");
    expect(dashes.length).toBeGreaterThan(0);
  });

  // ─── VIX 반포지션 label ────────────────────────────────
  it("shows (반포지션) label next to BUY when VIX is 25-30", () => {
    render(<ConsensusTable data={mockData} vix={27.5} />);
    expect(screen.getByText("(반포지션)")).toBeInTheDocument();
  });

  it("does not show (반포지션) when VIX is below 25", () => {
    render(<ConsensusTable data={mockData} vix={18.5} />);
    expect(screen.queryByText("(반포지션)")).not.toBeInTheDocument();
  });

  it("does not show (반포지션) when VIX is 30 or above", () => {
    render(<ConsensusTable data={mockData} vix={32.0} />);
    expect(screen.queryByText("(반포지션)")).not.toBeInTheDocument();
  });

  it("does not show (반포지션) for SELL or HOLD actions when VIX is 25-30", () => {
    const sellOnly = [{ ...mockData[1], final_action: "SELL" }];
    render(<ConsensusTable data={sellOnly} vix={27.5} />);
    expect(screen.queryByText("(반포지션)")).not.toBeInTheDocument();
  });

  it("does not show (반포지션) when vix is null", () => {
    render(<ConsensusTable data={mockData} vix={null} />);
    expect(screen.queryByText("(반포지션)")).not.toBeInTheDocument();
  });

  // ─── Divergence flag badge (P1 A2, docs/HARNESS.md §2 JKHY) ──
  it("renders divergence badge when divergence_flag is true", () => {
    const withDivergence = [{
      ...mockData[0],
      divergence_flag: true,
      divergence_reason: "기술지표 반대: TechnicalAgent 가 SELL",
    }];
    render(<ConsensusTable data={withDivergence} vix={null} />);
    const badge = screen.getByTestId("divergence-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("title", "기술지표 반대: TechnicalAgent 가 SELL");
  });

  it("does not render divergence badge when divergence_flag is false/undefined", () => {
    render(<ConsensusTable data={mockData} vix={null} />);
    expect(screen.queryByTestId("divergence-badge")).not.toBeInTheDocument();
  });

  it("falls back to default tooltip text when divergence_reason is empty string", () => {
    // Exercise the `row.divergence_reason || "기술지표 반대"` fallback branch.
    const withEmptyReason = [{
      ...mockData[0],
      divergence_flag: true,
      divergence_reason: "",
    }];
    render(<ConsensusTable data={withEmptyReason} vix={null} />);
    const badge = screen.getByTestId("divergence-badge");
    expect(badge).toHaveAttribute("title", "기술지표 반대");
  });

  // A-2c — scoring_detail (PR #368 API expose) 기반 UI 회귀 잠금.
  // Gotcha-Test Pair (STRATEGY §5.3.1): action-source 배지 / basis 라벨 / 기여도 강조를
  // 실수로 제거하면 아래 테스트가 fail.
  describe("scoring_detail surfacing (A-2c)", () => {
    // ScoringDetail 을 명시 반환 타입으로 — overrides 가 widen 해도 contract 유지.
    const makeScoring = (overrides: Partial<ScoringDetail> = {}): ScoringDetail => ({
      source: "consensus",
      schema_version: 1,
      weights: { technical: 0.4, fundamental: 0.3, risk: 0.2, macro: 0.1 },
      action_scores: { BUY: 0.55, SELL: 0.0, HOLD: 0.15 },
      contributions: [
        { agent_name: "technical", action: "BUY", confidence: 75, weight: 0.4, weighted: 0.3, counted_for_basis_action: true },
        { agent_name: "fundamental", action: "HOLD", confidence: 50, weight: 0.3, weighted: 0.15, counted_for_basis_action: false },
        { agent_name: "risk", action: "BUY", confidence: 60, weight: 0.2, weighted: 0.12, counted_for_basis_action: true },
        { agent_name: "macro", action: "BUY", confidence: 70, weight: 0.1, weighted: 0.07, counted_for_basis_action: true },
      ],
      final_action: "BUY",
      final_confidence: 72.5,
      final_action_source: "weighted_sum",
      basis_action: "BUY",
      agreement_rate: 0.75,
      risk_veto_fired: false,
      divergence_flag: false,
      penalty_applied: false,
      pre_penalty_action: "",
      ...overrides,
    });

    it("does not render action-source badge when weighted_sum", () => {
      const d = [{ ...mockData[0], scoring_detail: makeScoring() }];
      render(<ConsensusTable data={d} />);
      expect(screen.queryByTestId("action-source-badge")).not.toBeInTheDocument();
    });

    it("renders risk_veto action-source badge with tooltip", () => {
      const d = [{
        ...mockData[0],
        scoring_detail: makeScoring({ final_action_source: "risk_veto", risk_veto_fired: true }),
      }];
      render(<ConsensusTable data={d} />);
      const badge = screen.getByTestId("action-source-badge");
      // F-003: 이모지 → lucide svg. 의미 잠금은 title 로
      expect(badge.querySelector("svg")).not.toBeNull();
      expect(badge.getAttribute("title")).toContain("거부권");
    });

    it("renders divergence_penalty badge + basis label when penalty_applied", () => {
      const d = [{
        ...mockData[0],
        final_action: "HOLD",
        scoring_detail: makeScoring({
          final_action: "HOLD",
          final_action_source: "divergence_penalty",
          basis_action: "BUY",
          penalty_applied: true,
          pre_penalty_action: "BUY",
        }),
      }];
      render(<ConsensusTable data={d} />);
      // F-003: divergence 아이콘도 svg — 배지 존재 + basis label 로 의미 검증
      expect(screen.getByTestId("action-source-badge").querySelector("svg")).not.toBeNull();
      const basis = screen.getByTestId("penalty-basis-label");
      // "BUY → HOLD" downgrade 표시 — 사용자가 원 방향 추정 가능
      expect(basis.textContent).toContain("BUY");
      expect(basis.textContent).toContain("HOLD");
    });

    it("renders weighted contribution % for agents that voted for basis_action", () => {
      const d = [{ ...mockData[0], scoring_detail: makeScoring() }];
      render(<ConsensusTable data={d} />);
      fireEvent.click(screen.getByText("TSLA"));
      // technical counted_for_basis_action=true, weighted 0.3 / action_scores.BUY=0.55 ≈ 55%
      // (basis_action 분모 기반 — codex Round 1 LOW 1 fix)
      const pct = screen.getByTestId("contrib-pct-technical");
      const num = parseInt(pct.textContent!.replace("%", ""), 10);
      expect(num).toBeGreaterThan(40);
      expect(num).toBeLessThan(60);
    });

    it("omits contribution % for agents whose action differs from basis_action", () => {
      // fundamental = HOLD (counted_for_basis_action=false when basis=BUY) → % 가 의미 없어 미렌더
      const d = [{ ...mockData[0], scoring_detail: makeScoring() }];
      render(<ConsensusTable data={d} />);
      fireEvent.click(screen.getByText("TSLA"));
      expect(screen.queryByTestId("contrib-pct-fundamental")).not.toBeInTheDocument();
    });

    it("highlights counted_for_basis_action agents with emerald ring", () => {
      const d = [{ ...mockData[0], scoring_detail: makeScoring() }];
      render(<ConsensusTable data={d} />);
      fireEvent.click(screen.getByText("TSLA"));
      const tech = screen.getByTestId("agent-card-technical");
      expect(tech.className).toContain("emerald");
      const fund = screen.getByTestId("agent-card-fundamental");
      expect(fund.className).not.toContain("emerald-500");
    });

    it("falls back gracefully when scoring_detail is null (backward compat)", () => {
      const d = [{ ...mockData[0], scoring_detail: null }];
      render(<ConsensusTable data={d} />);
      // Expanded row 는 여전히 reasoning 표시 (기존 경로)
      fireEvent.click(screen.getByText("TSLA"));
      expect(screen.getByText("RSI oversold bounce")).toBeInTheDocument();
      // contribution % cell 은 없음
      expect(screen.queryByTestId("contrib-pct-technical")).not.toBeInTheDocument();
      // action-source 배지도 없음
      expect(screen.queryByTestId("action-source-badge")).not.toBeInTheDocument();
    });
  });
});
