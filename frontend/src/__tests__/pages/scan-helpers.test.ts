import { describe, it, expect } from "vitest";

import { mergeScanSwing, type ScanResult, type SwingEntry } from "@/app/scan/helpers";
import { summarizePayload } from "@/app/pipeline/helpers";

// #1219 U4b: scan/swing union 병합 + pipeline payload 요약 잠금.

const scanRow = (over: Partial<ScanResult> = {}): ScanResult => ({
  ticker: "AAA", price: 100, change_1d: 1.2, change_5d: -0.5,
  volume_ratio: 2.0, rsi: 55, signal: "momentum", score: 80, ...over,
});
const swingRow = (over: Partial<SwingEntry> = {}): SwingEntry => ({
  ticker: "AAA", price: 100, scan_signal: "momentum", scan_score: 80,
  agent_action: "BUY", agent_confidence: 70, approved: true, reason: "ok", ...over,
});

describe("mergeScanSwing", () => {
  it("joins swing agent fields onto matching scan rows — one row per ticker", () => {
    const rows = mergeScanSwing([scanRow()], [swingRow()]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      ticker: "AAA", change_1d: 1.2, rsi: 55, agent_action: "BUY", approved: true,
    });
  });

  it("keeps scan order first, appends swing-only tickers with null momentum fields", () => {
    const rows = mergeScanSwing(
      [scanRow({ ticker: "AAA" }), scanRow({ ticker: "BBB", score: 60 })],
      [swingRow({ ticker: "BBB" }), swingRow({ ticker: "CCC", approved: false, reason: "veto" })],
    );
    expect(rows.map((r) => r.ticker)).toEqual(["AAA", "BBB", "CCC"]);
    const ccc = rows[2];
    expect(ccc.change_1d).toBeNull();
    expect(ccc.rsi).toBeNull();
    expect(ccc.signal).toBe("momentum"); // scan_signal 대체
    expect(ccc.approved).toBe(false);
    expect(ccc.reason).toBe("veto");
  });

  it("scan-only rows carry null agent fields and approved: null (평가 없음 ≠ 미승인)", () => {
    const rows = mergeScanSwing([scanRow()], []);
    expect(rows[0].agent_action).toBeNull();
    expect(rows[0].approved).toBeNull();
  });

  it("empty inputs → empty output", () => {
    expect(mergeScanSwing([], [])).toEqual([]);
  });

  // API 실데이터는 타입 선언과 달리 null 필드를 실을 수 있다 (SQLite) — 폴백 arm 잠금.
  it("falls back to swing values when scan fields are null, and nulls stay null", () => {
    const nullishScan = { ...scanRow(), price: null, signal: null, score: null, change_1d: null, change_5d: null, rsi: null } as unknown as ScanResult;
    const rows = mergeScanSwing([nullishScan], [swingRow({ price: 99, scan_signal: "bounce", scan_score: 42 })]);
    expect(rows[0].price).toBe(99);
    expect(rows[0].signal).toBe("bounce");
    expect(rows[0].score).toBe(42);
    const nullishSwing = { ...swingRow({ ticker: "ZZZ" }), price: null, scan_signal: null, scan_score: null, agent_action: null, agent_confidence: null, reason: null } as unknown as SwingEntry;
    const only = mergeScanSwing([], [nullishSwing]);
    expect(only[0]).toMatchObject({ ticker: "ZZZ", price: null, signal: null, score: null, agent_action: null, reason: null });
    // 스윙 매치도 없는 null 스캔 행 — 최종 ?? null arm
    const bare = mergeScanSwing([nullishScan], []);
    expect(bare[0]).toMatchObject({ price: null, signal: null, score: null });
  });
});

describe("summarizePayload (#1219 raw JSON 폐지)", () => {
  it("priority keys win outright, truncated to 80 chars", () => {
    expect(summarizePayload({ stderr: "boom", records: 5 })).toBe("boom");
    expect(summarizePayload({ command: "make collect" })).toBe("make collect");
    expect(summarizePayload({ error: "x".repeat(120) })).toBe("x".repeat(80));
  });

  it("falls back to a kv summary (max 3 pairs + rest count), not JSON.stringify", () => {
    const out = summarizePayload({ records: 921551, tickers: 774, elapsed: 12.345, extra: 1, more: 2 });
    expect(out).toBe("records 921551 · tickers 774 · elapsed 12.35 +2");
    expect(out).not.toContain("{");
  });

  it("formats value types and tolerates nested objects", () => {
    expect(summarizePayload({ ok: true, off: false, note: null })).toBe("ok true · off false · note —");
    expect(summarizePayload({ step: "collect" })).toBe("step collect"); // 문자열 값 (비우선순위 키)
    expect(summarizePayload({ nested: { a: 1 } })).toBe('nested {"a":1}');
  });

  it("survives a circular payload value (JSON.stringify throw)", () => {
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    expect(summarizePayload({ weird: circular })).toBe("weird [object Object]");
  });

  it("empty/missing payload → empty string (렌더 억제)", () => {
    expect(summarizePayload(null)).toBe("");
    expect(summarizePayload(undefined)).toBe("");
    expect(summarizePayload({})).toBe("");
  });
});
