/**
 * Shared mock data and route interceptors for E2E tests.
 * All API calls to localhost:8001 are intercepted — no backend needed.
 *
 * SECURITY: All ticker/account/price data uses generic placeholders
 * (AAA/BBB/CCC, "test" account, round numbers). No real holdings exposed.
 */
import type { Page } from "@playwright/test";

export const mockDashboard = {
  verdict: "Market environment stable. Hold positions.",
  verdict_level: "hold",
  regime: "bull_low_vol",
  regime_confidence: 0.85,
  macro_score: 72,
  macro_interpretation: "Favorable",
  vix: 15.5,
  fear_greed: 65,
  spy_change: 0.8,
  total_value_usd: 100000,
  actions: {
    buy: [{ ticker: "AAA", confidence: 82, signal: "rsi_oversold" }],
    sell: [{ ticker: "BBB", confidence: 90, reason: "leveraged_etf" }],
    watch: [{ ticker: "CCC", note: "approaching support" }],
  },
  allocation: { cash: 20, equity_us: 60, equity_kr: 20 },
  freshness: { items: [] },
  pipeline_status: { steps: [] },
  exchange_rate: 1380.5,
};

export const mockPipelineStatus = {
  steps: [
    { step: "collect", label: "Collect", description: "23 collectors", record_count: 25000, last_updated: "2026-03-31T10:00:00", status: "done" },
    { step: "validate", label: "Validate", description: "Signal backtest", record_count: 150, last_updated: "2026-03-31T09:00:00", status: "done" },
    { step: "classify", label: "Classify", description: "10-regime", record_count: 30, last_updated: "2026-03-31T08:00:00", status: "idle" },
    { step: "diagnose", label: "Diagnose", description: "10 agents", record_count: 10, last_updated: null, status: "idle" },
    { step: "recommend", label: "Recommend", description: "Candidates", record_count: 5, last_updated: null, status: "idle" },
    { step: "track", label: "Track", description: "Outcomes", record_count: 0, last_updated: null, status: "idle" },
  ],
  pipeline_status: "ready",
};

export const mockTimeline = [
  { event_type: "step_completed", step: "collect", timestamp: "2026-03-31T10:00:00", payload: {} },
  { event_type: "step_completed", step: "validate", timestamp: "2026-03-31T09:00:00", payload: {} },
];

export const mockGates = {
  collect: { ready: true, passed: 3, total: 3, conditions: [{ passed: true, description: "prices fresh", detail: "OK" }] },
  validate: { ready: true, passed: 2, total: 2, conditions: [{ passed: true, description: "signals", detail: "OK" }] },
};

export const mockFreshness = {
  items: [
    { key: "prices", label: "Prices", status: "PASS", age_hours: 2, message: "OK" },
    { key: "macro_vix", label: "VIX", status: "WARN", age_hours: 30, message: "Stale" },
  ],
  overall: "WARN",
  pass: 1, warn: 1, fail: 0,
};

export const mockPortfolio = {
  holdings: [
    { ticker: "AAPL", account: "test", quantity: 10, avg_price: 180, currency: "USD", sector: "Tech", latest_price: 195, price_date: "2026-03-31" },
    { ticker: "TSLA", account: "test", quantity: 5, avg_price: 250, currency: "USD", sector: "SectorA", latest_price: 280, price_date: "2026-03-31" },
  ],
  count: 2,
};

export const mockBacktest = {
  total_return: 45.2,
  annual_return: 18.5,
  sharpe: 1.2,
  max_drawdown: -12.3,
  total_days: 500,
  equity_curve: Array.from({ length: 50 }, (_, i) => ({
    date: `2025-${String(Math.floor(i / 4) + 1).padStart(2, "0")}-01`,
    strategy: i * 0.9,
    spy: i * 0.6,
    drawdown: -Math.random() * 5,
  })),
};

/** Intercept all API calls with mock data. */
export async function mockAllAPIs(page: Page) {
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({ json: mockDashboard })
  );
  await page.route("**/api/pipeline/status", (route) =>
    route.fulfill({ json: mockPipelineStatus })
  );
  await page.route("**/api/pipeline/timeline", (route) =>
    route.fulfill({ json: mockTimeline })
  );
  await page.route("**/api/gate", (route) =>
    route.fulfill({ json: mockGates })
  );
  await page.route("**/api/freshness", (route) =>
    route.fulfill({ json: mockFreshness })
  );
  await page.route("**/api/portfolio", (route) =>
    route.fulfill({ json: mockPortfolio })
  );
  await page.route("**/api/certify", (route) =>
    route.fulfill({ json: { certified: true, score: 90, passed: 9, failed: 1, warnings: 0, total: 10, conditions: [], timestamp: "2026-03-31" } })
  );
  await page.route("**/api/rebalance-advisor", (route) =>
    route.fulfill({ json: { actions: [], total_violations: 0, critical: 0 } })
  );
  await page.route("**/api/backtest", (route) =>
    route.fulfill({ json: mockBacktest })
  );
  await page.route("**/api/strategy/status", (route) =>
    route.fulfill({ json: { regime: "bull_low_vol", allocation: { equity: 80, cash: 20 }, actions: [] } })
  );
  await page.route("**/api/stream", (route) =>
    route.fulfill({ status: 200, body: "data: {}\n\n", headers: { "Content-Type": "text/event-stream" } })
  );
  await page.route("**/api/decisions*", (route) =>
    route.fulfill({
      json: {
        decisions: [
          { id: 1, date: "2026-04-10", ticker: "AAA", action: "BUY", confidence: 75, regime: "bull_low_vol", macro_score: 72, vix: 15, fear_greed: 65, agreement_rate: 0.8, entry_price: 120.0, stop_loss: 111.6, target_1: 144.0, target_2: 168.0, pnl_7d: 5.2, pnl_30d: null, pnl_60d: null, pnl_90d: null, outcome: "pending", reasoning: "Technical + fundamental consensus" },
          { id: 2, date: "2026-04-09", ticker: "BBB", action: "SELL", confidence: 60, regime: "bull_low_vol", macro_score: 72, vix: 15, fear_greed: 65, agreement_rate: 0.6, entry_price: 250.0, stop_loss: null, target_1: null, target_2: null, pnl_7d: -3.1, pnl_30d: -8.5, pnl_60d: null, pnl_90d: null, outcome: "pending", reasoning: "Risk agent veto" },
        ],
        count: 2,
        summary: { total: 2, pending: 2, success: 0, failure: 0, neutral: 0 },
      },
    })
  );
  // Catch-all for other API routes
  await page.route("**/api/**", (route) =>
    route.fulfill({ json: {} })
  );
}
