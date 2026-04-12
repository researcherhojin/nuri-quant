import { describe, it, expect } from "vitest";
import {
  trendKo, vixZone, fgLabel, macroLevel, signalKo,
  formatPrice, formatDelta, tickerDisplay,
  POPULAR_US, POPULAR_KR, KR_NAMES,
} from "@/app/explore/helpers";

describe("trendKo", () => {
  it("returns 상승 for bull", () => expect(trendKo("bull")).toBe("상승"));
  it("returns 하락 for bear", () => expect(trendKo("bear")).toBe("하락"));
  it("returns 횡보 for sideways", () => expect(trendKo("sideways")).toBe("횡보"));
  it("returns 횡보 for unknown", () => expect(trendKo("unknown")).toBe("횡보"));
});

describe("vixZone", () => {
  it("returns — for null", () => expect(vixZone(null).label).toBe("—"));
  it("안정 for VIX < 12", () => expect(vixZone(10).label).toBe("안정"));
  it("낮음 for VIX 12-17", () => expect(vixZone(15).label).toBe("낮음"));
  it("보통 for VIX 17-23", () => expect(vixZone(20).label).toBe("보통"));
  it("주의 for VIX 23-33", () => expect(vixZone(28).label).toBe("주의"));
  it("위험 for VIX >= 33", () => expect(vixZone(40).label).toBe("위험"));
  it("has color for each zone", () => {
    expect(vixZone(10).color).toContain("blue");
    expect(vixZone(15).color).toContain("emerald");
    expect(vixZone(40).color).toContain("red");
  });
});

describe("fgLabel", () => {
  it("returns — for null", () => expect(fgLabel(null)).toBe("—"));
  it("극도 공포 for fg < 25", () => expect(fgLabel(10)).toBe("극도 공포"));
  it("공포 for fg 25-45", () => expect(fgLabel(30)).toBe("공포"));
  it("중립 for fg 45-55", () => expect(fgLabel(50)).toBe("중립"));
  it("탐욕 for fg 55-75", () => expect(fgLabel(65)).toBe("탐욕"));
  it("극도 탐욕 for fg > 75", () => expect(fgLabel(90)).toBe("극도 탐욕"));
});

describe("macroLevel", () => {
  it("양호 for score >= 70", () => expect(macroLevel(80).label).toBe("양호"));
  it("보통 for score 50-70", () => expect(macroLevel(55).label).toBe("보통"));
  it("부진 for score 30-50", () => expect(macroLevel(35).label).toBe("부진"));
  it("취약 for score < 30", () => expect(macroLevel(15).label).toBe("취약"));
});

describe("signalKo", () => {
  it("translates known signals", () => {
    expect(signalKo("bb_bounce")).toBe("볼린저밴드 반등");
    expect(signalKo("gap_up")).toBe("갭 상승");
    expect(signalKo("rsi_oversold")).toBe("RSI 과매도");
    expect(signalKo("macd_golden")).toBe("MACD 골든크로스");
  });
  it("falls back to readable format for unknown", () => {
    expect(signalKo("some_unknown_signal")).toBe("some unknown signal");
  });
});

describe("formatPrice", () => {
  it("formats USD price >= 100", () => expect(formatPrice(185.5, false)).toBe("$186"));
  it("formats USD price < 100", () => expect(formatPrice(34.67, false)).toBe("$34.67"));
  it("formats KRW price", () => expect(formatPrice(206000, true)).toBe("₩206,000"));
  it("returns 미수집 for null", () => expect(formatPrice(null, false)).toBe("미수집"));
});

describe("formatDelta", () => {
  it("returns positive delta", () => {
    const d = formatDelta(110, 100);
    expect(d!.str).toBe("+10.0%");
    expect(d!.color).toContain("emerald");
  });
  it("returns negative delta", () => {
    const d = formatDelta(90, 100);
    expect(d!.str).toBe("-10.0%");
    expect(d!.color).toContain("red");
  });
  it("returns null for null price", () => expect(formatDelta(null, 100)).toBeNull());
  it("returns null for null prev", () => expect(formatDelta(100, null)).toBeNull());
  it("returns null for zero prev", () => expect(formatDelta(100, 0)).toBeNull());
});

describe("tickerDisplay", () => {
  it("returns Korean name for KR tickers", () => {
    expect(tickerDisplay("005930.KS")).toBe("삼성전자");
    expect(tickerDisplay("000660.KS")).toBe("SK하이닉스");
  });
  it("returns ticker as-is for US", () => {
    expect(tickerDisplay("NVDA")).toBe("NVDA");
  });
});

describe("Popular tickers", () => {
  it("POPULAR_US has 6 entries", () => expect(POPULAR_US).toHaveLength(6));
  it("POPULAR_KR has 6 entries", () => expect(POPULAR_KR).toHaveLength(6));
  it("KR_NAMES maps all KR tickers", () => {
    for (const t of POPULAR_KR) {
      expect(KR_NAMES[t.ticker]).toBe(t.name);
    }
  });
});
