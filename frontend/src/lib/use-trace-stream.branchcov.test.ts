/**
 * use-trace-stream.branchcov.test.ts
 *
 * Branch coverage driver for useTraceStream.
 * jsdom는 EventSource를 제공하지 않으므로 fake를 vi.stubGlobal로 주입해
 * onmessage/onerror의 모든 분기를 결정적으로 트리거한다.
 * 특히 parsed.type if/else-if 체인의 implicit else (unknown type, line ~63) 분기를 커버.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTraceStream } from "./use-trace-stream";

// 마지막으로 생성된 fake EventSource 인스턴스 추적
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  // 테스트 헬퍼: 서버가 보낸 SSE 메시지 시뮬레이트
  emit(data: string) {
    this.onmessage?.({ data });
  }

  emitError() {
    this.onerror?.();
  }

  static last() {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1];
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useTraceStream branch coverage", () => {
  it("verdict 메시지를 누적한다 (type === 'verdict' 분기)", () => {
    const { result } = renderHook(() => useTraceStream());

    act(() => {
      result.current.start("TSLA");
    });
    expect(result.current.isStreaming).toBe(true);

    const es = FakeEventSource.last();
    expect(es.url).toContain("/api/consensus/TSLA/stream");

    act(() => {
      es.emit(
        JSON.stringify({
          type: "verdict",
          data: { agent_name: "A", ticker: "TSLA", action: "BUY" },
        })
      );
    });
    expect(result.current.verdicts).toHaveLength(1);
    expect(result.current.verdicts[0].agent_name).toBe("A");
  });

  it("consensus 메시지를 저장한다 (type === 'consensus' 분기)", () => {
    const { result } = renderHook(() => useTraceStream());
    act(() => result.current.start("NVDA"));
    const es = FakeEventSource.last();

    act(() => {
      es.emit(
        JSON.stringify({
          type: "consensus",
          data: { ticker: "NVDA", final_action: "BUY" },
        })
      );
    });
    expect(result.current.consensus?.final_action).toBe("BUY");
  });

  it("done 메시지에서 스트림을 종료한다 (type === 'done' 분기)", () => {
    const { result } = renderHook(() => useTraceStream());
    act(() => result.current.start("AMD"));
    const es = FakeEventSource.last();

    act(() => {
      es.emit(JSON.stringify({ type: "done" }));
    });
    expect(result.current.isStreaming).toBe(false);
    expect(es.closed).toBe(true);
  });

  it("알 수 없는 type은 상태를 바꾸지 않는다 (implicit else 분기, line ~63)", () => {
    const { result } = renderHook(() => useTraceStream());
    act(() => result.current.start("GOOGL"));
    const es = FakeEventSource.last();

    act(() => {
      es.emit(JSON.stringify({ type: "heartbeat", data: { x: 1 } }));
    });
    // 어떤 분기도 타지 않으므로 초기 상태 유지
    expect(result.current.verdicts).toHaveLength(0);
    expect(result.current.consensus).toBeNull();
    expect(result.current.isStreaming).toBe(true);
  });

  it("JSON 파싱 실패는 무시한다 (catch 분기)", () => {
    const { result } = renderHook(() => useTraceStream());
    act(() => result.current.start("META"));
    const es = FakeEventSource.last();

    act(() => {
      es.emit("not-json{");
    });
    expect(result.current.verdicts).toHaveLength(0);
    expect(result.current.error).toBeNull();
    expect(result.current.isStreaming).toBe(true);
  });

  it("onerror에서 에러 상태로 전환한다", () => {
    const { result } = renderHook(() => useTraceStream());
    act(() => result.current.start("OKLO"));
    const es = FakeEventSource.last();

    act(() => {
      es.emitError();
    });
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.error).toBe("스트림 연결 실패");
    expect(es.closed).toBe(true);
  });

  it("start 재호출 시 기존 EventSource를 닫는다 (esRef.current?.close() truthy 분기)", () => {
    const { result } = renderHook(() => useTraceStream());
    act(() => result.current.start("FIRST"));
    const first = FakeEventSource.last();
    expect(first.closed).toBe(false);

    act(() => result.current.start("SECOND"));
    // 두 번째 start가 첫 번째 인스턴스를 닫아야 함
    expect(first.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(2);
  });

  it("stop은 esRef가 있을 때 닫고 스트리밍을 멈춘다", () => {
    const { result } = renderHook(() => useTraceStream());
    act(() => result.current.start("IONQ"));
    const es = FakeEventSource.last();

    act(() => result.current.stop());
    expect(es.closed).toBe(true);
    expect(result.current.isStreaming).toBe(false);
  });

  it("stop은 esRef가 없을 때도 안전하다 (esRef.current?.close() nullish 분기)", () => {
    const { result } = renderHook(() => useTraceStream());
    // start 호출 없이 stop → esRef.current === null → ?. short-circuit
    act(() => result.current.stop());
    expect(result.current.isStreaming).toBe(false);
    expect(FakeEventSource.instances).toHaveLength(0);
  });
});
