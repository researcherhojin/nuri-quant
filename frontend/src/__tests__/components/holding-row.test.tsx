import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  HoldingRow,
  buildEnrichedHoldings,
  formatPrice,
  type RawHolding,
  type RawAction,
  type RawTarget,
  type RawAdvisorAction,
  type RawEvent,
  type EnrichedHolding,
} from "@/components/ui/holding-row";

vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: any) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

// ── helpers ──────────────────────────────────────────────────
function holdingFixture(overrides: Partial<EnrichedHolding> = {}): EnrichedHolding {
  return {
    account: "Main",
    ticker: "AAPL",
    name: "Apple Inc",
    currency: "USD",
    pnlPct: 5.2,
    dailyDeltaPct: null,
    sparkline: [],
    latestPrice: 105,
    avgPrice: 100,
    status: { kind: "hold" },
    stopLoss: 90,
    target1: 120,
    target2: 140,
    target1Reached: false,
    target2Reached: false,
    watch: { kind: "none" },
    sector: null,
    positionPct: null,
    ...overrides,
  };
}

const baseHolding: RawHolding = {
  ticker: "AAPL",
  account: "brokerage_alpha",
  accountLabel: "Main",
  quantity: 10,
  avg_price: 100,
  latest_price: 110,
  currency: "USD",
  name: "Apple Inc",
  sector: "Tech",
};

// ─────────────────────────────────────────────────────────────
// formatPrice
// ─────────────────────────────────────────────────────────────
describe("formatPrice", () => {
  it("formats null as em dash", () => {
    expect(formatPrice(null, "USD")).toBe("—");
  });
  it("formats KRW with won symbol and thousands separator", () => {
    expect(formatPrice(210000, "KRW")).toBe("₩210,000");
  });
  it("formats USD < 100 with 2 decimals", () => {
    expect(formatPrice(45.67, "USD")).toBe("$45.67");
  });
  it("formats USD >= 100 as integer with thousands separator", () => {
    expect(formatPrice(2345, "USD")).toBe("$2,345");
  });
});

// Sparkline SVG component has its own test file (sparkline.test.tsx).

// ─────────────────────────────────────────────────────────────
// buildEnrichedHoldings — status priority
// ─────────────────────────────────────────────────────────────
describe("buildEnrichedHoldings status priority", () => {
  it("returns hold when no action, no target trigger, no violation", () => {
    const result = buildEnrichedHoldings([baseHolding], [], [], [], []);
    expect(result).toHaveLength(1);
    expect(result[0].status.kind).toBe("hold");
  });

  it("returns buy when matching BUY action exists", () => {
    const action: RawAction = { action: "BUY", ticker: "AAPL", account: "Main", confidence: 78 };
    const result = buildEnrichedHoldings([baseHolding], [action], [], [], []);
    expect(result[0].status.kind).toBe("buy");
    if (result[0].status.kind === "buy") {
      expect(result[0].status.confidence).toBe(78);
    }
  });

  it("returns sell when matching SELL action exists", () => {
    const action: RawAction = { action: "SELL", ticker: "AAPL", account: "Main", confidence: 85 };
    const result = buildEnrichedHoldings([baseHolding], [action], [], [], []);
    expect(result[0].status.kind).toBe("sell");
  });

  it("returns tp1 when take_profit_triggered=target_1", () => {
    const target: RawTarget = { ticker: "AAPL", stop_loss: 90, target_1: 120, target_2: 140, take_profit_triggered: "target_1" };
    const result = buildEnrichedHoldings([baseHolding], [], [target], [], []);
    expect(result[0].status.kind).toBe("tp1");
    expect(result[0].target1Reached).toBe(true);
    expect(result[0].target2Reached).toBe(false);
  });

  it("returns tp2 when take_profit_triggered=target_2 (and target1Reached implied)", () => {
    const target: RawTarget = { ticker: "AAPL", stop_loss: 90, target_1: 120, target_2: 140, take_profit_triggered: "target_2" };
    const result = buildEnrichedHoldings([baseHolding], [], [target], [], []);
    expect(result[0].status.kind).toBe("tp2");
    expect(result[0].target1Reached).toBe(true);
    expect(result[0].target2Reached).toBe(true);
  });

  it("returns stop_loss when latest price drops below stop", () => {
    const holding = { ...baseHolding, latest_price: 80 };
    const target: RawTarget = { ticker: "AAPL", stop_loss: 90, target_1: 120, target_2: 140 };
    const result = buildEnrichedHoldings([holding], [], [target], [], []);
    expect(result[0].status.kind).toBe("stop_loss");
  });

  it("returns violation when advisor flags severity high with matching account in reason", () => {
    const advisor: RawAdvisorAction = {
      ticker: "AAPL",
      violation_type: "position_limit_exceeded",
      severity: "high",
      current_value: 22,
      reason: "brokerage_alpha 비중 22.0% > 한도 15%",
    };
    const result = buildEnrichedHoldings([baseHolding], [], [], [advisor], []);
    expect(result[0].status.kind).toBe("violation");
    if (result[0].status.kind === "violation") {
      expect(result[0].status.weight).toBe(22);
    }
  });

  it("ignores advisor severity medium/low", () => {
    const advisor: RawAdvisorAction = {
      ticker: "AAPL",
      violation_type: "position_limit_exceeded",
      severity: "medium",
      current_value: 16,
      reason: "brokerage_alpha 비중 16.0%",
    };
    const result = buildEnrichedHoldings([baseHolding], [], [], [advisor], []);
    expect(result[0].status.kind).toBe("hold");
  });

  it("stop_loss takes priority over violation and sell", () => {
    const holding = { ...baseHolding, latest_price: 80 };
    const action: RawAction = { action: "SELL", ticker: "AAPL", account: "Main", confidence: 80 };
    const target: RawTarget = { ticker: "AAPL", stop_loss: 90 };
    const advisor: RawAdvisorAction = {
      ticker: "AAPL",
      violation_type: "position_limit_exceeded",
      severity: "high",
      current_value: 30,
      reason: "brokerage_alpha 비중 30%",
    };
    const result = buildEnrichedHoldings([holding], [action], [target], [advisor], []);
    expect(result[0].status.kind).toBe("stop_loss");
  });
});

// ─────────────────────────────────────────────────────────────
// buildEnrichedHoldings — watch trigger
// ─────────────────────────────────────────────────────────────
// Build a YYYY-MM-DD string for `daysOffset` days from local today (timezone-safe)
function localDateOffset(daysOffset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + daysOffset);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

describe("buildEnrichedHoldings watch trigger", () => {
  it("returns earnings watch when upcoming earnings within 30 days", () => {
    const event: RawEvent = {
      date: localDateOffset(9),
      event_type: "earnings",
      ticker: "AAPL",
      description: "Apple Q1 earnings",
    };
    const result = buildEnrichedHoldings([baseHolding], [], [], [], [event]);
    expect(result[0].watch.kind).toBe("earnings");
    if (result[0].watch.kind === "earnings") {
      expect(result[0].watch.daysUntil).toBe(9);
    }
  });

  it("returns none when earnings > 30 days away", () => {
    const event: RawEvent = {
      date: localDateOffset(60),
      event_type: "earnings",
      ticker: "AAPL",
    };
    const result = buildEnrichedHoldings([baseHolding], [], [], [], [event]);
    expect(result[0].watch.kind).toBe("none");
  });

  it("ignores non-earnings events", () => {
    const event: RawEvent = {
      date: localDateOffset(5),
      event_type: "fomc",
      ticker: "AAPL",
    };
    const result = buildEnrichedHoldings([baseHolding], [], [], [], [event]);
    expect(result[0].watch.kind).toBe("none");
  });

  it("picks the nearest of multiple upcoming earnings (sort branch)", () => {
    // Multiple events for same ticker → sort by daysUntil ascending → pick first
    const events: RawEvent[] = [
      { date: localDateOffset(20), event_type: "earnings", ticker: "AAPL" },
      { date: localDateOffset(5), event_type: "earnings", ticker: "AAPL" },
      { date: localDateOffset(12), event_type: "earnings", ticker: "AAPL" },
    ];
    const result = buildEnrichedHoldings([baseHolding], [], [], [], events);
    expect(result[0].watch.kind).toBe("earnings");
    if (result[0].watch.kind === "earnings") {
      expect(result[0].watch.daysUntil).toBe(5);
    }
  });
});

// ─────────────────────────────────────────────────────────────
// buildEnrichedHoldings — sorting
// ─────────────────────────────────────────────────────────────
describe("buildEnrichedHoldings sorting", () => {
  it("sorts by account alphabetically, then status priority, then |pnl| desc", () => {
    const holdings: RawHolding[] = [
      { ticker: "AAA", accountLabel: "Sub", quantity: 10, avg_price: 100, latest_price: 105, currency: "USD" },
      { ticker: "BBB", accountLabel: "Main", quantity: 10, avg_price: 100, latest_price: 50, currency: "USD" },  // -50% pnl
      { ticker: "CCC", accountLabel: "Main", quantity: 10, avg_price: 100, latest_price: 102, currency: "USD" },
    ];
    const target: RawTarget = { ticker: "BBB", stop_loss: 80 };  // BBB triggers stop_loss (price 50 < 80)
    const result = buildEnrichedHoldings(holdings, [], [target], [], []);
    expect(result.map((h) => h.ticker)).toEqual(["BBB", "CCC", "AAA"]);
    expect(result[0].status.kind).toBe("stop_loss");  // Main BBB first (priority 1)
    expect(result[1].status.kind).toBe("hold");        // Main CCC (priority 7)
    expect(result[2].status.kind).toBe("hold");        // Sub AAA (alphabetical after Main)
  });
});

// ─────────────────────────────────────────────────────────────
// HoldingRow component rendering
// ─────────────────────────────────────────────────────────────
describe("HoldingRow", () => {
  it("renders ticker name, account label, and pnl", () => {
    render(<HoldingRow holding={holdingFixture()} />);
    expect(screen.getByText("Apple Inc")).toBeInTheDocument();
    expect(screen.getByText("Main")).toBeInTheDocument();
    expect(screen.getByText("+5.2%")).toBeInTheDocument();
  });

  it("renders 보유 status badge for hold", () => {
    render(<HoldingRow holding={holdingFixture()} />);
    expect(screen.getByText("보유")).toBeInTheDocument();
  });

  it("renders 매수 N status with confidence for buy", () => {
    render(<HoldingRow holding={holdingFixture({ status: { kind: "buy", confidence: 78 } })} />);
    expect(screen.getByText("매수 78")).toBeInTheDocument();
  });

  it("renders 매도 N status for sell", () => {
    render(<HoldingRow holding={holdingFixture({ status: { kind: "sell", confidence: 85 }, pnlPct: -3.0 })} />);
    expect(screen.getByText("매도 85")).toBeInTheDocument();
    expect(screen.getByText("-3.0%")).toBeInTheDocument();
  });

  it("renders ✓ 익절₁ when status is tp1", () => {
    render(<HoldingRow holding={holdingFixture({ status: { kind: "tp1" }, target1Reached: true })} />);
    expect(screen.getByText("✓ 익절₁")).toBeInTheDocument();
  });

  it("renders ✓ 익절₂ when status is tp2 (statusVisual tp2 branch)", () => {
    render(
      <HoldingRow
        holding={holdingFixture({
          status: { kind: "tp2" },
          target1Reached: true,
          target2Reached: true,
        })}
      />,
    );
    expect(screen.getByText("✓ 익절₂")).toBeInTheDocument();
  });

  it("renders 손절 status when stop_loss triggered", () => {
    render(<HoldingRow holding={holdingFixture({ status: { kind: "stop_loss" }, pnlPct: -8.5 })} />);
    expect(screen.getByText("손절")).toBeInTheDocument();
  });

  it("renders ⚠ 위반 status for violation", () => {
    render(<HoldingRow holding={holdingFixture({ status: { kind: "violation", weight: 22 } })} />);
    expect(screen.getByText("⚠ 위반")).toBeInTheDocument();
  });

  it("renders ✓ 도달 in target_1 cell when reached", () => {
    render(<HoldingRow holding={holdingFixture({ status: { kind: "tp1" }, target1Reached: true })} />);
    const reached = screen.getAllByText("✓ 도달");
    expect(reached.length).toBeGreaterThanOrEqual(1);
  });

  // watch column row-render tests removed in #221 iter 4 — column deleted from
  // the row (same info shown in the top 이벤트 strip). The buildEnrichedHoldings
  // tests below still cover the watch computation; only the visual column is gone.

  it("renders current price and avg price in compound cell (#214 polish)", () => {
    render(<HoldingRow holding={holdingFixture({ latestPrice: 245.67, avgPrice: 180 })} />);
    expect(screen.getByText("$246")).toBeInTheDocument();  // formatPrice rounds ≥100
    expect(screen.getByText("$180")).toBeInTheDocument();
  });

  it("renders em dash when latestPrice or avgPrice is null", () => {
    render(<HoldingRow holding={holdingFixture({ latestPrice: null, avgPrice: null })} />);
    const cell = screen.getByLabelText("현재가/평단가");
    expect(cell.textContent).toContain("—");
  });

  it("renders daily delta with + and color when positive", () => {
    render(<HoldingRow holding={holdingFixture({ dailyDeltaPct: 1.2 })} />);
    expect(screen.getByTestId("daily-delta")).toHaveTextContent("+1.2%");
  });

  it("renders daily delta with - for negative", () => {
    render(<HoldingRow holding={holdingFixture({ dailyDeltaPct: -0.4 })} />);
    expect(screen.getByTestId("daily-delta")).toHaveTextContent("-0.4%");
  });

  it("renders em dash in daily delta when dailyDeltaPct is null", () => {
    render(<HoldingRow holding={holdingFixture({ dailyDeltaPct: null })} />);
    expect(screen.getByTestId("daily-delta")).toHaveTextContent("—");
  });

  it("renders SVG sparkline for valid series (dual narrow/wide variants)", () => {
    render(<HoldingRow holding={holdingFixture({ sparkline: [100, 105, 103, 108, 110, 115, 112, 118] })} />);
    // HoldingRow renders two sparkline variants — 80px at xl (narrow) + 240px at 2xl (wide).
    // Both share the "sparkline" testid; CSS breakpoints show only one at a time.
    const sparks = screen.getAllByTestId("sparkline");
    expect(sparks).toHaveLength(2);
    for (const spark of sparks) {
      expect(spark.tagName.toLowerCase()).toBe("svg");
      expect(spark).toHaveAttribute("data-direction", "up");
    }
    const widths = sparks.map((s) => s.getAttribute("width"));
    expect(widths).toContain("80");
    expect(widths).toContain("240");
  });

  it("renders em dash sparkline placeholder for empty series", () => {
    render(<HoldingRow holding={holdingFixture({ sparkline: [] })} />);
    // Both narrow + wide variants fall back to em dash
    const sparks = screen.getAllByTestId("sparkline");
    expect(sparks).toHaveLength(2);
    for (const spark of sparks) {
      expect(spark).toHaveTextContent("—");
    }
  });

  it("renders em dash sparkline placeholder for single-point series", () => {
    render(<HoldingRow holding={holdingFixture({ sparkline: [100] })} />);
    const sparks = screen.getAllByTestId("sparkline");
    expect(sparks).toHaveLength(2);
    for (const spark of sparks) {
      expect(spark).toHaveTextContent("—");
    }
  });

  it("renders KRW prices with won symbol for .KS tickers", () => {
    render(
      <HoldingRow
        holding={holdingFixture({
          ticker: "005930.KS",
          name: "삼성전자",
          currency: "KRW",
          stopLoss: 195000,
          target1: 240000,
          target2: 280000,
        })}
      />,
    );
    expect(screen.getByText("₩195,000")).toBeInTheDocument();
    expect(screen.getByText("₩240,000")).toBeInTheDocument();
  });

  it("links to /ticker/{symbol}", () => {
    render(<HoldingRow holding={holdingFixture()} />);
    const link = screen.getByTestId("holding-row");
    expect(link).toHaveAttribute("href", "/ticker/AAPL");
  });

  it("uses href override when provided", () => {
    render(<HoldingRow holding={holdingFixture()} href="/portfolio?ticker=AAPL" />);
    const link = screen.getByTestId("holding-row");
    expect(link).toHaveAttribute("href", "/portfolio?ticker=AAPL");
  });

  // ── #218 wide-viewport columns (sector / position %) ──────
  describe("#218 wide-viewport columns", () => {
    it("renders sector text when present", () => {
      render(<HoldingRow holding={holdingFixture({ sector: "Semiconductor" })} />);
      expect(screen.getByTestId("sector-cell")).toHaveTextContent("Semiconductor");
    });

    it("renders em dash in sector cell when null", () => {
      render(<HoldingRow holding={holdingFixture({ sector: null })} />);
      expect(screen.getByTestId("sector-cell")).toHaveTextContent("—");
    });

    it("renders sector as title attribute for truncation tooltip", () => {
      render(<HoldingRow holding={holdingFixture({ sector: "Consumer Discretionary" })} />);
      expect(screen.getByTestId("sector-cell")).toHaveAttribute("title", "Consumer Discretionary");
    });

    it("renders positionPct with 1-decimal percent when present", () => {
      render(<HoldingRow holding={holdingFixture({ positionPct: 12.3456 })} />);
      expect(screen.getByTestId("position-pct-cell")).toHaveTextContent("12.3%");
    });

    it("renders em dash in position-pct cell when null", () => {
      render(<HoldingRow holding={holdingFixture({ positionPct: null })} />);
      expect(screen.getByTestId("position-pct-cell")).toHaveTextContent("—");
    });

    it("renders small positionPct rounded to one decimal", () => {
      render(<HoldingRow holding={holdingFixture({ positionPct: 0.04 })} />);
      expect(screen.getByTestId("position-pct-cell")).toHaveTextContent("0.0%");
    });
  });
});

// ─────────────────────────────────────────────────────────────
// buildEnrichedHoldings — #218 wide-viewport (sector / positionPct)
// ─────────────────────────────────────────────────────────────
describe("buildEnrichedHoldings wide-viewport fields", () => {
  it("copies sector from raw holding through to enriched", () => {
    const result = buildEnrichedHoldings([baseHolding], [], [], [], []);
    expect(result[0].sector).toBe("Tech");
  });

  it("sets sector to null when raw holding omits it", () => {
    const h: RawHolding = { ...baseHolding, sector: undefined };
    const result = buildEnrichedHoldings([h], [], [], [], []);
    expect(result[0].sector).toBeNull();
  });

  it("computes positionPct as USD value / totalPortfolioUsd", () => {
    // USD holding: 10 shares @ $110 = $1,100 (latest_price). totalPortfolioUsd = $10,000 → 11%
    const result = buildEnrichedHoldings(
      [baseHolding],
      [],
      [],
      [],
      [],
      { totalPortfolioUsd: 10_000, usdKrwRate: 1400 },
    );
    expect(result[0].positionPct).not.toBeNull();
    expect(result[0].positionPct).toBeCloseTo(11, 5);
  });

  it("converts KRW holding to USD before computing positionPct", () => {
    // KR holding: 2 shares @ ₩1,400,000 = ₩2,800,000 / 1400 rate = $2,000. total $10,000 → 20%
    const krHolding: RawHolding = {
      ticker: "005930.KS",
      accountLabel: "Main",
      quantity: 2,
      avg_price: 1_000_000,
      latest_price: 1_400_000,
      currency: "KRW",
    };
    const result = buildEnrichedHoldings(
      [krHolding],
      [],
      [],
      [],
      [],
      { totalPortfolioUsd: 10_000, usdKrwRate: 1400 },
    );
    expect(result[0].positionPct).toBeCloseTo(20, 5);
  });

  it("returns null positionPct when totalPortfolioUsd is zero or missing", () => {
    const result = buildEnrichedHoldings([baseHolding], [], [], [], []);
    expect(result[0].positionPct).toBeNull();
  });

  it("returns null positionPct for KRW holding when usdKrwRate is 0", () => {
    const krHolding: RawHolding = {
      ticker: "005930.KS",
      accountLabel: "Main",
      quantity: 2,
      avg_price: 1_000_000,
      latest_price: 1_400_000,
      currency: "KRW",
    };
    const result = buildEnrichedHoldings(
      [krHolding],
      [],
      [],
      [],
      [],
      { totalPortfolioUsd: 10_000 },  // usdKrwRate omitted
    );
    expect(result[0].positionPct).toBeNull();
  });

  it("falls back to qty=0 when raw holding omits quantity (?? branch)", () => {
    // Covers BRDA:203 — `const qty = h.quantity ?? 0` when quantity is undefined.
    // Without the fallback the multiplier would throw NaN; with it, positionPct is 0.
    const noQty: RawHolding = { ...baseHolding, quantity: undefined };
    const result = buildEnrichedHoldings(
      [noQty],
      [],
      [],
      [],
      [],
      { totalPortfolioUsd: 10_000 },
    );
    expect(result[0].positionPct).toBe(0);
  });
});
