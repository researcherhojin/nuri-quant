/**
 * evidence-charts-lazy — next/dynamic 옵션 캡처 mock (#1225).
 * loader thunk 실행 + loading 스켈레톤 렌더까지 덮는다 (diff coverage).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

interface CapturedCall {
  loader: () => Promise<unknown>;
  opts?: { ssr?: boolean; loading?: () => React.ReactElement };
}

// vi.mock 은 파일 최상단으로 hoist 되므로 캡처 배열도 hoist 필요 (TDZ 회피)
const captured = vi.hoisted(() => [] as { loader: () => Promise<unknown>; opts?: { ssr?: boolean; loading?: () => React.ReactElement } }[]);

vi.mock("next/dynamic", () => ({
  default: (loader: CapturedCall["loader"], opts?: CapturedCall["opts"]) => {
    captured.push({ loader, opts });
    const Stub = () => <div data-testid="lazy-stub" />;
    return Stub;
  },
}));

import {
  FearGreedChartLazy,
  PortfolioTreemapLazy,
  RegimeChartLazy,
  SellEvidenceChartLazy,
  SignalPerformanceChartLazy,
} from "@/components/evidence/evidence-charts-lazy";

const LAZY = [
  RegimeChartLazy,
  PortfolioTreemapLazy,
  SignalPerformanceChartLazy,
  FearGreedChartLazy,
  SellEvidenceChartLazy,
];

describe("evidence-charts-lazy", () => {
  it("registers 5 dynamic components, all ssr:false", () => {
    expect(captured.length).toBe(5);
    expect(LAZY.every((c) => typeof c === "function")).toBe(true);
    expect(captured.every((c) => c.opts?.ssr === false)).toBe(true);
  });

  it("each loader resolves to a chart component", async () => {
    for (const { loader } of captured) {
      const mod = await loader();
      expect(typeof mod).toBe("function");
    }
  });

  it("each loading skeleton renders a pulse placeholder", () => {
    const testids = [
      "regime-chart-loading",
      "portfolio-treemap-loading",
      "signal-performance-loading",
      "fear-greed-loading",
      "sell-evidence-loading",
    ];
    captured.forEach((c, i) => {
      const Loading = c.opts?.loading;
      if (!Loading) throw new Error(`loading missing at ${i}`);
      render(<Loading />);
      expect(screen.getByTestId(testids[i])).toBeInTheDocument();
    });
  });
});
