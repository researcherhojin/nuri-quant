/**
 * Evidence 네이티브 차트 5종 (#1225 U5a-2).
 *
 * Recharts mock scope 주의: 같은 worker 의 다른 테스트와 충돌하지 않도록
 * 이 파일에서 쓰는 모든 recharts 컴포넌트를 broad mock (gate-failure-chart 관례).
 * 순수 헬퍼(색·행 변환)는 mock 없이 직접 단언.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ComposedChart: ({ children }: { children: React.ReactNode }) => <div data-testid="composed-chart">{children}</div>,
  LineChart: ({ children }: { children: React.ReactNode }) => <div data-testid="line-chart">{children}</div>,
  BarChart: ({ children }: { children: React.ReactNode }) => <div data-testid="bar-chart">{children}</div>,
  // content 람다까지 실행해 커버 — 실제 recharts 가 TreemapNode 를 넘기는 자리
  Treemap: (props: { children?: React.ReactNode; content?: (p: unknown) => React.ReactElement }) => (
    <div data-testid="treemap">
      <svg>
        {props.content?.({ x: 0, y: 0, width: 100, height: 50, depth: 1, name: "AAA", pnl_pct: -12, violation: "stop_loss" })}
      </svg>
      {props.children}
    </div>
  ),
  Area: () => null,
  Line: () => null,
  Bar: ({ children }: { children?: React.ReactNode }) => <div data-testid="bar">{children}</div>,
  Cell: (props: Record<string, unknown>) => <div data-testid="cell" data-fill={String(props.fill)} />,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ReferenceLine: () => null,
  ReferenceArea: (props: Record<string, unknown>) => <div data-testid="reference-area" data-y1={String(props.y1)} />,
}));

import {
  pnlColor,
  DRIFT_COLORS,
  VIOLATION_COLORS,
  type RegimeData,
  type HeatmapData,
  type SignalPerformanceData,
  type FearGreedData,
  type SellEvidenceData,
} from "@/components/evidence/chart-data";
import {
  RegimeChart,
  buildRegimeRows,
  priceTick,
  regimeChipLabel,
  VIX_BLOCK_LEVEL,
} from "@/components/evidence/regime-chart";
import {
  PortfolioTreemap,
  TreemapCell,
  buildTreemapData,
  cellStroke,
  valueTooltipFormatter,
} from "@/components/evidence/portfolio-treemap";
import {
  SignalPerformanceChart,
  driftColor,
  signalTooltipFormatter,
  winRateTick,
} from "@/components/evidence/signal-performance-chart";
import { FearGreedChart, FG_ZONES, fgTooltipFormatter, zoneLabel } from "@/components/evidence/fear-greed-chart";
import {
  SellEvidenceChart,
  buildSellRows,
  sellTooltipFormatter,
  severityTick,
} from "@/components/evidence/sell-evidence-chart";

// ── fixtures (형태는 API 실응답에서 복사 — mock-shape 규칙) ──

const REGIME: RegimeData = {
  spy: [
    { date: "2026-08-20", open: 1, high: 2, low: 1, close: 100, volume: 10, sma50: null, sma200: null },
    { date: "2026-08-21", open: 1, high: 2, low: 1, close: 102, volume: 12, sma50: 101, sma200: null },
  ],
  vix: [{ date: "2026-08-21", value: 18.5 }],
  regime: { regime: "bull_low_vol", trend: "bull", volatility: "low", confidence: 0.8 },
  count: 2,
};

const HEATMAP: HeatmapData = {
  items: [
    { ticker: "AAA", current_value_usd: 5000, pnl_pct: -12.0, weight_pct: 20.0, sector: "Tech", violation: "stop_loss" },
    { ticker: "BBB", current_value_usd: 0, pnl_pct: 3.0, weight_pct: 8.0, sector: null, violation: null },
  ],
  count: 2,
};

const SIGNALS: SignalPerformanceData = {
  signals: [
    { signal_id: "rsi_oversold", win_rate: 0.6, profit_factor: 1.5, total_trades: 10, drift_status: "critical" },
    { signal_id: "macd_golden", win_rate: 0.5, profit_factor: 1.2, total_trades: 8, drift_status: "stable" },
  ],
  count: 2,
};

const FEAR_GREED: FearGreedData = {
  history: [
    { date: "2026-08-20", value: 40 },
    { date: "2026-08-21", value: 62 },
  ],
  count: 2,
};

const SELL: SellEvidenceData = {
  violations: [
    { ticker: "AAA", type: "stop_loss", severity: 12.0, action: "SELL ALL", recovery: "손실 12.0% → 회복에 14% 상승 필요" },
    { ticker: "BBB", type: "overweight", severity: 5.0, action: "REDUCE", recovery: "비중 20.0% → 15%까지 리밸런싱 필요" },
  ],
  count: 2,
};

// ── 순수 헬퍼 ──

describe("chart-data helpers", () => {
  it("pnlColor buckets: 손실=빨강 계열, 0 근처=회색, 이익=초록 계열", () => {
    expect(pnlColor(-15)).toBe("#d32f2f");
    expect(pnlColor(-5)).toBe("#ef5350");
    expect(pnlColor(0)).toBe("#616161");
    expect(pnlColor(5)).toBe("#66bb6a");
    expect(pnlColor(25)).toBe("#2e7d32");
  });

  it("driftColor: critical/degrading 은 경고색, 그 외 기본색", () => {
    expect(driftColor("critical")).toBe(DRIFT_COLORS.critical);
    expect(driftColor("degrading")).toBe(DRIFT_COLORS.degrading);
    expect(driftColor("stable")).toBe("var(--chart-1)");
  });

  it("zoneLabel: FG 구간 경계", () => {
    expect(zoneLabel(10)).toBe("극단 공포");
    expect(zoneLabel(50)).toBe("중립");
    expect(zoneLabel(80)).toBe("극단 탐욕");
    expect(zoneLabel(100)).toBe("극단 탐욕");
  });

  it("VIX 차단선은 rules.yaml 의 30", () => {
    expect(VIX_BLOCK_LEVEL).toBe(30);
  });

  it("축 눈금 포매터", () => {
    expect(priceTick(101.4)).toBe("101");
    expect(winRateTick(0.55)).toBe("55%");
    expect(severityTick(12.3)).toBe("12%");
  });

  it("툴팁 포매터", () => {
    expect(fgTooltipFormatter(61.7)).toEqual(["62", "지수"]);
    expect(valueTooltipFormatter(5000)).toEqual(["$5,000", "가치"]);
    expect(signalTooltipFormatter(0.612, "win_rate")).toEqual(["61.2%", "승률"]);
    expect(signalTooltipFormatter(1.5, "profit_factor")).toEqual(["1.50", "PF"]);
    expect(signalTooltipFormatter("x", "other")).toEqual(["x", "other"]);
    const row = buildSellRows(SELL)[0];
    expect(sellTooltipFormatter(12.04, "severity", { payload: row })).toEqual([
      "12.0%",
      "SELL ALL — 손실 12.0% → 회복에 14% 상승 필요",
    ]);
    expect(sellTooltipFormatter(12.04, "severity", undefined)).toEqual(["12.0%", "심각도"]);
  });
});

describe("buildRegimeRows / regimeChipLabel", () => {
  it("날짜를 MM-DD 로 축약하고 SPY/VIX 행을 분리", () => {
    const { spy, vix } = buildRegimeRows(REGIME);
    expect(spy[0]).toEqual({ date: "08-20", close: 100, sma50: null, sma200: null });
    expect(vix[0]).toEqual({ date: "08-21", vix: 18.5 });
  });

  it("레짐 칩: 상태 + 신뢰도, 없으면 null", () => {
    expect(regimeChipLabel(REGIME.regime)).toBe("bull_low_vol · 신뢰도 80%");
    expect(regimeChipLabel(null)).toBeNull();
  });
});

describe("buildTreemapData / cellStroke / TreemapCell", () => {
  it("가치 0 이하는 1 로 클립, violation 전달", () => {
    const rows = buildTreemapData(HEATMAP);
    expect(rows[0]).toMatchObject({ name: "AAA", size: 5000, violation: "stop_loss" });
    expect(rows[1].size).toBe(1);
  });

  it("cellStroke: 위반별 테두리색, 정상은 경계색", () => {
    expect(cellStroke("stop_loss")).toBe(VIOLATION_COLORS.stop_loss);
    expect(cellStroke("overweight")).toBe(VIOLATION_COLORS.overweight);
    expect(cellStroke(null)).toBe("#27272a");
  });

  it("TreemapCell: 넓은 셀은 티커+손익 라벨, depth 0 은 빈 그룹", () => {
    const { container } = render(
      <svg>
        <TreemapCell x={0} y={0} width={100} height={50} name="AAA" pnl_pct={-12} violation="stop_loss" depth={1} />
      </svg>,
    );
    expect(container.textContent).toContain("AAA");
    expect(container.textContent).toContain("-12.0%");
    const rect = container.querySelector("rect");
    expect(rect?.getAttribute("fill")).toBe("#d32f2f");
    expect(rect?.getAttribute("stroke")).toBe(VIOLATION_COLORS.stop_loss);

    const root = render(
      <svg>
        <TreemapCell x={0} y={0} width={100} height={50} depth={0} />
      </svg>,
    );
    expect(root.container.querySelector("rect")).toBeNull();
  });

  it("좁은 셀은 라벨 생략", () => {
    const { container } = render(
      <svg>
        <TreemapCell x={0} y={0} width={30} height={15} name="AAA" pnl_pct={3} depth={1} />
      </svg>,
    );
    expect(container.textContent).not.toContain("AAA");
  });

  it("양수 손익은 + 부호, props 생략 시 0 기본값으로 렌더", () => {
    const wide = render(
      <svg>
        <TreemapCell x={0} y={0} width={100} height={50} name="BBB" pnl_pct={3} depth={1} />
      </svg>,
    );
    expect(wide.container.textContent).toContain("+3.0%");

    // recharts 가 빈 props 로 부르는 방어 경로 — 기본값 0 destructure
    const bare = render(
      <svg>
        <TreemapCell depth={1} />
      </svg>,
    );
    const rect = bare.container.querySelector("rect");
    expect(rect?.getAttribute("width")).toBe("0");
    expect(rect?.getAttribute("fill")).toBe(pnlColor(0));
  });
});

describe("buildSellRows", () => {
  it("티커 · 위반유형 한글 라벨 조립", () => {
    const rows = buildSellRows(SELL);
    expect(rows[0].label).toBe("AAA · 손절");
    expect(rows[1].label).toBe("BBB · 비중");
  });
});

// ── 렌더 (recharts broad mock) ──

describe("chart components render", () => {
  it("RegimeChart: 칩 + 메인/VIX 서브차트 + 범례", () => {
    render(<RegimeChart data={REGIME} />);
    expect(screen.getByText("bull_low_vol · 신뢰도 80%")).toBeInTheDocument();
    expect(screen.getByTestId("vix-subchart")).toBeInTheDocument();
    expect(screen.getByText("SMA200")).toBeInTheDocument();
  });

  it("RegimeChart: VIX 없으면 서브차트 생략", () => {
    render(<RegimeChart data={{ ...REGIME, vix: [], regime: null }} />);
    expect(screen.queryByTestId("vix-subchart")).not.toBeInTheDocument();
    expect(screen.queryByText(/신뢰도/)).not.toBeInTheDocument();
  });

  it("PortfolioTreemap: treemap + 위반 범례", () => {
    render(<PortfolioTreemap data={HEATMAP} />);
    expect(screen.getByTestId("treemap")).toBeInTheDocument();
    expect(screen.getByText("손절 위반")).toBeInTheDocument();
    expect(screen.getByText("비중 초과")).toBeInTheDocument();
  });

  it("SignalPerformanceChart: 드리프트 색 Cell + 범례", () => {
    render(<SignalPerformanceChart data={SIGNALS} />);
    const cells = screen.getAllByTestId("cell");
    expect(cells.map((c) => c.getAttribute("data-fill"))).toEqual([DRIFT_COLORS.critical, "var(--chart-1)"]);
    expect(screen.getByText("Profit Factor")).toBeInTheDocument();
  });

  it("FearGreedChart: 현재값 칩 + 존 5개", () => {
    render(<FearGreedChart data={FEAR_GREED} />);
    expect(screen.getByText("현재 62 · 탐욕")).toBeInTheDocument();
    expect(screen.getAllByTestId("reference-area").length).toBe(FG_ZONES.length);
  });

  it("SellEvidenceChart: 위반 타입별 색 Cell", () => {
    render(<SellEvidenceChart data={SELL} />);
    const cells = screen.getAllByTestId("cell");
    expect(cells.map((c) => c.getAttribute("data-fill"))).toEqual([
      VIOLATION_COLORS.stop_loss,
      VIOLATION_COLORS.overweight,
    ]);
  });
});
