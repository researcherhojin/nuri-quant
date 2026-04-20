/**
 * SiegeTimelineChart — V2 rendering 검증.
 *
 * 주의: recharts mock 은 같은 worker 의 모든 dynamic import 에 영향 (frontend/CLAUDE.md
 * gotcha). 이 파일은 recharts-dependent 만 담고, 다른 recharts 를 안 쓰는 테스트
 * 는 분리 파일로 이미 유지.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// recharts mock — hoisted to worker level
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  LineChart: ({ children }: { children: React.ReactNode }) => <div data-testid="line-chart">{children}</div>,
  Line: (props: Record<string, unknown>) => <div data-testid={`line-${props.dataKey}`} />,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ReferenceLine: (props: Record<string, unknown>) => <div data-testid={`ref-line-${props.x}`} />,
}));

import { SiegeTimelineChart, type CertificationPoint } from "@/components/ui/siege-timeline-chart";

function makePoint(overrides: Partial<CertificationPoint> = {}): CertificationPoint {
  return {
    id: 1,
    timestamp: "2026-04-20T10:00:00+09:00",
    certified: true,
    score: 85,
    total_conditions: 15,
    passed: 13,
    failed: 0,
    warnings: 2,
    regime: "sideways_low_vol",
    portfolio_hash: "hashA",
    caller: "cli",
    ...overrides,
  };
}

describe("SiegeTimelineChart", () => {
  it("empty state — no items 이면 안내 문구", () => {
    render(<SiegeTimelineChart items={[]} />);
    expect(screen.getByText(/아직 certification 실행 기록/)).toBeInTheDocument();
  });

  it("renders LineChart when items present", () => {
    const items = [
      makePoint({ id: 1, timestamp: "2026-04-20T10:00:00+09:00" }),
      makePoint({ id: 2, timestamp: "2026-04-20T11:00:00+09:00" }),
    ];
    render(<SiegeTimelineChart items={items} />);
    expect(screen.getByTestId("line-chart")).toBeInTheDocument();
    expect(screen.getByTestId("line-score")).toBeInTheDocument();
  });

  it("shows certified/rejected count in header", () => {
    const items = [
      makePoint({ id: 1, certified: true }),
      makePoint({ id: 2, certified: true }),
      makePoint({ id: 3, certified: false }),
    ];
    render(<SiegeTimelineChart items={items} />);
    // "최근 3건 (2 CERTIFIED / 1 REJECTED)"
    expect(screen.getByText(/3건.*2 CERTIFIED.*1 REJECTED/)).toBeInTheDocument();
  });

  it("inserts ReferenceLine marker when portfolio_hash changes", () => {
    // 3 points — 2번째에서 hash 변경
    const items = [
      makePoint({ id: 3, timestamp: "2026-04-20T12:00:00+09:00", portfolio_hash: "hashB" }),
      makePoint({ id: 2, timestamp: "2026-04-20T11:00:00+09:00", portfolio_hash: "hashB" }),
      makePoint({ id: 1, timestamp: "2026-04-20T10:00:00+09:00", portfolio_hash: "hashA" }),
    ];
    render(<SiegeTimelineChart items={items} />);
    // API 가 id DESC 로 주고, chart 는 flip해서 과거→현재 순서
    // hashA(10:00) → hashB(11:00) 전환 → 11:00 지점에 ref-line 존재
    // (hashB → hashB 는 transition 아님)
    expect(screen.getByTestId("ref-line-04-20 11:00")).toBeInTheDocument();
  });

  it("no ReferenceLine when all items share portfolio_hash", () => {
    const items = [
      makePoint({ id: 2, portfolio_hash: "hashA", timestamp: "2026-04-20T11:00:00+09:00" }),
      makePoint({ id: 1, portfolio_hash: "hashA", timestamp: "2026-04-20T10:00:00+09:00" }),
    ];
    const { queryAllByTestId } = render(<SiegeTimelineChart items={items} />);
    expect(queryAllByTestId(/ref-line-/)).toHaveLength(0);
  });

  it("legend includes CERTIFIED, REJECTED, portfolio state 변경", () => {
    render(<SiegeTimelineChart items={[makePoint()]} />);
    expect(screen.getByText("CERTIFIED")).toBeInTheDocument();
    expect(screen.getByText("REJECTED")).toBeInTheDocument();
    // 헤더 + 범례 2번 등장 — 최소 1개
    expect(screen.getAllByText(/portfolio state 변경/).length).toBeGreaterThan(0);
  });
});
