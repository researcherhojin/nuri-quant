/**
 * Dashboard (app/page.tsx) — error fallbacks + redirect + portfolio API failure branches.
 * Lines 62-64: .catch() for freshness & pipeline.
 * Lines 69-70: .catch(() => null) for advisor.
 * Line 76: redirect when portfolio empty.
 * Line 64: portfolio .catch(() => null) → empty holdings → redirect.
 *
 * Split from coverage-push-4.test.tsx (lines 218-380 + 653-703).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, act, waitFor } from "@testing-library/react";
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

describe("Dashboard — error fallbacks and redirect", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("redirects to onboarding when portfolio is empty", async () => {
    const { redirect } = await import("next/navigation");

    vi.doMock("@/lib/api", () => ({
      API_BASE: "http://localhost:8001",
      fetchAPI: vi.fn().mockImplementation((path: string) => {
        if (path === "/api/dashboard") {
          return Promise.resolve({
            verdict: "HOLD", verdict_level: "neutral",
            regime: { regime: "bull_low_vol", trend: "bull", volatility: "low", confidence: 80, vix: 15, fear_greed: 55 },
            macro: { score: 60, interpretation: "neutral" },
            allocation: { long: 60, short: 10, cash: 30 },
            actions: [], alerts: [], gate_score: 80, n_positions: 0,
          });
        }
        if (path === "/api/freshness") return Promise.reject(new Error("fail"));
        if (path === "/api/pipeline/status") return Promise.reject(new Error("fail"));
        if (path === "/api/portfolio") return Promise.resolve({ holdings: [], count: 0 });
        if (path === "/api/rebalance-advisor") return Promise.reject(new Error("fail"));
        return Promise.resolve({});
      }),
    }));

    const { default: OverviewPage } = await import("@/app/page");

    // The page is a server component returning Suspense > Dashboard
    // Dashboard is async, so we await the component
    try {
      const pageElement = OverviewPage();
      // Render the Suspense wrapper — the async Dashboard inside will throw redirect
      await act(async () => { render(pageElement); });
    } catch {
      // redirect() throws in Next.js test context
    }

    expect(redirect).toHaveBeenCalledWith("/explore");
  });

  it("handles freshness and pipeline API failures gracefully", async () => {
    // #1210: 도넛 폐지 — recharts doMock 불필요 (대시보드 트리에 소비자 없음).
    vi.doMock("@/lib/api", () => ({
      API_BASE: "http://localhost:8001",
      fetchAPI: vi.fn().mockImplementation((path: string) => {
        if (path === "/api/dashboard") {
          return Promise.resolve({
            verdict: "Aggressive allocation", verdict_level: "aggressive",
            regime: { regime: "bull_low_vol", trend: "bull", volatility: "low", confidence: 85, vix: 14, fear_greed: 65 },
            macro: { score: 72, interpretation: "positive" },
            allocation: { long: 70, short: 5, cash: 25 },
            actions: [{ action: "BUY", ticker: "NVDA", confidence: 78, agreement: 80, reason: "Strong momentum" }],
            alerts: [{ level: "warning", message: "VIX rising" }],
            gate_score: 90, n_positions: 5,
          });
        }
        // These catch() fallbacks at lines 62-64
        if (path === "/api/freshness") return Promise.reject(new Error("503 service unavailable"));
        if (path === "/api/pipeline/status") return Promise.reject(new Error("503 service unavailable"));
        // Portfolio with holdings (no redirect)
        if (path === "/api/portfolio") return Promise.resolve({
          holdings: [
            { ticker: "NVDA", quantity: 10, avg_price: 150, latest_price: 195, currency: "USD" },
            { ticker: "005930.KS", quantity: 5, avg_price: 60000, latest_price: 65000, currency: "KRW" },
          ],
          count: 2,
        });
        // Lines 69-70: catch(() => null)
        if (path === "/api/rebalance-advisor") return Promise.reject(new Error("fail"));
        return Promise.resolve({});
      }),
    }));

    const { default: OverviewPage } = await import("@/app/page");
    try {
      const pageElement = OverviewPage();
      await act(async () => { render(pageElement); });
    } catch {
      // May throw if redirect is called, but we expect no redirect here
    }

    // Dashboard should render despite API failures
    await waitFor(() => {
      // Check that some dashboard content is rendered
      const text = document.body.textContent || "";
      expect(text).toContain("NVDA");
    }, { timeout: 3000 });
  });
});


// ═══════════════════════════════════════════════════════════
// Dashboard — portfolio catch branch (line 64)
// ═══════════════════════════════════════════════════════════

describe("Dashboard — portfolio API failure (line 64)", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("handles portfolio API rejection (catch(() => null))", async () => {
    const { redirect } = await import("next/navigation");

    vi.doMock("@/lib/api", () => ({
      API_BASE: "http://localhost:8001",
      fetchAPI: vi.fn().mockImplementation((path: string) => {
        if (path === "/api/dashboard") {
          return Promise.resolve({
            verdict: "HOLD", verdict_level: "neutral",
            regime: { regime: "bull_low_vol", trend: "bull", volatility: "low", confidence: 80, vix: 15, fear_greed: 55 },
            macro: { score: 60, interpretation: "neutral" },
            allocation: { long: 60, short: 10, cash: 30 },
            actions: [], alerts: [], gate_score: 80, n_positions: 0,
          });
        }
        if (path === "/api/freshness") return Promise.resolve({ items: [], overall: "PASS" });
        if (path === "/api/pipeline/status") return Promise.resolve({ steps: [] });
        // Portfolio API FAILS — triggers .catch(() => null) on line 64
        if (path === "/api/portfolio") return Promise.reject(new Error("portfolio API down"));
        if (path === "/api/rebalance-advisor") return Promise.resolve(null);
        return Promise.resolve({});
      }),
    }));

    // When portfolio is null (from catch), holdingCount = portfolio?.count ?? ... = 0
    // So redirect should be called
    try {
      const { default: OverviewPage } = await import("@/app/page");
      const pageElement = OverviewPage();
      await act(async () => { render(pageElement); });
    } catch {
      // redirect throws
    }

    expect(redirect).toHaveBeenCalledWith("/explore");
  });
});
