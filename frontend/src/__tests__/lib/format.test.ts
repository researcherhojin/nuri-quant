// 통화·숫자 포맷 일원화 잠금 (#1197 U1b-1).
// 잠금 1: KRW 판정은 티커 접미사(.KS/.KQ)/currency 로만 — 가격 크기 휴리스틱(v > 10000)은
//        ₩8,145 종목을 $ 로 표기했던 버그라 되돌아오면 안 된다.
// 잠금 2: 퍼센트는 부호 병기 — 색만으로 방향을 전달하지 않는다.
import { describe, it, expect } from "vitest";
import { isKrwTicker, formatMoney, formatPct, formatNum } from "@/lib/format";

describe("isKrwTicker", () => {
  it("detects KOSPI (.KS) and KOSDAQ (.KQ) suffixes", () => {
    expect(isKrwTicker("005930.KS")).toBe(true);
    expect(isKrwTicker("402340.KS")).toBe(true);
    expect(isKrwTicker("035720.KQ")).toBe(true);
  });

  it("is case/whitespace tolerant", () => {
    expect(isKrwTicker(" 005930.ks ")).toBe(true);
    expect(isKrwTicker("035720.kq")).toBe(true);
  });

  it("rejects US tickers, empty, null, undefined", () => {
    expect(isKrwTicker("TSLA")).toBe(false);
    expect(isKrwTicker("BRK.B")).toBe(false);
    expect(isKrwTicker("")).toBe(false);
    expect(isKrwTicker(null)).toBe(false);
    expect(isKrwTicker(undefined)).toBe(false);
  });
});

describe("formatMoney", () => {
  it("renders KRW as ₩ integer with thousand separators", () => {
    expect(formatMoney(1128000, { ticker: "402340.KS" })).toBe("₩1,128,000");
    expect(formatMoney(8145.4, { ticker: "0167Z0.KS" })).toBe("₩8,145");
  });

  it("renders USD as $ with 2 decimals and thousand separators", () => {
    expect(formatMoney(345.13, { ticker: "TSLA" })).toBe("$345.13");
    expect(formatMoney(1123000, { ticker: "TSLA" })).toBe("$1,123,000.00");
  });

  it("low-priced KRW ticker stays ₩ (the v>10000 heuristic bug)", () => {
    expect(formatMoney(8145, { ticker: "0167Z0.KS" })).toBe("₩8,145");
  });

  it("high-priced US value stays $ (the reverse heuristic bug)", () => {
    expect(formatMoney(985.82, { ticker: "CAT" })).toBe("$985.82");
    expect(formatMoney(12000, {})).toBe("$12,000.00");
  });

  it("currency field overrides ticker inference", () => {
    expect(formatMoney(1000, { ticker: "TSLA", currency: "KRW" })).toBe("₩1,000");
    expect(formatMoney(10, { ticker: "005930.KS", currency: "USD" })).toBe("$10.00");
    expect(formatMoney(1000, { currency: "krw" })).toBe("₩1,000");
  });

  it("returns em-dash for null/undefined/NaN", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
    expect(formatMoney(Number.NaN, { ticker: "TSLA" })).toBe("—");
  });
});

describe("formatPct", () => {
  it("always carries the sign for positives", () => {
    expect(formatPct(7.6)).toBe("+7.6%");
    expect(formatPct(-8.0)).toBe("-8.0%");
    expect(formatPct(0)).toBe("0.0%");
  });

  it("respects digits and handles null/NaN", () => {
    expect(formatPct(29.0421, 2)).toBe("+29.04%");
    expect(formatPct(null)).toBe("—");
    expect(formatPct(Number.NaN)).toBe("—");
  });
});

describe("formatNum", () => {
  it("rounds raw floats (no 52.9428571428571 leakage)", () => {
    expect(formatNum(52.9428571428571)).toBe("52.9");
    expect(formatNum(71.5, 0)).toBe("72");
  });

  it("handles null/undefined/NaN", () => {
    expect(formatNum(null)).toBe("—");
    expect(formatNum(undefined)).toBe("—");
    expect(formatNum(Number.NaN)).toBe("—");
  });
});
