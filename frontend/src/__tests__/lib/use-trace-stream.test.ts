import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

// Mock EventSource
class MockEventSource {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  url: string;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  static instances: MockEventSource[] = [];

  simulateMessage(data: string) {
    if (this.onmessage) this.onmessage({ data } as MessageEvent);
  }

  simulateError() {
    if (this.onerror) this.onerror();
  }
}

const mockVerdict = {
  agent_name: "technical",
  ticker: "AAPL",
  action: "BUY",
  confidence: 75,
  reasoning: "RSI oversold",
  data_points: { rsi: 28 },
};

const mockConsensus = {
  ticker: "AAPL",
  final_action: "BUY",
  final_confidence: 72.5,
  agreement_rate: 0.8,
  verdicts: [],
  dissent: [],
  reasoning: "Strong buy consensus",
};

describe("useTraceStream", () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("returns initial state", async () => {
    const { useTraceStream } = await import("@/lib/use-trace-stream");
    const { result } = renderHook(() => useTraceStream());
    expect(result.current.verdicts).toEqual([]);
    expect(result.current.consensus).toBeNull();
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("creates EventSource on start()", async () => {
    const { useTraceStream } = await import("@/lib/use-trace-stream");
    const { result } = renderHook(() => useTraceStream());

    act(() => result.current.start("AAPL"));

    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.instances[0].url).toContain("/api/consensus/AAPL/stream");
    expect(result.current.isStreaming).toBe(true);
  });

  it("accumulates verdicts on verdict events", async () => {
    const { useTraceStream } = await import("@/lib/use-trace-stream");
    const { result } = renderHook(() => useTraceStream());

    act(() => result.current.start("AAPL"));
    const es = MockEventSource.instances[0];

    act(() => es.simulateMessage(JSON.stringify({ type: "verdict", data: mockVerdict })));
    expect(result.current.verdicts).toHaveLength(1);
    expect(result.current.verdicts[0].agent_name).toBe("technical");

    const v2 = { ...mockVerdict, agent_name: "risk", action: "HOLD", confidence: 60 };
    act(() => es.simulateMessage(JSON.stringify({ type: "verdict", data: v2 })));
    expect(result.current.verdicts).toHaveLength(2);
  });

  it("sets consensus on consensus event", async () => {
    const { useTraceStream } = await import("@/lib/use-trace-stream");
    const { result } = renderHook(() => useTraceStream());

    act(() => result.current.start("AAPL"));
    const es = MockEventSource.instances[0];

    act(() => es.simulateMessage(JSON.stringify({ type: "consensus", data: mockConsensus })));
    expect(result.current.consensus).not.toBeNull();
    expect(result.current.consensus!.final_action).toBe("BUY");
  });

  it("stops streaming and closes EventSource on done event", async () => {
    const { useTraceStream } = await import("@/lib/use-trace-stream");
    const { result } = renderHook(() => useTraceStream());

    act(() => result.current.start("AAPL"));
    const es = MockEventSource.instances[0];

    act(() => es.simulateMessage(JSON.stringify({ type: "done" })));
    expect(result.current.isStreaming).toBe(false);
    expect(es.close).toHaveBeenCalled();
  });

  it("handles EventSource error", async () => {
    const { useTraceStream } = await import("@/lib/use-trace-stream");
    const { result } = renderHook(() => useTraceStream());

    act(() => result.current.start("AAPL"));
    const es = MockEventSource.instances[0];

    act(() => es.simulateError());
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.error).toBe("스트림 연결 실패");
  });

  it("closes previous EventSource on restart", async () => {
    const { useTraceStream } = await import("@/lib/use-trace-stream");
    const { result } = renderHook(() => useTraceStream());

    act(() => result.current.start("AAPL"));
    const es1 = MockEventSource.instances[0];

    act(() => result.current.start("TSLA"));
    expect(es1.close).toHaveBeenCalled();
    expect(MockEventSource.instances).toHaveLength(2);
    expect(MockEventSource.instances[1].url).toContain("TSLA");
  });

  it("stop() closes EventSource", async () => {
    const { useTraceStream } = await import("@/lib/use-trace-stream");
    const { result } = renderHook(() => useTraceStream());

    act(() => result.current.start("AAPL"));
    const es = MockEventSource.instances[0];

    act(() => result.current.stop());
    expect(es.close).toHaveBeenCalled();
    expect(result.current.isStreaming).toBe(false);
  });
});
