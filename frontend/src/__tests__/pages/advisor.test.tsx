import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockAdvisorReport = {
  actions: [
    {
      ticker: "TSLA", violation_type: "stop_loss", priority: 1,
      current_value: -12.5, limit_value: -7, severity: "critical",
      action: "SELL_ALL", sell_shares: 33, sell_value_usd: 8250, reason: "손절 기준 초과",
    },
    {
      ticker: "NVDA", violation_type: "position_concentration", priority: 2,
      current_value: 22.0, limit_value: 15, severity: "high",
      action: "REDUCE", sell_shares: 5, sell_value_usd: 840, reason: "단일 종목 비중 초과",
    },
  ],
  total_violations: 2,
  total_recovery_usd: 9090,
  violations_by_type: { stop_loss: 1, position_concentration: 1 },
  violations_by_severity: { critical: 1, high: 1 },
  has_critical: true,
};

let mockFetchAPI: any;

vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: any[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

function setupFetchAPI(overrides: { advisor?: any } = {}) {
  mockFetchAPI = vi.fn().mockImplementation((_path: string) => {
    return Promise.resolve(overrides.advisor ?? mockAdvisorReport);
  });
}

describe("AdvisorPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setupFetchAPI();
  });

  it("renders page heading and description", async () => {
    const { default: AdvisorPage } = await import("@/app/advisor/page");
    await act(async () => {
      render(<AdvisorPage />);
    });

    expect(screen.getByText("Rebalance Advisor")).toBeInTheDocument();
    expect(screen.getByText(/투자 규칙 위반 감지/)).toBeInTheDocument();
  });

  it("renders violation count metrics", async () => {
    const { default: AdvisorPage } = await import("@/app/advisor/page");
    await act(async () => {
      render(<AdvisorPage />);
    });

    expect(screen.getByText("총 위반")).toBeInTheDocument();
    expect(screen.getByText("2건")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
    // "1건" appears for both Critical and High counts
    const oneCountElements = screen.getAllByText("1건");
    expect(oneCountElements.length).toBe(2);
  });

  it("renders total recovery amount", async () => {
    const { default: AdvisorPage } = await import("@/app/advisor/page");
    await act(async () => {
      render(<AdvisorPage />);
    });

    expect(screen.getByText("총 회수 가능")).toBeInTheDocument();
    expect(screen.getByText("$9,090")).toBeInTheDocument();
  });

  it("shows critical warning banner when has_critical is true", async () => {
    const { default: AdvisorPage } = await import("@/app/advisor/page");
    await act(async () => {
      render(<AdvisorPage />);
    });

    expect(screen.getByText(/CRITICAL 위반 1건 — 즉시 조치 필요/)).toBeInTheDocument();
  });

  it("renders violation type distribution", async () => {
    const { default: AdvisorPage } = await import("@/app/advisor/page");
    await act(async () => {
      render(<AdvisorPage />);
    });

    expect(screen.getByText("위반 유형별 분포")).toBeInTheDocument();
    expect(screen.getByText("stop_loss: 1건")).toBeInTheDocument();
    expect(screen.getByText("position_concentration: 1건")).toBeInTheDocument();
  });

  it("renders advisor table description", async () => {
    const { default: AdvisorPage } = await import("@/app/advisor/page");
    await act(async () => {
      render(<AdvisorPage />);
    });

    expect(screen.getByText(/Rebalance Advisor — 매도 우선순위 순/)).toBeInTheDocument();
  });

  it("shows READY badge and no-violation message when zero violations", async () => {
    setupFetchAPI({
      advisor: {
        actions: [],
        total_violations: 0,
        total_recovery_usd: 0,
        violations_by_type: {},
        violations_by_severity: {},
        has_critical: false,
      },
    });

    const { default: AdvisorPage } = await import("@/app/advisor/page");
    await act(async () => {
      render(<AdvisorPage />);
    });

    expect(screen.getByText("READY")).toBeInTheDocument();
    expect(screen.getByText("모든 투자 규칙 준수 중. 위반 사항 없음.")).toBeInTheDocument();
  });

  it("handles API failure gracefully", async () => {
    mockFetchAPI = vi.fn().mockRejectedValue(new Error("API down"));

    const { default: AdvisorPage } = await import("@/app/advisor/page");
    await act(async () => {
      render(<AdvisorPage />);
    });

    expect(screen.getByText("API 연결 실패. make api 실행 필요.")).toBeInTheDocument();
  });
});
