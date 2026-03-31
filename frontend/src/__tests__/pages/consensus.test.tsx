import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockConsensus = {
  regime: { vix: 18.5, regime: "bull_low_vol" },
  results: [
    {
      ticker: "NVDA",
      final_action: "BUY",
      final_confidence: 72.5,
      agreement_rate: 0.8,
      verdicts: [
        { agent_name: "technical", ticker: "NVDA", action: "BUY", confidence: 80, reasoning: "RSI oversold bounce", data_points: {} },
        { agent_name: "fundamental", ticker: "NVDA", action: "BUY", confidence: 75, reasoning: "Strong earnings growth", data_points: {} },
        { agent_name: "risk", ticker: "NVDA", action: "HOLD", confidence: 60, reasoning: "Concentration risk moderate", data_points: {} },
      ],
      dissent: ["risk: Concentration risk moderate"],
      reasoning: "Strong technical and fundamental signals",
    },
    {
      ticker: "TSLA",
      final_action: "SELL",
      final_confidence: 65.0,
      agreement_rate: 0.6,
      verdicts: [
        { agent_name: "technical", ticker: "TSLA", action: "SELL", confidence: 70, reasoning: "Death cross formed", data_points: {} },
        { agent_name: "fundamental", ticker: "TSLA", action: "HOLD", confidence: 50, reasoning: "PE too high", data_points: {} },
      ],
      dissent: ["fundamental: PE too high but growth potential", "macro: Policy tailwinds"],
      reasoning: "Technical weakness outweighs",
    },
    {
      ticker: "AAPL",
      final_action: "HOLD",
      final_confidence: 55.0,
      agreement_rate: 0.9,
      verdicts: [],
      dissent: [],
      reasoning: "Neutral outlook",
    },
  ],
  count: 3,
};

let mockFetchAPI: ReturnType<typeof vi.fn>;

vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: any[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

function setupFetchAPI(overrides: { consensus?: any } = {}) {
  mockFetchAPI = vi.fn().mockImplementation((_path: string) => {
    return Promise.resolve(overrides.consensus ?? mockConsensus);
  });
}

describe("ConsensusPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setupFetchAPI();
  });

  it("renders the page heading", async () => {
    const { default: ConsensusPage } = await import("@/app/consensus/page");
    await act(async () => {
      render(<ConsensusPage />);
    });

    expect(screen.getByText("Agents")).toBeInTheDocument();
  });

  it("renders consensus verdict count summary", async () => {
    const { default: ConsensusPage } = await import("@/app/consensus/page");
    await act(async () => {
      render(<ConsensusPage />);
    });

    // "3 tickers x 10 agents = 30 verdicts"
    expect(screen.getByText(/3 tickers × 10 agents = 30 verdicts/)).toBeInTheDocument();
  });

  it("renders ticker names in consensus table", async () => {
    const { default: ConsensusPage } = await import("@/app/consensus/page");
    await act(async () => {
      render(<ConsensusPage />);
    });

    // NVDA appears in both consensus table and dissent section
    expect(screen.getAllByText("NVDA").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("TSLA").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("renders action badges (BUY, SELL, HOLD)", async () => {
    const { default: ConsensusPage } = await import("@/app/consensus/page");
    await act(async () => {
      render(<ConsensusPage />);
    });

    // StatusBadge renders the action text
    expect(screen.getAllByText("BUY").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("SELL").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("HOLD").length).toBeGreaterThanOrEqual(1);
  });

  it("renders confidence values", async () => {
    const { default: ConsensusPage } = await import("@/app/consensus/page");
    await act(async () => {
      render(<ConsensusPage />);
    });

    expect(screen.getByText("72.5")).toBeInTheDocument();
    expect(screen.getByText("65.0")).toBeInTheDocument();
  });

  it("renders dissent section for tickers with disagreements", async () => {
    const { default: ConsensusPage } = await import("@/app/consensus/page");
    await act(async () => {
      render(<ConsensusPage />);
    });

    expect(screen.getByText("Dissent — Agent Disagreements")).toBeInTheDocument();
    // NVDA has 80% agreement
    expect(screen.getByText("80% agree")).toBeInTheDocument();
    // TSLA has 60% agreement
    expect(screen.getByText("60% agree")).toBeInTheDocument();
  });

  it("does not show VIX banner when VIX is low", async () => {
    const { default: ConsensusPage } = await import("@/app/consensus/page");
    await act(async () => {
      render(<ConsensusPage />);
    });

    // VIX 18.5 < 25, no banner
    expect(screen.queryByText(/VIX/)).not.toBeInTheDocument();
  });

  it("shows VIX warning banner when VIX 25-30", async () => {
    setupFetchAPI({
      consensus: { ...mockConsensus, regime: { vix: 27.5, regime: "bear_high_vol" } },
    });

    const { default: ConsensusPage } = await import("@/app/consensus/page");
    await act(async () => {
      render(<ConsensusPage />);
    });

    expect(screen.getByText(/VIX 27.5 \(25-30\)/)).toBeInTheDocument();
    expect(screen.getByText(/반포지션 적용 중/)).toBeInTheDocument();
  });

  it("shows VIX blocked banner when VIX >= 30", async () => {
    setupFetchAPI({
      consensus: { ...mockConsensus, regime: { vix: 35.2, regime: "bear_high_vol" } },
    });

    const { default: ConsensusPage } = await import("@/app/consensus/page");
    await act(async () => {
      render(<ConsensusPage />);
    });

    expect(screen.getByText(/VIX 35.2 > 30/)).toBeInTheDocument();
    expect(screen.getByText(/신규 매수 차단/)).toBeInTheDocument();
  });
});
