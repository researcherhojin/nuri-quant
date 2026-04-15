import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

// Mock recharts — jsdom can't render SVG charts
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: any) => <div data-testid="responsive-container">{children}</div>,
  ComposedChart: ({ children }: any) => <div data-testid="composed-chart">{children}</div>,
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

// ── BacktestSliders ──────────────────────────────────────────────────

describe("BacktestSliders", () => {
  let BacktestSliders: any;

  beforeEach(async () => {
    mockSearchParams = new URLSearchParams();
    const mod = await import("@/components/ui/backtest-sliders");
    BacktestSliders = mod.BacktestSliders;
  });

  it("renders current slider labels", () => {
    render(<BacktestSliders onRun={vi.fn()} />);
    expect(screen.getByText("Stop")).toBeInTheDocument();
    expect(screen.getByText("Take")).toBeInTheDocument();
  });

  it("shows default slider values", () => {
    render(<BacktestSliders onRun={vi.fn()} />);
    expect(screen.getByText("-7%")).toBeInTheDocument();
    expect(screen.getByText("20%")).toBeInTheDocument();
  });

  it("renders lookback buttons with 3Y active by default", () => {
    render(<BacktestSliders onRun={vi.fn()} />);
    const btn3Y = screen.getByText("3Y");
    expect(btn3Y).toBeInTheDocument();
    expect(btn3Y.className).toContain("bg-muted");
    expect(screen.getByText("1Y")).toBeInTheDocument();
    expect(screen.getByText("5Y")).toBeInTheDocument();
    expect(screen.getByText("SMA 50").className).toContain("bg-muted");
  });

  it("hides reset button when params are at defaults", () => {
    render(<BacktestSliders onRun={vi.fn()} />);
    expect(screen.queryByText("Reset defaults")).not.toBeInTheDocument();
  });

  it("shows reset button after changing lookback", () => {
    render(<BacktestSliders onRun={vi.fn()} />);
    fireEvent.click(screen.getByText("1Y"));
    expect(screen.getByText("Reset defaults")).toBeInTheDocument();
  });

  it("shows reset button after changing a slider value", () => {
    render(<BacktestSliders onRun={vi.fn()} />);
    // Find the stop-loss slider (first range input)
    const sliders = screen.getAllByRole("slider");
    fireEvent.change(sliders[0], { target: { value: "-10" } });
    expect(screen.getByText("Reset defaults")).toBeInTheDocument();
  });

  it("hides reset button again after clicking reset", () => {
    render(<BacktestSliders onRun={vi.fn()} />);
    // Change lookback to make reset visible
    fireEvent.click(screen.getByText("5Y"));
    expect(screen.getByText("Reset defaults")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Reset defaults"));
    expect(screen.queryByText("Reset defaults")).not.toBeInTheDocument();
  });

  it("calls onRun with current params when Run Backtest is clicked", () => {
    const onRun = vi.fn();
    render(<BacktestSliders onRun={onRun} />);
    fireEvent.click(screen.getByText("Run Backtest"));
    expect(onRun).toHaveBeenCalledWith({
      smaPeriod: 50,
      lookback: "3Y",
      stopLoss: -7,
      takeProfit: 20,
    });
  });

  it("shows 'Running...' when loading prop is true", () => {
    render(<BacktestSliders onRun={vi.fn()} loading={true} />);
    expect(screen.getByText("Running...")).toBeInTheDocument();
    expect(screen.queryByText("Run Backtest")).not.toBeInTheDocument();
  });

  it("disables run button when loading", () => {
    render(<BacktestSliders onRun={vi.fn()} loading={true} />);
    const btn = screen.getByText("Running...");
    expect(btn).toBeDisabled();
  });

  it("passes changed params to onRun after slider change", () => {
    const onRun = vi.fn();
    render(<BacktestSliders onRun={onRun} />);
    fireEvent.click(screen.getByText("SMA 100"));
    fireEvent.click(screen.getByText("1Y"));
    fireEvent.click(screen.getByText("Run Backtest"));
    expect(onRun).toHaveBeenCalledWith(
      expect.objectContaining({ smaPeriod: 100, lookback: "1Y" }),
    );
  });

  it("uses initial params when provided", () => {
    const onRun = vi.fn();
    render(
      <BacktestSliders
        onRun={onRun}
        initialParams={{ smaPeriod: 200, lookback: "5Y", stopLoss: -10, takeProfit: 30 }}
      />,
    );

    fireEvent.click(screen.getByText("Run Backtest"));

    expect(onRun).toHaveBeenCalledWith({
      smaPeriod: 200,
      lookback: "5Y",
      stopLoss: -10,
      takeProfit: 30,
    });
  });
});

// ── InteractiveBacktest ──────────────────────────────────────────────

describe("InteractiveBacktest", () => {
  const mockEquity = Array.from({ length: 20 }, (_, i) => ({
    date: `2025-01-${String(i + 1).padStart(2, "0")}`,
    strategy: i * 1.2,
    spy: i * 0.8,
    drawdown: -(Math.random() * 3).toFixed(1) as unknown as number,
  }));

  const mockMetrics = {
    total_return: 24.5,
    sharpe: 1.82,
    max_drawdown: -12.3,
    win_rate: 0.58,
    spy_total_return: 15.2,
    excess_return: 9.3,
  };

  let InteractiveBacktest: any;

  beforeEach(async () => {
    vi.restoreAllMocks();
    mockReplace.mockReset();
    mockSearchParams = new URLSearchParams();
    global.fetch = vi.fn();
    const mod = await import("@/components/ui/interactive-backtest");
    InteractiveBacktest = mod.InteractiveBacktest;
  });

  it("renders the equity curve chart with initial data", () => {
    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={mockMetrics} />);
    // EquityCurveChart renders two responsive containers (equity + drawdown)
    expect(screen.getAllByTestId("responsive-container").length).toBe(2);
  });

  it("starts in static mode", () => {
    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={mockMetrics} />);
    expect(screen.getByText("Static").className).toContain("bg-muted");
    expect(screen.queryByText("Backtest Parameters")).not.toBeInTheDocument();
  });

  it("displays initial metrics", () => {
    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={mockMetrics} />);
    expect(screen.getByText(/Return \+24\.5%/)).toBeInTheDocument();
    expect(screen.getByText(/Sharpe 1\.82/)).toBeInTheDocument();
    expect(screen.getByText(/MDD -12\.3%/)).toBeInTheDocument();
    expect(screen.getByText(/Win 58%/)).toBeInTheDocument();
    expect(screen.getByText(/vs SPY \+9\.3%/)).toBeInTheDocument();
  });

  it("does not show 'Custom params' label initially", () => {
    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={mockMetrics} />);
    expect(screen.queryByText("Custom params")).not.toBeInTheDocument();
  });

  it("renders without metrics gracefully", () => {
    render(<InteractiveBacktest initialData={mockEquity} />);
    // No metrics row — no "Return" text
    expect(screen.queryByText(/Return/)).not.toBeInTheDocument();
    // But chart still renders
    expect(screen.getAllByTestId("responsive-container").length).toBe(2);
  });

  it("shows 'Custom params' after a successful backtest run", async () => {
    const updatedEquity = mockEquity.map((p) => ({ ...p, strategy: p.strategy + 5 }));
    const updatedMetrics = { ...mockMetrics, total_return: 30.0, excess_return: 14.8 };
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ equity: updatedEquity, metrics: updatedMetrics }),
    } as Response);

    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={mockMetrics} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Interactive"));
    });
    await waitFor(() => expect(screen.getByText("Run Backtest")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByText("Run Backtest"));
    });

    await waitFor(() => {
      expect(screen.getByText("Custom params")).toBeInTheDocument();
    });
    expect(screen.getByText(/Return \+30/)).toBeInTheDocument();
    expect(mockReplace).toHaveBeenCalledWith("/strategy?sma=50&lb=3Y&sl=-7&tp=20");
  });

  it("keeps current data on fetch error", async () => {
    vi.mocked(global.fetch).mockRejectedValueOnce(new Error("network error"));

    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={mockMetrics} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Interactive"));
    });
    await waitFor(() => expect(screen.getByText("Run Backtest")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByText("Run Backtest"));
    });

    await waitFor(() => {
      // Loading should have cleared
      expect(screen.getByText("Run Backtest")).toBeInTheDocument();
    });
    // Original metrics still displayed
    expect(screen.getByText(/Return \+24\.5%/)).toBeInTheDocument();
    expect(screen.queryByText("Custom params")).not.toBeInTheDocument();
  });

  it("keeps current data when API returns non-ok response", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: false,
      json: async () => ({}),
    } as Response);

    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={mockMetrics} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Interactive"));
    });
    await waitFor(() => expect(screen.getByText("Run Backtest")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByText("Run Backtest"));
    });

    await waitFor(() => {
      expect(screen.getByText("Run Backtest")).toBeInTheDocument();
    });
    expect(screen.getByText(/Return \+24\.5%/)).toBeInTheDocument();
  });

  it("constructs the correct fetch URL with params", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ equity: [], metrics: null }),
    } as Response);

    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={mockMetrics} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Interactive"));
    });
    await waitFor(() => expect(screen.getByText("SMA 100")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByText("SMA 100"));
      fireEvent.click(screen.getAllByText("1Y")[0]);
    });
    await waitFor(() => expect(screen.getByText("SMA 100").className).toContain("bg-muted"));
    await act(async () => {
      fireEvent.click(screen.getByText("Run Backtest"));
    });

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        "/api/backtest/equity?sma=100&period=1Y&sl=-7&tp=20",
      );
    });
  });

  it("hydrates interactive mode from URL params", () => {
    mockSearchParams = new URLSearchParams("sma=200&lb=5Y&sl=-10&tp=30");

    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={mockMetrics} />);

    expect(screen.getByText("Interactive").className).toContain("bg-muted");
    expect(screen.getByText("Backtest Parameters")).toBeInTheDocument();
    expect(screen.getByText("Custom params")).toBeInTheDocument();
  });

  it("toggles back to static mode and hides sliders", async () => {
    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={mockMetrics} />);

    await act(async () => {
      fireEvent.click(screen.getByText("Interactive"));
    });
    expect(screen.getByText("Backtest Parameters")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByText("Static"));
    });

    expect(screen.getByText("Static").className).toContain("bg-muted");
    expect(screen.queryByText("Backtest Parameters")).not.toBeInTheDocument();
    expect(screen.getByText(/Return \+24\.5%/)).toBeInTheDocument();
  });

  it("reverts to initialMetrics after switching back to static post-run", async () => {
    const customEquity = mockEquity.map((p) => ({ ...p, strategy: p.strategy + 10 }));
    const customMetrics = { ...mockMetrics, total_return: 45.0, excess_return: 20.0 };
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ equity: customEquity, metrics: customMetrics }),
    } as Response);

    render(<InteractiveBacktest initialData={mockEquity} initialMetrics={mockMetrics} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Interactive"));
    });
    await waitFor(() => expect(screen.getByText("Run Backtest")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByText("Run Backtest"));
    });
    await waitFor(() => expect(screen.getByText(/Return \+45/)).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(screen.getByText("Static"));
    });

    expect(screen.getByText(/Return \+24\.5%/)).toBeInTheDocument();
    expect(screen.queryByText(/Return \+45/)).not.toBeInTheDocument();
    expect(screen.queryByText("Custom params")).not.toBeInTheDocument();
  });
});
