/**
 * ClientTable — variant coverage (scorecard, scan, gate, conflicts, drift,
 * rebalance, targets, swing, advisor) + branch coverage (signal types, price formats,
 * negative/zero pct, advisor severity).
 *
 * Split from coverage-push-2.test.tsx (lines 222-255) and coverage-push-5.test.tsx (lines 57-120).
 * Both source files only render ClientTable — no recharts/xyflow dependence on these
 * describes. The push-5 origin had next/navigation + chart-lazy mocks at top level
 * which are harmless to ClientTable. Mocks merged below.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

// ═══════════════════════════════════════════════════════════
// ClientTable — all variants coverage (push-2 origin)
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
// ClientTable — branch coverage (push-5 origin)
// ═══════════════════════════════════════════════════════════

describe("ClientTable branches", () => {
  it("renders targets with signal types and price formats", async () => {
    const { ClientTable } = await import("@/components/ui/client-table");
    const data = [
      { ticker: "AAPL", stock_type: "growth", current_price: 195.50,
        stop_loss: 181.82, target_1: 234.60, target_2: 273.70, analyst_target: 220.0,
        take_profit_triggered: "target_1", trailing_stop_triggered: false, take_profit_sell_pct: 50 },
      { ticker: "MSFT", stock_type: "value", current_price: 380.00,
        stop_loss: 342.00, target_1: 437.00, target_2: 494.00, analyst_target: null,
        take_profit_triggered: "target_2", trailing_stop_triggered: false, take_profit_sell_pct: 25 },
      { ticker: "005930.KS", stock_type: "value", current_price: 65000,
        stop_loss: 58500, target_1: 74750, target_2: 84500, analyst_target: 80000,
        take_profit_triggered: null, trailing_stop_triggered: true, take_profit_sell_pct: 0 },
      { ticker: "TSLA", stock_type: "growth", current_price: 0,
        stop_loss: 0, target_1: 0, target_2: 0, analyst_target: 0,
        take_profit_triggered: null, trailing_stop_triggered: false, take_profit_sell_pct: 0 },
    ];
    render(<ClientTable variant="targets" data={data} />);
    expect(screen.getByText("TP1 (50%)")).toBeInTheDocument();
    expect(screen.getByText("TP2 (25%)")).toBeInTheDocument();
    expect(screen.getByText("TRAIL STOP")).toBeInTheDocument();
    expect(screen.getByText("₩65,000")).toBeInTheDocument();
    expect(screen.getByText("$195.50")).toBeInTheDocument();
  });

  it("renders scorecard with negative/zero pct", async () => {
    const { ClientTable } = await import("@/components/ui/client-table");
    const data = [
      { signal_id: "rsi_oversold", total_trades: 100, win_rate: 0.65, profit_factor: 2.1, avg_return: 5.0 },
      { signal_id: "gap_down", total_trades: 50, win_rate: 0.45, profit_factor: 0.8, avg_return: -3.2 },
      { signal_id: "bb_bounce", total_trades: 30, win_rate: 0.50, profit_factor: 1.0, avg_return: 0.0 },
    ];
    const { container } = render(<ClientTable variant="scorecard" data={data} />);
    expect(container.querySelector(".text-emerald-400")).not.toBeNull();
    expect(container.querySelector(".text-red-400")).not.toBeNull();
  });

  it("renders unknown variant error message", async () => {
    const { ClientTable } = await import("@/components/ui/client-table");
    render(<ClientTable variant="nonexistent" data={[]} />);
    expect(screen.getByText("Unknown variant: nonexistent")).toBeInTheDocument();
  });

  it("renders advisor variant with severity levels", async () => {
    const { ClientTable } = await import("@/components/ui/client-table");
    render(<ClientTable variant="advisor" data={[
      { priority: 1, ticker: "BBB", severity: "critical", action: "SELL_ALL", sell_shares: 100, sell_value_usd: 5000, reason: "Leveraged ETF" },
      { priority: 2, ticker: "AAPL", severity: "high", action: "SELL_PARTIAL", sell_shares: 5, sell_value_usd: 900, reason: "Sector limit" },
    ]} />);
    expect(screen.getByText("전량 매도")).toBeInTheDocument();
    expect(screen.getByText("일부 매도")).toBeInTheDocument();
  });

  it("renders gate with title and passed/failed", async () => {
    const { ClientTable } = await import("@/components/ui/client-table");
    render(<ClientTable variant="gate" data={[
      { description: "VIX", phase: "collect", passed: true, detail: "OK" },
      { description: "Fresh", phase: "validate", passed: false, detail: "Stale" },
    ]} compact title="Gate" />);
    expect(screen.getByText("Gate")).toBeInTheDocument();
    expect(screen.getByText("✅")).toBeInTheDocument();
    expect(screen.getByText("❌")).toBeInTheDocument();
  });
});
