import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { AgentTrace } from "./agent-trace";

// useTraceStream 훅을 모킹해 네트워크(SSE) 없이 컴포넌트 분기를 직접 구동한다.
const mockStart = vi.fn();
const mockStop = vi.fn();
const traceState = {
  verdicts: [] as Array<Record<string, unknown>>,
  consensus: null as Record<string, unknown> | null,
  isStreaming: false,
  error: null as string | null,
  start: mockStart,
  stop: mockStop,
};

vi.mock("@/lib/use-trace-stream", () => ({
  useTraceStream: () => traceState,
}));

function resetState() {
  traceState.verdicts = [];
  traceState.consensus = null;
  traceState.isStreaming = false;
  traceState.error = null;
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  resetState();
});

describe("AgentTrace", () => {
  it("초기 상태(미시작): Trace 버튼만 보이고 카드 그리드/합의는 없다", () => {
    render(<AgentTrace ticker="AAPL" />);
    expect(screen.getByRole("button", { name: "Trace" })).toBeInTheDocument();
    // 미시작이면 에이전트 카드 라벨이 렌더되지 않는다
    expect(screen.queryByText("Tech")).not.toBeInTheDocument();
  });

  it("Trace 버튼 클릭 시 ticker로 start()가 호출된다", () => {
    render(<AgentTrace ticker="MSFT" />);
    fireEvent.click(screen.getByRole("button", { name: "Trace" }));
    expect(mockStart).toHaveBeenCalledWith("MSFT");
  });

  it("스트리밍 중: 중지 버튼 클릭 시 stop()이 호출되고 진행 표시가 보인다", () => {
    traceState.isStreaming = true;
    traceState.verdicts = [
      {
        agent_name: "technical",
        action: "BUY",
        confidence: 72.4,
        reasoning: "추세 상방",
        data_points: { rsi: 61.234 },
      },
    ];
    render(<AgentTrace ticker="AAPL" />);
    expect(screen.getByText(/분석 중/)).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: "중지" });
    fireEvent.click(btn);
    expect(mockStop).toHaveBeenCalledTimes(1);
  });

  it("error 존재 시 에러 메시지를 표시한다", () => {
    traceState.error = "스트림 연결 실패";
    render(<AgentTrace ticker="AAPL" />);
    expect(screen.getByText("스트림 연결 실패")).toBeInTheDocument();
  });

  it("verdict 도착 후: '다시 분석' 버튼으로 바뀌고 카드 그리드가 렌더된다", () => {
    traceState.isStreaming = false;
    traceState.verdicts = [
      {
        agent_name: "technical",
        action: "BUY",
        confidence: 80,
        reasoning: "이동평균 정배열",
        // number/string/null 혼합 → line 32 분기(number.toFixed, String, null) 모두 커버
        data_points: { rsi: 58.5, trend: "up", note: null },
      },
    ];
    render(<AgentTrace ticker="AAPL" />);
    expect(screen.getByRole("button", { name: "다시 분석" })).toBeInTheDocument();
    expect(screen.getByText("Tech")).toBeInTheDocument();
    // DataPills: number는 소수 2자리 포맷
    expect(screen.getByText("rsi=58.50")).toBeInTheDocument();
    // string 값 그대로
    expect(screen.getByText("trend=up")).toBeInTheDocument();
    // null 값은 빈 문자열로 (v ?? "")
    expect(screen.getByText("note=")).toBeInTheDocument();
    // verdict 없는 에이전트는 placeholder '--'
    expect(screen.getAllByText("--").length).toBeGreaterThan(0);
  });

  it("data_points가 빈 객체이면 DataPills가 null을 반환한다 (line 27)", () => {
    traceState.verdicts = [
      {
        agent_name: "macro",
        action: "HOLD",
        confidence: 50,
        reasoning: "중립",
        data_points: {}, // 빈 객체 → entries.length === 0 → return null
      },
    ];
    render(<AgentTrace ticker="AAPL" />);
    // reasoning은 보이지만 어떤 pill(=...)도 렌더되지 않아야 한다
    expect(screen.getByText("중립")).toBeInTheDocument();
    expect(screen.queryByText(/=/)).not.toBeInTheDocument();
  });

  it("consensus 존재 시 합의 패널을 렌더한다", () => {
    traceState.verdicts = [
      {
        agent_name: "technical",
        action: "BUY",
        confidence: 80,
        reasoning: "x",
        data_points: {},
      },
    ];
    traceState.consensus = {
      final_action: "BUY",
      final_confidence: 76.3,
      agreement_rate: 0.7,
      reasoning: "다수 매수 우위",
    };
    render(<AgentTrace ticker="AAPL" />);
    expect(screen.getByText("합의:")).toBeInTheDocument();
    expect(screen.getByText("76.3%")).toBeInTheDocument();
    expect(screen.getByText("(70% 동의)")).toBeInTheDocument();
    expect(screen.getByText("다수 매수 우위")).toBeInTheDocument();
  });
});
