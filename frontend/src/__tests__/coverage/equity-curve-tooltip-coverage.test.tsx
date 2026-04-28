/**
 * EquityCurveChart — Recharts Tooltip formatter coverage (lines 73-130 of source).
 * Uses vi.doMock for recharts to capture tickFormatter / Tooltip.formatter callbacks.
 *
 * Split from coverage-push-4.test.tsx (lines 20-110).
 *
 * NOTE: kept separate from equity-curve-chart-coverage.test.tsx (push-1 origin) —
 * that file uses static vi.mock("recharts") with stub components, while this file
 * needs vi.doMock to swap mocks per-test for formatter capture.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";

type RechartsTickFormatter = (value: number | string) => string;
type RechartsTooltipFormatter = (value: number | string, name?: string) => [string, string];

describe("EquityCurveChart — Tooltip formatters", () => {
  let capturedFormatters: RechartsTooltipFormatter[] = [];

  beforeEach(() => {
    vi.resetModules();
    capturedFormatters = [];

    vi.doMock("recharts", () => ({
      ResponsiveContainer: ({ children }: { children?: ReactNode }) => <div data-testid="responsive-container">{children}</div>,
      ComposedChart: ({ children }: { children?: ReactNode }) => <div data-testid="composed-chart">{children}</div>,
      Area: () => <div data-testid="area" />,
      Line: () => <div data-testid="line" />,
      XAxis: ({ tickFormatter }: { tickFormatter?: RechartsTickFormatter }) => {
        // Cover the XAxis tickFormatter: (v) => String(v).slice(2, 7)
        if (tickFormatter) tickFormatter("2024-06-15");
        return null;
      },
      YAxis: ({ tickFormatter }: { tickFormatter?: RechartsTickFormatter }) => {
        // Cover the YAxis tickFormatter: (v) => `${v}%`
        if (tickFormatter) tickFormatter(25);
        return null;
      },
      Tooltip: (props: { formatter?: RechartsTooltipFormatter }) => {
        if (props.formatter) capturedFormatters.push(props.formatter);
        return null;
      },
      CartesianGrid: () => null,
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("captures and exercises strategy/SPY formatter", async () => {
    const { EquityCurveChart } = await import("@/components/ui/equity-curve-chart");
    const data = [
      { date: "2024-01-01", strategy: 12.5, spy: 8.3, drawdown: -2.1 },
      { date: "2024-01-02", strategy: -3.7, spy: -1.2, drawdown: -5.4 },
      { date: "2024-01-03", strategy: 0, spy: 0, drawdown: 0 },
    ];
    render(<EquityCurveChart data={data} />);

    // Two Tooltips: one for strategy/SPY chart, one for drawdown chart
    expect(capturedFormatters.length).toBe(2);

    // Strategy/SPY formatter (first Tooltip)
    const mainFormatter = capturedFormatters[0];

    // Positive strategy value
    const [stratLabel, stratName] = mainFormatter(12.5, "strategy");
    expect(stratLabel).toBe("+12.5%");
    expect(stratName).toBe("Strategy");

    // Negative SPY value
    const [spyLabel, spyName] = mainFormatter(-1.2, "spy");
    expect(spyLabel).toBe("-1.2%");
    expect(spyName).toBe("SPY");

    // Zero value (no + prefix)
    const [zeroLabel] = mainFormatter(0, "strategy");
    expect(zeroLabel).toBe("0.0%");

    // Drawdown formatter (second Tooltip)
    const ddFormatter = capturedFormatters[1];
    const [ddLabel, ddName] = ddFormatter(-5.4);
    expect(ddLabel).toBe("-5.4%");
    expect(ddName).toBe("Drawdown");

    // Positive drawdown (edge case)
    const [ddPosLabel] = ddFormatter(0);
    expect(ddPosLabel).toBe("0.0%");
  });

  it("exercises string value coercion in formatters", async () => {
    const { EquityCurveChart } = await import("@/components/ui/equity-curve-chart");
    const data = [
      { date: "2024-01-01", strategy: 5.0, spy: 3.0, drawdown: -1.0 },
    ];
    render(<EquityCurveChart data={data} />);

    const mainFormatter = capturedFormatters[0];
    // String value coercion via Number()
    const [result] = mainFormatter("7.77", "strategy");
    expect(result).toBe("+7.8%");

    const ddFormatter = capturedFormatters[1];
    const [ddResult] = ddFormatter("-3.33");
    expect(ddResult).toBe("-3.3%");
  });
});
