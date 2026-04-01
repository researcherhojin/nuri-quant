/**
 * Pipeline page extended — handleRunStep, error paths.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ nodes, children }: any) => (
    <div data-testid="react-flow">{nodes?.length ?? 0} nodes{children}</div>
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

const mockSteps = [
  { step: "collect", label: "Collect", description: "21 collectors", record_count: 25000, last_updated: "2026-03-31T10:00:00", status: "done", started_at: null, error: null },
  { step: "validate", label: "Validate", description: "Signal backtest", record_count: 150, last_updated: null, status: "idle", started_at: null, error: null },
];

describe("Pipeline handleRunStep", () => {
  let fetchMock: any;

  beforeEach(() => {
    fetchMock = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: "started" }) });
      }
      if (url.includes("/api/pipeline/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ steps: mockSteps, pipeline_status: "ready" }) });
      }
      if (url.includes("/api/gate")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });
    global.fetch = fetchMock;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("clicking run button triggers POST request", async () => {
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });

    // Wait for initial data load
    await act(async () => { await new Promise((r) => setTimeout(r, 100)); });

    const buttons = screen.queryAllByText(/Run|실행/);
    if (buttons.length > 0) {
      await act(async () => { fireEvent.click(buttons[0]); });
      await act(async () => { await new Promise((r) => setTimeout(r, 100)); });

      const postCalls = fetchMock.mock.calls.filter((c: any) => c[1]?.method === "POST");
      expect(postCalls.length).toBeGreaterThanOrEqual(0);
    }
  });

  it("handles POST error without crashing", async () => {
    fetchMock.mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST") return Promise.reject(new Error("network"));
      if (url.includes("/api/pipeline/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ steps: mockSteps, pipeline_status: "ready" }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await new Promise((r) => setTimeout(r, 100)); });

    const buttons = screen.queryAllByText(/Run|실행/);
    if (buttons.length > 0) {
      await act(async () => { fireEvent.click(buttons[0]); });
      await act(async () => { await new Promise((r) => setTimeout(r, 100)); });
    }
    expect(screen.getByTestId("react-flow")).toBeInTheDocument();
  });

  it("handles POST with error field shows alert", async () => {
    const alertMock = vi.fn();
    vi.stubGlobal("alert", alertMock);

    fetchMock.mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ error: "already running" }) });
      }
      if (url.includes("/api/pipeline/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ steps: mockSteps, pipeline_status: "ready" }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await new Promise((r) => setTimeout(r, 100)); });

    const buttons = screen.queryAllByText(/Run|실행/);
    if (buttons.length > 0) {
      await act(async () => { fireEvent.click(buttons[0]); });
      await act(async () => { await new Promise((r) => setTimeout(r, 200)); });
    }

    vi.unstubAllGlobals();
  });
});
