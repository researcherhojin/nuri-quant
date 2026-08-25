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

  // #1219: 두 테이블 → 병합 단일 테이블. 헤더는 시그널 수 + 승인/거절 집계.
  it("renders the merged header with signal and approval counts", async () => {
    const { default: ScanPage } = await import("@/app/scan/page");
    await act(async () => {
      render(<ScanPage />);
    });
    const header = screen.getByText(/시그널/);
    expect(header.textContent).toContain("3 시그널");
    expect(header.textContent).toContain("승인 1");
    expect(header.textContent).toContain("거절 2");
  });

  it("renders one merged table with agent columns, not two tables", async () => {
    const { default: ScanPage } = await import("@/app/scan/page");
    let container!: HTMLElement;
    await act(async () => {
      ({ container } = render(<ScanPage />));
    });
    expect(container.querySelectorAll("table")).toHaveLength(1);
    // 중복 폐지: 병합 후 티커는 테이블에 1회만 (이전엔 scan+swing 두 테이블에 2회)
    expect(screen.getAllByText("NVDA")).toHaveLength(1);
    // 에이전트 컬럼 병합 확인
    expect(screen.getByText("Agent")).toBeInTheDocument();
    expect(screen.getAllByText("승인").length).toBeGreaterThan(0); // 컬럼 헤더 + 태그
  });

  it("renders rejected swing reasons in the fold", async () => {
    const { default: ScanPage } = await import("@/app/scan/page");
    await act(async () => {
      render(<ScanPage />);
    });
    expect(screen.getByText("미승인 사유 (2)")).toBeInTheDocument();
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

  // #1219: 스윙 전용 티커(top-N 밖)도 union 으로 테이블에 들어온다 — 모멘텀 필드는 —.
  it("includes swing-only tickers via union with dashed momentum fields", async () => {
    setupFetchAPI({
      swing: {
        entries: [
          ...mockSwing.entries,
          { ticker: "AAPL", price: 230.0, scan_signal: "pullback", scan_score: 60, agent_action: "BUY", agent_confidence: 66, approved: true, reason: "OK" },
        ],
        approved: 2,
        rejected: 2,
      },
    });
    const { default: ScanPage } = await import("@/app/scan/page");
    await act(async () => {
      render(<ScanPage />);
    });
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("renders with no rejected swing entries (no fold)", async () => {
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

    expect(screen.getByText(/승인 1/)).toBeInTheDocument();
    expect(screen.queryByText(/미승인 사유/)).not.toBeInTheDocument();
  });

  // #1219: 스윙 API 실패는 스캔 테이블을 죽이지 않는다 — 에이전트 컬럼만 — 로.
  it("renders scan rows with dashed agent fields when the swing API fails", async () => {
    mockFetchAPI = vi.fn().mockImplementation((path: string) => {
      if (path.includes("/api/scan")) return Promise.resolve(mockScan);
      if (path.includes("/api/swing/entries")) return Promise.reject(new Error("500"));
      return Promise.resolve({});
    });
    const { default: ScanPage } = await import("@/app/scan/page");
    await act(async () => {
      render(<ScanPage />);
    });
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText(/승인 0/)).toBeInTheDocument();
  });

  it("shows the one-line empty state when both sources are empty", async () => {
    setupFetchAPI({
      scan: { results: [], count: 0 },
      swing: { entries: [], approved: 0, rejected: 0 },
    });

    const { default: ScanPage } = await import("@/app/scan/page");
    await act(async () => {
      render(<ScanPage />);
    });

    expect(screen.getByText(/스캔 결과 없음/)).toBeInTheDocument();
  });
});
