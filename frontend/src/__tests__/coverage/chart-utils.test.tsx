/**
 * Chart utility functions — sma + formatVolume exported from price-chart.tsx.
 * Pure-function tests; no recharts/xyflow mocks (avoids vitest hoisting conflicts).
 *
 * Split from coverage-push-3.test.tsx (lines 13-43).
 */
import { describe, it, expect } from "vitest";

describe("sma", () => {
  it("returns nulls for insufficient data", async () => {
    const { sma } = await import("@/components/ui/price-chart");
    expect(sma([100, 101], 5)[0]).toBeNull();
    expect(sma([100, 101], 5)[1]).toBeNull();
  });

  it("calculates correct moving average", async () => {
    const { sma } = await import("@/components/ui/price-chart");
    const result = sma([10, 20, 30, 40, 50], 3);
    expect(result[2]).toBe(20);
    expect(result[4]).toBe(40);
  });
});

describe("formatVolume", () => {
  it("formats millions", async () => {
    const { formatVolume } = await import("@/components/ui/price-chart");
    expect(formatVolume(5_000_000)).toBe("5.0M");
  });

  it("formats thousands", async () => {
    const { formatVolume } = await import("@/components/ui/price-chart");
    expect(formatVolume(50_000)).toBe("50K");
  });

  it("formats small numbers raw", async () => {
    const { formatVolume } = await import("@/components/ui/price-chart");
    expect(formatVolume(999)).toBe("999");
  });
});
