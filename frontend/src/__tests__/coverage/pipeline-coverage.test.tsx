/**
 * Pipeline page — coverage branches (polling, running state, error display).
 * Split from coverage-push-1.test.tsx (lines 64-211).
 */
import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { ERRORS, PIPELINE as PL } from "@/lib/strings";

type PipelineNode = {
  id: string;
  data?: {
    label?: ReactNode;
    status?: string;
  };
};

vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ nodes, children }: { nodes?: PipelineNode[]; children?: ReactNode }) => (
    <div data-testid="react-flow">
      {nodes?.map((n: PipelineNode) => (
        <div key={n.id} data-testid={`node-${n.id}`}>
          {/* Render the custom node type to cover PipelineNode */}
          {n.data?.label}
          {n.data?.status === "error" && <span data-testid={`error-${n.id}`}>error</span>}
        </div>
      ))}
      {children}
    </div>
  ),
  Background: () => null,
  Controls: () => null,
  Handle: () => null,
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
}));

vi.mock("@/lib/api", () => ({
  API_BASE: "http://localhost:8001",
  fetchAPI: vi.fn(),
}));

// `GET /api/pipeline/status` 가 실제로 내보내는 5 스테이지
const STAGES = ["collect", "analyze", "consensus", "decide", "track"];

const mockStepsWithRunning = [
  { step: "collect", label: "Collect", description: "Collector jobs + external sources", record_count: 25000, last_updated: "2026-03-31T10:00:00", status: "running", started_at: "2026-03-31T10:00:00", error: null },
  { step: "analyze", label: "Analyze", description: "Factor composite", record_count: 0, last_updated: null, status: "idle", started_at: null, error: null },
  { step: "consensus", label: "Consensus", description: "10 agents weighted vote", record_count: 30, last_updated: "2026-03-31T08:00:00", status: "error", started_at: null, error: "timeout: consensus took too long" },
  { step: "decide", label: "Decide", description: "Decision record (in-memory hand-off)", record_count: 0, last_updated: null, status: "idle", started_at: null, error: null },
  { step: "track", label: "Track", description: "7–90d outcomes + alpha", record_count: 5, last_updated: "2026-03-30T12:00:00", status: "done", started_at: null, error: null },
];

const mockTimelineWithPayloads = [
  { timestamp: "2026-03-31T10:05:00", event_type: "error", step: "consensus", payload: { stderr: "Process timed out after 30s" } },
  { timestamp: "2026-03-31T10:00:00", event_type: "start", step: "collect", payload: { command: "make collect" } },
  { timestamp: "2026-03-31T09:55:00", event_type: "success", step: "analyze", payload: { error: "minor warning" } },
  { timestamp: "2026-03-31T09:50:00", event_type: "success", step: "track", payload: { records: 5 } },
];

describe("Pipeline — coverage branches", () => {
  let fetchMock: Mock;

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/pipeline/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ steps: mockStepsWithRunning }) });
      }

      if (url.includes("/api/pipeline/timeline")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: mockTimelineWithPayloads }) });
      }

      if (url.includes("/api/gate")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      }

      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders with running steps", async () => {
    const PipelinePage = (await import("@/app/pipeline/page-view")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    // 컨테이너만 보면 노드가 하나도 없어도 통과한다 — 다섯 노드 · 에러 표시 · 실행 중 카운터 (#1791)
    await waitFor(() => expect(screen.getByTestId("node-collect")).toBeInTheDocument());

    for (const id of STAGES) {
      expect(screen.getByTestId(`node-${id}`)).toBeInTheDocument();
    }

    expect(screen.getByTestId("error-consensus")).toBeInTheDocument();
    expect(screen.getByText(`1${PL.RUNNING_SUFFIX}`)).toBeInTheDocument();
  });

  it("re-polls the status endpoint at the 10s boundary", async () => {
    // status 만 센다 — 전체 fetch 를 세면 타임라인 폴링만 살아 있어도 통과한다 (#1791)
    const statusCalls = () => fetchMock.mock.calls.filter((c: unknown[]) => String(c[0]).includes("/api/pipeline/status")).length;
    const PipelinePage = (await import("@/app/pipeline/page-view")).default;
    await act(async () => { render(<PipelinePage />); });

    const initial = statusCalls();
    expect(initial).toBeGreaterThan(0);
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(statusCalls()).toBe(initial);
    await act(async () => { await vi.advanceTimersByTimeAsync(1_500); });
    expect(statusCalls()).toBe(initial + 1);
  });

  it("renders timeline events with payload data", async () => {
    const PipelinePage = (await import("@/app/pipeline/page-view")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    // 헤딩이 아니라 이벤트 요약 줄 (#1791)
    await waitFor(() => expect(screen.getByText("Process timed out after 30s")).toBeInTheDocument());
    expect(screen.getByText("make collect")).toBeInTheDocument();
    expect(screen.getByText("minor warning")).toBeInTheDocument();
    expect(screen.getByText("records 5")).toBeInTheDocument();
  });

  it("handles non-ok API responses gracefully", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/pipeline/status")) {
        return Promise.resolve({ ok: false, status: 500 });
      }

      if (url.includes("/api/pipeline/timeline")) {
        return Promise.resolve({ ok: false, status: 500 });
      }

      if (url.includes("/api/gate")) {
        return Promise.resolve({ ok: false, status: 500 });
      }

      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    const PipelinePage = (await import("@/app/pipeline/page-view")).default;
    await act(async () => { render(<PipelinePage />); });
    // 실패를 알리고, 노드는 폴백 다섯 스테이지로 남긴다 (#1791 — 예전엔 컨테이너만 봤다)
    await waitFor(() => expect(screen.getByText(ERRORS.PIPELINE_STATUS_FAILED)).toBeInTheDocument());

    for (const id of STAGES) {
      expect(screen.getByTestId(`node-${id}`)).toBeInTheDocument();
    }
  });
});
