import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { TraceState } from "@/lib/use-trace-stream";

// Mock useTraceStream
const mockStart = vi.fn();
const mockStop = vi.fn();
let mockState: TraceState = {
  verdicts: [],
  consensus: null,
  isStreaming: false,
  error: null,
};

vi.mock("@/lib/use-trace-stream", () => ({
  useTraceStream: () => ({ ...mockState, start: mockStart, stop: mockStop }),
}));

import { AgentTrace } from "@/components/ui/agent-trace";
import { CONSENSUS } from "@/lib/strings";

const mockVerdict = (name: string, action = "BUY", confidence = 75) => ({
  agent_name: name,
  ticker: "AAPL",
  action,
  confidence,
  reasoning: `${name} reasoning text`,
  data_points: { rsi: 28, sma50: 150.3 },
});

describe("AgentTrace", () => {
  beforeEach(() => {
    mockStart.mockClear();
    mockStop.mockClear();
    mockState = { verdicts: [], consensus: null, isStreaming: false, error: null };
  });

  it("renders Trace button with default state", () => {
    render(<AgentTrace ticker="AAPL" />);
    expect(screen.getByText("Trace")).toBeInTheDocument();
  });

  it("calls start(ticker) when Trace button clicked", () => {
    render(<AgentTrace ticker="AAPL" />);
    fireEvent.click(screen.getByText("Trace"));
    expect(mockStart).toHaveBeenCalledWith("AAPL");
  });

  it("shows progress indicator when streaming", () => {
    mockState = { verdicts: [mockVerdict("technical")], consensus: null, isStreaming: true, error: null };
    render(<AgentTrace ticker="AAPL" />);
    expect(screen.getByText("분석 중... (1/10)")).toBeInTheDocument();
  });

  it("shows 중지 button when streaming", () => {
    mockState = { verdicts: [], consensus: null, isStreaming: true, error: null };
    render(<AgentTrace ticker="AAPL" />);
    expect(screen.getByText("중지")).toBeInTheDocument();
  });

  it("calls stop() when 중지 clicked", () => {
    mockState = { verdicts: [], consensus: null, isStreaming: true, error: null };
    render(<AgentTrace ticker="AAPL" />);
    fireEvent.click(screen.getByText("중지"));
    expect(mockStop).toHaveBeenCalled();
  });

  it("renders agent card with verdict data", () => {
    mockState = { verdicts: [mockVerdict("technical")], consensus: null, isStreaming: false, error: null };
    render(<AgentTrace ticker="AAPL" />);
    expect(screen.getByText("Tech")).toBeInTheDocument();
    expect(screen.getByText("technical reasoning text")).toBeInTheDocument();
    expect(screen.getByText("75%")).toBeInTheDocument();
  });

  it("renders data_points as pills", () => {
    mockState = { verdicts: [mockVerdict("technical")], consensus: null, isStreaming: false, error: null };
    render(<AgentTrace ticker="AAPL" />);
    expect(screen.getByText("rsi=28.00")).toBeInTheDocument();
    expect(screen.getByText("sma50=150.30")).toBeInTheDocument();
  });

  it("shows skeleton for agents without verdicts", () => {
    mockState = { verdicts: [mockVerdict("technical")], consensus: null, isStreaming: true, error: null };
    render(<AgentTrace ticker="AAPL" />);
    // 9 agents still waiting — shown as "--" placeholder
    const placeholders = screen.getAllByText("--");
    expect(placeholders.length).toBe(9);
  });

  it("renders consensus result when complete", () => {
    mockState = {
      verdicts: [mockVerdict("technical")],
      consensus: {
        ticker: "AAPL",
        final_action: "BUY",
        final_confidence: 72.5,
        agreement_rate: 0.8,
        verdicts: [],
        dissent: [],
        reasoning: "Strong buy consensus",
      },
      isStreaming: false,
      error: null,
    };
    render(<AgentTrace ticker="AAPL" />);
    expect(screen.getByText("합의:")).toBeInTheDocument();
    expect(screen.getByText("72.5%")).toBeInTheDocument();
    expect(screen.getByText("(80% 동의)")).toBeInTheDocument();
    expect(screen.getByText("Strong buy consensus")).toBeInTheDocument();
  });

  it("shows error message", () => {
    mockState = { verdicts: [], consensus: null, isStreaming: false, error: "스트림 연결 실패" };
    render(<AgentTrace ticker="AAPL" />);
    expect(screen.getByText("스트림 연결 실패")).toBeInTheDocument();
  });

  it("shows 다시 분석 button after completion", () => {
    mockState = { verdicts: [mockVerdict("technical")], consensus: null, isStreaming: false, error: null };
    render(<AgentTrace ticker="AAPL" />);
    expect(screen.getByText("다시 분석")).toBeInTheDocument();
  });
});

describe("AgentTrace — 자리표시자는 의견이 아니다 (#1436)", () => {
  beforeEach(() => {
    mockStart.mockClear();
    mockStop.mockClear();
    mockState = { verdicts: [], consensus: null, isStreaming: false, error: null };
  });

  it("기권·미산출 카드는 배지·확신도 대신 라벨을 보여준다", () => {
    // 조건식의 **양쪽**을 다 밟는다 — 한쪽만 넣으면 반대 분기가 미커버로 남는다.
    mockState = {
      verdicts: [
        { ...mockVerdict("technical", "BUY", 75) },
        { ...mockVerdict("korean_market", "HOLD", 50), abstained: true },
        { ...mockVerdict("crypto", "HOLD", 0), degraded: true },
      ],
      consensus: null,
      isStreaming: false,
      error: null,
    };
    render(<AgentTrace ticker="AAPL" />);

    expect(screen.getByText(CONSENSUS.PLACEHOLDER_ABSTAINED)).toBeInTheDocument();
    expect(screen.getByText(CONSENSUS.PLACEHOLDER_DEGRADED)).toBeInTheDocument();
    // 자리표시자에 확신도 %를 찍으면 같은 화면의 커버리지 수치와 모순된다
    expect(screen.queryByText("50%")).not.toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    // 카나리아 — 진짜 의견은 그대로 확신도를 보여준다
    expect(screen.getByText("75%")).toBeInTheDocument();
  });
});
