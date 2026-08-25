/**
 * #1227 U5c: /advisor 는 /rebalance 리다이렉트, AdvisorSection 은 rebalance 로 이동.
 * 섹션은 async Server Component 라 await-render (RSC coverage gotcha — jsdom 은
 * 중첩 Suspense child 를 commit 안 함).
 */
import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, act } from "@testing-library/react";

const redirectMock = vi.fn();
vi.mock("next/navigation", () => ({
  redirect: (...args: unknown[]) => redirectMock(...args),
}));

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

let mockFetchAPI: Mock;

vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

function setupFetchAPI(overrides: { advisor?: unknown } = {}) {
  mockFetchAPI = vi.fn().mockImplementation((_path: string) => {
    return Promise.resolve(overrides.advisor ?? mockAdvisorReport);
  });
}

async function renderSection() {
  const { AdvisorSection } = await import("@/app/rebalance/advisor-section");
  const ui = await AdvisorSection();
  await act(async () => {
    render(ui);
  });
}

describe("AdvisorPage (redirect)", () => {
  it("redirects /advisor to /rebalance — 북마크 보존 (#1227)", async () => {
    redirectMock.mockClear();
    const { default: AdvisorPage } = await import("@/app/advisor/page");
    AdvisorPage();
    expect(redirectMock).toHaveBeenCalledWith("/rebalance");
  });
});

describe("AdvisorSection (moved to /rebalance)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setupFetchAPI();
  });

  it("renders violation count metrics", async () => {
    await renderSection();
    expect(screen.getByText("총 위반")).toBeInTheDocument();
    expect(screen.getByText("2건")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
    // "1건" appears for both Critical and High counts
    const oneCountElements = screen.getAllByText("1건");
    expect(oneCountElements.length).toBe(2);
  });

  it("renders total recovery amount", async () => {
    await renderSection();
    expect(screen.getByText("총 회수 가능")).toBeInTheDocument();
    expect(screen.getByText("$9,090")).toBeInTheDocument();
  });

  it("shows critical warning banner when has_critical is true", async () => {
    await renderSection();
    expect(screen.getByText(/CRITICAL 위반 1건 — 즉시 조치 필요/)).toBeInTheDocument();
  });

  it("renders violation type distribution", async () => {
    await renderSection();
    expect(screen.getByText("위반 유형별 분포")).toBeInTheDocument();
    expect(screen.getByText("stop_loss: 1건")).toBeInTheDocument();
    expect(screen.getByText("position_concentration: 1건")).toBeInTheDocument();
  });

  it("renders advisor table description", async () => {
    await renderSection();
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
    await renderSection();
    expect(screen.getByText("READY")).toBeInTheDocument();
    expect(screen.getByText("모든 투자 규칙 준수 중. 위반 사항 없음.")).toBeInTheDocument();
  });

  it("handles API failure gracefully", async () => {
    mockFetchAPI = vi.fn().mockRejectedValue(new Error("API down"));
    await renderSection();
    expect(screen.getByText("API 연결 실패. make api 실행 필요.")).toBeInTheDocument();
  });
});
