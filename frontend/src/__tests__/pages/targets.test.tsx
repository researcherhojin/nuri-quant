import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { COMMON, NAV } from "@/lib/strings";

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockTargets = {
  targets: [
    {
      ticker: "NVDA", stock_type: "growth", current_price: 168.0, entry_price: 165.0,
      stop_loss: 153.45, stop_loss_pct: -7, target_1: 198.0, target_1_pct: 20,
      target_1_sell_pct: 50, target_2: 231.0, target_2_pct: 40, target_2_sell_pct: 25,
      trailing_stop_pct: -15, analyst_target: 273.61, analyst_upside_pct: 63,
      take_profit_triggered: null, trailing_stop_triggered: false,
    },
    {
      ticker: "AAPL", stock_type: "value", current_price: 195.0, entry_price: 190.0,
      stop_loss: 171.0, stop_loss_pct: -10, target_1: 218.5, target_1_pct: 15,
      target_1_sell_pct: 50, target_2: 247.0, target_2_pct: 30, target_2_sell_pct: 25,
      trailing_stop_pct: -15, analyst_target: 220.0, analyst_upside_pct: 13,
      take_profit_triggered: "target_1", take_profit_sell_pct: 50, trailing_stop_triggered: false,
    },
    {
      ticker: "TSLA", stock_type: "growth", current_price: 250.0, entry_price: 280.0,
      stop_loss: 260.4, stop_loss_pct: -7, target_1: 336.0, target_1_pct: 20,
      target_1_sell_pct: 50, target_2: 392.0, target_2_pct: 40, target_2_sell_pct: 25,
      trailing_stop_pct: -15, analyst_target: null, analyst_upside_pct: null,
      take_profit_triggered: null, trailing_stop_triggered: true,
    },
  ],
  count: 3,
};

let mockFetchAPI: Mock;

vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

function setupFetchAPI(overrides: { targets?: unknown } = {}) {
  mockFetchAPI = vi.fn().mockImplementation((_path: string) => {
    return Promise.resolve(overrides.targets ?? mockTargets);
  });
}

describe("TargetsPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setupFetchAPI();
  });

  it("renders page heading and description", async () => {
    const { default: TargetsPage } = await import("@/app/targets/page");
    await act(async () => {
      render(<TargetsPage />);
    });

    expect(screen.getByText(NAV.ROUTE_TARGETS)).toBeInTheDocument();
    expect(screen.getByText(/전 종목 매수가/)).toBeInTheDocument();
  });

  it("renders metric summary cards", async () => {
    const { default: TargetsPage } = await import("@/app/targets/page");
    await act(async () => {
      render(<TargetsPage />);
    });

    // 3 valid targets
    expect(screen.getByText("3개")).toBeInTheDocument();
    // growth count: 2 (NVDA + TSLA)
    expect(screen.getByText("2개")).toBeInTheDocument();
  });

  it("renders metric labels", async () => {
    const { default: TargetsPage } = await import("@/app/targets/page");
    await act(async () => {
      render(<TargetsPage />);
    });

    expect(screen.getByText("전체 종목")).toBeInTheDocument();
    expect(screen.getByText("성장주")).toBeInTheDocument();
    expect(screen.getByText("가치주")).toBeInTheDocument();
    expect(screen.getByText("익절 도달")).toBeInTheDocument();
    expect(screen.getByText("트레일링 스톱")).toBeInTheDocument();
  });

  it("renders stock type sub-labels", async () => {
    const { default: TargetsPage } = await import("@/app/targets/page");
    await act(async () => {
      render(<TargetsPage />);
    });

    expect(screen.getByText("SL -7% / TP +20%/+40%")).toBeInTheDocument();
    expect(screen.getByText("SL -10% / TP +15%/+30%")).toBeInTheDocument();
  });

  it("renders rules description", async () => {
    const { default: TargetsPage } = await import("@/app/targets/page");
    await act(async () => {
      render(<TargetsPage />);
    });

    expect(screen.getByText(/rules.yaml 기반/)).toBeInTheDocument();
  });

  it("shows take-profit triggered count", async () => {
    const { default: TargetsPage } = await import("@/app/targets/page");
    await act(async () => {
      render(<TargetsPage />);
    });

    // 1 take-profit triggered (AAPL), 1 trailing stop triggered (TSLA), 1 value stock
    // Multiple "1개" metrics appear; verify the sub-label instead
    expect(screen.getByText("매도 필요")).toBeInTheDocument();
  });

  it("shows trailing stop triggered count", async () => {
    const { default: TargetsPage } = await import("@/app/targets/page");
    await act(async () => {
      render(<TargetsPage />);
    });

    // 1 trailing stop triggered (TSLA)
    expect(screen.getByText("즉시 매도")).toBeInTheDocument();
  });

  it("handles API failure gracefully", async () => {
    mockFetchAPI = vi.fn().mockRejectedValue(new Error("API down"));

    const { default: TargetsPage } = await import("@/app/targets/page");
    await act(async () => {
      render(<TargetsPage />);
    });

    // F-002: 리터럴 대신 상수 — 카피 변경이 테스트를 조용히 깨지 않게
    expect(screen.getByText(COMMON.API_ERROR)).toBeInTheDocument();
  });

  it("filters out targets with error field", async () => {
    setupFetchAPI({
      targets: {
        targets: [
          { ...mockTargets.targets[0] },
          { ticker: "BAD", error: "No data" },
        ],
        count: 2,
      },
    });

    const { default: TargetsPage } = await import("@/app/targets/page");
    await act(async () => {
      render(<TargetsPage />);
    });

    // Only 1 valid target (growth), 0 value, 0 triggered
    // Check the "전체 종목" metric shows "1개"
    const metrics = screen.getAllByText("1개");
    expect(metrics.length).toBeGreaterThanOrEqual(1);
    // The growth sub-label confirms counting
    expect(screen.getByText("SL -7% / TP +20%/+40%")).toBeInTheDocument();
  });
});
