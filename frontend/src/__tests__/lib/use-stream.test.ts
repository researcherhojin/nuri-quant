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
    MockEventSource.instance = this;
  }

  static instance: MockEventSource | null = null;

  // Simulate receiving a message
  simulateMessage(data: string) {
    if (this.onmessage) {
      this.onmessage({ data } as MessageEvent);
    }
  }

  simulateError() {
    if (this.onerror) {
      this.onerror();
    }
  }
}

describe("useStream", () => {
  beforeEach(() => {
    MockEventSource.instance = null;
    vi.stubGlobal("EventSource", MockEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns null initially", async () => {
    const { useStream } = await import("@/lib/use-stream");
    const { result } = renderHook(() => useStream());
    expect(result.current).toBeNull();
  });

  it("updates data on message", async () => {
    const { useStream } = await import("@/lib/use-stream");
    const { result } = renderHook(() => useStream());

    await act(async () => {
      MockEventSource.instance?.simulateMessage(
        JSON.stringify({ regime: "bull_low_vol", vix: 15.5, macro_score: 72 })
      );
    });

    expect(result.current).not.toBeNull();
    expect(result.current?.regime).toBe("bull_low_vol");
    expect(result.current?.vix).toBe(15.5);
    expect(result.current?.macro_score).toBe(72);
  });

  it("handles invalid JSON gracefully", async () => {
    const { useStream } = await import("@/lib/use-stream");
    const { result } = renderHook(() => useStream());

    await act(async () => {
      MockEventSource.instance?.simulateMessage("not-json");
    });

    // Should remain null (parse error caught)
    expect(result.current).toBeNull();
  });

  it("handles error without crashing", async () => {
    const { useStream } = await import("@/lib/use-stream");
    const { result } = renderHook(() => useStream());

    await act(async () => {
      MockEventSource.instance?.simulateError();
    });

    expect(result.current).toBeNull();
  });

  it("closes EventSource on unmount", async () => {
    const { useStream } = await import("@/lib/use-stream");
    const { unmount } = renderHook(() => useStream());

    const instance = MockEventSource.instance;
    unmount();
    expect(instance?.close).toHaveBeenCalled();
  });
});
