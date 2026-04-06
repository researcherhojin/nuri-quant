import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConsensusTable } from "@/components/ui/consensus-table";

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
});
