/**
 * Statement-coverage push for src/app/engine/page.tsx (#coverage/full-push).
 *
 * 모든 async Server Component (GateSection / ConflictsSection /
 * CertificationsSection / MemorySection) 를 직접 await 해 반환 JSX 만 렌더한다.
 * 페이지 전체(<EnginePage/>)는 형제 Suspense RSC 가 jsdom 에서 resolve 안 되어
 * 미커버 라인이 남으므로, 섹션별 격리 렌더로 100% statement 를 달성한다.
 *
 * - ConflictsSection: 비어있지 않은 분기(severity high/medium/low 3-arm ternary,
 *   L121-129) + 빈 분기(L117) 모두.
 * - GateSection: ready/blocked StatusBadge, score 색상 3-arm, passed/failed 조건,
 *   마지막 phase divider 분기(L92) 모두.
 * - MemorySection: 빈 분기(L164) + drift row 분기(L166) 모두.
 * - CertificationsSection: Promise.all fetch 경로 (lazy card 는 stub).
 *
 * CertificationsCardLazy / ClientTable 은 가벼운 stub 으로 mock — recharts/next-dynamic
 * 가 jsdom 에서 깨지는 것을 피한다(파일-level recharts mock hoist gotcha 회피).
 * PRIVACY: AAPL/MSFT placeholder + round numbers only (public repo).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

vi.mock("@/lib/api", () => ({
  fetchAPI: vi.fn(),
}));

vi.mock("@/components/ui/certifications-card-lazy", () => ({
  CertificationsCardLazy: () => <div data-testid="certs-card-lazy" />,
}));

vi.mock("@/components/ui/client-table", () => ({
  ClientTable: () => <div data-testid="client-table" />,
}));

import {
  GateSection,
  ConflictsSection,
  CertificationsSection,
  MemorySection,
} from "./page";
import EnginePage from "./page";
import { fetchAPI } from "@/lib/api";

const mockFetchAPI = vi.mocked(fetchAPI);

beforeEach(() => {
  mockFetchAPI.mockReset();
});

describe("engine/page sections (coverage)", () => {
  it("ConflictsSection renders all severity rows (high/medium/low)", async () => {
    mockFetchAPI.mockResolvedValue({
      count: 3,
      high: 1,
      conflicts: [
        {
          ticker: "AAPL",
          conflict_type: "momentum_vs_value",
          severity: "high",
          buy_signals: ["rsi_oversold"],
          sell_signals: ["death_cross"],
          detail: "RSI rebound conflicts with death cross",
          recommendation: "Trim into strength",
        },
        {
          ticker: "MSFT",
          conflict_type: "trend_vs_mean",
          severity: "medium",
          buy_signals: ["breakout"],
          sell_signals: ["overbought"],
          detail: "Breakout while overbought",
          recommendation: "Wait for pullback",
        },
        {
          ticker: "MSFT",
          conflict_type: "volume_vs_price",
          severity: "low",
          buy_signals: ["accumulation"],
          sell_signals: ["distribution"],
          detail: "Mixed volume signature",
          recommendation: "Hold and monitor",
        },
      ],
    });

    render(await ConflictsSection());

    // severity ternary 3-arm: high→SELL, medium→WATCH, low→HOLD
    expect(screen.getByText("SELL")).toBeInTheDocument();
    expect(screen.getByText("WATCH")).toBeInTheDocument();
    expect(screen.getByText("HOLD")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getAllByText("MSFT")).toHaveLength(2);
    expect(screen.getByText("→ Trim into strength")).toBeInTheDocument();
  });

  it("ConflictsSection renders empty state when no conflicts", async () => {
    mockFetchAPI.mockResolvedValue({ count: 0, high: 0, conflicts: [] });

    render(await ConflictsSection());

    expect(screen.getByText("시그널 충돌 없음")).toBeInTheDocument();
  });

  it("GateSection renders ready/blocked phases with conditions", async () => {
    mockFetchAPI.mockResolvedValue({
      collect: {
        phase: "collect",
        total: 1,
        passed: 1,
        score: 1.0, // >= 0.7 → emerald
        ready: true,
        conditions: [
          { id: "c1", phase: "collect", description: "Prices fresh", passed: true, detail: "" },
        ],
      },
      analyze: {
        phase: "analyze",
        total: 2,
        passed: 1,
        score: 0.5, // 0.4..0.7 → amber
        ready: false,
        conditions: [
          { id: "c2", phase: "analyze", description: "Signals computed", passed: false, detail: "stale" },
        ],
      },
      score: {
        phase: "score",
        total: 1,
        passed: 0,
        score: 0.2, // < 0.4 → red
        ready: false,
        conditions: [
          { id: "c3", phase: "score", description: "Scored", passed: false, detail: "missing" },
        ],
      },
    });

    render(await GateSection());

    expect(screen.getByText("READY")).toBeInTheDocument();
    expect(screen.getAllByText("BLOCKED")).toHaveLength(2);
    expect(screen.getByText("Prices fresh")).toBeInTheDocument();
    expect(screen.getByText("stale")).toBeInTheDocument(); // failed condition detail
  });

  it("MemorySection renders empty state when no drift", async () => {
    mockFetchAPI.mockResolvedValue({ critical: 0, degrading: 0, drifts: [] });

    render(await MemorySection());

    expect(screen.getByText("드리프트 데이터 없음 — make validate 실행 필요")).toBeInTheDocument();
  });

  it("MemorySection renders the drift table when drifts exist", async () => {
    mockFetchAPI.mockResolvedValue({
      critical: 1,
      degrading: 1,
      drifts: [
        {
          signal_id: "rsi_oversold",
          regime: "bull",
          all_time_wr: 0.6,
          recent_wr: 0.4,
          drift_pct: -20,
          status: "degrading",
          detail: "win rate falling",
        },
      ],
    });

    render(await MemorySection());

    expect(screen.getByTestId("client-table")).toBeInTheDocument();
  });

  it("CertificationsSection fetches history + summary and renders the lazy card", async () => {
    mockFetchAPI.mockImplementation((path: string) => {
      if (path.startsWith("/api/certifications/summary")) {
        return Promise.resolve({ total: 0, certified: 0, rejected: 0, avg_score: 0 });
      }
      return Promise.resolve({ certifications: [], count: 0 });
    });

    render(await CertificationsSection());

    expect(screen.getByTestId("certs-card-lazy")).toBeInTheDocument();
    expect(mockFetchAPI).toHaveBeenCalledWith("/api/certifications?limit=30");
    expect(mockFetchAPI).toHaveBeenCalledWith("/api/certifications/summary?days=30");
  });

  it("EnginePage renders the static heading + Suspense fallbacks (Loading)", () => {
    mockFetchAPI.mockResolvedValue({});

    render(<EnginePage />);

    // 정적 헤더는 동기 렌더; Suspense fallback(Loading) 가 마운트되어 default export +
    // Loading 컴포넌트 statement 를 커버한다.
    expect(screen.getByText("Certification Engine")).toBeInTheDocument();
  });
});
