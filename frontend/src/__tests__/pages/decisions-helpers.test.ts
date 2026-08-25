import { describe, it, expect } from "vitest";

import {
  ADJUDICATION_DAYS,
  addDays,
  adjudicationInfo,
  filterHref,
  fmtFixed,
  fmtKvNumber,
  fmtKvValue,
  groupByDate,
  parseActionFilter,
  parseDetailKV,
  parseOutcomeFilter,
} from "@/app/decisions/helpers";

// #1216 U3: 판정일 계산·필터 URL·evidence key-value 파싱 잠금.

describe("addDays / adjudicationInfo", () => {
  it("adds the 90-day adjudication window (decisions.py 규칙 미러)", () => {
    expect(ADJUDICATION_DAYS).toBe(90);
    expect(addDays("2026-01-15", 90)).toBe("2026-04-15");
    expect(addDays("2025-12-31", 1)).toBe("2026-01-01"); // 연 경계
  });

  it("adjudicated outcome → 판정 기준일", () => {
    const adj = adjudicationInfo("2026-01-15", "success", "2026-08-25");
    expect(adj).toEqual({ kind: "adjudicated", adjudicationDate: "2026-04-15" });
  });

  it("pending before the window → waiting with D-n (D-1 이 마지막 대기일)", () => {
    expect(adjudicationInfo("2026-08-01", "pending", "2026-08-25")).toEqual({
      kind: "waiting", adjudicationDate: "2026-10-30", daysLeft: 66,
    });
    expect(adjudicationInfo("2026-05-28", "pending", "2026-08-25").daysLeft).toBe(1);
  });

  // 경계 미러 (codex R1 P1): 백엔드는 elapsed >= 90 — 판정일 **당일부터** 판정 가능.
  // 2026-05-27 결정은 2026-08-25 에 이미 판정 대상이므로 D-0 대기가 아니라 due 다.
  it("pending on/after the adjudication date → due (백엔드 elapsed>=90 미러)", () => {
    expect(adjudicationInfo("2026-05-27", "pending", "2026-08-25")).toEqual({
      kind: "due", adjudicationDate: "2026-08-25",
    });
    expect(adjudicationInfo("2026-01-15", "pending", "2026-08-25")).toEqual({
      kind: "due", adjudicationDate: "2026-04-15",
    });
  });
});

describe("groupByDate", () => {
  it("keeps DESC order and groups consecutive same dates", () => {
    const rows = [
      { date: "2026-08-25", id: 3 },
      { date: "2026-08-25", id: 2 },
      { date: "2026-08-24", id: 1 },
    ];
    const groups = groupByDate(rows);
    expect(groups.map(([d, r]) => [d, r.length])).toEqual([
      ["2026-08-25", 2],
      ["2026-08-24", 1],
    ]);
  });

  it("empty input → empty groups", () => {
    expect(groupByDate([])).toEqual([]);
  });
});

describe("filters", () => {
  it("parses only known values", () => {
    expect(parseOutcomeFilter("success")).toBe("success");
    expect(parseOutcomeFilter("bogus")).toBeUndefined();
    expect(parseOutcomeFilter(undefined)).toBeUndefined();
    expect(parseActionFilter("SELL")).toBe("SELL");
    expect(parseActionFilter("sell")).toBeUndefined();
  });

  it("filterHref omits defaults for a minimal shareable URL", () => {
    expect(filterHref(undefined, undefined)).toBe("/decisions");
    expect(filterHref("pending", undefined)).toBe("/decisions?outcome=pending");
    expect(filterHref(undefined, "BUY")).toBe("/decisions?action=BUY");
    expect(filterHref("failure", "SELL")).toBe("/decisions?outcome=failure&action=SELL");
  });
});

describe("evidence key-value (#1216 raw JSON 폐지)", () => {
  it("parses a JSON object into formatted pairs", () => {
    const kv = parseDetailKV('{"pe": null, "roe": 0.10783, "fx_rate": 1480.780029296875, "is_korean": true, "market": "KOSPI"}');
    expect(kv).toEqual([
      ["pe", "—"],
      ["roe", "0.11"],
      ["fx_rate", "1480.78"],
      ["is_korean", "true"],
      ["market", "KOSPI"],
    ]);
  });

  it("non-object / broken JSON → null (호출자가 raw fallback)", () => {
    expect(parseDetailKV(null)).toBeNull();
    expect(parseDetailKV("")).toBeNull();
    expect(parseDetailKV("plain text detail")).toBeNull();
    expect(parseDetailKV("[1,2,3]")).toBeNull();
    expect(parseDetailKV("42")).toBeNull();
  });

  it("fmtKvNumber trims to ≤2 decimals without trailing zeros", () => {
    expect(fmtKvNumber(70976.0)).toBe("70976");
    expect(fmtKvNumber(4.66)).toBe("4.66");
    expect(fmtKvNumber(0.10783)).toBe("0.11");
    expect(fmtKvNumber(5.7)).toBe("5.7");
  });

  it("fmtKvValue handles nested objects, booleans, and non-finite numbers", () => {
    expect(fmtKvValue({ a: 1 })).toBe('{"a":1}');
    expect(fmtKvValue(Number.NaN)).toBe("—");
    expect(fmtKvValue(undefined)).toBe("—");
    expect(fmtKvValue(false)).toBe("false");
  });

  it("fmtKvValue falls back to String() when JSON.stringify throws (순환 참조)", () => {
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    expect(fmtKvValue(circular)).toBe("[object Object]");
  });
});

describe("fmtFixed (raw float 종결)", () => {
  it("fixes decimals and dashes null", () => {
    expect(fmtFixed(21.040000915527344)).toBe("21.0");
    expect(fmtFixed(50.9, 1)).toBe("50.9");
    expect(fmtFixed(null)).toBe("—");
    expect(fmtFixed(undefined)).toBe("—");
  });
});
