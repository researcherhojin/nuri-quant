import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ClientTable } from "@/components/ui/client-table";

// DataTable is a client component used by ClientTable
// We don't mock it — we test the integrated output

describe("ClientTable", () => {
  // ─── Variant: scorecard ────────────────────────────────
  it("renders scorecard variant with columns", () => {
    const data = [
      { signal_id: "rsi_oversold", total_trades: 50, win_rate: 0.65, profit_factor: 2.1, avg_return: 3.5 },
      { signal_id: "macd_golden", total_trades: 30, win_rate: 0.55, profit_factor: 1.5, avg_return: 2.0 },
    ];
    render(<ClientTable variant="scorecard" data={data} />);
    expect(screen.getByText("Signal")).toBeInTheDocument();
    expect(screen.getByText("Trades")).toBeInTheDocument();
    expect(screen.getByText("Win Rate")).toBeInTheDocument();
    expect(screen.getByText("PF")).toBeInTheDocument();
    expect(screen.getByText("rsi_oversold")).toBeInTheDocument();
    expect(screen.getByText("macd_golden")).toBeInTheDocument();
  });

  it("renders scorecard trade counts", () => {
    const data = [
      { signal_id: "rsi_oversold", total_trades: 50, win_rate: 0.65, profit_factor: 2.1, avg_return: 3.5 },
    ];
    render(<ClientTable variant="scorecard" data={data} />);
    expect(screen.getByText("50")).toBeInTheDocument();
  });

  // ─── Variant: drift ─────────────────────────────────────
  it("renders drift variant columns", () => {
    const data = [
      { signal_id: "rsi_oversold", status: "stable", all_time_wr: 65, recent_wr: 60, drift_pct: -5 },
    ];
    render(<ClientTable variant="drift" data={data} />);
    expect(screen.getByText("Signal")).toBeInTheDocument();
    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("All-time WR")).toBeInTheDocument();
    expect(screen.getByText("Recent WR")).toBeInTheDocument();
    expect(screen.getByText("Drift")).toBeInTheDocument();
  });

  it("renders drift data with percentages", () => {
    const data = [
      { signal_id: "rsi_oversold", status: "degrading", all_time_wr: 65, recent_wr: 45, drift_pct: -20 },
    ];
    render(<ClientTable variant="drift" data={data} />);
    expect(screen.getByText("rsi_oversold")).toBeInTheDocument();
    expect(screen.getByText("degrading")).toBeInTheDocument();
  });

  // ─── Variant: scan ──────────────────────────────────────
  it("renders scan variant columns", () => {
    const data = [
      { ticker: "TSLA", price: 250.0, change_1d: 2.5, change_5d: -1.3, rsi: 45, signal: "bounce", score: 85 },
    ];
    render(<ClientTable variant="scan" data={data} />);
    expect(screen.getByText("Ticker")).toBeInTheDocument();
    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(screen.getByText("1D")).toBeInTheDocument();
    expect(screen.getByText("5D")).toBeInTheDocument();
    expect(screen.getByText("RSI")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();
  });

  // ─── Variant: targets ───────────────────────────────────
  it("renders targets variant columns", () => {
    const data = [
      {
        ticker: "NVDA",
        stock_type: "growth",
        current_price: 168.0,
        stop_loss: 156.24,
        target_1: 201.6,
        target_2: 235.2,
        analyst_target: 273.0,
        take_profit_triggered: null,
        trailing_stop_triggered: false,
        take_profit_sell_pct: 0,
      },
    ];
    render(<ClientTable variant="targets" data={data} />);
    expect(screen.getByText("Ticker")).toBeInTheDocument();
    expect(screen.getByText("Type")).toBeInTheDocument();
    // Korean labels
    expect(screen.getByText(/현재가/)).toBeInTheDocument();
    expect(screen.getByText(/손절가/)).toBeInTheDocument();
    expect(screen.getByText(/1차 익절/)).toBeInTheDocument();
    expect(screen.getByText(/2차 익절/)).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
  });

  // ─── Variant: advisor ───────────────────────────────────
  it("renders advisor variant columns", () => {
    const data = [
      {
        priority: 1,
        ticker: "TSLA",
        severity: "critical",
        action: "SELL_ALL",
        sell_shares: 33,
        sell_value_usd: 8250,
        reason: "Stop loss triggered",
      },
    ];
    render(<ClientTable variant="advisor" data={data} />);
    expect(screen.getByText("Ticker")).toBeInTheDocument();
    expect(screen.getByText(/심각도/)).toBeInTheDocument();
    expect(screen.getByText(/조치/)).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();
    expect(screen.getByText(/전량 매도/)).toBeInTheDocument();
  });

  // ─── Unknown variant ────────────────────────────────────
  it("shows error message for unknown variant", () => {
    render(<ClientTable variant="nonexistent" data={[]} />);
    expect(screen.getByText("Unknown variant: nonexistent")).toBeInTheDocument();
  });

  // ─── Empty data ──────────────────────────────────────────
  it("renders empty table when data is empty", () => {
    const { container } = render(<ClientTable variant="scorecard" data={[]} />);
    const tbody = container.querySelector("tbody");
    expect(tbody).not.toBeNull();
    expect(tbody!.children).toHaveLength(0);
  });

  // ─── Title ──────────────────────────────────────────────
  it("renders title when provided", () => {
    render(<ClientTable variant="scorecard" data={[]} title="Signal Scorecard" />);
    expect(screen.getByText("Signal Scorecard")).toBeInTheDocument();
  });

  it("does not render title when not provided", () => {
    render(<ClientTable variant="scorecard" data={[]} />);
    // No title text should be present (no p element with title class)
    const titleElements = document.querySelectorAll("p.text-xs.text-muted-foreground.mb-3");
    expect(titleElements).toHaveLength(0);
  });

  // ─── Compact mode ──────────────────────────────────────
  it("passes compact prop to DataTable", () => {
    const data = [
      { signal_id: "rsi_oversold", total_trades: 50, win_rate: 0.65, profit_factor: 2.1, avg_return: 3.5 },
    ];
    const { container } = render(<ClientTable variant="scorecard" data={data} compact />);
    const table = container.querySelector("table");
    expect(table!.className).toContain("text-xs");
  });

  // ─── Variant: swing ─────────────────────────────────────
  it("renders swing variant columns", () => {
    const data = [
      { ticker: "PLTR", price: 85.0, scan_signal: "breakout", scan_score: 90, agent_action: "BUY", agent_confidence: 72 },
    ];
    render(<ClientTable variant="swing" data={data} />);
    expect(screen.getByText("Ticker")).toBeInTheDocument();
    expect(screen.getByText("Signal")).toBeInTheDocument();
    expect(screen.getByText("Score")).toBeInTheDocument();
    expect(screen.getByText("Agent")).toBeInTheDocument();
    expect(screen.getByText("PLTR")).toBeInTheDocument();
  });

  // ─── Targets row highlighting ──────────────────────────
  it("highlights target_1 row with emerald background", () => {
    const data = [{
      ticker: "AAPL", stock_type: "value", current_price: 195, stop_loss: 171, target_1: 218.5,
      target_2: 247, analyst_target: 220, take_profit_triggered: "target_1", take_profit_sell_pct: 50,
      trailing_stop_triggered: false,
    }];
    const { container } = render(<ClientTable variant="targets" data={data} />);
    expect(container.querySelector("tbody tr")!.className).toContain("bg-emerald-500/8");
  });

  it("highlights target_2 row with amber background", () => {
    const data = [{
      ticker: "NVDA", stock_type: "growth", current_price: 240, stop_loss: 156, target_1: 198,
      target_2: 235.2, analyst_target: 273, take_profit_triggered: "target_2", take_profit_sell_pct: 25,
      trailing_stop_triggered: false,
    }];
    const { container } = render(<ClientTable variant="targets" data={data} />);
    expect(container.querySelector("tbody tr")!.className).toContain("bg-amber-500/8");
  });

  it("highlights trailing stop row with red background", () => {
    const data = [{
      ticker: "TSLA", stock_type: "growth", current_price: 250, stop_loss: 260, target_1: 336,
      target_2: 392, analyst_target: null, take_profit_triggered: null, take_profit_sell_pct: 0,
      trailing_stop_triggered: true,
    }];
    const { container } = render(<ClientTable variant="targets" data={data} />);
    expect(container.querySelector("tbody tr")!.className).toContain("bg-red-500/8");
  });

  it("does not highlight row when no signals triggered", () => {
    const data = [{
      ticker: "NVDA", stock_type: "growth", current_price: 168, stop_loss: 156, target_1: 201.6,
      target_2: 235.2, analyst_target: 273, take_profit_triggered: null, take_profit_sell_pct: 0,
      trailing_stop_triggered: false,
    }];
    const { container } = render(<ClientTable variant="targets" data={data} />);
    const cls = container.querySelector("tbody tr")!.className;
    expect(cls).not.toContain("bg-emerald");
    expect(cls).not.toContain("bg-amber");
    expect(cls).not.toContain("bg-red-500/8");
  });

  // ─── Advisor priority badge ────────────────────────────
  it("renders priority 1 with red badge", () => {
    const data = [{ priority: 1, ticker: "TSLA", severity: "critical", action: "SELL_ALL", sell_shares: 33, sell_value_usd: 8250, reason: "Stop loss" }];
    const { container } = render(<ClientTable variant="advisor" data={data} />);
    const badge = container.querySelector("tbody tr td span.rounded-full");
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toBe("1");
    expect(badge!.className).toContain("text-red-400");
  });

  it("renders priority 2 with amber badge", () => {
    const data = [{ priority: 2, ticker: "NVDA", severity: "high", action: "REDUCE", sell_shares: 5, sell_value_usd: 840, reason: "Position limit" }];
    const { container } = render(<ClientTable variant="advisor" data={data} />);
    const badge = container.querySelector("tbody tr td span.rounded-full");
    expect(badge!.textContent).toBe("2");
    expect(badge!.className).toContain("text-amber-400");
  });

  it("renders priority 3+ with muted badge", () => {
    const data = [{ priority: 3, ticker: "AAPL", severity: "medium", action: "REDUCE", sell_shares: 2, sell_value_usd: 390, reason: "Sector limit" }];
    const { container } = render(<ClientTable variant="advisor" data={data} />);
    const badge = container.querySelector("tbody tr td span.rounded-full");
    expect(badge!.textContent).toBe("3");
    expect(badge!.className).toContain("text-muted-foreground");
  });
});
