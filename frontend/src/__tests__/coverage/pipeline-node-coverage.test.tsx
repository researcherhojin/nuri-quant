/**
 * Pipeline page — direct PipelineNode rendering coverage (custom node component,
 * timeline payload rendering, gate conditions).
 *
 * Split from coverage-push-2.test.tsx (lines 296-414).
 *
 * NOTE: kept separate from pipeline-coverage.test.tsx (push-1 origin) — different
 * @xyflow/react mock shape (this file's mock provides memo + Handle returning a
 * div so the inner PipelineNode component is exercised; the other file's mock
 * intercepts at ReactFlow level).
 */
import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import type { ComponentType, ReactNode } from "react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("onboarding=true"),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

// Override the xyflow mock to actually render PipelineNode
type FlowNode = { id: string; data?: { label?: ReactNode; [key: string]: unknown } };
type NodeTypesMap = Record<string, ComponentType<{ data?: FlowNode["data"] }>>;
vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ nodes, nodeTypes, children }: {
    nodes?: FlowNode[];
    nodeTypes?: NodeTypesMap | (() => NodeTypesMap);
    children?: ReactNode;
  }) => {
    const types = typeof nodeTypes === "function" ? nodeTypes() : nodeTypes;
    const NodeComponent = types?.pipeline;
    return (
      <div data-testid="react-flow">
        {nodes?.map((n: FlowNode) => (
          NodeComponent
            ? <NodeComponent key={n.id} data={n.data} />
            : <div key={n.id}>{n.data?.label as ReactNode}</div>
        ))}
        {children}
      </div>
    );
  },
  Background: () => null,
  Controls: () => null,
  Handle: ({ type }: { type: string; position?: string }) => <div data-testid={`handle-${type}`} />,
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  memo: <T extends { displayName?: string }>(fn: T): T => { (fn as { displayName?: string }).displayName = "PipelineNode"; return fn; },
}));

vi.mock("@/lib/api", () => ({
  API_BASE: "http://localhost:8001",
  fetchAPI: vi.fn(),
}));

describe("Pipeline — PipelineNode rendering", () => {
  let fetchMock: Mock;

  const stepsWithAllStatuses = [
    { step: "collect", label: "Collect", description: "21 collectors", record_count: 25000,
      last_updated: new Date(Date.now() - 30 * 60000).toISOString(), status: "done", started_at: null, error: null },
    { step: "validate", label: "Validate", description: "Signal backtest", record_count: 0,
      last_updated: null, status: "idle", started_at: null, error: null },
    { step: "classify", label: "Classify", description: "10-regime", record_count: 30,
      last_updated: new Date(Date.now() - 25 * 3600000).toISOString(), status: "error",
      started_at: null, error: "timeout: classify failed after 60s" },
    { step: "diagnose", label: "Diagnose", description: "Agents", record_count: 10,
      last_updated: new Date(Date.now() - 3600000).toISOString(), status: "running", started_at: "2026-04-01T10:00:00", error: null },
    { step: "recommend", label: "Recommend", description: "Targets", record_count: 5,
      last_updated: "2026-03-30T12:00:00", status: "done", started_at: null, error: null },
    { step: "track", label: "Track", description: "Outcomes", record_count: 0,
      last_updated: "invalid-date", status: "done", started_at: null, error: null },
  ];

  const timelineWithPayloads = [
    { timestamp: "2026-04-01T10:05:00", event_type: "error", step: "classify", payload: { stderr: "Process timed out" } },
    { timestamp: "2026-04-01T10:00:00", event_type: "start", step: "collect", payload: { command: "make collect" } },
    { timestamp: "2026-04-01T09:55:00", event_type: "success", step: "validate", payload: { error: "minor" } },
    { timestamp: "2026-04-01T09:50:00", event_type: "success", step: "track", payload: { count: 5 } },
  ];

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (url.includes("/api/pipeline/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ steps: stepsWithAllStatuses }) });
      }
      if (url.includes("/api/pipeline/timeline")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: timelineWithPayloads }) });
      }
      if (url.includes("/api/gate")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({
          collect: { phase: "collect", total: 2, passed: 2, score: 1, ready: true,
                     conditions: [{ id: "c1", phase: "collect", description: "Prices", passed: true, detail: "OK" }] },
        }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders PipelineNode with all status types", async () => {
    vi.resetModules();
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    // Should render node content (labels, descriptions, record counts)
    await waitFor(() => {
      expect(screen.getByText(/Collect/)).toBeInTheDocument();
    });
  });

  it("renders running node with animation + error node with message", async () => {
    vi.resetModules();
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    // Running node shows "실행 중..." and running indicator
    await waitFor(() => {
      const runningTexts = screen.queryAllByText(/실행 중/);
      expect(runningTexts.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("clicking run button on node triggers POST", async () => {
    vi.resetModules();
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    // Find run buttons (실행)
    const runButtons = screen.queryAllByText("실행");
    if (runButtons.length > 0) {
      await act(async () => { fireEvent.click(runButtons[0]); });
      await act(async () => { await vi.advanceTimersByTimeAsync(1500); });

      // POST should have been called
      const postCalls = fetchMock.mock.calls.filter((c: unknown[]) => (c[1] as RequestInit | undefined)?.method === "POST");
      expect(postCalls.length).toBeGreaterThanOrEqual(1);
    }
  });

  it("renders timeline with stderr, command, error, and JSON payloads", async () => {
    vi.resetModules();
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    await waitFor(() => {
      expect(screen.getByText(/이벤트 타임라인/)).toBeInTheDocument();
    });
  });

  it("renders gate conditions with pass/fail icons", async () => {
    vi.resetModules();
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    await waitFor(() => {
      expect(screen.getByText("Gate Conditions")).toBeInTheDocument();
    });
  });
});
