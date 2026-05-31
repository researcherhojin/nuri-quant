import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ReactNode } from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import type { InteractiveBacktest as InteractiveBacktestType } from "@/components/ui/interactive-backtest";

// recharts mock — jsdom 은 SVG 차트를 렌더하지 못함. hoist leak 방지 위해 전용 파일.
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div data-testid="responsive-container">{children}</div>,
  ComposedChart: ({ children }: { children: ReactNode }) => <div data-testid="composed-chart">{children}</div>,
  Area: () => <div data-testid="area" />,
  Line: () => <div data-testid="line" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  Tooltip: () => <div data-testid="tooltip" />,
  CartesianGrid: () => <div data-testid="grid" />,
}));

const mockReplace = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams,
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => "/strategy",
}));

const mockEquity = Array.from({ length: 20 }, (_, i) => ({
  date: `2025-01-${String(i + 1).padStart(2, "0")}`,
  strategy: i * 1.2,
  spy: i * 0.8,
  drawdown: -1,
}));

const posMetrics = {
  total_return: 24.5,
  sharpe: 1.82,
  max_drawdown: -12.3,
  win_rate: 0.58,
  spy_total_return: 15.2,
  excess_return: 9.3,
};

const negMetrics = {
  total_return: -8.4,
  sharpe: 0.5,
  max_drawdown: -12.3,
  win_rate: 0.42,
  spy_total_return: 3.1,
  excess_return: -3.2,
};

describe("InteractiveBacktest branch coverage", () => {
  let InteractiveBacktest: typeof InteractiveBacktestType;

  beforeEach(async () => {
    vi.restoreAllMocks();
    mockReplace.mockReset();
    mockSearchParams = new URLSearchParams();
    global.fetch = vi.fn();
    const mod = await import("@/components/ui/interactive-backtest");
    InteractiveBacktest = mod.InteractiveBacktest;
  });

  // ── TARGET branches: metric sign cond-expr false arms (L101/102/107/108) ──
  it("renders red classes and no '+' prefix when returns are negative", () => {
    const { container } = render(
      <InteractiveBacktest initialData={mockEquity} initialMetrics={negMetrics} />,
    );
    const html = container.innerHTML;
    expect(html).toContain("text-red-400"); // L101 false arm
    expect(html).toContain("text-red-500"); // L107 false arm
    expect(screen.getByText(/Return -8\.4%/)).toBeInTheDocument(); // L102 false arm ("")
    expect(screen.getByText(/vs SPY -3\.2%/)).toBeInTheDocument(); // L108 false arm ("")
  });

  it("renders emerald classes and '+' prefix when returns are positive", () => {
    const { container } = render(
      <InteractiveBacktest initialData={mockEquity} initialMetrics={posMetrics} />,
    );
    const html = container.innerHTML;
    expect(html).toContain("text-emerald-400"); // L101 true arm
    expect(html).toContain("text-emerald-500"); // L107 true arm
    expect(screen.getByText(/Return \+24\.5%/)).toBeInTheDocument(); // L102 true arm ("+")
    expect(screen.getByText(/vs SPY \+9\.3%/)).toBeInTheDocument(); // L108 true arm ("+")
  });

  // ── chart / static-mode defaults ──
  it("renders the equity curve chart and starts in static mode", () => {
    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={posMetrics} />);
    expect(screen.getAllByTestId("responsive-container").length).toBe(2);
    expect(screen.getByText("Static").className).toContain("bg-muted");
    expect(screen.queryByText("Backtest Parameters")).not.toBeInTheDocument();
    expect(screen.queryByText("Custom params")).not.toBeInTheDocument();
  });

  // ── L99 binary-expr false arm: no metrics -> metrics row hidden ──
  it("renders without metrics gracefully", () => {
    render(<InteractiveBacktest initialData={mockEquity} />);
    expect(screen.queryByText(/Return/)).not.toBeInTheDocument();
    expect(screen.getAllByTestId("responsive-container").length).toBe(2);
  });

  // ── L33 hydrate-from-URL branch + L38/L110 interactive+isCustom arms ──
  it("hydrates interactive mode from URL params and shows Custom params", () => {
    mockSearchParams = new URLSearchParams("sma=200&lb=5Y&sl=-10&tp=30");
    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={posMetrics} />);
    expect(screen.getByText("Interactive").className).toContain("bg-muted");
    expect(screen.getByText("Backtest Parameters")).toBeInTheDocument();
    expect(screen.getByText("Custom params")).toBeInTheDocument();
  });

  // ── mode toggle: interactive shows sliders, static hides ──
  it("toggles between interactive and static modes", async () => {
    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={posMetrics} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Interactive"));
    });
    expect(screen.getByText("Backtest Parameters")).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByText("Static"));
    });
    expect(screen.getByText("Static").className).toContain("bg-muted");
    expect(screen.queryByText("Backtest Parameters")).not.toBeInTheDocument();
  });

  // ── runBacktest happy path: ok + equity.length>0 (L57 true, L59 true) ──
  it("shows 'Custom params' after a successful backtest run", async () => {
    const updatedEquity = mockEquity.map((p) => ({ ...p, strategy: p.strategy + 5 }));
    const updatedMetrics = { ...posMetrics, total_return: 30.0, excess_return: 14.8 };
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ equity: updatedEquity, metrics: updatedMetrics }),
    } as Response);

    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={posMetrics} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Interactive"));
    });
    await waitFor(() => expect(screen.getByText("Run Backtest")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByText("Run Backtest"));
    });

    await waitFor(() => expect(screen.getByText("Custom params")).toBeInTheDocument());
    expect(screen.getByText(/Return \+30/)).toBeInTheDocument();
    expect(mockReplace).toHaveBeenCalledWith("/strategy?sma=50&lb=3Y&sl=-7&tp=20");
  });

  // ── runBacktest: ok but equity empty (L59 false arm) ──
  it("keeps current data when API returns ok with empty equity", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ equity: [], metrics: null }),
    } as Response);

    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={posMetrics} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Interactive"));
    });
    await waitFor(() => expect(screen.getByText("Run Backtest")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByText("Run Backtest"));
    });
    await waitFor(() => expect(screen.getByText("Run Backtest")).toBeInTheDocument());
    expect(screen.getByText(/Return \+24\.5%/)).toBeInTheDocument();
  });

  // ── runBacktest: non-ok response (L57 false arm) ──
  it("keeps current data when API returns non-ok response", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: false,
      json: async () => ({}),
    } as Response);

    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={posMetrics} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Interactive"));
    });
    await waitFor(() => expect(screen.getByText("Run Backtest")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByText("Run Backtest"));
    });
    await waitFor(() => expect(screen.getByText("Run Backtest")).toBeInTheDocument());
    expect(screen.getByText(/Return \+24\.5%/)).toBeInTheDocument();
  });

  // ── runBacktest: fetch throws (catch path) ──
  it("keeps current data on fetch error", async () => {
    vi.mocked(global.fetch).mockRejectedValueOnce(new Error("network error"));

    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={posMetrics} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Interactive"));
    });
    await waitFor(() => expect(screen.getByText("Run Backtest")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByText("Run Backtest"));
    });
    await waitFor(() => expect(screen.getByText("Run Backtest")).toBeInTheDocument());
    expect(screen.getByText(/Return \+24\.5%/)).toBeInTheDocument();
    expect(screen.queryByText("Custom params")).not.toBeInTheDocument();
  });
});
