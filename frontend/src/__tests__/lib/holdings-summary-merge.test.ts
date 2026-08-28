/**
 * `mergeAccountTotals` — 미상(null)을 0 으로 접지 않는다 (#1284).
 *
 * 이 로직은 원래 `page.tsx` 인라인이었다. 뮤테이션 실측에서 **아무 테스트도 잡지
 * 못해** 밖으로 뺐다 — 인라인이라 테스트가 닿지 않았고, 닿지 않으면 잠긴 게 아니다.
 */
import { describe, expect, it } from "vitest";

import { mergeAccountTotals } from "@/lib/holdings-summary";

describe("mergeAccountTotals (#1284)", () => {
  it("미상 보유 + 현금이면 계좌 합계가 미상이다", () => {
    // Mutation lock: `(prev ?? 0) + (value ?? 0)` 로 되돌리면 500 이 나와 FAIL.
    // 500 은 "이 계좌엔 현금 500 뿐" 이라는 거짓이다 — 보유 평가액을 모를 뿐이다.
    const merged = mergeAccountTotals(
      [{ account: "Brokerage Alpha", value: null }],
      [{ account: "Brokerage Alpha", total_usd: 500 }],
    );
    expect(merged).toEqual([{ account: "Brokerage Alpha", value: null }]);
  });

  it("미상 현금도 같은 방향으로 전파된다", () => {
    const merged = mergeAccountTotals(
      [{ account: "Brokerage Alpha", value: 1000 }],
      [{ account: "Brokerage Alpha", total_usd: null }],
    );
    expect(merged[0].value).toBeNull();
  });

  it("대조군 — 전부 알면 예전처럼 더한다", () => {
    const merged = mergeAccountTotals(
      [{ account: "Brokerage Alpha", value: 1000 }],
      [{ account: "Brokerage Alpha", total_usd: 500 }],
    );
    expect(merged).toEqual([{ account: "Brokerage Alpha", value: 1500 }]);
  });

  it("대조군 — 계좌가 서로 다르면 각각 유지된다", () => {
    const merged = mergeAccountTotals(
      [{ account: "Brokerage Alpha", value: 1000 }],
      [{ account: "Brokerage Beta", total_usd: 500 }],
    );
    expect(merged).toEqual([
      { account: "Brokerage Alpha", value: 1000 },
      { account: "Brokerage Beta", value: 500 },
    ]);
  });
});
