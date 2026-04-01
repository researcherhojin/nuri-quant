import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Mock next/navigation — redirect throws to interrupt rendering
const mockRedirect = vi.fn().mockImplementation((path: string) => {
  throw new Error(`REDIRECT:${path}`);
});
vi.mock("next/navigation", () => ({
  redirect: (path: string) => mockRedirect(path),
}));

// Mock fetchAPI
const mockFetchAPI = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

// Mock FreshnessBar
vi.mock("@/components/ui/freshness-bar", () => ({
  FreshnessBar: ({ items }: { items: unknown[] }) => (
    <div data-testid="freshness-bar">{items.length} items</div>
  ),
}));

const mockDashboardData = {
  verdict: "Cautious stance recommended. Hold existing positions.",
  verdict_level: "cautious",
  regime: {
    regime: "bull_low_vol",
    trend: "bull",
    volatility: "low",
    confidence: 78,
    vix: 18.5,
    fear_greed: 55,
  },
  macro: { score: 65, interpretation: "Moderately positive" },
  allocation: { long: 50, short: 10, cash: 40 },
  actions: [
    { action: "BUY", ticker: "NVDA", confidence: 72, agreement: 80, reason: "Strong multi-factor score" },
    { action: "SELL", ticker: "INTC", confidence: 65, agreement: 70, reason: "Negative momentum" },
  ],
  alerts: [
    { level: "warning", message: "VIX approaching 25 threshold" },
    { level: "critical", message: "TSLA trailing stop triggered" },
  ],
  gate_score: 85,
  n_positions: 5,
};

const mockFreshness = {
  items: [
    { key: "prices", label: "Prices", status: "PASS", age_hours: 2, message: "OK" },
    { key: "vix", label: "VIX", status: "WARN", age_hours: 30, message: "Stale" },
  ],
  overall: "WARN",
  pass: 1,
  warn: 1,
  fail: 0,
};

const mockPipelineStatus = {
  steps: [
    { step: "collect", label: "Collect", status: "done", record_count: 25000, last_updated: "2026-03-31" },
    { step: "validate", label: "Validate", status: "done", record_count: 150, last_updated: "2026-03-31" },
  ],
};

const mockPortfolio = {
  count: 10,
  holdings: [
    { ticker: "TSLA", quantity: 33, avg_price: 343, latest_price: 250, currency: "USD" },
    { ticker: "005930.KS", quantity: 4, avg_price: 200500, latest_price: 210000, currency: "KRW" },
  ],
};

const mockSiege = {
  certified: true,
  score: 90,
  passed: 9,
  total: 10,
  conditions: [],
};

const mockAdvisor = {
  has_critical: false,
  total_violations: 0,
  total_recovery_usd: 0,
};

describe("DashboardPage (OverviewPage)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockFetchAPI.mockReset();
    mockRedirect.mockClear();
    // Re-set the redirect mock (restoreAllMocks clears it)
    mockRedirect.mockImplementation((path: string) => {
      throw new Error(`REDIRECT:${path}`);
    });
  });

  function setupMocks(overrides: Record<string, unknown> = {}) {
    mockFetchAPI.mockImplementation((path: string) => {
      if (path.includes("/api/dashboard")) return Promise.resolve(overrides.dashboard ?? mockDashboardData);
      if (path.includes("/api/freshness")) return Promise.resolve(overrides.freshness ?? mockFreshness);
      if (path.includes("/api/pipeline/status")) return Promise.resolve(overrides.pipeline ?? mockPipelineStatus);
      if (path.includes("/api/portfolio")) return Promise.resolve(overrides.portfolio ?? mockPortfolio);
      if (path.includes("/api/certify")) return Promise.resolve(overrides.siege ?? mockSiege);
      if (path.includes("/api/rebalance-advisor")) return Promise.resolve(overrides.advisor ?? mockAdvisor);
      return Promise.resolve({});
    });
  }

  it("renders top metric cards", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("Portfolio")).toBeInTheDocument();
      expect(screen.getByText("SIEGE")).toBeInTheDocument();
      expect(screen.getByText("Violations")).toBeInTheDocument();
      // "Market" appears in both the metric card and the Quick Stats section
      expect(screen.getAllByText("Market").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("renders SIEGE certified status", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("CERTIFIED")).toBeInTheDocument();
      expect(screen.getByText("90% (9/10)")).toBeInTheDocument();
    });
  });

  it("renders SIEGE rejected status", async () => {
    setupMocks({
      siege: {
        certified: false,
        score: 40,
        passed: 4,
        total: 10,
        conditions: [
          { passed: false, severity: "error", description: "Signal test failed", detail: "Win rate too low" },
        ],
      },
    });
    const Page = await import("@/app/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("REJECTED")).toBeInTheDocument();
      expect(screen.getByText("40% (4/10)")).toBeInTheDocument();
    });
  });

  it("renders verdict with correct level", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("CAUTIOUS")).toBeInTheDocument();
      expect(screen.getByText(/Cautious stance recommended/)).toBeInTheDocument();
    });
  });

  it("renders allocation bar", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("Cash 40%")).toBeInTheDocument();
    });
  });

  it("renders action items", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("Actions (2)")).toBeInTheDocument();
      expect(screen.getByText("NVDA")).toBeInTheDocument();
      expect(screen.getByText("INTC")).toBeInTheDocument();
    });
  });

  it("shows no actions message when empty", async () => {
    setupMocks({ dashboard: { ...mockDashboardData, actions: [] } });
    const Page = await import("@/app/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("Actions (0)")).toBeInTheDocument();
      expect(screen.getByText(/No actions/)).toBeInTheDocument();
    });
  });

  it("renders alerts", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("Alerts")).toBeInTheDocument();
      expect(screen.getByText("VIX approaching 25 threshold")).toBeInTheDocument();
      expect(screen.getByText("TSLA trailing stop triggered")).toBeInTheDocument();
    });
  });

  it("renders market regime info", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      // BULL appears in the Market metric card and in the Quick Stats section
      expect(screen.getAllByText("BULL").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("65/100")).toBeInTheDocument();
    });
  });

  it("renders freshness bar", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      expect(screen.getByText("Freshness")).toBeInTheDocument();
      expect(screen.getByTestId("freshness-bar")).toBeInTheDocument();
    });
  });

  it("renders pipeline status row", async () => {
    setupMocks();
    const Page = await import("@/app/page");
    await act(async () => {
      render(<Page.default />);
    });

    await waitFor(() => {
      // Pipeline status shows step labels
      expect(screen.getAllByText("Collect").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("Validate").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("renders loading skeleton initially when data is pending", async () => {
    mockFetchAPI.mockReturnValue(new Promise(() => {}));
    const Page = await import("@/app/page");
    const { container } = render(<Page.default />);

    // Suspense fallback shows animate-pulse skeletons
    const pulseElements = container.querySelectorAll(".animate-pulse");
    expect(pulseElements.length).toBeGreaterThan(0);
  });

});
