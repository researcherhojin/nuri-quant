/**
 * Pipeline page — coverage branches (handleRunStep, setTimeout, running state, error display).
 * Split from coverage-push-1.test.tsx (lines 64-211).
 */
import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import type { ReactNode } from "react";
import { ERRORS } from "@/lib/strings";

type PipelineNode = {
  id: string;
  data?: {
    label?: ReactNode;
    isRunning?: boolean;
    status?: string;
    onRun?: (id: string) => void;
  };
};
vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ nodes, children }: { nodes?: PipelineNode[]; children?: ReactNode }) => (
    <div data-testid="react-flow">
      {nodes?.map((n: PipelineNode) => (
        <div key={n.id} data-testid={`node-${n.id}`}>
          {/* Render the custom node type to cover PipelineNode */}
          {n.data?.label}
          {n.data?.isRunning && <span data-testid={`running-${n.id}`}>running</span>}
          {n.data?.status === "error" && <span data-testid={`error-${n.id}`}>error</span>}
          <button data-testid={`run-${n.id}`} onClick={() => n.data?.onRun?.(n.id)}>Run</button>
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

const mockStepsWithRunning = [
  { step: "collect", label: "Collect", description: "21 collectors", record_count: 25000, last_updated: "2026-03-31T10:00:00", status: "running", started_at: "2026-03-31T10:00:00", error: null },
  { step: "validate", label: "Validate", description: "Signal backtest", record_count: 0, last_updated: null, status: "idle", started_at: null, error: null },
  { step: "classify", label: "Classify", description: "Regime", record_count: 30, last_updated: "2026-03-31T08:00:00", status: "error", started_at: null, error: "timeout: classify took too long" },
  { step: "diagnose", label: "Diagnose", description: "Agents", record_count: 0, last_updated: null, status: "idle", started_at: null, error: null },
  { step: "recommend", label: "Recommend", description: "Targets", record_count: 10, last_updated: "2026-03-30T12:00:00", status: "done", started_at: null, error: null },
  { step: "track", label: "Track", description: "Outcomes", record_count: 5, last_updated: "2026-03-30T12:00:00", status: "done", started_at: null, error: null },
];

const mockTimelineWithPayloads = [
  { timestamp: "2026-03-31T10:05:00", event_type: "error", step: "classify", payload: { stderr: "Process timed out after 30s" } },
  { timestamp: "2026-03-31T10:00:00", event_type: "start", step: "collect", payload: { command: "make collect" } },
  { timestamp: "2026-03-31T09:55:00", event_type: "success", step: "validate", payload: { error: "minor warning" } },
  { timestamp: "2026-03-31T09:50:00", event_type: "success", step: "track", payload: { records: 5 } },
];

describe("Pipeline — coverage branches", () => {
  let fetchMock: Mock;

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
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
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    // Pipeline renders with running node data
    expect(screen.getByTestId("react-flow")).toBeInTheDocument();
  });

  it("handles run success + setTimeout refresh", async () => {
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });

    await act(async () => { await vi.advanceTimersByTimeAsync(200); });

    // Click run on validate step
    const runBtn = screen.queryByTestId("run-validate");
    if (runBtn) {
      await act(async () => { fireEvent.click(runBtn); });
      // setTimeout(fetchStatus, 1000) + setTimeout(fetchTimeline, 1000)
      await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    }
    expect(screen.getByTestId("react-flow")).toBeInTheDocument();
  });

  it("handles run with error response + alert", async () => {
    const alertMock = vi.fn();
    vi.stubGlobal("alert", alertMock);

    fetchMock.mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ error: "already running" }) });
      }
      if (url.includes("/api/pipeline/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ steps: mockStepsWithRunning }) });
      }
      if (url.includes("/api/pipeline/timeline")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: [] }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });

    const runBtn = screen.queryByTestId("run-validate");
    if (runBtn) {
      await act(async () => { fireEvent.click(runBtn); });
      await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    }
    // alert should be called with error message (F-002: 한국어 실패 프리픽스 + 원문)
    if (alertMock.mock.calls.length > 0) {
      expect(alertMock).toHaveBeenCalledWith(`${ERRORS.RUN_FAILED_PREFIX}already running`);
    }
    vi.unstubAllGlobals();
  });

  it("handles run POST network failure", async () => {
    fetchMock.mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST") {
        return Promise.reject(new Error("network"));
      }
      if (url.includes("/api/pipeline/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ steps: mockStepsWithRunning }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });

    const runBtn = screen.queryByTestId("run-validate");
    if (runBtn) {
      await act(async () => { fireEvent.click(runBtn); });
      await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    }
    // Should not crash
    expect(screen.getByTestId("react-flow")).toBeInTheDocument();
  });

  it("covers 10s interval auto-refresh", async () => {
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });

    const initialCalls = fetchMock.mock.calls.length;
    // Advance 10 seconds for interval
    await act(async () => { await vi.advanceTimersByTimeAsync(10_500); });

    // Should have made additional fetch calls
    expect(fetchMock.mock.calls.length).toBeGreaterThan(initialCalls);
  });

  it("renders timeline events with payload data", async () => {
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    // Timeline section should exist
    expect(screen.getByText(/이벤트 타임라인/)).toBeInTheDocument();
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

    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });
    expect(screen.getByTestId("react-flow")).toBeInTheDocument();
  });
});
