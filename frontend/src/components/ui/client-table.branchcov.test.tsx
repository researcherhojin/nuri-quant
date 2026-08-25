import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { ClientTable } from "./client-table";

// DataTable 은 columns.render(value, row) 를 그대로 호출하는 범용 테이블이므로,
// 각 variant 별 fixture 를 렌더해 client-table 내부 렌더러의 모든 분기를 트리거한다.
// 특히 미커버 분기:
//  - pct(): v < 0 (red) / v === 0 (neutral) / typeof v !== "number" 폴백
//  - num(): typeof v !== "number" 폴백 (String(v))
//  - dim(): v == null → "—" 폴백
//  - price(): falsy(0) → "—" / KR(>10000) / US 분기
//  - targets take_profit_triggered render 의 trail/tp2/tp1/dash 분기
//  - advisor priority(1/2/그외) · severity(critical/high/그외) · action(SELL_ALL/그외)
//  - ROW_CLASSNAMES.targets trail/tp2/tp1/없음 분기

vi.mock("./status-badge", () => ({
  StatusBadge: ({ status, size }: { status: string; size: string }) => (
    <span data-testid="badge" data-size={size}>
      {String(status)}
    </span>
  ),
}));

describe("ClientTable branch coverage", () => {
  it("unknown variant returns error paragraph", () => {
    const { container } = render(<ClientTable variant="nope" data={[]} />);
    expect(container.textContent).toContain("Unknown variant: nope");
  });

  it("renders title when provided", () => {
    const { container } = render(
      <ClientTable variant="scanner" data={[]} title="My Title" compact />
    );
    expect(container.textContent).toContain("My Title");
  });

  it("renders without title (falsy branch)", () => {
    const { container } = render(<ClientTable variant="scanner" data={[]} />);
    expect(container.textContent).not.toContain("My Title");
  });

  it("scorecard: pct positive / negative / zero + num number/non-number", () => {
    const data = [
      // win_rate*100 > 0 (positive "+"), avg_return < 0 (red), profit_factor number
      { signal_id: "RSI", total_trades: 10, win_rate: 0.6, profit_factor: 1.5, avg_return: -3.2 },
      // win_rate*100 === 0 (neutral, no "+"), avg_return === 0 (neutral), profit_factor non-number
      { signal_id: "MACD", total_trades: 0, win_rate: 0, profit_factor: "n/a", avg_return: 0 },
    ];
    const { container } = render(<ClientTable variant="scorecard" data={data} />);
    const txt = container.textContent || "";
    // pct(v*100) positive → leading "+"
    expect(txt).toContain("+60.0%");
    // pct negative → red value
    expect(container.querySelector(".text-red-400")).toBeTruthy();
    // pct neutral (0) → muted, no "+"
    expect(container.querySelector(".text-muted-foreground")).toBeTruthy();
    expect(txt).toContain("0.0%");
    // num non-number fallback → String("n/a")
    expect(txt).toContain("n/a");
    // num number → toFixed(1)
    expect(txt).toContain("1.5");
  });

  it("scanner: price renderer with number and undefined, pct non-number fallback (#1219)", () => {
    const data = [
      { ticker: "TSLA", price: 250.5, change_1d: 1.2, change_5d: -2.0, rsi: 55.3, signal: "BUY", score: 80,
        agent_action: "BUY", agent_confidence: 70, approved: true, reason: null },
      // change_1d 가 비수치 → pct() 의 `typeof v === "number" ? v.toFixed(1) : v` else 분기
      { ticker: "NVDA", price: undefined, change_1d: "n/a", change_5d: 0, rsi: "x", signal: "HOLD", score: 0,
        agent_action: null, agent_confidence: null, approved: null, reason: null },
    ];
    const { container } = render(<ClientTable variant="scanner" data={data} />);
    const txt = container.textContent || "";
    expect(txt).toContain("$250.50");
    // num non-number (rsi: "x") fallback
    expect(txt).toContain("x");
    // pct non-number fallback → renders raw value "n/a" then "%"
    expect(txt).toContain("n/a%");
  });

  it("gate: passed boolean true/false glyphs + dim with value and null", () => {
    const data = [
      { description: "Stop", phase: "P1", passed: true, detail: "ok" },
      { description: "Limit", phase: "P2", passed: false, detail: null },
    ];
    const { container } = render(<ClientTable variant="gate" data={data} />);
    const txt = container.textContent || "";
    expect(txt).toContain("✓"); // FINDING-002
    expect(txt).toContain("✕");
    // dim with value
    expect(txt).toContain("ok");
    // dim with null → "—"
    expect(txt).toContain("—");
  });

  it("conflicts: dim join with array and with undefined", () => {
    const data = [
      { ticker: "AMD", conflict_type: "X", severity: "high", buy_signals: ["a", "b"], sell_signals: undefined },
    ];
    const { container } = render(<ClientTable variant="conflicts" data={data} />);
    const txt = container.textContent || "";
    expect(txt).toContain("a, b");
    // sell_signals undefined → dim(undefined?.join) → "—"
    expect(txt).toContain("—");
  });

  it("drift: badge + pct renderers", () => {
    const data = [
      { signal_id: "RSI", status: "DRIFT", all_time_wr: 55.0, recent_wr: -10.0, drift_pct: 0 },
    ];
    const { container } = render(<ClientTable variant="drift" data={data} />);
    expect(container.textContent).toContain("55.0%");
  });

  it("rebalance: weight format + signals dim", () => {
    const data = [
      { ticker: "GOOGL", sector: "Tech", action: "REBALANCE", current_weight: 12.3, target_weight: 10.0, signals: ["s1"] },
      { ticker: "META", sector: null, action: "TRIM", current_weight: undefined, target_weight: undefined, signals: undefined },
    ];
    const { container } = render(<ClientTable variant="rebalance" data={data} />);
    const txt = container.textContent || "";
    expect(txt).toContain("12.3%");
    expect(txt).toContain("s1");
  });

  it("targets: price branches (falsy/KR/US), analyst target present+absent, signal trail/tp2/tp1/dash", () => {
    const data = [
      // trailing stop triggered → TRAIL STOP + row class red
      {
        ticker: "OKLO", stock_type: "growth", current_price: 50.25, stop_loss: 46.5,
        target_1: 60, target_2: 72, analyst_target: 80,
        take_profit_triggered: "target_1", take_profit_sell_pct: 50, trailing_stop_triggered: true,
      },
      // TP2 → amber, KR price (>10000), analyst target absent → dim
      {
        ticker: "005930.KS", stock_type: "value", current_price: 75000, stop_loss: 70000,
        target_1: 90000, target_2: 110000, analyst_target: 0,
        take_profit_triggered: "target_2", take_profit_sell_pct: 25, trailing_stop_triggered: false,
      },
      // TP1 → emerald, price falsy(0) → "—"
      {
        ticker: "NBIS", stock_type: "growth", current_price: 0, stop_loss: 0,
        target_1: 0, target_2: 0, analyst_target: undefined,
        take_profit_triggered: "target_1", take_profit_sell_pct: 50, trailing_stop_triggered: false,
      },
      // no signal → dash, no row class
      {
        ticker: "IONQ", stock_type: "value", current_price: 30, stop_loss: 28,
        target_1: 36, target_2: 42, analyst_target: 45,
        take_profit_triggered: null, take_profit_sell_pct: 0, trailing_stop_triggered: false,
      },
    ];
    const { container } = render(<ClientTable variant="targets" data={data} />);
    const txt = container.textContent || "";
    expect(txt).toContain("TRAIL STOP");
    expect(txt).toContain("TP2 (25%)");
    expect(txt).toContain("TP1 (50%)");
    // KR price formatting (₩)
    expect(txt).toContain("₩");
    // US price formatting ($)
    expect(txt).toContain("$50.25");
    // stock_type growth → momentum badge, value → HOLD badge
    expect(txt).toContain("momentum");
    expect(txt).toContain("HOLD");
    // row classes
    expect(container.querySelector(".bg-red-500\\/8")).toBeTruthy();
    expect(container.querySelector(".bg-amber-500\\/8")).toBeTruthy();
    expect(container.querySelector(".bg-emerald-500\\/8")).toBeTruthy();
  });

  it("scanner: agent/approved arms (#1219)", () => {
    const data = [
      { ticker: "AMD", price: 150.5, change_1d: 1.0, change_5d: 2.0, rsi: 50, signal: "BUY", score: 70,
        agent_action: "LONG", agent_confidence: 80, approved: false, reason: "risk veto" },
    ];
    const { container } = render(<ClientTable variant="scanner" data={data} />);
    expect(container.textContent).toContain("AMD");
    expect(container.textContent).toContain("미승인");
  });

  it("advisor: priority 1/2/other, severity critical/high/other, action SELL_ALL/other", () => {
    const data = [
      { priority: 1, ticker: "OKLO", severity: "critical", action: "SELL_ALL", sell_shares: 100, sell_value_usd: 5000, reason: "stop breach" },
      { priority: 2, ticker: "IONQ", severity: "high", action: "SELL_PARTIAL", sell_shares: 50, sell_value_usd: 2500, reason: "trim" },
      { priority: 3, ticker: "NBIS", severity: "low", action: "OTHER", sell_shares: 10, sell_value_usd: 0, reason: null },
    ];
    const { container } = render(<ClientTable variant="advisor" data={data} />);
    const txt = container.textContent || "";
    // priority 1 → red, 2 → amber, 3 → zinc
    expect(container.querySelector(".bg-red-500\\/20")).toBeTruthy();
    expect(container.querySelector(".bg-amber-500\\/20")).toBeTruthy();
    expect(container.querySelector(".bg-zinc-500\\/20")).toBeTruthy();
    // severity → badge SELL / REDUCE / WATCH
    expect(txt).toContain("SELL");
    expect(txt).toContain("REDUCE");
    expect(txt).toContain("WATCH");
    // action SELL_ALL → 전량 매도, other → 일부 매도
    expect(txt).toContain("전량 매도");
    expect(txt).toContain("일부 매도");
    // money + shares
    expect(txt).toContain("주");
    // reason dim null → "—"
    expect(txt).toContain("—");
  });
});
