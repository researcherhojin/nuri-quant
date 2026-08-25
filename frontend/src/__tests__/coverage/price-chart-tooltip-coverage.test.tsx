/**
 * PriceChart — Recharts Tooltip formatter coverage (volume/close/SMA name branches).
 * Uses vi.doMock for recharts to capture Tooltip.formatter callback.
 *
 * Split from coverage-push-4.test.tsx (lines 118-208).
 *
 * NOTE: kept separate from price-chart-coverage.test.tsx (push-1 origin) — that file
 * uses static vi.mock("recharts") with stub components, while this file needs
 * vi.doMock to swap per-test for formatter capture.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";

type RechartsTooltipFormatter = (value: number | string, name?: string) => [string, string];

describe("PriceChart — Tooltip formatter", () => {
  let capturedFormatter: RechartsTooltipFormatter | null = null;

  beforeEach(() => {
    vi.resetModules();
    capturedFormatter = null;

    vi.doMock("recharts", () => ({
      ResponsiveContainer: ({ children }: { children?: ReactNode }) => <div data-testid="responsive-container">{children}</div>,
      ComposedChart: ({ children }: { children?: ReactNode }) => <div data-testid="composed-chart">{children}</div>,
      Area: () => <div data-testid="area" />,
      Line: () => <div data-testid="line" />,
      Bar: () => <div data-testid="bar" />,
      XAxis: () => null,
      YAxis: ({ tickFormatter }: { tickFormatter?: (v: number) => string }) => {
        // Cover price YAxis tickFormatter: (v) => v.toFixed(0)
        if (tickFormatter) tickFormatter(150.7);
        return null;
      },
      Tooltip: (props: { formatter?: RechartsTooltipFormatter }) => {
        if (props.formatter) capturedFormatter = props.formatter;
        return null;
      },
      CartesianGrid: () => null,
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("formats volume, close, and SMA names correctly", async () => {
    const { PriceChart } = await import("@/components/ui/price-chart");
    const data = Array.from({ length: 60 }, (_, i) => ({
      date: `2024-01-${String((i % 28) + 1).padStart(2, "0")}`,
      open: 100, high: 105, low: 95, close: 100 + i * 0.5,
      volume: 1_500_000,
    }));
    render(<PriceChart data={data} ticker="AAPL" />);

    expect(capturedFormatter).not.toBeNull();
    const fmt = capturedFormatter!;

    // Volume branch
    const [volLabel, volName] = fmt(1_500_000, "volume");
    expect(volLabel).toBe("1.5M");
    expect(volName).toBe("Vol");

    // Close branch
    const [closeLabel, closeName] = fmt(195.50, "close");
    expect(closeLabel).toBe("$195.50");
    expect(closeName).toBe("Close");

    // SMA name branch (fallback: any other name → uppercased)
    const [sma20Label, sma20Name] = fmt(150.25, "sma20");
    expect(sma20Label).toBe("$150.25");
    expect(sma20Name).toBe("SMA20");

    const [sma50Label, sma50Name] = fmt(148.00, "sma50");
    expect(sma50Label).toBe("$148.00");
    expect(sma50Name).toBe("SMA50");
  });

  // #1197 잠금: KR 티커 툴팁은 ₩ — 헤더는 ₩ 인데 툴팁만 $ 였던 혼합 표기 회귀 방지
  it("formats KRW ticker tooltip prices with ₩", async () => {
    const { PriceChart } = await import("@/components/ui/price-chart");
    const data = Array.from({ length: 30 }, (_, i) => ({
      date: `2024-01-${String((i % 28) + 1).padStart(2, "0")}`,
      open: 1_120_000, high: 1_140_000, low: 1_100_000, close: 1_128_000 + i,
      volume: 10_000,
    }));
    render(<PriceChart data={data} ticker="402340.KS" />);

    expect(capturedFormatter).not.toBeNull();
    const [closeLabel] = capturedFormatter!(1_128_000, "close");
    expect(closeLabel).toBe("₩1,128,000");
    const [smaLabel] = capturedFormatter!(1_130_000.4, "sma20");
    expect(smaLabel).toBe("₩1,130,000");
  });

  it("formats volume in K range", async () => {
    const { PriceChart } = await import("@/components/ui/price-chart");
    const data = Array.from({ length: 30 }, (_, i) => ({
      date: `2024-01-${String((i % 28) + 1).padStart(2, "0")}`,
      open: 100, high: 105, low: 95, close: 100,
      volume: 50_000,
    }));
    render(<PriceChart data={data} ticker="TEST" />);

    expect(capturedFormatter).not.toBeNull();
    const [volLabel] = capturedFormatter!(50_000, "volume");
    expect(volLabel).toBe("50K");
  });

  it("formats small volume numbers", async () => {
    const { PriceChart } = await import("@/components/ui/price-chart");
    const data = Array.from({ length: 30 }, (_, i) => ({
      date: `2024-01-${String((i % 28) + 1).padStart(2, "0")}`,
      open: 100, high: 105, low: 95, close: 100,
      volume: 500,
    }));
    render(<PriceChart data={data} ticker="MICRO" />);

    expect(capturedFormatter).not.toBeNull();
    const [volLabel] = capturedFormatter!(500, "volume");
    expect(volLabel).toBe("500");
  });
});
