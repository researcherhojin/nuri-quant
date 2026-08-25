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

import {
  SiegeTimelineChart,
  type CertificationPoint,
  type ChartPoint,
  callerShape,
  countByCaller,
  dotFill,
  dotRadius,
  labelFormatter,
  LegendShape,
  renderDot,
  tickFormatter,
  valueFormatter,
} from "@/components/ui/siege-timeline-chart";

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

// Recharts callback 은 mock 이 호출 안 하므로 module-level helper 로 extract 한
// tickFormatter/labelFormatter/valueFormatter/dotFill/renderDot 직접 테스트.
describe("SiegeTimelineChart helpers", () => {
  const samplePoint = (overrides: Partial<ChartPoint> = {}): ChartPoint => ({
    idx: 0,
    id: 1,
    timestamp: "2026-04-20T10:00:00+09:00",
    short: "04-20 10:00",
    certified: true,
    score: 85,
    failed: 0,
    warnings: 2,
    regime: "bull_low_vol",
    caller: "cli",
    hashChanged: false,
    ...overrides,
  });

  it("tickFormatter returns string", () => {
    expect(tickFormatter(50)).toBe("50");
    expect(tickFormatter(0)).toBe("0");
    expect(tickFormatter(100)).toBe("100");
  });

  it("labelFormatter returns '#id — short' for payload", () => {
    const p = samplePoint({ id: 42, short: "04-20 14:30" });
    expect(labelFormatter(null, [{ payload: p }])).toBe("#42 — 04-20 14:30");
  });

  it("labelFormatter returns '' for empty payload", () => {
    expect(labelFormatter(null, undefined)).toBe("");
    expect(labelFormatter(null, [])).toBe("");
  });

  it("valueFormatter formats CERTIFIED row", () => {
    const p = samplePoint({
      certified: true,
      failed: 0,
      warnings: 1,
      regime: "bull_low_vol",
      caller: "cli",
    });
    const [text, label] = valueFormatter(85, "score", { payload: p });
    expect(label).toBe("score");
    expect(text).toContain("✓ CERTIFIED");
    expect(text).toContain("(85)");
    expect(text).toContain("0F/1W");
    expect(text).toContain("regime=bull_low_vol");
    expect(text).toContain("caller=cli");
  });

  it("valueFormatter formats REJECTED with null regime/caller fallback", () => {
    const p = samplePoint({
      certified: false,
      failed: 2,
      warnings: 3,
      regime: null,
      caller: null,
    });
    const [text] = valueFormatter(45, "score", { payload: p });
    expect(text).toContain("✕ REJECTED");
    expect(text).toContain("(45)");
    expect(text).toContain("2F/3W");
    expect(text).toContain("regime=-");
    expect(text).toContain("caller=-");
  });

  it("dotFill returns emerald for certified, red for rejected", () => {
    expect(dotFill(samplePoint({ certified: true }))).toBe("#10b981");
    expect(dotFill(samplePoint({ certified: false }))).toBe("#ef4444");
  });

  it("renderDot returns circle element with correct fill + coords", () => {
    const el = renderDot({
      cx: 100,
      cy: 50,
      payload: samplePoint({ certified: true }),
      index: 3,
    });
    // React 19 type: ReactElement.props 는 `unknown` → narrow cast 로 assertion.
    const props = el.props as {
      cx: number;
      cy: number;
      r: number;
      fill: string;
      stroke: string;
    };
    expect(el.type).toBe("circle");
    expect(props.cx).toBe(100);
    expect(props.cy).toBe(50);
    expect(props.r).toBe(3.5);
    expect(props.fill).toBe("#10b981");
    expect(props.stroke).toBe("#18181b");
  });

  it("renderDot rejected point uses red fill", () => {
    const el = renderDot({
      cx: 10,
      cy: 20,
      payload: samplePoint({ certified: false }),
      index: 0,
    });
    const props = el.props as { fill: string };
    expect(props.fill).toBe("#ef4444");
  });

  it("callerShape maps caller → DotShape", () => {
    expect(callerShape("cli")).toBe("circle");
    expect(callerShape("direct")).toBe("circle");
    expect(callerShape("api:actions:health")).toBe("triangle");
    expect(callerShape("api:certify")).toBe("triangle");
    expect(callerShape("audit:historical")).toBe("square");
    expect(callerShape("scheduler")).toBe("diamond");
    expect(callerShape("unknown:stuff")).toBe("circle");
    expect(callerShape(null)).toBe("circle");
  });

  it("dotRadius: hashChanged → 5, normal → 3.5", () => {
    expect(dotRadius(false)).toBe(3.5);
    expect(dotRadius(true)).toBe(5);
  });

  it("renderDot produces triangle for api:* caller", () => {
    const el = renderDot({
      cx: 40,
      cy: 30,
      payload: samplePoint({ caller: "api:certify", hashChanged: false }),
      index: 1,
    });
    expect(el.type).toBe("polygon");
    const props = el.props as { fill: string; points: string };
    expect(props.fill).toBe("#10b981"); // certified=true 유지
    expect(props.points).toContain("40,"); // cx 가 points 내에 포함
  });

  it("renderDot produces square for audit:* caller (E4-0b 호환)", () => {
    const el = renderDot({
      cx: 50,
      cy: 50,
      payload: samplePoint({ caller: "audit:historical" }),
      index: 2,
    });
    expect(el.type).toBe("rect");
    const props = el.props as { x: number; y: number; width: number; height: number };
    expect(props.width).toBeGreaterThan(0);
    expect(props.height).toBe(props.width);
  });

  it("renderDot produces diamond polygon for scheduler caller", () => {
    const el = renderDot({
      cx: 60,
      cy: 40,
      payload: samplePoint({ caller: "scheduler" }),
      index: 3,
    });
    expect(el.type).toBe("polygon");
    const props = el.props as { points: string };
    // diamond: 4 points with `cx,cy±h` / `cx±h,cy` pattern
    expect(props.points.split(" ")).toHaveLength(4);
  });

  it("renderDot hashChanged 포인트는 radius 증가 (circle 기준)", () => {
    const el = renderDot({
      cx: 70,
      cy: 40,
      payload: samplePoint({ caller: "cli", hashChanged: true }),
      index: 4,
    });
    const props = el.props as { r: number };
    expect(props.r).toBe(5);
  });

  it("countByCaller: 분포를 descending count 로 집계", () => {
    const pts: ChartPoint[] = [
      samplePoint({ caller: "cli", id: 1 }),
      samplePoint({ caller: "cli", id: 2 }),
      samplePoint({ caller: "api:actions:health", id: 3 }),
      samplePoint({ caller: null, id: 4 }),
    ];
    const buckets = countByCaller(pts);
    expect(buckets).toEqual([
      { caller: "cli", count: 2, shape: "circle" },
      { caller: "api:actions:health", count: 1, shape: "triangle" },
      { caller: "(none)", count: 1, shape: "circle" },
    ]);
  });

  it("LegendShape renders different elements per shape", () => {
    const triangle = LegendShape({ shape: "triangle" });
    expect(triangle.type).toBe("svg");
    const square = LegendShape({ shape: "square" });
    expect(square.type).toBe("span");
    const diamond = LegendShape({ shape: "diamond" });
    expect(diamond.type).toBe("svg");
    const circle = LegendShape({ shape: "circle" });
    expect(circle.type).toBe("span");
  });
});
