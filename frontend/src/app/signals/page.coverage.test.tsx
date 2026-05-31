/**
 * Signals page — statement coverage push.
 *
 * 기존 coverage/signals-page-coverage.test.tsx 는 ScorecardSection 의 error 분기만
 * 다뤄, pf() 의 ∞ 분기(page.tsx:14)와 정상 렌더 경로(ScorecardSection/CrossSection)가
 * 미커버 상태였다. 이 파일은 네 가지 경로를 모두 실제 렌더로 커버한다:
 *   1. scorecard 정상 + cross-analysis profit_factor >= 99  → pf() "∞" 분기 (line 14)
 *   2. cross-analysis profit_factor < 99                     → pf() toFixed 분기 (line 15)
 *   3. scorecard error object                                → ScorecardSection 에러 반환 (line 24)
 *   4. cross-analysis error/no-data                          → CrossSection null 반환 (line 46)
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

const mockFetchAPI = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

const scorecard = [
  {
    signal_id: "alpha_signal",
    total_trades: 30,
    win_rate: 0.6,
    avg_return: 2.5,
    profit_factor: 2.0,
    max_return: 15.0,
    max_loss: -7.0,
  },
];

function setupMocks(overrides: { scorecard?: unknown; cross?: unknown } = {}) {
  mockFetchAPI.mockImplementation((path: string) => {
    if (path.includes("/api/scorecard"))
      return Promise.resolve(overrides.scorecard ?? { scorecard, date: "2026-01-15" });
    if (path.includes("/api/cross-analysis"))
      return Promise.resolve(overrides.cross ?? { data: [] });
    return Promise.resolve({});
  });
}

describe("SignalsPage statement coverage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockFetchAPI.mockReset();
  });

  it('renders "∞" when profit_factor >= 99 and renders the scorecard section', async () => {
    setupMocks({
      cross: {
        data: [{ regime: "bull", signal_id: "alpha_signal", profit_factor: 99 }],
      },
    });
    const Page = await import("@/app/signals/page");
    await act(async () => {
      render(<Page.default />);
    });
    // ScorecardSection 정상 렌더 (date 표시)
    expect(screen.getByText(/Signal Scorecard/)).toBeInTheDocument();
    // pf() ∞ 분기
    expect(screen.getByText("PF ∞")).toBeInTheDocument();
  });

  it("renders finite PF value when profit_factor < 99", async () => {
    setupMocks({
      cross: {
        data: [{ regime: "bear", signal_id: "beta_signal", profit_factor: 3.4 }],
      },
    });
    const Page = await import("@/app/signals/page");
    await act(async () => {
      render(<Page.default />);
    });
    expect(screen.getByText("PF 3.4")).toBeInTheDocument();
  });

  it("renders error text when scorecard API returns an error object", async () => {
    setupMocks({ scorecard: { error: "CSV not found" } });
    const Page = await import("@/app/signals/page");
    await act(async () => {
      render(<Page.default />);
    });
    await waitFor(() => {
      expect(screen.getByText("CSV not found")).toBeInTheDocument();
    });
  });

  it("renders nothing for CrossSection when cross-analysis has no data", async () => {
    setupMocks({ cross: { error: "no data" } });
    const Page = await import("@/app/signals/page");
    await act(async () => {
      render(<Page.default />);
    });
    // CrossSection 은 null 반환 → Signal × Regime 헤더가 없어야 한다
    expect(screen.queryByText("Signal × Regime")).not.toBeInTheDocument();
  });
});
