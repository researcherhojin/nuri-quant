import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// Server Component 데이터 패칭은 fetchAPI(@/lib/api) 사용 → 모킹 (기존 *.coverage.test.tsx 스타일)
vi.mock("@/lib/api", () => ({
  fetchAPI: vi.fn(),
}));

// PriceChartLazy 는 recharts/next-dynamic client 컴포넌트 → 가벼운 stub 으로 mock
// (recharts hoist gotcha 회피). prices 가 있는 fixture 에서 차트 섹션을 렌더하기 위함.
vi.mock("@/components/ui/price-chart-lazy", () => ({
  PriceChartLazy: () => <div data-testid="price-chart" />,
}));

import { fetchAPI } from "@/lib/api";
import { TickerDetail } from "./page";

const mockFetchAPI = vi.mocked(fetchAPI);

// 4개의 Promise.all fetch (data, prices, targets, external) 순서대로 resolve 값 지정
function setupFetches(opts: {
  data: Record<string, unknown>;
  prices?: Record<string, unknown>;
  targets?: Record<string, unknown> | null;
  external?: Record<string, unknown> | null;
}) {
  const prices = opts.prices ?? { prices: [] };
  const targets = "targets" in opts ? opts.targets : null;
  const external = "external" in opts ? opts.external : null;
  mockFetchAPI.mockImplementation((path: string) => {
    if (path.includes("/prices")) return Promise.resolve(prices);
    if (path.includes("/targets/")) return Promise.resolve(targets);
    if (path.includes("/external/")) return Promise.resolve(external);
    return Promise.resolve(opts.data);
  });
}

describe("TickerDetail branch coverage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ----- FALSY / FALLBACK arms -----
  // L112-117: consensus/analyst_ratings/earnings/insider_trades/superinvestors 모두 부재
  //           → 각 `|| {}` / `|| []` 우측 fallback arm.
  // L141 falsy: data.name 부재 → `data.name &&` falsy arm (ticker span 미렌더).
  // L143/146/149/152 falsy: price.close / final_action / final_confidence / agreement_rate 부재.
  // L158 falsy: prices 빈배열 → price chart 섹션 미렌더.
  // L183 falsy: dissent 부재.
  // L227/237 falsy: earnings/insiders 빈 → "No ... data" 분기.
  it("uses default fallbacks when all optional collections are absent", async () => {
    setupFetches({ data: { ticker: "AAPL" } });
    const jsx = await TickerDetail({ symbol: "AAPL" });
    render(jsx);

    expect(screen.getByText("Analyst Ratings (0)")).toBeInTheDocument();
    expect(screen.getByText("Earnings (0Q)")).toBeInTheDocument();
    expect(screen.getByText("Insider Activity (0)")).toBeInTheDocument();
    // L141 falsy: data.name 없으면 h1 은 ticker, 별도 ticker span 은 없음 (AAPL 1회만)
    expect(screen.getAllByText("AAPL")).toHaveLength(1);
    // L158 falsy: 차트 미렌더
    expect(screen.queryByTestId("price-chart")).not.toBeInTheDocument();
    // L227/237 falsy: 빈 상태 문구
    expect(screen.getByText("No rating data")).toBeInTheDocument();
    expect(screen.getByText("No earnings data")).toBeInTheDocument();
    expect(screen.getByText("No insider data")).toBeInTheDocument();
    // Smart Money / Fundamentals 섹션 미렌더 (supers 빈배열, fund undefined)
    expect(screen.queryByText(/Smart Money/)).not.toBeInTheDocument();
    expect(screen.queryByText("Fundamentals")).not.toBeInTheDocument();
  });

  // L209: r.action 이 up/upgrade/down/downgrade 어느 것도 아님 → 중첩 삼항의 HOLD arm.
  it("renders HOLD badge for analyst rating with non-directional action", async () => {
    setupFetches({
      data: {
        ticker: "AAPL",
        analyst_ratings: [{ firm: "GS", action: "maintain", date: "2026-05-01" }],
      },
    });
    const jsx = await TickerDetail({ symbol: "AAPL" });
    render(jsx);
    expect(screen.getByText("GS")).toBeInTheDocument();
    expect(screen.getByText("HOLD")).toBeInTheDocument();
  });

  // L261: roe <= 0.15 → "default" arm.
  // L263: revenue_growth <= 0 → "red" arm.
  // L267: profit_margin <= 0.1 → "default" arm.
  it("renders fundamentals with below-threshold color arms", async () => {
    setupFetches({
      data: {
        ticker: "AAPL",
        fundamentals: {
          pe_ratio: 20,
          roe: 0.1, // <= 0.15 → default
          revenue_growth: -0.05, // <= 0 → red
          debt_to_equity: 0.5,
          profit_margin: 0.05, // <= 0.1 → default
          beta: 1.2,
        },
      },
    });
    const jsx = await TickerDetail({ symbol: "AAPL" });
    render(jsx);
    expect(screen.getByText("ROE")).toBeInTheDocument();
    expect(screen.getByText("Rev Growth")).toBeInTheDocument();
    expect(screen.getByText("Margin")).toBeInTheDocument();
    expect(screen.getByText("-5%")).toBeInTheDocument();
  });

  // L302 (id43-a0): analyst_target 존재 + analyst_upside_pct === null
  //   → `analyst_upside_pct ?? 0` nullish-우측(0) arm + `(... ?? 0) > 0` false → 부호 "" arm.
  it("renders analyst target with null upside (no plus sign)", async () => {
    setupFetches({
      data: { ticker: "AAPL" },
      targets: {
        stock_type: "growth",
        stop_loss: 90,
        stop_loss_pct: -7,
        target_1: 120,
        target_1_pct: 20,
        target_2: 140,
        target_2_pct: 40,
        trailing_stop_pct: -15,
        analyst_target: 130,
        analyst_upside_pct: null,
      },
    });
    const jsx = await TickerDetail({ symbol: "AAPL" });
    render(jsx);
    expect(screen.getByText(/Price Targets/)).toBeInTheDocument();
    const analystLine = screen.getByText(/\$130\.00/);
    expect(analystLine.textContent).not.toContain("+");
  });

  // ----- TRUTHY / HAPPY-PATH arms (fully populated fixture) -----
  // 커버:
  //  L123-127: earnings 필드 present → `?.`/`??`/`||`/삼항 좌측.
  //  L141 truthy: data.name → ticker span 렌더.
  //  L143 truthy: price.close. L146/149/152 truthy: consensus 필드.
  //  L158 truthy: prices 존재 → 차트. L183 truthy: dissent.
  //  L208/209: action up→BUY, down→SELL. L213 truthy: target_price.
  //  L227/237 truthy: 테이블/insider 렌더. L241 sale→SELL & non-sale→BUY.
  //  L245 value present → $M, value 부재 → shares.
  //  L261/263/267 green arms (above threshold). L277 truthy: supers.
  //  L302 (id43 true): analyst_upside_pct > 0 → "+".
  //  L310/311 truthy: external.count > 0.
  it("renders all truthy/happy-path arms with a fully populated payload", async () => {
    setupFetches({
      data: {
        ticker: "AAPL",
        name: "Apple Inc.",
        price: { close: 195.5 },
        consensus: {
          final_action: "BUY",
          final_confidence: 82,
          agreement_rate: 0.9,
          verdicts: [{ agent_name: "momentum", action: "BUY", confidence: 80 }],
          dissent: ["valuation agent: overvalued"],
        },
        analyst_ratings: [
          { firm: "MS", action: "up", date: "2026-05-02", target_price: 220 },
          { firm: "JPM", action: "down", date: "2026-04-15" },
        ],
        earnings: [
          {
            quarter: "2026-Q1-extra",
            eps_actual: 1.52,
            eps_estimate: 1.4,
            surprise_pct: 0.085,
          },
        ],
        insider_trades: [
          { insider_name: "Jane Doe", transaction_type: "sale", value: 5000000 },
          { insider_name: "John Roe", transaction_type: "buy", shares: 1200 },
        ],
        superinvestors: [{ investor: "Big Fund", portfolio_pct: 4.2 }],
        fundamentals: {
          pe_ratio: 28,
          roe: 0.3, // > 0.15 → green
          revenue_growth: 0.12, // > 0 → green
          debt_to_equity: 1.1,
          profit_margin: 0.25, // > 0.1 → green
          beta: 1.05,
        },
      },
      prices: {
        prices: [
          { date: "2026-05-01", open: 1, high: 2, low: 0.5, close: 1.5, volume: 1000 },
        ],
      },
      targets: {
        stock_type: "growth",
        stop_loss: 180,
        stop_loss_pct: -7,
        target_1: 234,
        target_1_pct: 20,
        target_2: 273,
        target_2_pct: 40,
        trailing_stop_pct: -15,
        analyst_target: 220,
        analyst_upside_pct: 12.5, // > 0 → "+"
      },
      external: {
        count: 1,
        data: [{ source: "tipranks", data_type: "rating", value: "Strong Buy" }],
      },
    });

    const jsx = await TickerDetail({ symbol: "AAPL" });
    render(jsx);

    // L141 truthy: name 헤더 + ticker span 둘 다
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    // L143 truthy: 가격
    expect(screen.getByText(/195\.5/)).toBeInTheDocument();
    // L146/149/152 truthy: consensus 표시
    expect(screen.getByText("82")).toBeInTheDocument();
    expect(screen.getByText("90% agree")).toBeInTheDocument();
    // L158 truthy: 차트
    expect(screen.getByTestId("price-chart")).toBeInTheDocument();
    // L183 truthy: dissent
    expect(screen.getByText("valuation agent: overvalued")).toBeInTheDocument();
    // L208/209: BUY + SELL 배지 (up→BUY, down→SELL)
    expect(screen.getByText("MS")).toBeInTheDocument();
    expect(screen.getByText("JPM")).toBeInTheDocument();
    // L213 truthy: target_price
    expect(screen.getByText("$220")).toBeInTheDocument();
    // L227 truthy: earnings 테이블 (No earnings data 없음)
    expect(screen.queryByText("No earnings data")).not.toBeInTheDocument();
    // L237 truthy: insider 렌더 (sale value→$M, buy shares)
    expect(screen.getByText("$5.0M")).toBeInTheDocument();
    expect(screen.getByText("1,200 sh")).toBeInTheDocument();
    // L277 truthy: smart money
    expect(screen.getByText("Big Fund")).toBeInTheDocument();
    // L302 truthy: analyst_upside_pct > 0 → "+" 포함
    const analystLine = screen.getByText(/\$220\.00/);
    expect(analystLine.textContent).toContain("+");
    // L310/311 truthy: external 데이터
    expect(screen.getByText("External Data (1)")).toBeInTheDocument();
    expect(screen.getByText("Strong Buy")).toBeInTheDocument();
  });

  // L123-127 (id6-10) 우측 arms: earnings 필드가 부재한 행 → `?.`/`??`/`||` 우측 ("—"),
  //   surprise_pct 삼항의 false arm 및 `(e.surprise_pct || 0)` 우측(0).
  it("renders earnings em-dash fallbacks when fields are missing", async () => {
    setupFetches({
      data: {
        ticker: "AAPL",
        earnings: [{}], // 모든 필드 부재 → quarter/actual/est/surprise 모두 "—"
      },
    });
    const jsx = await TickerDetail({ symbol: "AAPL" });
    render(jsx);
    expect(screen.getByText("Earnings (1Q)")).toBeInTheDocument();
    // DataTable 이 "—" fallback 들을 렌더 (quarter/actual/est/surprise)
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
  });
});
