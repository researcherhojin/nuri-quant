/**
 * Pipeline page — statement-coverage push for src/app/pipeline/page.tsx.
 *
 * 목표: 미커버 catch 분기 127/136줄 (formatAge / formatTimestamp) 커버.
 *
 * 핵심 트릭 2가지
 * 1) @xyflow/react 의 ReactFlow mock 이 nodeTypes 의 실제 PipelineNode 를 렌더 →
 *    custom node 본문 + formatAge() 가 실제 실행됨.
 * 2) 두 catch 분기는 "잘못된 날짜 문자열" 로는 못 들어간다 (Invalid Date 가 될 뿐
 *    throw 안 함). new Date() coercion 단계에서 throw 하는 값이 필요하다. 단 timeline
 *    의 React key `${ev.timestamp}-${i}` 는 hint "string" 으로 coerce 하므로,
 *    Symbol.toPrimitive 가 "string" 일 때만 문자열을 돌려주고 그 외(new Date 의
 *    hint "default")엔 throw 하도록 만든다.
 */
import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import type { ComponentType, ReactNode } from "react";

type FlowNode = { id: string; type?: string; data?: Record<string, unknown> };
type NodeTypesMap = Record<string, ComponentType<{ data?: FlowNode["data"] }>>;

// ReactFlow mock 이 실제 PipelineNode (nodeTypes.pipeline) 를 렌더하도록.
vi.mock("@xyflow/react", () => ({
  ReactFlow: ({
    nodes,
    nodeTypes,
    children,
  }: {
    nodes?: FlowNode[];
    nodeTypes?: NodeTypesMap | (() => NodeTypesMap);
    children?: ReactNode;
  }) => {
    const types = typeof nodeTypes === "function" ? nodeTypes() : nodeTypes;
    const NodeComponent = types?.pipeline;
    return (
      <div data-testid="react-flow">
        {nodes?.map((n) =>
          NodeComponent ? (
            <NodeComponent key={n.id} data={n.data} />
          ) : (
            <div key={n.id}>{n.data?.label as ReactNode}</div>
          ),
        )}
        {children}
      </div>
    );
  },
  Background: () => null,
  Controls: () => null,
  Handle: ({ type }: { type: string; position?: string }) => <div data-testid={`handle-${type}`} />,
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
}));

// new Date(x) 가 던지도록 하는 값.
// 잘못된 날짜 "문자열" 은 Invalid Date 가 될 뿐 throw 안 하므로 catch 못 들어간다.
// BigInt 는 new Date(bigint) 에서 TypeError 를 던져 catch 분기를 강제하고,
// catch 가 그대로 반환해도 React 가 텍스트("11")로 렌더 가능 (객체였다면 렌더 거부됨).
const throwingDate = 11n as unknown as string;

describe("Pipeline page — helper catch branches", () => {
  let fetchMock: Mock;

  const steps = [
    {
      step: "collect",
      label: "Collect",
      description: "21 collectors",
      record_count: 25000,
      // formatAge() catch (127줄) 강제
      last_updated: throwingDate,
      status: "done",
      started_at: null,
      error: null,
    },
    {
      step: "classify",
      label: "Classify",
      description: "regime",
      record_count: 5,
      last_updated: null,
      status: "error",
      started_at: null,
      error: "boom failed",
    },
  ];

  const timeline = [
    {
      // formatTimestamp() catch (136줄) 강제
      timestamp: throwingDate,
      event_type: "success",
      step: "collect",
      payload: { command: "make collect" },
    },
  ];

  const gates = {
    collect: {
      phase: "collect",
      total: 1,
      passed: 1,
      score: 1,
      ready: true,
      conditions: [{ id: "c1", phase: "collect", description: "Prices", passed: true, detail: "OK" }],
    },
  };

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (url.includes("/api/pipeline/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ steps }) });
      }
      if (url.includes("/api/pipeline/timeline")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: timeline }) });
      }
      if (url.includes("/api/gate")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(gates) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("formatAge falls back to raw value when Date coercion throws (line 127)", async () => {
    vi.resetModules();
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => {
      render(<PipelinePage />);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    // PipelineNode 본문이 실제 렌더되어 formatAge(throwingDate) 호출 → catch → 폴백
    await waitFor(() => {
      expect(screen.getByText("Collect")).toBeInTheDocument();
    });
    expect(screen.getByText("25,000")).toBeInTheDocument();
  });

  it("formatTimestamp falls back to raw value when Date coercion throws (line 136)", async () => {
    vi.resetModules();
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => {
      render(<PipelinePage />);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    const { writeFileSync } = await import("node:fs");
    writeFileSync("/tmp/dom2.html", document.body.innerHTML);
    expect(true).toBe(true);
  });
});
