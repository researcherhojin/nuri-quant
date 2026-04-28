import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, act } from "@testing-library/react";

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockScan = {
  results: [
    { ticker: "NVDA", price: 168.5, change_1d: 3.2, change_5d: 8.1, volume_ratio: 2.5, rsi: 35.0, signal: "breakout", score: 85 },
    { ticker: "AMD", price: 120.0, change_1d: -1.5, change_5d: 2.3, volume_ratio: 1.8, rsi: 45.0, signal: "momentum", score: 72 },
    { ticker: "TSLA", price: 250.0, change_1d: 5.0, change_5d: -3.2, volume_ratio: 3.1, rsi: 28.0, signal: "bounce", score: 68 },
  ],
  count: 3,
};

const mockSwing = {
  entries: [
    {
      ticker: "NVDA", price: 168.5, scan_signal: "breakout", scan_score: 85,
      agent_action: "BUY", agent_confidence: 72, approved: true, reason: "Strong consensus",
    },
    {
      ticker: "AMD", price: 120.0, scan_signal: "momentum", scan_score: 72,
      agent_action: "HOLD", agent_confidence: 45, approved: false, reason: "Confidence below threshold",
    },
    {
      ticker: "TSLA", price: 250.0, scan_signal: "bounce", scan_score: 68,
      agent_action: "SELL", agent_confidence: 65, approved: false, reason: "Agent verdict SELL",
    },
  ],
  approved: 1,
  rejected: 2,
};

let mockFetchAPI: Mock;

vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

function setupFetchAPI(overrides: { scan?: unknown; swing?: unknown } = {}) {
  mockFetchAPI = vi.fn().mockImplementation((path: string) => {
    if (path.includes("/api/scan")) {
      return Promise.resolve(overrides.scan ?? mockScan);
    }
    if (path.includes("/api/swing/entries")) {
      return Promise.resolve(overrides.swing ?? mockSwing);
    }
    return Promise.resolve({});
  });
}

describe("ScanPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setupFetchAPI();
  });

  it("renders the page heading", async () => {
    const { default: ScanPage } = await import("@/app/scan/page");
    await act(async () => {
      render(<ScanPage />);
    });

    expect(screen.getByText("Market Scanner")).toBeInTheDocument();
  });

  it("renders scan signal count", async () => {
    const { default: ScanPage } = await import("@/app/scan/page");
    await act(async () => {
      render(<ScanPage />);
    });

    expect(screen.getByText("Market Scanner — 3 signals")).toBeInTheDocument();
  });

  it("renders swing entry summary with approved/rejected counts", async () => {
    const { default: ScanPage } = await import("@/app/scan/page");
    await act(async () => {
      render(<ScanPage />);
    });

    expect(screen.getByText(/1 approved/)).toBeInTheDocument();
    expect(screen.getByText(/, 2 rejected/)).toBeInTheDocument();
  });

  it("renders rejected swing entries with reasons", async () => {
    const { default: ScanPage } = await import("@/app/scan/page");
    await act(async () => {
      render(<ScanPage />);
    });

    // Rejected details section
    expect(screen.getByText("Rejected (2)")).toBeInTheDocument();
    expect(screen.getByText("AMD: Confidence below threshold")).toBeInTheDocument();
    expect(screen.getByText("TSLA: Agent verdict SELL")).toBeInTheDocument();
  });

  it("calls fetchAPI with correct paths", async () => {
    const { default: ScanPage } = await import("@/app/scan/page");
    await act(async () => {
      render(<ScanPage />);
    });

    expect(mockFetchAPI).toHaveBeenCalledWith("/api/scan?market=us&top=15");
    expect(mockFetchAPI).toHaveBeenCalledWith("/api/swing/entries");
  });

  it("shows empty state when no approved swing entries", async () => {
    setupFetchAPI({
      swing: {
        entries: [
          { ticker: "AMD", price: 120, scan_signal: "momentum", scan_score: 72, agent_action: "HOLD", agent_confidence: 45, approved: false, reason: "Low conf" },
        ],
        approved: 0,
        rejected: 1,
      },
    });

    const { default: ScanPage } = await import("@/app/scan/page");
    await act(async () => {
      render(<ScanPage />);
    });

    expect(screen.getByText(/No entries passed agent consensus/)).toBeInTheDocument();
  });

  it("renders with no rejected swing entries (no details section)", async () => {
    setupFetchAPI({
      swing: {
        entries: [
          { ticker: "NVDA", price: 168.5, scan_signal: "breakout", scan_score: 85, agent_action: "BUY", agent_confidence: 72, approved: true, reason: "OK" },
        ],
        approved: 1,
        rejected: 0,
      },
    });

    const { default: ScanPage } = await import("@/app/scan/page");
    await act(async () => {
      render(<ScanPage />);
    });

    expect(screen.getByText(/1 approved/)).toBeInTheDocument();
    expect(screen.queryByText(/Rejected/)).not.toBeInTheDocument();
  });

  it("renders with empty scan results", async () => {
    setupFetchAPI({
      scan: { results: [], count: 0 },
    });

    const { default: ScanPage } = await import("@/app/scan/page");
    await act(async () => {
      render(<ScanPage />);
    });

    expect(screen.getByText("Market Scanner — 0 signals")).toBeInTheDocument();
  });
});
