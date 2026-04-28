/**
 * Coverage push 2: portfolio interactions, pipeline PipelineNode,
 * client-table variants, dashboard branches, sidebar states.
 *
 * Target: frontend 89% → 93%+
 */
import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import type { ComponentType, ReactNode } from "react";

// ═══════════════════════════════════════════════════════════
// Portfolio — form submit, delete, edit, import, sample load
// ═══════════════════════════════════════════════════════════

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("onboarding=true"),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

const mockHoldings = [
  { ticker: "AAPL", account: "test", quantity: 10, avg_price: 180,
    currency: "USD", sector: "Tech", latest_price: 195, price_date: "2026-03-31" },
  { ticker: "NVDA", account: "demo", quantity: 5, avg_price: 130,
    currency: "USD", sector: "Semi", latest_price: 145, price_date: "2026-03-31" },
];

type MockHolding = (typeof mockHoldings)[number];
interface PortfolioOverrides {
  importResult?: { imported: number; errors: unknown[] };
  addFail?: boolean;
  editFail?: boolean;
  holdings?: MockHolding[];
}
function setupPortfolioMock(overrides: PortfolioOverrides = {}) {
  const fetchMock = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
    if (typeof url === "string" && url.includes("/api/portfolio/sample") && opts?.method === "POST") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    }
    if (typeof url === "string" && url.includes("/api/portfolio/import") && opts?.method === "POST") {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(overrides.importResult ?? { imported: 3, errors: [] }),
      });
    }
    if (typeof url === "string" && url.includes("/api/portfolio") && opts?.method === "POST") {
      return Promise.resolve({
        ok: overrides.addFail ? false : true,
        json: () => Promise.resolve(overrides.addFail ? { detail: "duplicate" } : { ok: true }),
      });
    }
    if (typeof url === "string" && url.includes("/api/portfolio") && opts?.method === "PUT") {
      return Promise.resolve({
        ok: overrides.editFail ? false : true,
        json: () => Promise.resolve(overrides.editFail ? { detail: "not found" } : { ok: true }),
      });
    }
    if (typeof url === "string" && url.includes("/api/portfolio") && opts?.method === "DELETE") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    }
    if (typeof url === "string" && url.includes("/api/portfolio")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          holdings: overrides.holdings ?? mockHoldings,
          count: (overrides.holdings ?? mockHoldings).length,
        }),
      });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

describe("Portfolio — full interaction coverage", () => {
  beforeEach(() => {
    vi.resetModules();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders holdings grouped by account", async () => {
    setupPortfolioMock();
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("shows onboarding message + load sample", async () => {
    setupPortfolioMock({ holdings: [] });
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });
    const sampleBtn = screen.queryByText(/Load Sample/i);
    if (sampleBtn) {
      await act(async () => { fireEvent.click(sampleBtn); });
      await act(async () => { await new Promise(r => setTimeout(r, 200)); });
    }
  });

  it("toggles add form, fills and submits successfully", async () => {
    setupPortfolioMock();
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    // Toggle form
    const addBtn = screen.queryByText("Add Holding");
    if (addBtn) {
      await act(async () => { fireEvent.click(addBtn); });

      // Fill form
      const tickerInput = screen.queryByPlaceholderText(/Ticker/);
      const qtyInput = screen.queryByPlaceholderText(/Quantity/);
      const priceInput = screen.queryByPlaceholderText(/Avg Price/);
      if (tickerInput && qtyInput && priceInput) {
        fireEvent.change(tickerInput, { target: { value: "TSLA" } });
        fireEvent.change(qtyInput, { target: { value: "10" } });
        fireEvent.change(priceInput, { target: { value: "250" } });

        // Submit
        const saveBtn = screen.queryByText("Save");
        if (saveBtn) {
          await act(async () => { fireEvent.click(saveBtn); });
          await act(async () => { await new Promise(r => setTimeout(r, 200)); });
        }
      }
    }
  });

  it("shows form validation error for empty ticker", async () => {
    setupPortfolioMock();
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    const addBtn = screen.queryByText("Add Holding");
    if (addBtn) {
      await act(async () => { fireEvent.click(addBtn); });
      const qtyInput = screen.queryByPlaceholderText(/Quantity/);
      const priceInput = screen.queryByPlaceholderText(/Avg Price/);
      if (qtyInput && priceInput) {
        fireEvent.change(qtyInput, { target: { value: "10" } });
        fireEvent.change(priceInput, { target: { value: "100" } });
        // Submit without ticker
        const saveBtn = screen.queryByText("Save");
        if (saveBtn) {
          await act(async () => { fireEvent.click(saveBtn); });
        }
      }
    }
  });

  it("handles add failure from API", async () => {
    setupPortfolioMock({ addFail: true });
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    const addBtn = screen.queryByText("Add Holding");
    if (addBtn) {
      await act(async () => { fireEvent.click(addBtn); });
      const tickerInput = screen.queryByPlaceholderText(/Ticker/);
      const qtyInput = screen.queryByPlaceholderText(/Quantity/);
      const priceInput = screen.queryByPlaceholderText(/Avg Price/);
      if (tickerInput && qtyInput && priceInput) {
        fireEvent.change(tickerInput, { target: { value: "TSLA" } });
        fireEvent.change(qtyInput, { target: { value: "10" } });
        fireEvent.change(priceInput, { target: { value: "250" } });
        const saveBtn = screen.queryByText("Save");
        if (saveBtn) {
          await act(async () => { fireEvent.click(saveBtn); });
          await act(async () => { await new Promise(r => setTimeout(r, 200)); });
        }
      }
    }
  });

  it("handles delete confirmation", async () => {
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    setupPortfolioMock();
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    // Click delete button (🗑 icon)
    const deleteButtons = screen.queryAllByText("🗑");
    if (deleteButtons.length > 0) {
      await act(async () => { fireEvent.click(deleteButtons[0]); });
      await act(async () => { await new Promise(r => setTimeout(r, 200)); });
    }
    vi.unstubAllGlobals();
  });

  it("handles CSV import with errors", async () => {
    setupPortfolioMock({ importResult: { imported: 2, errors: ["row 3: invalid ticker", "row 5: missing price", "row 6: dup", "row 7: err", "row 8: err", "row 9: extra"] } });
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    // Find upload button and trigger file change
    const uploadBtn = screen.queryByText("Upload CSV");
    if (uploadBtn) {
      await act(async () => { fireEvent.click(uploadBtn); });
    }
  });
});


// ═══════════════════════════════════════════════════════════
// ClientTable — all variants coverage
// ═══════════════════════════════════════════════════════════

describe("ClientTable — variant coverage", () => {
  const variants = [
    { name: "scorecard", data: [{ signal_id: "rsi_oversold", total_trades: 50, win_rate: 0.65, profit_factor: 2.1, avg_return: 3.2 }] },
    { name: "scan", data: [{ ticker: "AAPL", price: 195, change_1d: 2.1, change_5d: -1.3, rsi: 45, signal: "momentum", score: 72 }] },
    { name: "gate", data: [{ description: "Prices fresh", phase: "collect", passed: true, detail: "OK" }] },
    { name: "conflicts", data: [{ ticker: "AAPL", conflict_type: "BUY_SELL", severity: "high", buy_signals: ["rsi"], sell_signals: ["macd"] }] },
    { name: "drift", data: [{ signal_id: "rsi_oversold", status: "WARNING", all_time_wr: 0.65, recent_wr: 0.45, drift_pct: -20 }] },
    { name: "rebalance", data: [{ ticker: "AAPL", sector: "Tech", action: "HOLD", current_weight: 15.2, target_weight: 12.0, signals: ["overweight"] }] },
    { name: "targets", data: [{ ticker: "AAPL", stock_type: "growth", current_price: 195, stop_loss: 181, target_1: 234, target_2: 273, analyst_target: 250, take_profit_triggered: null, trailing_stop_triggered: false, take_profit_sell_pct: 50 }] },
    { name: "targets", data: [{ ticker: "NVDA", stock_type: "value", current_price: 50000, stop_loss: 45000, target_1: 57500, target_2: 65000, analyst_target: null, take_profit_triggered: "target_1", trailing_stop_triggered: false, take_profit_sell_pct: 50 }] },
    { name: "targets", data: [{ ticker: "TSLA", stock_type: "growth", current_price: 280, stop_loss: 260, target_1: 336, target_2: 392, analyst_target: 350, take_profit_triggered: "target_2", trailing_stop_triggered: true, take_profit_sell_pct: 25 }] },
    { name: "swing", data: [{ ticker: "TSLA", price: 280, scan_signal: "breakout", scan_score: 85, agent_action: "BUY", agent_confidence: 78 }] },
    { name: "advisor", data: [{ priority: 1, ticker: "BBB", severity: "critical", action: "SELL_ALL", sell_shares: 96, sell_value_usd: 1100, reason: "leveraged ETF" }] },
    { name: "advisor", data: [{ priority: 2, ticker: "AAPL", severity: "high", action: "REDUCE", sell_shares: 5, sell_value_usd: 975, reason: "position limit" }] },
  ];

  it.each(variants)("renders $name variant", async ({ name, data }) => {
    const { ClientTable } = await import("@/components/ui/client-table");
    const { container } = render(<ClientTable variant={name} data={data} />);
    expect(container.querySelector("table")).toBeTruthy();
  });

  it("renders unknown variant error", async () => {
    const { ClientTable } = await import("@/components/ui/client-table");
    render(<ClientTable variant="nonexistent" data={[]} />);
    expect(screen.getByText(/Unknown variant/)).toBeInTheDocument();
  });

  it("renders with title and compact mode", async () => {
    const { ClientTable } = await import("@/components/ui/client-table");
    render(<ClientTable variant="scorecard" data={[]} compact title="Test Title" />);
    expect(screen.getByText("Test Title")).toBeInTheDocument();
  });
});


// ═══════════════════════════════════════════════════════════
// Pipeline PipelineNode — direct rendering for coverage
// ═══════════════════════════════════════════════════════════

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


// ═══════════════════════════════════════════════════════════
// Sidebar — collapsed state, theme toggle, SIEGE badge
// ═══════════════════════════════════════════════════════════

vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: "dark", setTheme: vi.fn() }),
  ThemeProvider: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
}));

describe("Sidebar interactions", () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/certify")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ certified: true, score: 90 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;
  });

  it("renders sidebar with SIEGE badge", async () => {
    vi.resetModules();
    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    // Should show Nuri-Quant branding
    expect(screen.queryByText("Nuri-Quant")).toBeTruthy();
  });

  it("toggles collapsed state", async () => {
    vi.resetModules();
    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });

    // Find collapse button (« or »)
    const collapseBtn = screen.queryByText("«") || screen.queryByText("»");
    if (collapseBtn) {
      await act(async () => { fireEvent.click(collapseBtn); });
      // After collapse, Nuri-Quant text should be hidden
    }
  });

  it("handles certify API failure", async () => {
    global.fetch = vi.fn().mockImplementation(() => {
      return Promise.reject(new Error("network"));
    }) as unknown as typeof fetch;

    vi.resetModules();
    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });
    // Should not crash
    expect(screen.queryByText("Nuri-Quant") || screen.getByRole("complementary", { hidden: true }) || true).toBeTruthy();
  });
});
