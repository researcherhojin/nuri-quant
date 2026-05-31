import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// ── next/navigation: ExploreSearch (search.tsx) 가 useRouter() 호출 ──
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));

// ── next/link → 단순 anchor (recharts 미사용 — hoist gotcha 무관) ──
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// ── @/lib/api fetchAPI: 엔드포인트별 응답을 테스트가 주입 ──
const fetchAPIMock = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => fetchAPIMock(...args),
}));

import ExplorePage from "./page";

// 엔드포인트별 응답 라우터. reject 시 page.tsx 의 .catch() 분기를 실행.
function routeFetch(
  byPath: Record<string, unknown | (() => Promise<unknown>)>,
) {
  fetchAPIMock.mockImplementation((path: string) => {
    for (const key of Object.keys(byPath)) {
      if (path.startsWith(key)) {
        const v = byPath[key];
        if (typeof v === "function") return (v as () => Promise<unknown>)();
        return Promise.resolve(v);
      }
    }
    return Promise.resolve(null);
  });
}

beforeEach(() => {
  fetchAPIMock.mockReset();
});

describe("ExplorePage (server component tree)", () => {
  it("renders fully-populated state — exercises all data branches", async () => {
    routeFetch({
      // QuickLinksGrid: 일부 ticker 만 가격 → hasAnyMissing TRUE,
      // KS/KQ suffix (isKr TRUE) + delta 양수(formatDelta 비-null) 모두 커버
      "/api/tickers/latest-prices": {
        prices: {
          AAPL: { price: 200, prev: 180, date: "2026-01-01" },
          "005930.KS": { price: 70000, prev: 71000, date: "2026-01-01" },
        },
      },
      // MarketContext: trend/vix/fg/macro 전부 채워 모든 조건부 render + bull tColor
      "/api/tickers/market-context": {
        trend: "bull",
        vix: 18.37,
        vix_date: "2026-01-01",
        fear_greed: 55,
        fg_date: "2026-01-01",
        macro_score: 42,
      },
      // RecentSignals: 중복 ticker 포함 → dedupe filter 의 양쪽 분기 + signalKo
      "/api/candidates": {
        candidates: [
          { ticker: "AAPL", direction: "BUY", signal_id: "rsi_oversold", confidence: 0.9 },
          { ticker: "AAPL", direction: "SELL", signal_id: "rsi_overbought", confidence: 0.8 },
          { ticker: "MSFT", direction: "HOLD", signal_id: "", confidence: 0.5 },
        ],
      },
    });

    render(<ExplorePage />);

    // 정적 헤더는 동기 렌더
    expect(screen.getByRole("heading", { name: "Explore" })).toBeInTheDocument();

    // async Server Components 가 resolve 되면 데이터가 표시됨
    await waitFor(() => {
      expect(fetchAPIMock).toHaveBeenCalledWith("/api/tickers/market-context");
      expect(fetchAPIMock).toHaveBeenCalledWith("/api/candidates?days=5");
    });

    // QuickLinksGrid: 두 universe 모두 + 가격 미수집 힌트
    await waitFor(() => {
      expect(
        fetchAPIMock.mock.calls.some(([p]) =>
          String(p).startsWith("/api/tickers/latest-prices?tickers="),
        ),
      ).toBe(true);
    });
  });

  it("renders bear trend tColor branch + macro absent (mInfo null)", async () => {
    routeFetch({
      "/api/tickers/latest-prices": {
        prices: { AAPL: { price: 200, prev: 200, date: "2026-01-01" } },
      },
      // bear + macro_score 0 → hasMacro FALSE → mInfo null 분기
      "/api/tickers/market-context": {
        trend: "bear",
        vix: 32.5,
        vix_date: "2026-01-01",
        fear_greed: 12,
        fg_date: "2026-01-01",
        macro_score: 0,
      },
      "/api/candidates": { candidates: [] },
    });

    render(<ExplorePage />);
    await waitFor(() => {
      expect(fetchAPIMock).toHaveBeenCalledWith("/api/tickers/market-context");
    });
  });

  it("renders neutral trend (amber tColor) + no-macro, vix/fg null", async () => {
    routeFetch({
      "/api/tickers/latest-prices": {
        prices: { AAPL: { price: 200, prev: 199, date: "2026-01-01" } },
      },
      // trend present but not bull/bear → amber; vix/fg null; macro present
      "/api/tickers/market-context": {
        trend: "neutral",
        vix: null,
        vix_date: null,
        fear_greed: null,
        fg_date: null,
        macro_score: 30,
      },
      "/api/candidates": { candidates: [{ ticker: "MSFT", direction: "WATCH", signal_id: "ma_cross", confidence: 0.6 }] },
    });

    render(<ExplorePage />);
    await waitFor(() => {
      expect(fetchAPIMock).toHaveBeenCalledWith("/api/candidates?days=5");
    });
  });

  it("renders market 'no data' branch when all context fields empty", async () => {
    routeFetch({
      "/api/tickers/latest-prices": { prices: {} },
      // trend null, vix null, fg null, macro 0 → hasAny FALSE → no-data return
      "/api/tickers/market-context": {
        trend: null,
        vix: null,
        vix_date: null,
        fear_greed: null,
        fg_date: null,
        macro_score: 0,
      },
      "/api/candidates": { candidates: [] },
    });

    render(<ExplorePage />);
    await waitFor(() => {
      expect(fetchAPIMock).toHaveBeenCalledWith("/api/tickers/market-context");
    });
  });

  it("handles fetchAPI rejections — exercises every .catch() fallback", async () => {
    routeFetch({
      "/api/tickers/latest-prices": () => Promise.reject(new Error("prices down")),
      "/api/tickers/market-context": () => Promise.reject(new Error("ctx down")),
      "/api/candidates": () => Promise.reject(new Error("candidates down")),
    });

    render(<ExplorePage />);
    await waitFor(() => {
      expect(fetchAPIMock).toHaveBeenCalledWith("/api/tickers/market-context");
      expect(fetchAPIMock).toHaveBeenCalledWith("/api/candidates?days=5");
    });
  });
});
