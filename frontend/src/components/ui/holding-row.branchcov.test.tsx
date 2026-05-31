/**
 * holding-row branch coverage — residual conditional/binary arms.
 *
 * 기존 holding-row.coverage.test.tsx 가 커버하지 못한 buildEnrichedHoldings 의
 * fallback / 옵셔널 필드 분기들을 메운다.
 *
 *  - line 139 `h.accountLabel ?? accountRaw` 의 우측 arm (accountLabel 누락)
 *  - line 164 `advisor.current_value ?? 0` 의 우측 arm (current_value 누락)
 *  - line 197 `prevClose != null && prevClose > 0 ? ... : null` 의 true arm + && 우항
 *  - line 200 `Array.isArray(h.sparkline_30d) ? h.sparkline_30d : []` 의 true arm
 *
 * 순수 data-layer 테스트 (recharts/next-link import 없음).
 */
import { describe, it, expect } from "vitest";

import {
  buildEnrichedHoldings,
  type RawHolding,
  type RawAdvisorAction,
} from "@/components/ui/holding-row";

describe("buildEnrichedHoldings — accountLabel fallback (line 139)", () => {
  it("falls back to raw account when accountLabel is missing", () => {
    // accountLabel 누락 → `h.accountLabel ?? accountRaw` 우측 arm 실행.
    // accountRaw 는 account 필드(있으면) → 결과 account == raw account.
    const holdings: RawHolding[] = [
      {
        ticker: "AAPL",
        account: "RAW_ACCT_1",
        // accountLabel 의도적 누락
        quantity: 1,
        avg_price: 100,
        latest_price: 120,
        currency: "USD",
      },
    ];

    const [enriched] = buildEnrichedHoldings(holdings);

    expect(enriched.account).toBe("RAW_ACCT_1");
  });
});

describe("buildEnrichedHoldings — advisor current_value fallback (line 164)", () => {
  it("uses 0 weight when a matching advisor violation has no current_value", () => {
    // advisor 매칭은 되지만 current_value 누락 → `advisor.current_value ?? 0`
    // 우측 arm 실행 → violation weight 0.
    const holdings: RawHolding[] = [
      {
        ticker: "TSLA",
        account: "", // accountRaw === "" → advisor 매칭 reason 검사 우회
        accountLabel: "Brokerage Alpha",
        quantity: 1,
        avg_price: 100,
        latest_price: 120,
        currency: "USD",
      },
    ];
    const advisorActions: RawAdvisorAction[] = [
      {
        ticker: "TSLA",
        violation_type: "sector_limit",
        severity: "high",
        // current_value 의도적 누락
        reason: "sector overweight",
      },
    ];

    const [enriched] = buildEnrichedHoldings(holdings, [], [], advisorActions);

    expect(enriched.status).toEqual({ kind: "violation", weight: 0 });
  });
});

describe("buildEnrichedHoldings — daily delta from previous_close (line 197)", () => {
  it("computes dailyDeltaPct when previous_close is positive (cond true arm + && right)", () => {
    // previous_close != null && previous_close > 0 → true → 일변 계산.
    // 110 vs 100 → +10%.
    const holdings: RawHolding[] = [
      {
        ticker: "NVDA",
        accountLabel: "Brokerage Alpha",
        quantity: 1,
        avg_price: 90,
        latest_price: 110,
        previous_close: 100,
        currency: "USD",
      },
    ];

    const [enriched] = buildEnrichedHoldings(holdings);

    expect(enriched.dailyDeltaPct).toBeCloseTo(10, 5);
  });

  it("returns null dailyDeltaPct when previous_close is zero (&& right operand false arm)", () => {
    // previous_close != null (true) 이지만 > 0 이 false → && 우항이 평가되고 null.
    const holdings: RawHolding[] = [
      {
        ticker: "AMD",
        accountLabel: "Brokerage Alpha",
        quantity: 1,
        avg_price: 90,
        latest_price: 110,
        previous_close: 0,
        currency: "USD",
      },
    ];

    const [enriched] = buildEnrichedHoldings(holdings);

    expect(enriched.dailyDeltaPct).toBeNull();
  });
});

describe("buildEnrichedHoldings — sparkline array passthrough (line 200)", () => {
  it("passes through sparkline_30d array when present (Array.isArray true arm)", () => {
    // sparkline_30d 가 배열 → `Array.isArray(...) ? h.sparkline_30d : []` true arm.
    const series = [100, 101, 102, 103];
    const holdings: RawHolding[] = [
      {
        ticker: "GOOGL",
        accountLabel: "Brokerage Alpha",
        quantity: 1,
        avg_price: 100,
        latest_price: 120,
        sparkline_30d: series,
        currency: "USD",
      },
    ];

    const [enriched] = buildEnrichedHoldings(holdings);

    expect(enriched.sparkline).toEqual(series);
  });
});
