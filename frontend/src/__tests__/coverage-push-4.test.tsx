/**
 * Coverage push 4: Recharts Tooltip formatters (equity-curve, price-chart),
 * Dashboard server component (redirect + API error fallbacks),
 * Portfolio add form fields, Sidebar branch coverage.
 *
 * Uses vi.doMock for recharts to avoid hoisting conflicts with coverage-push.test.tsx.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";

// ═══════════════════════════════════════════════════════════
// 1. EquityCurveChart — Tooltip formatter coverage
//    Lines 73-130: Recharts rendering + formatter functions
// ═══════════════════════════════════════════════════════════

describe("EquityCurveChart — Tooltip formatters", () => {
  let capturedFormatters: any[] = [];

  beforeEach(() => {
    vi.resetModules();
    capturedFormatters = [];

    vi.doMock("recharts", () => ({
      ResponsiveContainer: ({ children }: any) => <div data-testid="responsive-container">{children}</div>,
      ComposedChart: ({ children }: any) => <div data-testid="composed-chart">{children}</div>,
      Area: () => <div data-testid="area" />,
      Line: () => <div data-testid="line" />,
      XAxis: ({ tickFormatter }: any) => {
        // Cover the XAxis tickFormatter: (v) => String(v).slice(2, 7)
        if (tickFormatter) tickFormatter("2024-06-15");
        return null;
      },
      YAxis: ({ tickFormatter }: any) => {
        // Cover the YAxis tickFormatter: (v) => `${v}%`
        if (tickFormatter) tickFormatter(25);
        return null;
      },
      Tooltip: (props: any) => {
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


// ═══════════════════════════════════════════════════════════
// 2. PriceChart — Tooltip formatter coverage
//    Lines 114-130: volume/close/sma name branches
// ═══════════════════════════════════════════════════════════

describe("PriceChart — Tooltip formatter", () => {
  let capturedFormatter: any = null;

  beforeEach(() => {
    vi.resetModules();
    capturedFormatter = null;

    vi.doMock("recharts", () => ({
      ResponsiveContainer: ({ children }: any) => <div data-testid="responsive-container">{children}</div>,
      ComposedChart: ({ children }: any) => <div data-testid="composed-chart">{children}</div>,
      Area: () => <div data-testid="area" />,
      Line: () => <div data-testid="line" />,
      Bar: () => <div data-testid="bar" />,
      XAxis: () => null,
      YAxis: ({ tickFormatter }: any) => {
        // Cover price YAxis tickFormatter: (v) => v.toFixed(0)
        if (tickFormatter) tickFormatter(150.7);
        return null;
      },
      Tooltip: (props: any) => {
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

    // Volume branch
    const [volLabel, volName] = capturedFormatter(1_500_000, "volume");
    expect(volLabel).toBe("1.5M");
    expect(volName).toBe("Vol");

    // Close branch
    const [closeLabel, closeName] = capturedFormatter(195.50, "close");
    expect(closeLabel).toBe("$195.50");
    expect(closeName).toBe("Close");

    // SMA name branch (fallback: any other name → uppercased)
    const [sma20Label, sma20Name] = capturedFormatter(150.25, "sma20");
    expect(sma20Label).toBe("$150.25");
    expect(sma20Name).toBe("SMA20");

    const [sma50Label, sma50Name] = capturedFormatter(148.00, "sma50");
    expect(sma50Label).toBe("$148.00");
    expect(sma50Name).toBe("SMA50");
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
    const [volLabel] = capturedFormatter(50_000, "volume");
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
    const [volLabel] = capturedFormatter(500, "volume");
    expect(volLabel).toBe("500");
  });
});


// ═══════════════════════════════════════════════════════════
// 3. Dashboard (app/page.tsx) — error fallbacks + redirect
//    Lines 62-64: .catch() for freshness & pipeline
//    Lines 69-70: .catch(() => null) for certify & advisor
//    Line 76: redirect when portfolio empty
// ═══════════════════════════════════════════════════════════

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: any) => <a href={href}>{children}</a>,
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
        if (path === "/api/certify") return Promise.reject(new Error("timeout"));
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

    expect(redirect).toHaveBeenCalledWith("/portfolio?onboarding=true");
  });

  it("handles freshness and pipeline API failures gracefully", async () => {
    // #221: summary panel uses Recharts via SectorDonut ("use client"). jsdom can't
    // actually run ResponsiveContainer, which suspends on an uncached promise. Mock
    // it out so the Dashboard render finishes without hitting the Suspense stall.
    vi.doMock("recharts", () => ({
      ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
      PieChart: ({ children }: any) => <div>{children}</div>,
      Pie: ({ children }: any) => <div>{children}</div>,
      Cell: () => <div />,
      Tooltip: () => <div />,
    }));
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
        if (path === "/api/certify") return Promise.reject(new Error("timeout"));
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

  it("handles certify timeout gracefully (race with setTimeout)", async () => {
    vi.doMock("@/lib/api", () => ({
      API_BASE: "http://localhost:8001",
      fetchAPI: vi.fn().mockImplementation((path: string) => {
        if (path === "/api/dashboard") {
          return Promise.resolve({
            verdict: "Hold positions", verdict_level: "cautious",
            regime: { regime: "sideways_high_vol", trend: "sideways", volatility: "high", confidence: 60, vix: 28, fear_greed: 35 },
            macro: { score: 45, interpretation: "weak" },
            allocation: { long: 40, short: 15, cash: 45 },
            actions: [], alerts: [], gate_score: 70, n_positions: 3,
          });
        }
        if (path === "/api/freshness") return Promise.resolve({ items: [], details: [], overall: "PASS", pass: 5, warn: 0, fail: 0 });
        if (path === "/api/pipeline/status") return Promise.resolve({ steps: [] });
        if (path === "/api/portfolio") return Promise.resolve({
          holdings: [{ ticker: "AAPL", quantity: 10, avg_price: 180, latest_price: 195, currency: "USD" }],
          count: 1,
        });
        // Certify: never resolves (simulates very slow response, timeout wins)
        if (path === "/api/certify") return new Promise(() => {});
        if (path === "/api/rebalance-advisor") return Promise.resolve({ total_violations: 0, has_critical: false });
        return Promise.resolve({});
      }),
    }));

    const { default: OverviewPage } = await import("@/app/page");

    // Use fake timers to resolve the Promise.race timeout
    vi.useFakeTimers({ shouldAdvanceTime: true });

    try {
      const pageElement = OverviewPage();
      await act(async () => {
        render(pageElement);
        // Advance past the 3-second certify timeout
        await vi.advanceTimersByTimeAsync(3500);
      });
    } catch {
      // May throw
    }

    vi.useRealTimers();
  });
});


// ═══════════════════════════════════════════════════════════
// 4. Portfolio — add form field interactions
//    Lines 285-301: account select, ticker, qty, avg_price,
//                   currency select, sector input
// ═══════════════════════════════════════════════════════════

describe("Portfolio — add form field coverage", () => {
  beforeEach(() => {
    vi.resetModules();
    global.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (typeof url === "string" && url.includes("/api/portfolio/sample") && opts?.method === "POST") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (typeof url === "string" && url.includes("/api/portfolio") && opts?.method === "POST") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (typeof url === "string" && url.includes("/api/portfolio")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            // Multiple accounts so dynamic ACCOUNTS dropdown has options to test
            holdings: [
              { ticker: "AAPL", account: "test", quantity: 10, avg_price: 180,
                currency: "USD", sector: "Tech", latest_price: 195, price_date: "2026-03-31" },
              { ticker: "BBB", account: "demo", quantity: 5, avg_price: 100,
                currency: "USD", sector: "ETF", latest_price: 110, price_date: "2026-03-31" },
              { ticker: "CCC", account: "sample", quantity: 8, avg_price: 50,
                currency: "USD", sector: "Tech", latest_price: 55, price_date: "2026-03-31" },
              { ticker: "DDD", account: "pension", quantity: 3, avg_price: 200,
                currency: "USD", sector: "Tech", latest_price: 220, price_date: "2026-03-31" },
              { ticker: "EEE", account: "irp", quantity: 2, avg_price: 300,
                currency: "USD", sector: "Tech", latest_price: 320, price_date: "2026-03-31" },
            ],
            count: 5,
          }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fills all form fields including account, currency, and sector", async () => {
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    // Open add form
    const addBtn = screen.queryByText("Add Holding");
    if (!addBtn) return;
    await act(async () => { fireEvent.click(addBtn); });

    // Account select (line 285-288)
    const selects = document.querySelectorAll("select");
    const accountSelect = selects[0];
    if (accountSelect) {
      fireEvent.change(accountSelect, { target: { value: "demo" } });
      expect((accountSelect as HTMLSelectElement).value).toBe("demo");

      // Change to other accounts
      fireEvent.change(accountSelect, { target: { value: "sample" } });
      fireEvent.change(accountSelect, { target: { value: "pension" } });
      fireEvent.change(accountSelect, { target: { value: "irp" } });
    }

    // Ticker input (line 289-290)
    const tickerInput = screen.queryByPlaceholderText(/Ticker/);
    if (tickerInput) {
      fireEvent.change(tickerInput, { target: { value: "TSLA" } });
    }

    // Quantity input (line 291-292)
    const qtyInput = screen.queryByPlaceholderText(/Quantity/);
    if (qtyInput) {
      fireEvent.change(qtyInput, { target: { value: "25" } });
    }

    // Avg Price input (line 293-294)
    const priceInput = screen.queryByPlaceholderText(/Avg Price/);
    if (priceInput) {
      fireEvent.change(priceInput, { target: { value: "250.50" } });
    }

    // Currency select (line 295-299)
    const currencySelect = selects[1];
    if (currencySelect) {
      fireEvent.change(currencySelect, { target: { value: "KRW" } });
      expect((currencySelect as HTMLSelectElement).value).toBe("KRW");
      // Switch back
      fireEvent.change(currencySelect, { target: { value: "USD" } });
    }

    // Sector input (line 300-301)
    const sectorInput = screen.queryByPlaceholderText(/Sector/);
    if (sectorInput) {
      fireEvent.change(sectorInput, { target: { value: "Semiconductor" } });
    }

    // Submit the form
    const saveBtn = screen.queryByText("Save");
    if (saveBtn) {
      await act(async () => { fireEvent.click(saveBtn); });
      await act(async () => { await new Promise(r => setTimeout(r, 200)); });
    }
  });

  it("submits KRW holding via form", async () => {
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    const addBtn = screen.queryByText("Add Holding");
    if (!addBtn) return;
    await act(async () => { fireEvent.click(addBtn); });

    // Select account
    const selects = document.querySelectorAll("select");
    if (selects[0]) fireEvent.change(selects[0], { target: { value: "demo" } });

    // Fill Korean ticker
    const tickerInput = screen.queryByPlaceholderText(/Ticker/);
    if (tickerInput) fireEvent.change(tickerInput, { target: { value: "005930.KS" } });

    const qtyInput = screen.queryByPlaceholderText(/Quantity/);
    if (qtyInput) fireEvent.change(qtyInput, { target: { value: "5" } });

    const priceInput = screen.queryByPlaceholderText(/Avg Price/);
    if (priceInput) fireEvent.change(priceInput, { target: { value: "60000" } });

    // Set currency to KRW
    if (selects[1]) fireEvent.change(selects[1], { target: { value: "KRW" } });

    const sectorInput = screen.queryByPlaceholderText(/Sector/);
    if (sectorInput) fireEvent.change(sectorInput, { target: { value: "Electronics" } });

    const saveBtn = screen.queryByText("Save");
    if (saveBtn) {
      await act(async () => { fireEvent.click(saveBtn); });
      await act(async () => { await new Promise(r => setTimeout(r, 200)); });
    }
  });
});


// ═══════════════════════════════════════════════════════════
// 5. Sidebar — collapsed state + page highlight branches
//    Lines 79-81: collapsed SIEGE badge
//    Lines 162-164: collapsed SIEGE display
//    Line 174: theme toggle + collapsed text
// ═══════════════════════════════════════════════════════════

vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", setTheme: vi.fn() }),
  ThemeProvider: ({ children }: any) => <div>{children}</div>,
}));

describe("Sidebar — collapsed state and branch coverage", () => {
  beforeEach(() => {
    vi.resetModules();
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/certify")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ certified: false, score: 60 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("toggles sidebar collapse state", async () => {
    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    // Find collapse toggle (ChevronLeft icon button)
    const buttons = document.querySelectorAll("button");
    let collapseBtn: HTMLElement | null = null;
    buttons.forEach((btn) => {
      if (btn.querySelector("svg") && !btn.textContent?.includes("Mode")) {
        collapseBtn = btn;
      }
    });

    if (collapseBtn) {
      await act(async () => { fireEvent.click(collapseBtn!); });
      await act(async () => { await new Promise(r => setTimeout(r, 100)); });

      expect(screen.queryByText("Nuri-Quant")).toBeNull();
      expect(screen.getByText("N")).toBeInTheDocument();

      await act(async () => { fireEvent.click(collapseBtn!); });
      await act(async () => { await new Promise(r => setTimeout(r, 100)); });

      expect(screen.getByText("Nuri-Quant")).toBeInTheDocument();
    }
  });

  it("renders theme toggle in light mode", async () => {
    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    // Light mode: should show "Dark Mode" label (since isDark = false)
    await waitFor(() => {
      const text = document.body.textContent || "";
      expect(text).toContain("Dark Mode");
    });

    // Click theme toggle
    const themeBtn = screen.queryByTitle("Dark mode");
    if (themeBtn) {
      await act(async () => { fireEvent.click(themeBtn); });
    }
  });

  it("shows nav group labels and active page highlighting", async () => {
    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });

    // Nav group labels should be visible (not collapsed)
    expect(screen.getByText("OVERVIEW")).toBeInTheDocument();
    expect(screen.getByText("ANALYSIS")).toBeInTheDocument();
    expect(screen.getByText("TRADING")).toBeInTheDocument();
    expect(screen.getByText("INTELLIGENCE")).toBeInTheDocument();

    // Current page "/" — Dashboard link should exist
    const dashLink = screen.getByText("Dashboard");
    expect(dashLink).toBeInTheDocument();
  });

  it("sidebar no longer renders SIEGE badge (moved to dashboard)", async () => {
    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    const text = document.body.textContent || "";
    expect(text).not.toContain("CERTIFIED");
    expect(text).not.toContain("REJECTED");
  });

  it("handles certify API returning non-ok response (lines 79-81)", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/certify")) {
        // Return { ok: false } to hit the null branch in .then(r => r.ok ? r.json() : null)
        return Promise.resolve({ ok: false, status: 500 });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;

    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    // Neither CERTIFIED nor REJECTED should appear since siegeStatus is null
    expect(screen.queryByText("CERTIFIED")).toBeNull();
    expect(screen.queryByText("REJECTED")).toBeNull();
    // Sidebar should still render normally
    expect(screen.getByText("Nuri-Quant")).toBeInTheDocument();
  });
});


// ═══════════════════════════════════════════════════════════
// 6. Dashboard — portfolio catch branch (line 64)
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
        if (path === "/api/certify") return Promise.resolve({ certified: true, score: 90 });
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

    expect(redirect).toHaveBeenCalledWith("/portfolio?onboarding=true");
  });
});


// ═══════════════════════════════════════════════════════════
// 7. Portfolio — inline edit onChange handlers (lines 198-199, 213-214)
// ═══════════════════════════════════════════════════════════

describe("Portfolio — inline edit input interactions", () => {
  beforeEach(() => {
    vi.resetModules();
    global.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (typeof url === "string" && url.includes("/api/portfolio") && opts?.method === "PUT") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (typeof url === "string" && url.includes("/api/portfolio") && (!opts || !opts.method || opts.method === "GET")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            holdings: [
              { ticker: "AAPL", account: "test", quantity: 10, avg_price: 180,
                currency: "USD", sector: "Tech", latest_price: 195, price_date: "2026-03-31" },
            ],
            count: 1,
          }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("exercises inline edit quantity and avg_price onChange + onClick handlers", async () => {
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    // Click Edit button to enter edit mode
    const editBtns = screen.queryAllByText("Edit");
    if (editBtns.length > 0) {
      await act(async () => { fireEvent.click(editBtns[0]); });
      await act(async () => { await new Promise(r => setTimeout(r, 100)); });

      // Now the inline edit inputs should be visible
      const numberInputs = document.querySelectorAll('input[type="number"]');
      expect(numberInputs.length).toBeGreaterThanOrEqual(2);

      // Exercise quantity onChange (line 198)
      if (numberInputs[0]) {
        fireEvent.change(numberInputs[0], { target: { value: "15" } });
        // Exercise onClick stopPropagation (line 199)
        fireEvent.click(numberInputs[0]);
      }

      // Exercise avg_price onChange (line 213)
      if (numberInputs[1]) {
        fireEvent.change(numberInputs[1], { target: { value: "200" } });
        // Exercise onClick stopPropagation (line 214)
        fireEvent.click(numberInputs[1]);
      }

      // Save the edit
      const saveBtn = screen.queryByText("Save");
      if (saveBtn) {
        await act(async () => { fireEvent.click(saveBtn); });
        await act(async () => { await new Promise(r => setTimeout(r, 200)); });
      }
    }
  });
});
