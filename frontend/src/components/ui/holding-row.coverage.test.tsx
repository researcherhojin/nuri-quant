/**
 * holding-row coverage — line 183 (malformed earnings date guard).
 *
 * buildEnrichedHoldings 의 earnings-date 파서는 YYYY-MM-DD 를 split 해서
 * [y, m, d] 로 받는다. date 문자열이 형식을 벗어나면 Number() 가 NaN 을 내고
 * `if (!y || !m || !d) return { ev, days: Number.NaN }` 가도록 방어한다.
 * 이 가드(라인 183)를 실제로 통과시켜 watch 가 earnings 로 잡히지 않음을 검증한다.
 *
 * 순수 함수만 호출 — 컴포넌트/recharts import 없음 (recharts-hoist gotcha 무관).
 */
import { describe, it, expect } from "vitest";

import {
  buildEnrichedHoldings,
  type RawHolding,
  type RawEvent,
} from "@/components/ui/holding-row";

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
});
