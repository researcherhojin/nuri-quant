// Branch-coverage harness for src/app/strategy/page.tsx (StrategyDashboard async Server Component).
// jsdom does not commit nested Suspense children when rendering <Page/>, so we render the
// exported StrategyDashboard directly via `render(await StrategyDashboard())` (gotcha: async SC).
// @/lib/api is mocked because the Server Component fetches via fetchAPI (not global fetch).
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

const fetchAPI = vi.fn();
vi.mock("@/lib/api", () => ({ fetchAPI: (...a: unknown[]) => fetchAPI(...a) }));

// InteractiveBacktest is a client/lazy component; stub so the equity_curve branch renders deterministically.
vi.mock("@/components/ui/interactive-backtest-lazy", () => ({
  InteractiveBacktestLazy: (props: Record<string, unknown>) => (
    <div data-testid="interactive-backtest" data-metrics={JSON.stringify(props.initialMetrics ?? null)} />
  ),
}));

import { StrategyDashboard } from "@/app/strategy/page";

// fetchAPI is called twice in order: [0] /api/strategy/status, [1] /api/backtest.
function mockResponses(status: unknown, bt: unknown) {
  fetchAPI.mockReset();
  fetchAPI.mockImplementation((url: string) => {
    if (url === "/api/strategy/status") return Promise.resolve(status);
    if (url === "/api/backtest") return Promise.resolve(bt);
    return Promise.resolve({});
  });
}

beforeEach(() => cleanup());

describe("StrategyDashboard branch coverage", () => {
  // Covers the ||{}, ||[], ??0, ||0 defensive-default arms (lines 75-84, 139-162, 227-231, 251-252)
  // by OMITTING every optional field. status.allocation undefined -> alloc={}; bt.result undefined -> r={};
  // status.actions undefined -> []; status.positions undefined -> []; bt.stress undefined -> [].
  it("renders with fully-empty payloads (all nullish-default arms)", async () => {
    mockResponses({}, {});
    render(await StrategyDashboard());

    // regime?.regime || "unknown" -> UNKNOWN; regime?.confidence != null is false -> empty confidence text.
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
    expect(screen.getByText("0 positions open")).toBeInTheDocument();
    // r.total_days || 0  and  r.regime_changes || 0
    expect(screen.getByText("Backtest — 0 days, 0 regime switches")).toBeInTheDocument();
    // (r.total_return||0) > 0 false -> "" sign + red-400; value 0.0%
    const ret = screen.getByText("0.0%", { selector: "p.text-red-400" });
    expect(ret).toBeInTheDocument();
    // Allocation bar: long/short/cash all 0 -> none of the three divs render.
    expect(screen.queryByText(/^Long /)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Short /)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Cash /)).not.toBeInTheDocument();
    // No actions, no positions, no timing, no equity curve.
    expect(screen.queryByTestId("interactive-backtest")).not.toBeInTheDocument();
  });

  // Covers the truthy / positive / above-SPY arms:
  //  - allocation long/short/cash > 0 (3 alloc bar branches)
  //  - regime.confidence != null  (confidence span)
  //  - r.total_return > 0  (emerald + "+")
  //  - r.sharpe > r.spy_sharpe (emerald)
  //  - actions.length > 0 + a.reason present (optional-chain truthy arm)
  //  - timing present: avg_forward_30/60/90 > 0 (emerald + "+")
  //  - stress strategy_return > spy_return (emerald) + strategy_return > 0 ("+") + protected true ("✓")
  //  - positions present: direction "long" (emerald dot) + return_pct > 0 (emerald)
  //  - equity_curve present + length > 0  -> InteractiveBacktest renders, metrics ?? present-value path
  it("renders positive / above-benchmark / truthy arms", async () => {
    mockResponses(
      {
        regime: { regime: "bull", confidence: 0.82 },
        allocation: { long_pct: 60, short_pct: 25, cash_pct: 15 },
        actions: [{ action: "open_long", ticker: "NVDA", reason: "momentum breakout above 50d MA cross signal" }],
        positions: { positions: [{ ticker: "NVDA", direction: "long", return_pct: 12.3 }] },
      },
      {
        result: {
          total_return: 34.5,
          sharpe: 1.8,
          spy_sharpe: 0.9,
          max_drawdown: -12.4,
          spy_max_drawdown: -28.1,
          win_rate: 0.6,
          spy_total_return: 18.2,
          excess_return: 16.3,
          total_days: 252,
          regime_changes: 7,
          transaction_costs: 1.2,
          equity_curve: [{ date: "2025-01-01", value: 100 }, { date: "2025-01-02", value: 101 }],
        },
        timing: {
          current_regime: "bull",
          avg_forward_30d: 3.1,
          avg_forward_60d: 5.4,
          avg_forward_90d: 8.2,
          pct_to_bull: 0.7,
          pct_to_bear: 0.1,
        },
        stress: [{ name: "2008 GFC", spy_return: -38, strategy_return: 5, protected: true }],
      },
    );
    render(await StrategyDashboard());

    expect(screen.getByText("BULL")).toBeInTheDocument();
    expect(screen.getByText("82% confidence")).toBeInTheDocument();
    expect(screen.getByText("1 positions open")).toBeInTheDocument();
    // alloc bars
    expect(screen.getByText("Long 60%")).toBeInTheDocument();
    expect(screen.getByText("Short 25%")).toBeInTheDocument();
    expect(screen.getByText("Cash 15%")).toBeInTheDocument();
    // total_return > 0 -> emerald + leading "+"
    expect(screen.getByText("+34.5%", { selector: "p.text-emerald-400" })).toBeInTheDocument();
    // sharpe > spy_sharpe -> emerald
    expect(screen.getByText("1.80", { selector: "p.text-emerald-400" })).toBeInTheDocument();
    // action reason slice rendered (optional-chain truthy); reason.slice(0,30) -> first 30 chars
    expect(screen.getByText("momentum breakout above 50d MA")).toBeInTheDocument();
    // timing positive arms
    expect(screen.getByText("+3.1%")).toBeInTheDocument();
    expect(screen.getByText("+5.4%")).toBeInTheDocument();
    expect(screen.getByText("+8.2%")).toBeInTheDocument();
    // stress: strategy_return > spy_return -> emerald, > 0 -> "+", protected -> "✓"
    expect(screen.getByText("+5%", { selector: "span.text-emerald-400" })).toBeInTheDocument();
    expect(screen.getByText("✓")).toBeInTheDocument();
    // position direction long -> emerald dot; return_pct > 0 -> emerald
    expect(screen.getByText("12.3%", { selector: "span.text-emerald-400" })).toBeInTheDocument();
    // equity_curve present -> InteractiveBacktest renders w/ metrics (?? truthy-arm values)
    const ib = screen.getByTestId("interactive-backtest");
    expect(ib).toBeInTheDocument();
    expect(ib.getAttribute("data-metrics")).toContain("34.5");
  });

  // Covers negative / below-benchmark / falsy arms not hit above:
  //  - r.total_return <= 0 (red + no "+") -- via -5 (also distinct from 0 default test)
  //  - r.sharpe <= r.spy_sharpe (foreground/80)
  //  - timing avg_forward_* <= 0 (red + no "+")
  //  - stress strategy_return <= spy_return (red) + strategy_return <= 0 (no "+") + protected false ("✗")
  //  - positions direction != "long" (red dot) + return_pct <= 0 (red)
  it("renders negative / below-benchmark / falsy arms", async () => {
    mockResponses(
      {
        regime: { regime: "bear", confidence: 0.4 },
        positions: { positions: [{ ticker: "TSLA", direction: "short", return_pct: -8.7 }] },
      },
      {
        result: {
          total_return: -5.2,
          sharpe: 0.3,
          spy_sharpe: 1.1,
          spy_total_return: 9.0,
          total_days: 100,
          regime_changes: 3,
        },
        timing: {
          current_regime: "bear",
          avg_forward_30d: -2.5,
          avg_forward_60d: -4.0,
          avg_forward_90d: -6.5,
          pct_to_bull: 0.2,
          pct_to_bear: 0.6,
        },
        stress: [{ name: "COVID crash", spy_return: -30, strategy_return: -34, protected: false }],
      },
    );
    render(await StrategyDashboard());

    // total_return < 0 -> red, no "+"
    expect(screen.getByText("-5.2%", { selector: "p.text-red-400" })).toBeInTheDocument();
    // sharpe <= spy_sharpe -> foreground/80
    expect(screen.getByText("0.30", { selector: "p.text-foreground\\/80" })).toBeInTheDocument();
    // timing negative arms: red + no "+"
    expect(screen.getByText("-2.5%", { selector: "span.text-red-400" })).toBeInTheDocument();
    expect(screen.getByText("-4%", { selector: "span.text-red-400" })).toBeInTheDocument();
    expect(screen.getByText("-6.5%", { selector: "span.text-red-400" })).toBeInTheDocument();
    // stress: strategy_return < spy_return -> red, <0 no "+", not protected -> "✗"
    expect(screen.getByText("-34%", { selector: "span.text-red-400" })).toBeInTheDocument();
    expect(screen.getByText("✗")).toBeInTheDocument();
    // position direction short -> red dot; return_pct < 0 -> red
    expect(screen.getByText("-8.7%", { selector: "span.text-red-400" })).toBeInTheDocument();
  });

  // Covers action with NO reason (a.reason?.slice optional-chain undefined arm) and
  // stress strategy_return == spy_return boundary not strictly needed; also regime undefined entirely
  // (regime?.regime undefined -> "unknown"; regime?.confidence path with regime undefined).
  it("renders action without reason and undefined regime", async () => {
    mockResponses(
      {
        // regime omitted entirely -> regime undefined -> regime?.regime undefined -> "unknown"
        actions: [{ action: "open_short", ticker: "AMD" }], // reason omitted -> a.reason?.slice undefined
      },
      {},
    );
    render(await StrategyDashboard());
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
    expect(screen.getByText("AMD")).toBeInTheDocument();
  });

  // Covers the `?? 0` and `|| 0` RIGHT-side (nullish/falsy fallback) arms that the positive
  // test (which supplied every field) never triggers:
  //  - lines 227-232: bt.result.{total_return,sharpe,max_drawdown,win_rate,spy_total_return,excess_return} ?? 0
  //    -> need equity_curve present (to enter the InteractiveBacktest block) but those metric fields OMITTED.
  //  - line 251-252: (p.return_pct || 0) -> a position with return_pct OMITTED so the || 0 fallback fires.
  it("renders InteractiveBacktest metric ?? 0 fallbacks and position return_pct || 0 fallback", async () => {
    mockResponses(
      {
        positions: { positions: [{ ticker: "PLTR", direction: "long" }] }, // return_pct omitted -> || 0
      },
      {
        // equity_curve present so the InteractiveBacktest block renders; metric fields omitted -> ?? 0 each
        result: { equity_curve: [{ date: "2025-01-01", value: 100 }] },
      },
    );
    render(await StrategyDashboard());

    // All six ?? 0 fallbacks -> metrics object is all zeros.
    const ib = screen.getByTestId("interactive-backtest");
    expect(JSON.parse(ib.getAttribute("data-metrics")!)).toEqual({
      total_return: 0,
      sharpe: 0,
      max_drawdown: 0,
      win_rate: 0,
      spy_total_return: 0,
      excess_return: 0,
    });
    // position return_pct || 0 -> "0.0%" (and 0 is not > 0 -> red text)
    expect(screen.getByText("0.0%", { selector: "span.text-red-400" })).toBeInTheDocument();
  });
});
