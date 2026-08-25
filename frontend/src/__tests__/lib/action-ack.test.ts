import { describe, it, expect, beforeEach, afterAll } from "vitest";

import { actionKey, isNewItem, loadAckMap, ackItem } from "@/lib/action-ack";

// #1212 U2b-4: seen-state 규칙 잠금 — identity, re-alert, 스토리지 강건성.
//
// 이 vitest jsdom 에는 window.localStorage 가 아예 없다 (Node experimental
// localStorage 로 위임되는데 --localstorage-file 미지정) — 인메모리 스텁을 단다.
// 라이브러리 자체는 스토리지 부재도 try/catch 로 견딘다 (아래 마지막 테스트).
function makeStorageStub(): Storage {
  let store: Record<string, string> = {};
  return {
    getItem: (k: string) => (k in store ? store[k] : null),
    setItem: (k: string, v: string) => { store[k] = String(v); },
    removeItem: (k: string) => { delete store[k]; },
    clear: () => { store = {}; },
    key: (i: number) => Object.keys(store)[i] ?? null,
    get length() { return Object.keys(store).length; },
  } as Storage;
}
const originalDescriptor = Object.getOwnPropertyDescriptor(window, "localStorage");
Object.defineProperty(window, "localStorage", { value: makeStorageStub(), configurable: true });
afterAll(() => {
  if (originalDescriptor) Object.defineProperty(window, "localStorage", originalDescriptor);
  else delete (window as { localStorage?: Storage }).localStorage;
});

const item = (over: Partial<{ ticker: string; account?: string; action: string; priority: string; as_of?: string | null }> = {}) => ({
  ticker: "AAA",
  account: "Alpha",
  action: "SELL",
  priority: "urgent",
  as_of: "2026-08-25",
  ...over,
});

beforeEach(() => {
  window.localStorage.clear();
});

describe("actionKey", () => {
  it("composes ticker|account|action|priority, empty account tolerated", () => {
    expect(actionKey(item())).toBe("AAA|Alpha|SELL|urgent");
    expect(actionKey(item({ account: undefined }))).toBe("AAA||SELL|urgent");
  });

  // codex R1 P1: 버킷이 다르면 같은 튜플이라도 별개 identity — 교차 오염 금지,
  // check→urgent 승격은 재경보.
  it("distinguishes the same tuple across buckets", () => {
    expect(actionKey(item({ priority: "urgent" }))).not.toBe(actionKey(item({ priority: "portfolio" })));
  });
});

describe("isNewItem", () => {
  it("null map (pre-mount) → never NEW (hydration safety)", () => {
    expect(isNewItem(item(), null)).toBe(false);
  });

  it("no entry → NEW; acked same as_of → not NEW", () => {
    expect(isNewItem(item(), {})).toBe(true);
    expect(isNewItem(item(), { "AAA|Alpha|SELL|urgent": "2026-08-25" })).toBe(false);
  });

  // re-alert: 같은 항목이라도 판정일이 갱신되면 다시 NEW
  it("newer as_of than acked → NEW again", () => {
    expect(isNewItem(item({ as_of: "2026-08-26" }), { "AAA|Alpha|SELL|urgent": "2026-08-25" })).toBe(true);
  });

  it("null as_of stays acked after one ack", () => {
    expect(isNewItem(item({ as_of: null }), { "AAA|Alpha|SELL|urgent": "" })).toBe(false);
  });
});

describe("loadAckMap / ackItem", () => {
  it("round-trips through localStorage", () => {
    const next = ackItem({}, item());
    expect(next).toEqual({ "AAA|Alpha|SELL|urgent": "2026-08-25" });
    expect(loadAckMap()).toEqual({ "AAA|Alpha|SELL|urgent": "2026-08-25" });
  });

  it("null as_of is stored as empty string", () => {
    expect(ackItem({}, item({ as_of: null }))).toEqual({ "AAA|Alpha|SELL|urgent": "" });
  });

  it("corrupt or non-object storage → empty map, never throws", () => {
    window.localStorage.setItem("nuri.actions.ack.v1", "{not json");
    expect(loadAckMap()).toEqual({});
    window.localStorage.setItem("nuri.actions.ack.v1", "[1,2]");
    expect(loadAckMap()).toEqual({});
    window.localStorage.setItem("nuri.actions.ack.v1", JSON.stringify({ a: 1, b: "ok" }));
    expect(loadAckMap()).toEqual({ b: "ok" }); // 문자열 값만 채택
  });

  // 스토리지 부재(프라이빗 창·차단 환경·이 jsdom 기본값) — accessor 가 throw/undefined 여도
  // load 는 {}, ack 는 in-memory 결과를 반환해야 한다.
  it("survives a missing localStorage entirely", () => {
    Object.defineProperty(window, "localStorage", { value: undefined, configurable: true });
    try {
      expect(loadAckMap()).toEqual({});
      expect(ackItem({}, item())).toEqual({ "AAA|Alpha|SELL|urgent": "2026-08-25" });
    } finally {
      Object.defineProperty(window, "localStorage", { value: makeStorageStub(), configurable: true });
    }
  });
});
