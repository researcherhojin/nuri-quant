import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockScorecard = {
  scorecard: [
    { signal_id: "rsi_oversold", total_trades: 50, win_rate: 0.62, avg_return: 3.2, profit_factor: 2.1, max_return: 15.0, max_loss: -8.0 },
    { signal_id: "macd_golden", total_trades: 30, win_rate: 0.55, avg_return: 1.8, profit_factor: 1.4, max_return: 10.0, max_loss: -6.0 },
    { signal_id: "bb_bounce", total_trades: 20, win_rate: 0.45, avg_return: -0.5, profit_factor: 0.8, max_return: 7.0, max_loss: -9.0 },
  ],
  date: "2026-03-31",
};

const mockCrossAnalysis = {
  data: [
    { signal_id: "rsi_oversold", regime: "bull_low_vol", profit_factor: 2.5, win_rate: 0.7 },
    { signal_id: "macd_golden", regime: "bull_low_vol", profit_factor: 1.8, win_rate: 0.6 },
    { signal_id: "rsi_oversold", regime: "bear_high_vol", profit_factor: 0.9, win_rate: 0.4 },
    { signal_id: "bb_bounce", regime: "bear_high_vol", profit_factor: 1.2, win_rate: 0.5 },
  ],
};

let mockFetchAPI: any;

vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: any[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

function setupFetchAPI(overrides: { scorecard?: any; crossAnalysis?: any } = {}) {
  mockFetchAPI = vi.fn().mockImplementation((path: string) => {
    if (path.includes("/api/scorecard")) {
      return Promise.resolve(overrides.scorecard ?? mockScorecard);
    }
    if (path.includes("/api/cross-analysis")) {
      return Promise.resolve(overrides.crossAnalysis ?? mockCrossAnalysis);
    }
    return Promise.resolve({});
  });
}

describe("SignalsPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setupFetchAPI();
  });

  it("renders the page heading", async () => {
    const { default: SignalsPage } = await import("@/app/signals/page");
    await act(async () => {
      render(<SignalsPage />);
    });

    expect(screen.getByText("Signals")).toBeInTheDocument();
  });

  it("renders scorecard date label", async () => {
    const { default: SignalsPage } = await import("@/app/signals/page");
    await act(async () => {
      render(<SignalsPage />);
    });

    expect(screen.getByText(/Signal Scorecard — 2026-03-31/)).toBeInTheDocument();
  });

  it("renders cross-analysis regime labels", async () => {
    const { default: SignalsPage } = await import("@/app/signals/page");
    await act(async () => {
      render(<SignalsPage />);
    });

    expect(screen.getByText("bear_high_vol")).toBeInTheDocument();
    expect(screen.getByText("bull_low_vol")).toBeInTheDocument();
  });

  it("renders signal ids in cross-analysis cards", async () => {
    const { default: SignalsPage } = await import("@/app/signals/page");
    await act(async () => {
      render(<SignalsPage />);
    });

    expect(screen.getAllByText("rsi_oversold").length).toBeGreaterThanOrEqual(1);
  });

  it("renders profit factor values in cross-analysis", async () => {
    const { default: SignalsPage } = await import("@/app/signals/page");
    await act(async () => {
      render(<SignalsPage />);
    });

    expect(screen.getByText("PF 2.5")).toBeInTheDocument();
  });

  it("handles scorecard with error field", async () => {
    setupFetchAPI({ scorecard: { error: "No data found", scorecard: [] } });

    const { default: SignalsPage } = await import("@/app/signals/page");
    await act(async () => {
      render(<SignalsPage />);
    });

    expect(screen.getByText("Signals")).toBeInTheDocument();
  });

  it("hides cross-analysis when error returned", async () => {
    setupFetchAPI({ crossAnalysis: { error: "Not available", data: null } });

    const { default: SignalsPage } = await import("@/app/signals/page");
    await act(async () => {
      render(<SignalsPage />);
    });

    // CrossSection returns null on error
    expect(screen.queryByText("Signal × Regime")).not.toBeInTheDocument();
  });

  it("shows cross-analysis heading even with empty data array", async () => {
    setupFetchAPI({ crossAnalysis: { data: [] } });

    const { default: SignalsPage } = await import("@/app/signals/page");
    await act(async () => {
      render(<SignalsPage />);
    });

    expect(screen.getByText("Signal × Regime")).toBeInTheDocument();
  });
});
