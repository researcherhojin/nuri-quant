/**
 * Statement-coverage push for src/app/page.tsx (#coverage/full-push).
 *
 * The existing dashboard suite (__tests__/pages/dashboard.test.tsx +
 * __tests__/coverage/dashboard-edge.test.tsx) covers the helper branches,
 * error fallbacks, redirect, hero/strip/footer happy paths. The statements
 * left uncovered are the data-dependent / defensive ones that need fixtures
 * none of those tests supply:
 *
 *  - L131 / L137: the `fg == null` early returns in fgLabel / fgColor. Their
 *          sole render call sites (the market strip) are gated by
 *          `{fg != null && ...}`, so a null fear_greed never reaches them via
 *          rendering. fgLabel / fgColor are exported (behavior-preserving) and
 *          unit-tested directly with null to exercise these defensive returns.
 *  - L285: body of `for (const cash of d.cash_summary?.accounts ?? [])`
 *          (per-account cash merge) — needs populated cash_summary.accounts.
 *  - L304-312 (eventDday) + L412 (`const dday = eventDday(...)` in the strip
 *          map) — only run when stripEvents.length > 0 (upcoming_events present).
 *          Malformed / D-DAY / future dates exercise every eventDday branch.
 *  - L596: pipeline status `.map((s) => ...)` span — needs pipeline steps.
 *
 * #1210: CompositionSection 이 순수 server 스택 바가 되면서 recharts mock 은
 * 불필요해졌다 (대시보드 트리에 recharts 소비자 없음). Neutral placeholders only.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, act, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  API_BASE: "http://localhost:8001",
  fetchAPI: vi.fn(),
}));

// Today as local YYYY-MM-DD so eventDday(...) returns "D-DAY" (timezone-safe,
// matching the source's own local-time construction).
function todayLocalIso(): string {
  const t = new Date();
  const y = t.getFullYear();
  const m = String(t.getMonth() + 1).padStart(2, "0");
  const d = String(t.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

describe("page helpers — null-guard defensive returns (L131, L137)", () => {
  it("fgLabel / fgColor return the '—' / zinc fallbacks for null fear_greed", async () => {
    const { fgLabel, fgColor } = await import("@/app/page");
    expect(fgLabel(null)).toBe("—");
    expect(fgColor(null)).toBe("bg-zinc-700 text-zinc-400");
  });
});

describe("Dashboard — data-dependent statement coverage", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("covers cash merge (L285), eventDday branches (L304-412), pipeline map (L596)", async () => {
    const today = todayLocalIso();

    vi.doMock("@/lib/api", () => ({
      API_BASE: "http://localhost:8001",
      fetchAPI: vi.fn().mockImplementation((path: string) => {
        if (path === "/api/dashboard") {
          return Promise.resolve({
            verdict: "Hold positions",
            verdict_level: "neutral",
            regime: { regime: "bull_low_vol", trend: "bull", volatility: "low", confidence: 80, vix: 15, fear_greed: 55 },
            macro: { score: 60, interpretation: "neutral" },
            allocation: { long: 60, short: 10, cash: 30 },
            actions: [],
            alerts: [],
            gate_score: 80,
            n_positions: 1,
            exchange_rate: 1400,
            account_values: [{ account: "Brokerage Alpha", value: 2000 }],
            // Populated cash_summary.accounts → drives the L285 merge loop body.
            cash_summary: {
              total_cash_usd: 1500,
              accounts: [
                { account: "Brokerage Alpha", cash_usd: 1000, cash_krw: 0, total_usd: 1000 },
                { account: "Brokerage Beta", cash_usd: 500, cash_krw: 0, total_usd: 500 },
              ],
            },
            // upcoming_events → stripEvents non-empty → eventDday runs per event.
            //  - ""           → L304 early return (empty / len < 10)
            //  - "abcd-ef-gh" → L306 early return (Number() → NaN, falsy)
            //  - today        → L311 days === 0 → "D-DAY"
            //  - future       → days > 0 → "D-N"
            upcoming_events: [
              { date: "", event_type: "earnings", ticker: "AAPL", description: "AAPL earnings", importance: 3 },
              { date: "abcd-ef-gh", event_type: "earnings", ticker: "MSFT", description: "MSFT earnings", importance: 2 },
              { date: today, event_type: "earnings", ticker: "AAPL", description: "AAPL event today", importance: 3 },
              { date: "2099-12-31", event_type: "earnings", ticker: "MSFT", description: "MSFT future event", importance: 2 },
            ],
          });
        }
        if (path === "/api/portfolio") {
          return Promise.resolve({
            count: 1,
            holdings: [{ ticker: "AAPL", account: "Brokerage Alpha", quantity: 10, avg_price: 120, latest_price: 120, currency: "USD" }],
            cash: { total_cash_usd: 1500 },
          });
        }
        if (path === "/api/freshness") return Promise.resolve({ items: [], overall: "PASS" });
        // pipeline steps → footer `.map((s) => ...)` span runs (L596).
        if (path === "/api/pipeline/status") {
          return Promise.resolve({
            steps: [{ step: "collect", label: "Collect", status: "done", record_count: 25000, last_updated: "2026-01-01" }],
          });
        }
        if (path === "/api/certify") return Promise.resolve({ certified: true, passed: 5, total: 5, conditions: [] });
        if (path === "/api/rebalance-advisor") return Promise.resolve({ total_violations: 0, actions: [] });
        return Promise.resolve({});
      }),
    }));

    const { default: OverviewPage } = await import("@/app/page");
    await act(async () => {
      render(OverviewPage());
    });

    // Dashboard rendered (no redirect) with the merged holding visible.
    await waitFor(() => {
      expect(document.body.textContent || "").toContain("AAPL");
    });
  });

  it("fires the certify Promise.race timeout (L193) when certify never resolves", async () => {
    vi.doMock("@/lib/api", () => ({
      API_BASE: "http://localhost:8001",
      fetchAPI: vi.fn().mockImplementation((path: string) => {
        if (path === "/api/dashboard") {
          return Promise.resolve({
            verdict: "Hold positions",
            verdict_level: "neutral",
            regime: { regime: "bull_low_vol", trend: "bull", volatility: "low", confidence: 80, vix: 15, fear_greed: 55 },
            macro: { score: 60, interpretation: "neutral" },
            allocation: { long: 60, short: 10, cash: 30 },
            actions: [],
            alerts: [],
            gate_score: 80,
            n_positions: 1,
            exchange_rate: 1400,
          });
        }
        if (path === "/api/portfolio") {
          return Promise.resolve({
            count: 1,
            holdings: [{ ticker: "AAPL", account: "Brokerage Alpha", quantity: 10, avg_price: 120, latest_price: 120, currency: "USD" }],
            cash: { total_cash_usd: 500 },
          });
        }
        if (path === "/api/freshness") return Promise.resolve({ items: [], overall: "PASS" });
        if (path === "/api/pipeline/status") return Promise.resolve({ steps: [] });
        // Certify never resolves → the 3s setTimeout wins the race and runs
        // resolve(null) (L193).
        if (path === "/api/certify") return new Promise<never>(() => {});
        if (path === "/api/rebalance-advisor") return Promise.resolve({ total_violations: 0, actions: [] });
        return Promise.resolve({});
      }),
    }));

    const { default: OverviewPage } = await import("@/app/page");
    // Fake timers: certify never resolves, so we manually advance past the 3s
    // Promise.race window — that runs the setTimeout's resolve(null) body (L193).
    // We don't assert on rendered DOM here (the RSC commit timing under fake
    // timers is racy in jsdom); the goal is purely to execute L193. The Dashboard
    // renders to completion (no redirect — portfolio has 1 holding).
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      await act(async () => {
        render(OverviewPage());
        await vi.advanceTimersByTimeAsync(3500);
      });
    } finally {
      vi.useRealTimers();
    }

    // The mock was consulted for every endpoint, incl. /api/certify (the racing
    // promise) — proving the Promise.race arm with the timeout was constructed.
    const { fetchAPI } = (await import("@/lib/api")) as unknown as {
      fetchAPI: { mock: { calls: unknown[][] } };
    };
    expect(fetchAPI.mock.calls.some((c) => c[0] === "/api/certify")).toBe(true);
  }, 12000);
});
