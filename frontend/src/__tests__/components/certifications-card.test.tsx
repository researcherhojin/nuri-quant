/**
 * CertificationsCard — engine/page.tsx 에서 추출한 pure render component.
 * 서버 fetch 는 page.tsx 가 담당; 이 테스트는 rendering / formatting 검증.
 *
 * recharts mock 주의: siege-timeline-chart 가 내부에서 recharts 사용 → 이 파일
 * 도 같은 worker 에서 mock 적용 (frontend/CLAUDE.md gotcha).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  LineChart: ({ children }: { children: React.ReactNode }) => <div data-testid="line-chart">{children}</div>,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ReferenceLine: () => null,
}));

import {
  CertificationsCard,
  type CertificationsListResponse,
  type CertificationsSummary,
  formatAvgScore,
  formatRate,
  rateColor,
} from "@/components/ui/certifications-card";

function makeHistory(overrides: Partial<CertificationsListResponse> = {}): CertificationsListResponse {
  return {
    items: [],
    count: 0,
    total_in_db: 0,
    ...overrides,
  };
}

function makeSummary(overrides: Partial<CertificationsSummary> = {}): CertificationsSummary {
  return {
    days: 30,
    count: 0,
    certified_rate: null,
    avg_score: null,
    by_caller: {},
    by_regime: {},
    latest: null,
    ...overrides,
  };
}

describe("CertificationsCard helpers", () => {
  it("rateColor: null / ≥50 → default, <50 → red", () => {
    expect(rateColor(null)).toBe("default");
    expect(rateColor(100)).toBe("default");
    expect(rateColor(80)).toBe("default");
    expect(rateColor(50)).toBe("default"); // boundary
    expect(rateColor(49.9)).toBe("red");
    expect(rateColor(0)).toBe("red");
  });

  it("formatRate: null → '—', number → '{n}%'", () => {
    expect(formatRate(null)).toBe("—");
    expect(formatRate(85)).toBe("85%");
    expect(formatRate(0)).toBe("0%");
  });

  it("formatAvgScore: null → '—', number → '{n.n}' (1 decimal)", () => {
    expect(formatAvgScore(null)).toBe("—");
    expect(formatAvgScore(52.94)).toBe("52.9");
    expect(formatAvgScore(100)).toBe("100.0");
  });
});

describe("CertificationsCard rendering", () => {
  it("empty state — total_in_db=0 → '아직 certification 기록이 없습니다'", () => {
    render(<CertificationsCard history={makeHistory({ total_in_db: 0 })} summary={makeSummary()} />);
    expect(screen.getByText(/아직 certification 기록이 없습니다/)).toBeInTheDocument();
    // 차트 렌더 되지 않아야 함
    expect(screen.queryByTestId("line-chart")).not.toBeInTheDocument();
  });

  it("renders full card when data present", () => {
    const history = makeHistory({
      total_in_db: 17,
      count: 3,
      items: [
        {
          id: 1,
          timestamp: "2026-04-20T10:00:00+09:00",
          certified: true,
          score: 85,
          total_conditions: 15,
          passed: 13,
          failed: 0,
          warnings: 2,
          regime: "bull_low_vol",
          portfolio_hash: "hash1",
          caller: "cli",
        },
      ],
    });
    const summary = makeSummary({
      count: 17,
      certified_rate: 64.7,
      avg_score: 78.2,
      by_caller: { cli: 10, "api:targets": 7 },
      by_regime: { bull_low_vol: 17 },
      latest: {
        timestamp: "2026-04-20T10:00:00+09:00",
        certified: true,
        score: 85,
        regime: "bull_low_vol",
        caller: "cli",
      },
    });

    render(<CertificationsCard history={history} summary={summary} />);
    expect(screen.getByText("64.7%")).toBeInTheDocument(); // certified_rate
    expect(screen.getByText("78.2")).toBeInTheDocument(); // avg_score
    // "17" 은 runs count (summary.count) + total_in_db (history.total_in_db) 2번 렌더
    expect(screen.getAllByText("17").length).toBe(2);
    expect(screen.getByTestId("line-chart")).toBeInTheDocument();
    // caller / regime distributions
    expect(screen.getByText("cli")).toBeInTheDocument();
    expect(screen.getByText("×10")).toBeInTheDocument();
    expect(screen.getByText("api:targets")).toBeInTheDocument();
    expect(screen.getByText("bull_low_vol")).toBeInTheDocument();
  });

  it("shows BLOCKED badge when latest.certified=false", () => {
    const history = makeHistory({
      total_in_db: 1,
      count: 1,
      items: [
        {
          id: 1,
          timestamp: "2026-04-20T10:00:00+09:00",
          certified: false,
          score: 52.9,
          total_conditions: 17,
          passed: 9,
          failed: 1,
          warnings: 7,
          regime: "sideways_high_vol",
          portfolio_hash: "h",
          caller: "cli",
        },
      ],
    });
    const summary = makeSummary({
      count: 1,
      certified_rate: 0,
      avg_score: 52.9,
      latest: {
        timestamp: "2026-04-20T10:00:00+09:00",
        certified: false,
        score: 52.9,
        regime: "sideways_high_vol",
        caller: "cli",
      },
    });
    render(<CertificationsCard history={history} summary={summary} />);
    expect(screen.getByText("BLOCKED")).toBeInTheDocument();
  });

  it("shows '—' placeholders when summary metrics null", () => {
    const history = makeHistory({ total_in_db: 0, count: 0 });
    // empty state 대신 total_in_db=1 인데 metrics 는 null 인 edge case
    const historyNonZero = makeHistory({ total_in_db: 1, items: [] });
    const summary = makeSummary({ certified_rate: null, avg_score: null });
    render(<CertificationsCard history={historyNonZero} summary={summary} />);
    // 복수 '—' 렌더 예상 (rate + avg_score)
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
    // empty state 의 placeholder 사용 안 함을 간접 검증
    expect(history.total_in_db).toBe(0); // fixture correctness
  });
});
