import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

// Mock @xyflow/react
vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ nodes, edges, children }: { nodes: any[]; edges: any[]; children: React.ReactNode }) => (
    <div data-testid="react-flow">
      <div data-testid="flow-nodes">{nodes.length} nodes</div>
      <div data-testid="flow-edges">{edges.length} edges</div>
      {children}
    </div>
  ),
  Background: () => <div data-testid="flow-background" />,
  Controls: () => <div data-testid="flow-controls" />,
  Handle: ({ type, position }: { type: string; position: string }) => (
    <div data-testid={`handle-${type}-${position}`} />
  ),
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
}));

// Mock API_BASE
vi.mock("@/lib/api", () => ({
  API_BASE: "http://localhost:8001",
  fetchAPI: vi.fn(),
}));

const mockSteps = [
  { step: "collect", label: "Collect", description: "15 collectors", record_count: 25000, last_updated: "2026-03-31T10:00:00", status: "done", started_at: null, error: null },
  { step: "validate", label: "Validate", description: "Signal backtest", record_count: 150, last_updated: "2026-03-31T09:00:00", status: "done", started_at: null, error: null },
  { step: "classify", label: "Classify", description: "6-regime classifier", record_count: 30, last_updated: "2026-03-31T08:00:00", status: "idle", started_at: null, error: null },
  { step: "diagnose", label: "Diagnose", description: "10 agents consensus", record_count: 0, last_updated: null, status: "idle", started_at: null, error: null },
  { step: "recommend", label: "Recommend", description: "Buy/sell candidates", record_count: 10, last_updated: "2026-03-30T12:00:00", status: "done", started_at: null, error: null },
  { step: "track", label: "Track", description: "30/60/90d outcomes", record_count: 5, last_updated: "2026-03-30T12:00:00", status: "done", started_at: null, error: null },
];

const mockTimeline = [
  { timestamp: "2026-03-31T10:00:00", event_type: "success", step: "collect", payload: { command: "make collect" } },
  { timestamp: "2026-03-31T09:00:00", event_type: "start", step: "validate", payload: {} },
  { timestamp: "2026-03-31T08:30:00", event_type: "error", step: "classify", payload: { error: "timeout" } },
];

const mockGates = {
  collect: {
    phase: "collect",
    total: 2,
    passed: 2,
    score: 1.0,
    ready: true,
    conditions: [
      { id: "c1", phase: "collect", description: "Prices available", passed: true, detail: "OK" },
      { id: "c2", phase: "collect", description: "VIX available", passed: true, detail: "OK" },
    ],
  },
  validate: {
    phase: "validate",
    total: 2,
    passed: 1,
    score: 0.5,
    ready: false,
    conditions: [
      { id: "v1", phase: "validate", description: "Signals pass", passed: true, detail: "OK" },
      { id: "v2", phase: "validate", description: "Scorecard pass", passed: false, detail: "Too low" },
    ],
  },
};

describe("PipelinePage", () => {
  let fetchMock: any;

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/pipeline/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ steps: mockSteps }) });
      }
      if (url.includes("/api/pipeline/timeline")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: mockTimeline }) });
      }
      if (url.includes("/api/gate")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockGates) });
      }
      if (url.includes("/api/pipeline/") && url.includes("/run")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    global.fetch = fetchMock;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders page title", async () => {
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => {
      render(<PipelinePage />);
    });
    expect(screen.getByText("Pipeline")).toBeInTheDocument();
  });

  it("renders ReactFlow canvas", async () => {
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => {
      render(<PipelinePage />);
    });
    expect(screen.getByTestId("react-flow")).toBeInTheDocument();
  });

  it("renders 6 pipeline nodes from API data", async () => {
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => {
      render(<PipelinePage />);
    });
    // Wait for fetch to complete
    await waitFor(() => {
      expect(screen.getByTestId("flow-nodes")).toHaveTextContent("6 nodes");
    });
  });

  it("renders 5 edges connecting nodes", async () => {
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => {
      render(<PipelinePage />);
    });
    expect(screen.getByTestId("flow-edges")).toHaveTextContent("5 edges");
  });

  it("renders status legend", async () => {
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => {
      render(<PipelinePage />);
    });
    // Korean labels from the legend
    expect(screen.getByText(/정상/)).toBeInTheDocument();
    expect(screen.getByText(/에러/)).toBeInTheDocument();
    expect(screen.getByText(/실행 중/)).toBeInTheDocument();
  });

  it("shows auto-refresh indicator", async () => {
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => {
      render(<PipelinePage />);
    });
    expect(screen.getByText(/10초 자동 갱신/)).toBeInTheDocument();
  });

  it("renders empty timeline message when no events", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/pipeline/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ steps: mockSteps }) });
      }
      if (url.includes("/api/pipeline/timeline")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: [] }) });
      }
      if (url.includes("/api/gate")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => {
      render(<PipelinePage />);
    });

    await waitFor(() => {
      expect(screen.getByText(/파이프라인 스텝을 실행하세요/)).toBeInTheDocument();
    });
  });

  it("renders gate conditions section", async () => {
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => {
      render(<PipelinePage />);
    });

    await waitFor(() => {
      expect(screen.getByText("Gate Conditions")).toBeInTheDocument();
    });
  });

  it("shows gate condition descriptions", async () => {
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => {
      render(<PipelinePage />);
    });

    await waitFor(() => {
      expect(screen.getByText("Prices available")).toBeInTheDocument();
      expect(screen.getByText("VIX available")).toBeInTheDocument();
    });
  });

  it("renders default nodes before API response", async () => {
    // Delay fetch response so default nodes render first
    fetchMock.mockImplementation(() => new Promise(() => {})); // never resolves

    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => {
      render(<PipelinePage />);
    });

    // Default nodes have 6 entries
    expect(screen.getByTestId("flow-nodes")).toHaveTextContent("6 nodes");
  });

  it("fetches pipeline status on mount", async () => {
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => {
      render(<PipelinePage />);
    });

    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/pipeline/status"));
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/pipeline/timeline"));
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/gate"));
  });
});
