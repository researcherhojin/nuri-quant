/**
 * /evidence 페이지 — 네이티브 차트 전환 후 (#1225 U5a-2).
 *
 * recharts-free: lazy wrapper 모듈을 통째로 mock (vi.mock("recharts") hoisting
 * gotcha 회피 — 차트 본체는 evidence-charts.test.tsx 에서 별도 검증).
 */
import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, act } from "@testing-library/react";

import { EVIDENCE as E } from "@/lib/strings";

vi.mock("@/components/evidence/evidence-charts-lazy", () => ({
  RegimeChartLazy: () => <div data-testid="regime-chart" />,
  PortfolioTreemapLazy: () => <div data-testid="portfolio-treemap" />,
  SignalPerformanceChartLazy: () => <div data-testid="signal-performance-chart" />,
  FearGreedChartLazy: () => <div data-testid="fear-greed-chart" />,
  SellEvidenceChartLazy: () => <div data-testid="sell-evidence-chart" />,
}));

let mockFetchAPI: Mock;

vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

// 형태는 /api/evidence/data/{chart_id} 실응답에서 복사 (mock-shape 규칙)
const PAYLOADS: Record<string, unknown> = {
  "/api/evidence/data/regime": {
    spy: [
      { date: "2026-08-20", open: 1, high: 2, low: 1, close: 100, volume: 10, sma50: null, sma200: null },
      { date: "2026-08-21", open: 1, high: 2, low: 1, close: 101, volume: 10, sma50: 100.5, sma200: null },
    ],
    vix: [{ date: "2026-08-21", value: 18.0 }],
    regime: { regime: "bull_low_vol", trend: "bull", volatility: "low", confidence: 0.8 },
    count: 2,
  },
  "/api/evidence/data/portfolio_heatmap": {
    items: [
      { ticker: "AAA", current_value_usd: 5000, pnl_pct: -12.0, weight_pct: 20.0, sector: "Tech", violation: "stop_loss" },
    ],
    count: 1,
  },
  "/api/evidence/data/signal_performance": {
    signals: [
      { signal_id: "rsi_oversold", win_rate: 0.6, profit_factor: 1.5, total_trades: 10, drift_status: "critical" },
    ],
    count: 1,
  },
  "/api/evidence/data/fear_greed": {
    history: [{ date: "2026-08-21", value: 55.0 }],
    count: 1,
  },
  "/api/evidence/data/sell_evidence": {
    violations: [
      { ticker: "AAA", type: "stop_loss", severity: 12.0, action: "SELL ALL", recovery: "손실 12.0% → 회복에 14% 상승 필요" },
    ],
    count: 1,
  },
};

function setupFetchAPI(overrides: Record<string, unknown> = {}) {
  mockFetchAPI = vi.fn().mockImplementation((path: string) => {
    if (path in overrides) {
      const v = overrides[path];
      if (v instanceof Error) return Promise.reject(v);
      return Promise.resolve(v);
    }
    return Promise.resolve(PAYLOADS[path]);
  });
}

async function renderPage() {
  const { default: EvidencePage } = await import("@/app/evidence/page");
  await act(async () => {
    render(<EvidencePage />);
  });
}

describe("EvidencePage (native charts)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setupFetchAPI();
  });

  it("renders page heading and subtitle", async () => {
    await renderPage();
    expect(screen.getByText("Evidence Charts")).toBeInTheDocument();
    expect(screen.getByText(E.SUBTITLE)).toBeInTheDocument();
  });

  it("renders all 5 chart card titles", async () => {
    await renderPage();
    for (const title of [E.TITLE_REGIME, E.TITLE_HEATMAP, E.TITLE_SIGNALS, E.TITLE_FEAR_GREED, E.TITLE_SELL]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
  });

  it("renders native chart components — and zero iframes", async () => {
    await renderPage();
    expect(screen.getByTestId("regime-chart")).toBeInTheDocument();
    expect(screen.getByTestId("portfolio-treemap")).toBeInTheDocument();
    expect(screen.getByTestId("signal-performance-chart")).toBeInTheDocument();
    expect(screen.getByTestId("fear-greed-chart")).toBeInTheDocument();
    expect(screen.getByTestId("sell-evidence-chart")).toBeInTheDocument();
    // #1225 핵심: iframe 완전 제거
    expect(document.querySelectorAll("iframe").length).toBe(0);
  });

  it("shows one-line empty state when a chart has no data", async () => {
    setupFetchAPI({
      "/api/evidence/data/regime": { spy: [], vix: [], regime: null, count: 0 },
    });
    await renderPage();
    expect(screen.getByText(E.NO_DATA)).toBeInTheDocument();
    expect(screen.queryByTestId("regime-chart")).not.toBeInTheDocument();
    // 나머지 카드는 그대로 렌더
    expect(screen.getByTestId("portfolio-treemap")).toBeInTheDocument();
  });

  it("distinguishes zero violations (정상) from missing data", async () => {
    setupFetchAPI({
      "/api/evidence/data/sell_evidence": { violations: [], count: 0 },
    });
    await renderPage();
    expect(screen.getByText(E.NO_VIOLATIONS)).toBeInTheDocument();
    expect(screen.queryByText(E.NO_DATA)).not.toBeInTheDocument();
  });

  it("shows NO_DATA (not NO_VIOLATIONS) when sell endpoint fails but others succeed", async () => {
    setupFetchAPI({
      "/api/evidence/data/sell_evidence": new Error("boom"),
    });
    await renderPage();
    expect(screen.getByText(E.NO_DATA)).toBeInTheDocument();
    expect(screen.queryByText(E.NO_VIOLATIONS)).not.toBeInTheDocument();
  });

  it("shows LOAD_FAILED only when every endpoint fails", async () => {
    const boom = new Error("down");
    setupFetchAPI({
      "/api/evidence/data/regime": boom,
      "/api/evidence/data/portfolio_heatmap": boom,
      "/api/evidence/data/signal_performance": boom,
      "/api/evidence/data/fear_greed": boom,
      "/api/evidence/data/sell_evidence": boom,
    });
    await renderPage();
    expect(screen.getByText(E.LOAD_FAILED)).toBeInTheDocument();
    expect(screen.queryByText(E.TITLE_REGIME)).not.toBeInTheDocument();
  });
});
