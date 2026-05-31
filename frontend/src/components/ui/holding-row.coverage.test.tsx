/**
 * holding-row coverage — residual statements.
 *
 * 1) line 183 (malformed earnings date guard): buildEnrichedHoldings 의
 *    earnings-date 파서는 YYYY-MM-DD 를 split 해서 [y, m, d] 로 받는다. date
 *    문자열이 형식을 벗어나면 Number() 가 NaN 을 내고
 *    `if (!y || !m || !d) return { ev, days: Number.NaN }` 가도록 방어한다.
 * 2) line 120 (null-ticker event skip): upcomingEvents 의 ticker 가 falsy 면 continue.
 * 3) line 254 (sort |pnl| tiebreaker): account·status 가 같으면 |pnl| desc 로 정렬.
 * 4) line 308 (displayName fallback): name 이 없으면 ticker 에서 ".KS" 를 떼어 표시.
 *
 * recharts import 없음 (recharts-hoist gotcha 무관). next/link 만 mock.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { AnchorHTMLAttributes, ReactNode } from "react";

import {
  HoldingRow,
  buildEnrichedHoldings,
  type RawHolding,
  type RawEvent,
  type EnrichedHolding,
} from "@/components/ui/holding-row";

vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: ReactNode; href: string } & AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

function enrichedFixture(overrides: Partial<EnrichedHolding> = {}): EnrichedHolding {
  return {
    account: "Brokerage Alpha",
    ticker: "AAPL",
    name: "Apple Inc",
    currency: "USD",
    pnlPct: 5,
    dailyDeltaPct: null,
    sparkline: [],
    latestPrice: 120,
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
  accountLabel: "Brokerage Alpha",
  quantity: 10,
  avg_price: 100,
  latest_price: 120,
  currency: "USD",
};

describe("buildEnrichedHoldings — malformed earnings date guard (line 183)", () => {
  it("treats a non-date earnings string as no upcoming earnings", () => {
    const events: RawEvent[] = [
      {
        date: "not-a-date", // split("-") → ["not","a","date"] → map(Number) → [NaN,NaN,NaN]
        event_type: "earnings",
        ticker: "AAPL",
      },
    ];

    const [enriched] = buildEnrichedHoldings([baseHolding], [], [], [], events);

    // 가드가 NaN days 를 반환 → filter 에서 탈락 → watch = none
    expect(enriched.watch).toEqual({ kind: "none" });
  });

  it("treats a partially-numeric earnings date (missing day) as no upcoming earnings", () => {
    const events: RawEvent[] = [
      {
        date: "2026-06-", // split → ["2026","06",""] → d = Number("") = 0 → falsy
        event_type: "earnings",
        ticker: "AAPL",
      },
    ];

    const [enriched] = buildEnrichedHoldings([baseHolding], [], [], [], events);

    expect(enriched.watch).toEqual({ kind: "none" });
  });

  it("still resolves a well-formed upcoming earnings date (guard not triggered)", () => {
    const future = new Date();
    future.setDate(future.getDate() + 5);
    const yyyy = future.getFullYear();
    const mm = String(future.getMonth() + 1).padStart(2, "0");
    const dd = String(future.getDate()).padStart(2, "0");

    const events: RawEvent[] = [
      {
        date: `${yyyy}-${mm}-${dd}`,
        event_type: "earnings",
        ticker: "AAPL",
      },
    ];

    const [enriched] = buildEnrichedHoldings([baseHolding], [], [], [], events);

    expect(enriched.watch).toEqual({ kind: "earnings", daysUntil: 5 });
  });

  it("skips an upcoming event whose ticker is null (line 120 continue)", () => {
    // ticker 가 null → `if (!ev.ticker) continue` 분기 실행. 해당 이벤트는
    // earningsByTicker 에 들어가지 않으므로 watch 는 none.
    const events: RawEvent[] = [
      { date: "2026-06-15", event_type: "earnings", ticker: null },
    ];

    const [enriched] = buildEnrichedHoldings([baseHolding], [], [], [], events);

    expect(enriched.watch).toEqual({ kind: "none" });
  });
});

describe("buildEnrichedHoldings — sort |pnl| tiebreaker (line 254)", () => {
  it("orders same-account, same-status holdings by absolute pnl desc", () => {
    // 두 종목 모두 동일 account + 동일 status(hold) → sort 비교자가 account 분기와
    // status-priority 분기를 모두 통과해 라인 254(|pnl| desc tiebreaker)에 도달한다.
    const holdings: RawHolding[] = [
      // +10% pnl
      { ticker: "MSFT", accountLabel: "Brokerage Alpha", quantity: 1, avg_price: 100, latest_price: 110, currency: "USD" },
      // +50% pnl (더 큰 |pnl| → 앞으로 정렬)
      { ticker: "NVDA", accountLabel: "Brokerage Alpha", quantity: 1, avg_price: 100, latest_price: 150, currency: "USD" },
    ];

    const result = buildEnrichedHoldings(holdings, [], [], [], []);

    expect(result.map((h) => h.ticker)).toEqual(["NVDA", "MSFT"]);
  });
});

describe("HoldingRow — displayName fallback (line 308)", () => {
  it("strips .KS from ticker as display name when name is null", () => {
    // name 이 falsy → `h.ticker.replace(".KS", "")` 분기 실행.
    render(<HoldingRow holding={enrichedFixture({ name: null, ticker: "005930.KS", currency: "KRW" })} />);

    expect(screen.getByText("005930")).toBeInTheDocument();
  });
});
