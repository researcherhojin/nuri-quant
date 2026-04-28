import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, act } from "@testing-library/react";

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockEvidence = {
  charts: [
    { id: "regime_timeline", description: "Regime Timeline", available: true, date: "2026-03-31" },
    { id: "portfolio_allocation", description: "Portfolio Allocation", available: true, date: "2026-03-31" },
    { id: "signal_performance", description: "Signal Performance", available: false, date: "2026-03-31" },
    { id: "fear_greed_history", description: "Fear & Greed History", available: true, date: "2026-03-31" },
    { id: "sell_evidence", description: "Sell Evidence", available: false, date: "2026-03-31" },
  ],
  date: "2026-03-31",
};

let mockFetchAPI: Mock;

vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

function setupFetchAPI(overrides: { evidence?: unknown } = {}) {
  mockFetchAPI = vi.fn().mockImplementation((_path: string) => {
    return Promise.resolve(overrides.evidence ?? mockEvidence);
  });
}

describe("EvidencePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setupFetchAPI();
  });

  it("renders page heading and description", async () => {
    const { default: EvidencePage } = await import("@/app/evidence/page");
    await act(async () => {
      render(<EvidencePage />);
    });

    expect(screen.getByText("Evidence Charts")).toBeInTheDocument();
    expect(screen.getByText(/투자 결정 근거 시각화/)).toBeInTheDocument();
  });

  it("renders chart descriptions for all charts", async () => {
    const { default: EvidencePage } = await import("@/app/evidence/page");
    await act(async () => {
      render(<EvidencePage />);
    });

    expect(screen.getByText("Regime Timeline")).toBeInTheDocument();
    expect(screen.getByText("Portfolio Allocation")).toBeInTheDocument();
    expect(screen.getByText("Signal Performance")).toBeInTheDocument();
    expect(screen.getByText("Fear & Greed History")).toBeInTheDocument();
    expect(screen.getByText("Sell Evidence")).toBeInTheDocument();
  });

  it("renders READY badge for available charts", async () => {
    const { default: EvidencePage } = await import("@/app/evidence/page");
    await act(async () => {
      render(<EvidencePage />);
    });

    // 3 available charts get READY badge
    const readyBadges = screen.getAllByText("READY");
    expect(readyBadges.length).toBe(3);
  });

  it("renders BLOCKED badge for unavailable charts", async () => {
    const { default: EvidencePage } = await import("@/app/evidence/page");
    await act(async () => {
      render(<EvidencePage />);
    });

    // 2 unavailable charts get BLOCKED badge
    const blockedBadges = screen.getAllByText("BLOCKED");
    expect(blockedBadges.length).toBe(2);
  });

  it("shows make evidence instruction for unavailable charts", async () => {
    const { default: EvidencePage } = await import("@/app/evidence/page");
    await act(async () => {
      render(<EvidencePage />);
    });

    const instructions = screen.getAllByText("make evidence");
    expect(instructions.length).toBe(2);
  });

  it("renders iframe for available charts", async () => {
    const { default: EvidencePage } = await import("@/app/evidence/page");
    await act(async () => {
      render(<EvidencePage />);
    });

    // Each available chart gets an iframe
    const iframes = document.querySelectorAll("iframe");
    expect(iframes.length).toBe(3);

    // Check iframe src contains chart id
    const srcs = Array.from(iframes).map((f) => f.getAttribute("src"));
    expect(srcs).toContain("/api/evidence/regime_timeline");
    expect(srcs).toContain("/api/evidence/portfolio_allocation");
    expect(srcs).toContain("/api/evidence/fear_greed_history");
  });

  it("shows empty state when no charts exist", async () => {
    setupFetchAPI({ evidence: { charts: [], date: "2026-03-31" } });

    const { default: EvidencePage } = await import("@/app/evidence/page");
    await act(async () => {
      render(<EvidencePage />);
    });

    expect(screen.getByText(/증거 차트 없음/)).toBeInTheDocument();
    expect(screen.getByText("make full-scan")).toBeInTheDocument();
  });

  it("handles API failure gracefully", async () => {
    mockFetchAPI = vi.fn().mockRejectedValue(new Error("Network error"));

    const { default: EvidencePage } = await import("@/app/evidence/page");
    await act(async () => {
      render(<EvidencePage />);
    });

    expect(screen.getByText(/증거 차트 로드 실패/)).toBeInTheDocument();
  });

  it("renders chart dates for available charts", async () => {
    const { default: EvidencePage } = await import("@/app/evidence/page");
    await act(async () => {
      render(<EvidencePage />);
    });

    // Available charts show date next to READY badge
    const dates = screen.getAllByText("2026-03-31");
    expect(dates.length).toBe(3);
  });
});
