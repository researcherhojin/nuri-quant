/**
 * GateFailureChart — V2.1 #1 stacked bar breakdown.
 *
 * Recharts mock scope 주의: 같은 vitest worker 의 다른 테스트가 LineChart 만
 * 사용해도 이 파일의 mock 이 먼저 hoist 되면 override 됨. 따라서 모든
 * chart 컴포넌트를 broad mock.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  BarChart: ({ children }: { children: React.ReactNode }) => <div data-testid="bar-chart">{children}</div>,
  Bar: (props: Record<string, unknown>) => <div data-testid={`bar-${props.dataKey}`} />,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  Legend: () => null,
  // also mock LineChart in case another test imports siege-timeline within the worker
  LineChart: ({ children }: { children: React.ReactNode }) => <div data-testid="line-chart">{children}</div>,
  Line: () => null,
  ReferenceLine: () => null,
}));

import type { CertificationPoint, GateCondition } from "@/components/ui/siege-timeline-chart";
import {
  GateFailureChart,
  buildGateFailureData,
  colorForCategory,
  formatCategoryLabel,
  legendFormatter,
  normalizeGateCategory,
  tooltipValueFormatter,
} from "@/components/ui/gate-failure-chart";

function makeCondition(overrides: Partial<GateCondition> = {}): GateCondition {
  return {
    id: "position_limit",
    description: "",
    passed: false,
    detail: "",
    severity: "error",
    ...overrides,
  };
}

function makePoint(overrides: Partial<CertificationPoint> = {}): CertificationPoint {
  return {
    id: 1,
    timestamp: "2026-04-20T10:00:00+09:00",
    certified: false,
    score: 55,
    total_conditions: 10,
    passed: 7,
    failed: 1,
    warnings: 2,
    regime: null,
    portfolio_hash: "h",
    caller: "cli",
    conditions: [],
    ...overrides,
  };
}

describe("normalizeGateCategory", () => {
  it("prefix 전 부분을 반환, nested 에서 첫 segment 만", () => {
    expect(normalizeGateCategory("data_fresh:us_equity:primary")).toBe("data_fresh");
    expect(normalizeGateCategory("position_limit")).toBe("position_limit");
    expect(normalizeGateCategory("volatility_gate:kr_equity:secondary")).toBe("volatility_gate");
  });

  it("빈/falsy 입력은 'other'", () => {
    expect(normalizeGateCategory("")).toBe("other");
  });

  it("리딩 콜론 `:suffix` → prefix 가 빈 문자열 이면 'other'", () => {
    // `":suffix".split(":")[0] === ""` → falsy → 'other' fallback
    expect(normalizeGateCategory(":warning")).toBe("other");
    expect(normalizeGateCategory(":")).toBe("other");
  });
});

describe("colorForCategory", () => {
  it("known category: error/warning 색 분리", () => {
    const errorColor = colorForCategory("position_limit", "error");
    const warningColor = colorForCategory("position_limit", "warning");
    expect(errorColor).not.toBe(warningColor);
    expect(errorColor).toMatch(/^#/);
  });

  it("unknown category → 중립 fallback", () => {
    const errorColor = colorForCategory("mystery_gate", "error");
    const warningColor = colorForCategory("mystery_gate", "warning");
    expect(errorColor).toMatch(/^#/);
    expect(warningColor).toMatch(/^#/);
    expect(errorColor).not.toBe(warningColor);
  });
});

describe("formatCategoryLabel", () => {
  it("key `cat__sev` → `cat (sev)`", () => {
    expect(formatCategoryLabel("position_limit__error")).toBe("position_limit (error)");
    expect(formatCategoryLabel("data_fresh__warning")).toBe("data_fresh (warning)");
  });
});

describe("Recharts callback helpers", () => {
  it("tooltipValueFormatter: string name → formatted label, number value → string", () => {
    expect(tooltipValueFormatter(3, "position_limit__error")).toEqual([
      "3",
      "position_limit (error)",
    ]);
    expect(tooltipValueFormatter(0, "drift_safe__warning")).toEqual([
      "0",
      "drift_safe (warning)",
    ]);
  });

  it("tooltipValueFormatter: non-string name → String(name) fallback", () => {
    expect(tooltipValueFormatter(1, 42)).toEqual(["1", "42"]);
    expect(tooltipValueFormatter("x", null)).toEqual(["x", "null"]);
    expect(tooltipValueFormatter(undefined, undefined)).toEqual(["undefined", "undefined"]);
  });

  it("legendFormatter: string → label; non-string → String()", () => {
    expect(legendFormatter("external_data__warning")).toBe("external_data (warning)");
    expect(legendFormatter(42)).toBe("42");
    expect(legendFormatter(null)).toBe("null");
    expect(legendFormatter(undefined)).toBe("undefined");
  });
});

describe("buildGateFailureData", () => {
  it("passed=true condition 은 count 에 제외", () => {
    const p = makePoint({
      conditions: [
        makeCondition({ id: "position_limit", passed: true }),
        makeCondition({ id: "sector_limit", passed: false, severity: "error" }),
      ],
    });
    const data = buildGateFailureData([p]);
    expect(data.rows).toHaveLength(1);
    expect(data.rows[0]["sector_limit__error"]).toBe(1);
    expect(data.rows[0]["position_limit__error"]).toBeUndefined();
    expect(data.categories).toEqual([
      expect.objectContaining({ category: "sector_limit__error", severity: "error" }),
    ]);
  });

  it("multiple runs, category stable ordering (error → warning → alpha)", () => {
    const items = [
      makePoint({
        id: 2,
        conditions: [
          makeCondition({ id: "drift_safe", passed: false, severity: "warning" }),
        ],
      }),
      makePoint({
        id: 1,
        conditions: [
          makeCondition({ id: "position_limit", passed: false, severity: "error" }),
          makeCondition({ id: "external_data:us_equity", passed: false, severity: "warning" }),
        ],
      }),
    ];
    const data = buildGateFailureData(items);
    // oldest→newest 재정렬
    expect(data.rows[0].id).toBe(1);
    expect(data.rows[1].id).toBe(2);
    // category order: error first, then alphabetical among warnings
    expect(data.categories[0].severity).toBe("error");
    const warningCategories = data.categories.filter((c) => c.severity === "warning").map((c) => c.category);
    expect(warningCategories).toEqual([...warningCategories].sort());
  });

  it("같은 condition id 가 한 run 안에 여러 번 → count 누적", () => {
    const p = makePoint({
      conditions: [
        makeCondition({ id: "data_fresh:us_equity:primary", passed: false, severity: "warning" }),
        makeCondition({ id: "data_fresh:kr_equity:primary", passed: false, severity: "warning" }),
        makeCondition({ id: "data_fresh:kr_equity:secondary", passed: false, severity: "warning" }),
      ],
    });
    const data = buildGateFailureData([p]);
    expect(data.rows[0]["data_fresh__warning"]).toBe(3);
    expect(data.categories).toHaveLength(1);
  });

  it("runsWithIssues 집계 — all-passed run 은 제외", () => {
    const clean = makePoint({ id: 1, conditions: [makeCondition({ passed: true })] });
    const dirty = makePoint({ id: 2, conditions: [makeCondition({ passed: false })] });
    const data = buildGateFailureData([dirty, clean]);
    expect(data.totalRuns).toBe(2);
    expect(data.runsWithIssues).toBe(1);
  });

  it("정렬: error 만 → alpha; warning 만 → alpha; 혼합 → error before warning (양방향 검증)", () => {
    // warning → error 비교 (a.severity=warning → `: 1` branch)
    const items = [
      makePoint({
        id: 1,
        conditions: [
          makeCondition({ id: "zulu", passed: false, severity: "warning" }),
          makeCondition({ id: "alpha", passed: false, severity: "error" }),
        ],
      }),
    ];
    const { categories } = buildGateFailureData(items);
    expect(categories.map((c) => c.severity)).toEqual(["error", "warning"]);
    expect(categories.map((c) => c.category)).toEqual(["alpha__error", "zulu__warning"]);
  });

  it("category severity conflict — error 가 warning 을 이긴다", () => {
    const items = [
      makePoint({
        id: 2,
        conditions: [makeCondition({ id: "stop_loss", passed: false, severity: "warning" })],
      }),
      makePoint({
        id: 1,
        conditions: [makeCondition({ id: "stop_loss", passed: false, severity: "error" })],
      }),
    ];
    const data = buildGateFailureData(items);
    // 메타에는 error + warning 두 버킷 공존
    const keys = data.categories.map((c) => c.category);
    expect(keys).toContain("stop_loss__error");
    expect(keys).toContain("stop_loss__warning");
  });
});

describe("GateFailureChart rendering", () => {
  it("empty items → null (파일을 차지하지 않음)", () => {
    const { container } = render(<GateFailureChart items={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("모든 run passed → BarChart 대신 안내 문구", () => {
    const items = [
      makePoint({ id: 1, conditions: [makeCondition({ passed: true })] }),
      makePoint({ id: 2, conditions: [makeCondition({ passed: true })] }),
    ];
    render(<GateFailureChart items={items} />);
    expect(screen.getByText(/failed\/warning condition 없음/)).toBeInTheDocument();
    expect(screen.queryByTestId("bar-chart")).not.toBeInTheDocument();
  });

  it("failures 있으면 BarChart + category Bar 렌더", () => {
    const items = [
      makePoint({
        id: 1,
        conditions: [
          makeCondition({ id: "position_limit", passed: false, severity: "error" }),
          makeCondition({ id: "drift_safe", passed: false, severity: "warning" }),
        ],
      }),
    ];
    render(<GateFailureChart items={items} />);
    expect(screen.getByTestId("bar-chart")).toBeInTheDocument();
    expect(screen.getByTestId("bar-position_limit__error")).toBeInTheDocument();
    expect(screen.getByTestId("bar-drift_safe__warning")).toBeInTheDocument();
    expect(screen.getByText(/최근 1건/)).toBeInTheDocument();
    expect(screen.getByText(/stacked: category × severity/)).toBeInTheDocument();
  });

  it("conditions=undefined 도 안전하게 처리 (legacy row)", () => {
    const items = [makePoint({ id: 1, conditions: undefined })];
    render(<GateFailureChart items={items} />);
    expect(screen.getByText(/failed\/warning condition 없음/)).toBeInTheDocument();
  });
});
