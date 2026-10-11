/**
 * 종목 미리보기 자료 적재 · 표시 형식 잠금.
 *
 * `loadTicker` 의 리서치 읽기는 다른 종목의 자료를 절대 이 화면에 싣지 않는다 — 응답의 ticker,
 * dossier.ticker, profile.symbol 중 하나라도 요청 심볼과 다르면 버린다. 실패는 null 로 접고
 * 페이지는 "불러오지 못함" 을 말한다 (빈 자료로 둔갑시키지 않는다).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadTicker, researchSchema, type TickerReview } from "./data";
import { amount, compactAmount, priceRows } from "./research-format";

const fetchAPI = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({ fetchAPI, API_BASE: "http://localhost:8001" }));

const dossier = (ticker = "DEMO", symbol = "DEMO") => ({
  ticker, collected_at: "2026-01-06T09:00:00+09:00",
  profile: { name: "Demo Company", symbol }, statements: { income: [], cashflow: [], balance: [] },
});

const research = (overrides: Record<string, unknown> = {}) => ({ ticker: "DEMO", dossier: dossier(), news: [], events: [], fundamentals_history: [], ...overrides });

const item = (ticker: string, reason: string) => ({ ticker, action: "HOLD", confidence: 50, reasons: [reason] });

beforeEach(() => {
  fetchAPI.mockReset();
  fetchAPI.mockImplementation(async (path: string) => (path === "/api/actions"
    ? { urgent: [item("DEMO", "urgent reason")], check: [item("OTHER", "other ticker reason")], hold: [item("DEMO", "hold reason")], portfolio: [], generated_at: "2026-01-06T09:00:00" }
    : { prices: [], decisions: [] }));
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function respond(body: unknown, ok = true) {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok, json: async () => body })));
}

describe("loadTicker research guard", () => {
  it("keeps research that belongs to the requested symbol and reads it without a cache", async () => {
    respond(research());
    const data = await loadTicker("DEMO");

    expect(data.research?.dossier?.profile.name).toBe("Demo Company");
    expect(fetch).toHaveBeenCalledWith("http://localhost:8001/api/ticker/DEMO/research", { cache: "no-store" });
  });

  it.each([
    ["the response is for another ticker", research({ ticker: "OTHER" })],
    ["the dossier is for another ticker", research({ dossier: dossier("OTHER") })],
    ["the provider profile names another symbol", research({ dossier: dossier("DEMO", "OTHER") })],
  ])("drops research when %s", async (_, body) => {
    respond(body);
    expect((await loadTicker("DEMO")).research).toBeNull();
  });

  it("drops research on an HTTP error, a schema mismatch and a network failure", async () => {
    respond(research(), false);
    expect((await loadTicker("DEMO")).research).toBeNull();
    respond({ ticker: "DEMO", news: "not a list" });
    expect((await loadTicker("DEMO")).research).toBeNull();
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("network down"); }));
    expect((await loadTicker("DEMO")).research).toBeNull();
  });

  it("collects only this symbol's reviews from every bucket and tags each with its bucket", async () => {
    // 버킷마다 이 종목과 다른 종목을 하나씩 둔다 — 순회에서 버킷 하나를 빼거나 종목 필터를 지우면 결과가 바뀐다
    const buckets = ["urgent", "check", "portfolio", "hold"] as const;

    fetchAPI.mockImplementation(async (path: string) => (path === "/api/actions"
      ? { ...Object.fromEntries(buckets.map(bucket => [bucket, [item("OTHER", `other ${bucket} reason`), item("DEMO", `${bucket} reason`)]])), generated_at: "2026-01-06T09:00:00" }
      : { prices: [], decisions: [] }));
    respond(research());
    const { reviews } = await loadTicker("DEMO");

    expect(reviews).toEqual(buckets.map(bucket => ({ ...item("DEMO", `${bucket} reason`), bucket })));
  });

});

describe("research-format", () => {
  it("prints amounts under 100,000 in full and larger amounts in compact Korean units", () => {
    expect(compactAmount(null, "USD")).toBe("—");
    expect(compactAmount(50_000, "USD")).toBe("50,000 USD");
    expect(compactAmount(100_000)).toBe("10만");
    expect(compactAmount(1_000_000, "USD")).toBe("100만 USD");
    expect(compactAmount(-3_000_000)).toBe("-300만");
    expect(amount(1_000_000)).toBe("1,000,000");
  });

  const base: TickerReview = { ticker: null, prices: null, history: null, actions: null, reviews: [], research: null };

  const stored = { date: "2026-01-02", open: 1, high: 1, low: 1, close: 1, volume: 1 };

  const collected = { ...stored, date: "2026-01-05", close: 2 };

  it("prefers collected price history, falls back to stored prices, and returns nothing without either", () => {
    const withHistory = researchSchema.parse(research({ dossier: { ...dossier(), price_history: [collected] } }));
    const withoutHistory = researchSchema.parse(research({ dossier: { ...dossier(), price_history: [] } }));

    expect(priceRows({ ...base, prices: { prices: [stored] }, research: withHistory })).toEqual([collected]);
    expect(priceRows({ ...base, prices: { prices: [stored] }, research: withoutHistory })).toEqual([stored]);
    expect(priceRows({ ...base, research: withoutHistory })).toEqual([]);
    expect(priceRows(base)).toEqual([]);
  });
});
