/**
 * Branch-coverage push for src/app/page.tsx (coverage/frontend-branch-100).
 *
 * The Dashboard is one monolithic async Server Component (no nested sections),
 * so we render the whole OverviewPage() with targeted fixtures. The existing
 * page.coverage.test.tsx covers the cash merge / eventDday / pipeline-happy /
 * certify-race statements; this file targets the remaining *branch* arms:
 *
 *  - L367  trend color ternary — bull / bear / sideways arms (3 fixtures)
 *  - L217  `h.latest_price || 0` falsy arm (holding missing latest_price)
 *  - L218  `h.quantity || 0` falsy arm (holding missing quantity)
 *  - L496/L497/L502-503  holdings toggle Link, both collapsed (default) and
 *          ?holdings=expanded arms — needs > 8 (HOLDINGS_COLLAPSED_LIMIT)
 *          non-pension holdings so the toggle renders.
 *  - L544-546  `holdingsExpanded ? all : slice(0, LIMIT)` both arms.
 *  - L564/L565  opportunities section gate — > 0 truthy arm.
 *  - L577/L578  coverage section gate — coverage present + checks.length > 0.
 *  - L602/L603  pipeline status color: known status (done) vs unknown status
 *          (fallback `bg-zinc-500`) — both arms of `colors[status] || fallback`.
 *  - L613/L614  siege failed severity ternary — "error" (✖ red) vs non-error
 *          (△ amber).
 *
 * RENDER GOTCHA (jsdom): page.tsx wraps Dashboard in <Suspense>. The lazy
 * CompositionSection (next/dynamic ssr:false) suspends forever in jsdom, so the
 * outer Suspense permanently shows the LoadingSkeleton and the Dashboard never
 * commits. We stub `@/components/ui/composition-section-lazy` with a synchronous
 * component (preserving the real parseCompositionTab) so the page commits, and
 * stub OpportunityExplorer (a "use client" fetch-on-mount component) so the
 * opportunities section can't hang. recharts is still mocked at file level per
 * the vi.mock("recharts") hoist-leak rule. Neutral placeholders only (public).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, act, cleanup } from "@testing-library/react";
import type { ReactNode } from "react";

// Full async RSC render + Suspense flush pumps; the default 5s testTimeout is
// tight under load, so give the file headroom.
vi.setConfig({ testTimeout: 15000 });

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  PieChart: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Pie: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Cell: () => <div />,
  Tooltip: () => <div />,
}));

// next/dynamic (ssr:false) makes CompositionSectionLazy suspend forever in
// jsdom — the outer <Suspense> then reverts to the page's LoadingSkeleton, so
// the committed Dashboard never stays in the DOM. Stub the lazy wrapper with a
// synchronous component (keep the real parseCompositionTab) so the page commits.
vi.mock("@/components/ui/composition-section-lazy", async () => {
  const actual = await vi.importActual<typeof import("@/components/ui/composition-section")>(
    "@/components/ui/composition-section",
  );
  return {
    CompositionSectionLazy: () => <div data-testid="composition-stub" />,
    parseCompositionTab: actual.parseCompositionTab,
  };
});

// OpportunityExplorer is a "use client" component that fetches the 10-Agent
// detail via global fetch on mount — that async work hangs the test. We only
// need page.tsx's L564/L565 section gate, so stub it with a marker.
vi.mock("@/components/ui/opportunity-explorer", () => ({
  OpportunityExplorer: () => <div data-testid="opportunity-stub" />,
}));

// next/link mock MUST forward all props (not just href/children) — the holdings
// toggle is `<Link data-testid="holdings-toggle" ...>`, and a children-only mock
// drops data-testid, making the toggle unqueryable by test id.
vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  API_BASE: "http://localhost:8001",
  fetchAPI: vi.fn(),
}));

type Json = Record<string, unknown>;

// A holding missing latest_price AND quantity — exercises the holdingsValue
// reducer's `|| 0` fallback arms (L217 / L218). Included in EVERY portfolio
// fixture because v8 keeps per-file branch counts from the *last* module
// instance under vi.resetModules() + dynamic import, so a single dedicated test
// can lose its hit in the cross-test merge.
const BAD_HOLDING = { ticker: "NOPRICE", account: "Brokerage Alpha", avg_price: 100, currency: "USD" };

/** Build a fetchAPI mock keyed by endpoint, with sensible empty defaults. */
function makeFetchAPI(overrides: Record<string, Json>) {
  const base: Record<string, Json> = {
    "/api/dashboard": {
      verdict: "Hold positions",
      verdict_level: "neutral",
      regime: { regime: "bull_low_vol", trend: "bull", volatility: "low", confidence: 80, vix: 15, fear_greed: 55 },
      macro: { score: 60, interpretation: "neutral" },
      allocation: { long: 60, short: 10, cash: 30 },
      actions: [],
      alerts: [],
      gate_score: 80,
      n_positions: 2,
      exchange_rate: 1400,
    },
    "/api/freshness": { items: [], overall: "PASS" },
    "/api/pipeline/status": { steps: [] },
    // No `count` key on purpose: the default fixture drives the L210
    // `?? portfolio?.holdings?.length` arm (holdingCount derived from length).
    "/api/portfolio": {
      holdings: [
        { ticker: "AAPL", account: "Brokerage Alpha", quantity: 10, avg_price: 120, latest_price: 130, currency: "USD" },
        BAD_HOLDING,
      ],
      cash: { total_cash_usd: 500 },
    },
    "/api/certify": { certified: true, passed: 5, total: 5, conditions: [] },
    "/api/rebalance-advisor": { total_violations: 0, actions: [] },
    "/api/targets": { targets: [] },
    "/api/actions": { urgent: [], check: [], hold: [], portfolio: [] },
    "/api/opportunities": { opportunities: [] },
    "/api/market-context": { macro_events: [], system_health: {} },
    "/api/coverage": null as unknown as Json,
  };
  const map = { ...base, ...overrides };
  return vi.fn().mockImplementation((path: string) => Promise.resolve(map[path] ?? {}));
}

/** Generate N distinct non-pension USD holdings, plus the falsy-default probe. */
function manyHoldings(n: number) {
  const rows = Array.from({ length: n }, (_, i) => ({
    ticker: `T${i}`,
    account: "Brokerage Alpha",
    quantity: 10 + i,
    avg_price: 100,
    latest_price: 120,
    currency: "USD",
  }));
  return [...rows, BAD_HOLDING];
}

async function renderWith(
  overrides: Record<string, Json>,
  searchParams?: Promise<{ period?: string; comp?: string; holdings?: string }>,
) {
  vi.doMock("@/lib/api", () => ({
    API_BASE: "http://localhost:8001",
    fetchAPI: makeFetchAPI(overrides),
  }));
  const { default: OverviewPage } = await import("@/app/page");
  let container!: HTMLElement;
  await act(async () => {
    ({ container } = render(OverviewPage(searchParams ? { searchParams } : undefined)));
  });
  // The nested async Dashboard only commits after its fetchAPI Promise.all (and,
  // for the searchParams path, the extra `await searchParams` microtask) drains.
  // Pump microtask + macrotask cycles until THIS render's committed Dashboard
  // (`flex flex-col gap-4 h-full`, distinct from the `gap-3` LoadingSkeleton
  // fallback) appears in its own container. Scoping to `container` avoids
  // counting any leftover tree from a prior test. Bounded so a non-committing
  // render fails fast instead of hanging.
  for (let i = 0; i < 40; i++) {
    if (container.querySelector("div.gap-4.h-full")) break;
    await act(async () => {
      await Promise.resolve();
      await new Promise((r) => setTimeout(r, 0));
    });
  }
  expect(container.querySelector("div.gap-4.h-full")).not.toBeNull();
  return container;
}

// Pure exported helpers — every band is its own branch arm. The render strip
// only ever exercises one band per fixture, so we unit-test the full ladders
// directly (the helpers are exported, behavior-preserving). This covers all the
// vixZone (L123-128) / fgLabel (L131-134) / fgColor (L137-142) / macroLevel
// (L145-148) / trendKo (L121) / accountKo (L152-154) / parseSparklinePeriod
// (L165-166) interior + boundary arms in one deterministic place.
describe("page.tsx pure helper branch ladders", () => {
  it("vixZone covers every band incl. null", async () => {
    const { vixZone } = await import("@/app/page");
    expect(vixZone(null).color).toBe("text-zinc-500"); // v == null
    expect(vixZone(10).color).toBe("text-blue-400");   // < 12
    expect(vixZone(15).color).toBe("text-emerald-400"); // < 17
    expect(vixZone(20).color).toBe("text-zinc-300");   // < 23
    expect(vixZone(28).color).toBe("text-orange-400"); // < 33
    expect(vixZone(40).color).toBe("text-red-400");    // else (>= 33)
  });

  it("fgLabel covers every band incl. null", async () => {
    const { fgLabel } = await import("@/app/page");
    expect(fgLabel(null)).toBe("—");      // null
    expect(fgLabel(10)).toBeTruthy();     // < 25
    expect(fgLabel(30)).toBeTruthy();     // < 45
    expect(fgLabel(50)).toBeTruthy();     // <= 55
    expect(fgLabel(65)).toBeTruthy();     // <= 75
    expect(fgLabel(90)).toBeTruthy();     // else (> 75)
  });

  it("fgColor covers every band incl. null", async () => {
    const { fgColor } = await import("@/app/page");
    expect(fgColor(null)).toContain("zinc"); // null
    expect(fgColor(10)).toContain("red");    // < 25
    expect(fgColor(30)).toContain("orange"); // < 45
    expect(fgColor(50)).toContain("yellow"); // <= 55
    expect(fgColor(65)).toContain("lime");   // <= 75
    expect(fgColor(90)).toContain("emerald"); // else (> 75)
  });

  it("macroLevel covers every band", async () => {
    const { macroLevel } = await import("@/app/page");
    expect(macroLevel(80).color).toBe("text-emerald-400"); // >= 70
    expect(macroLevel(60).color).toBe("text-zinc-300");    // >= 50
    expect(macroLevel(35).color).toBe("text-orange-400");  // >= 30
    expect(macroLevel(10).color).toBe("text-red-400");     // else (< 30)
  });

  it("trendKo covers bull / bear / sideways", async () => {
    const { trendKo } = await import("@/app/page");
    expect(trendKo("bull")).toBeTruthy();
    expect(trendKo("bear")).toBeTruthy();
    expect(trendKo("flat")).toBeTruthy(); // else -> SIDEWAYS
  });

  it("accountKo covers empty / Pension / passthrough", async () => {
    const { accountKo } = await import("@/app/page");
    expect(accountKo(undefined)).toBe(""); // !label
    expect(accountKo("Pension")).toBeTruthy(); // === "Pension"
    expect(accountKo("Brokerage Alpha")).toBe("Brokerage Alpha"); // passthrough
  });

  it("parseSparklinePeriod covers valid + default arms", async () => {
    const { parseSparklinePeriod } = await import("@/app/page");
    expect(parseSparklinePeriod("60")).toBe(60);   // valid -> n
    expect(parseSparklinePeriod("999")).toBe(30);  // invalid -> default 30
    expect(parseSparklinePeriod(undefined)).toBe(30); // raw ?? "30"
  });
});

describe("page.tsx branch coverage", () => {
  beforeEach(() => {
    vi.resetModules();
  });
  afterEach(async () => {
    // Drain dangling Dashboard async work (unresolved fetch promises, the
    // searchParams microtask chain) before teardown — otherwise it fires during
    // the NEXT test's render window and aborts its commit.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    cleanup();
    vi.restoreAllMocks();
    vi.doUnmock("@/lib/api");
  });

  // L131-134 — fgLabel mid-bands: fgLabel is exported; unit-test it directly so
  // the FEAR (25-45) / NEUTRAL (45-55) / GREED (55-75) interior arms run (the
  // render strip only ever passes one fg value per test).
  it("fgLabel covers FEAR / NEUTRAL / GREED interior bands (L132/L133)", async () => {
    const { fgLabel, fgColor } = await import("@/app/page");
    // 30 -> FEAR band (>=25, <45); 50 -> NEUTRAL (<=55); 65 -> GREED (<=75)
    expect(fgLabel(30)).not.toBe("—");
    expect(fgLabel(50)).not.toBe("—");
    expect(fgLabel(65)).not.toBe("—");
    expect(fgColor(30)).toContain("orange");
    expect(fgColor(50)).toContain("yellow");
    expect(fgColor(65)).toContain("lime");
  });

  // L145/L147 — macroLevel GOOD (score>=70) and WEAK (score>=30) arms, reached
  // via render with the respective macro.score.
  it("renders macro GOOD level when score >= 70 (L145)", async () => {
    const container = await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 80, interpretation: "good" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: 1400,
      },
    });
    // macroLevel(80) -> emerald color span in the macro strip.
    expect(container.querySelector("span.text-emerald-400")).not.toBeNull();
  });

  it("renders macro WEAK level when score in [30,50) (L147)", async () => {
    const container = await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 35, interpretation: "weak" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: 1400,
      },
    });
    // macroLevel(35) -> orange color span (WEAK).
    expect(container.querySelector("span.text-orange-400")).not.toBeNull();
  });

  // L289/L292 arm0 — `acctTotals.get(account) ?? 0` LEFT arm (the Map already
  // holds the account, so .get() returns a real number, not undefined). Achieved
  // by a duplicate account in account_values, and an account in cash_summary
  // that also appears in account_values.
  it("merges duplicate accounts via acctTotals.get LEFT arm (L289/L292)", async () => {
    const container = await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: 1400,
        // Same account twice -> second iteration's .get() finds the first value.
        account_values: [
          { account: "Brokerage Alpha", value: 1000 },
          { account: "Brokerage Alpha", value: 500 },
        ],
        cash_summary: {
          total_cash_usd: 300,
          accounts: [
            // already in acctTotals from account_values -> .get() non-undefined.
            { account: "Brokerage Alpha", cash_usd: 300, cash_krw: 0, total_usd: 300 },
          ],
        },
      },
    });
    expect(container.querySelector("div.gap-4.h-full")).not.toBeNull();
  });

  // L308 arm0 — fmtEventDate `iso && iso.length >= 10` LEFT operand FALSE (empty
  // iso). An event with an empty date string makes the && short-circuit on the
  // falsy left side.
  it("fmtEventDate short-circuits on empty date (L308 arm0)", async () => {
    const container = await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: 1400,
        upcoming_events: [
          { date: "", event_type: "earnings", ticker: "AAPL", description: "AAPL ev", importance: 3 },
        ],
      },
    });
    // The events strip still renders (description shown) despite the empty date.
    expect(container.textContent || "").toContain("AAPL");
  });

  // Many `??` / `||` arms on the data-extraction lines (L210/L215/L220/L222/
  // L225/L226/L229/L230/L232/L246/L252/L274/L357/L460/L461/L588/L594/L599) take
  // their RIGHT (fallback) operand only when the optional/left value is missing.
  // One render with minimal/empty data drives all of those fallback arms at once
  // (no account_values, no cash, missing exchange_rate, missing
  // target_allocation, single winner so losers.length===0, advisor violations,
  // freshness via items, siege fail) — complementing the happy-path fixtures.
  it("drives the missing-data fallback arms (?? / || right operands)", async () => {
    const container = await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        // vix/fear_greed/exchange_rate omitted -> L215/L225/L226 fallback arms.
        regime: { regime: "bull", trend: "bull", confidence: 80 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        // target_allocation omitted -> L357 `?? d.allocation` arm.
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: null,
      },
      // single winner (latest>avg) -> winners.length>0, losers.length===0 so
      // L460 `&&` short-circuits and L461 losers `&&` left-false arm.
      "/api/portfolio": {
        count: 1,
        holdings: [{ ticker: "WIN", account: "Brokerage Alpha", quantity: 1, avg_price: 100, latest_price: 150, currency: "USD" }],
      },
      // advisor with violations -> L594 footer rule-violation line.
      "/api/rebalance-advisor": { total_violations: 2, actions: [] },
      // siege all-pass (passed omitted -> L588 `|| 0`).
      "/api/certify": { total: 2, conditions: [{ passed: true, severity: "info", description: "ok", detail: "d" }] },
      // freshness via items -> L599 items arm.
      "/api/freshness": { items: [{ source: "p", status: "PASS", age_hours: 1, threshold_hours: 24 }], overall: "PASS" } as unknown as Json,
    });
    expect(container.querySelector("div.gap-4.h-full")).not.toBeNull();
  });

  // L211 arm0 — `holdingCount === 0 -> redirect("/explore")`: when portfolio has
  // no holdings/count, redirect (mocked) is called and the page does NOT commit.
  it("redirects to /explore when there are zero holdings (L211)", async () => {
    vi.doMock("@/lib/api", () => ({
      API_BASE: "http://localhost:8001",
      fetchAPI: makeFetchAPI({ "/api/portfolio": { count: 0, holdings: [] } }),
    }));
    const nav = await import("next/navigation");
    const { default: OverviewPage } = await import("@/app/page");
    await act(async () => {
      render(OverviewPage());
    });
    for (let i = 0; i < 20; i++) {
      if ((nav.redirect as unknown as { mock: { calls: unknown[][] } }).mock.calls.length) break;
      await act(async () => {
        await Promise.resolve();
        await new Promise((r) => setTimeout(r, 0));
      });
    }
    expect((nav.redirect as unknown as { mock: { calls: unknown[][] } }).mock.calls.some((c) => c[0] === "/explore")).toBe(true);
  });

  // L219 arm0 — holdingsValue reducer's KR-ticker `.KS` true branch (price*qty
  // converted via KRW_RATE). A `.KS` holding takes the conditional's first arm.
  it("converts a .KS (KRW) holding via the L219 true arm", async () => {
    const container = await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 2, exchange_rate: 1400,
      },
      "/api/portfolio": {
        count: 2,
        holdings: [
          { ticker: "005930.KS", account: "Brokerage Alpha", quantity: 10, avg_price: 70000, latest_price: 80000, currency: "KRW" },
          { ticker: "AAPL", account: "Brokerage Alpha", quantity: 1, avg_price: 100, latest_price: 110, currency: "USD" },
        ],
        cash: { total_cash_usd: 0 },
      },
    });
    expect(container.textContent || "").toContain("AAPL");
  });

  // L229/L230/L252 RIGHT arms + L357 `?? null` arm2 — null siege & advisor &
  // missing allocations. siege null -> L229 `|| []` + L230 `|| 0`; advisor null
  // -> L252 `?? []`; both target_allocation AND allocation absent -> L357 final
  // `?? null` arm. portfolio still has 1 holding so the page commits.
  it("drives null siege/advisor + missing allocation fallbacks (L229/L230/L252/L357)", async () => {
    const container = await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        // no allocation / target_allocation / actual_allocation at all.
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: 1400,
      } as unknown as Json,
      // certify resolves to null -> siege is null in the page.
      "/api/certify": null as unknown as Json,
      // rebalance-advisor resolves to null -> advisor is null.
      "/api/rebalance-advisor": null as unknown as Json,
    });
    expect(container.querySelector("div.gap-4.h-full")).not.toBeNull();
  });

  // L232 RIGHT arm + L274 `?? 0` arms — portfolio with `count` but no `holdings`
  // array makes `portfolio?.holdings || []` take the `[]` arm; we still pass the
  // redirect gate via count>0. (positionPct sort `?? 0` also runs on the empty
  // list path through allEnrichedHoldings.)
  it("handles portfolio count without holdings array (L232 arm)", async () => {
    // count=1 (>0) so the redirect gate passes, but no `holdings` array -> the
    // `portfolio?.holdings || []` L232 right arm fires. The Dashboard commits
    // (gap-4 container) with an empty holdings list. renderWith already asserts
    // the commit, so reaching past it proves no redirect happened.
    const container = await renderWith({
      "/api/portfolio": { count: 1 } as unknown as Json,
    });
    expect(container.querySelector("div.gap-4.h-full")).not.toBeNull();
  });

  // L210 arm1 — `portfolio?.count ?? portfolio?.holdings?.length`: with `count`
  // ABSENT but a holdings array present, holdingCount falls through to
  // `holdings.length` (the middle `??` operand). (Also exercised by the default
  // fixture, which omits `count`.)
  it("derives holdingCount from holdings.length when count is absent (L210 arm1)", async () => {
    const container = await renderWith({
      "/api/portfolio": {
        // no `count` key -> `?? holdings?.length` arm.
        holdings: [{ ticker: "AAPL", account: "Brokerage Alpha", quantity: 1, avg_price: 100, latest_price: 110, currency: "USD" }],
        cash: { total_cash_usd: 0 },
      } as unknown as Json,
    });
    expect(container.textContent || "").toContain("AAPL");
  });

  // L210 arm2 — final `?? 0`: portfolio present but NEITHER count NOR a holdings
  // array, so `count ?? holdings?.length ?? 0` resolves to 0 -> redirect gate.
  it("falls through to 0 holdings and redirects (L210 arm2)", async () => {
    vi.doMock("@/lib/api", () => ({
      API_BASE: "http://localhost:8001",
      // empty object: no count, no holdings -> holdingCount === 0 -> redirect.
      fetchAPI: makeFetchAPI({ "/api/portfolio": {} as unknown as Json }),
    }));
    const nav = await import("next/navigation");
    (nav.redirect as unknown as { mockClear: () => void }).mockClear?.();
    const { default: OverviewPage } = await import("@/app/page");
    await act(async () => {
      render(OverviewPage());
    });
    for (let i = 0; i < 20; i++) {
      if ((nav.redirect as unknown as { mock: { calls: unknown[][] } }).mock.calls.length) break;
      await act(async () => {
        await Promise.resolve();
        await new Promise((r) => setTimeout(r, 0));
      });
    }
    expect((nav.redirect as unknown as { mock: { calls: unknown[][] } }).mock.calls.some((c) => c[0] === "/explore")).toBe(true);
  });

  // L246 arm2 — `accountLabels[...] || h.account || ""` final "" arm: a holding
  // with NO account and NO matching label falls through both `||` to "".
  it("labels a holding with no account via the empty-string arm (L246 arm2)", async () => {
    const container = await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: 1400,
      },
      "/api/portfolio": {
        count: 1,
        holdings: [{ ticker: "NOACCT", quantity: 1, avg_price: 100, latest_price: 110, currency: "USD" }],
        cash: { total_cash_usd: 0 },
      },
    });
    expect(container.textContent || "").toContain("NOACCT");
  });

  // L460/L461 arm + L319 eventDday D+ (past) arm — a loser holding (latest<avg)
  // so losers.length>0 (L461 right arm; L460 winners&&losers separator), plus a
  // PAST upcoming_event so eventDday returns the `D+N` (days<0) ternary arm.
  it("renders losers + a past event (L460/L461 + L319 D+ arm)", async () => {
    const container = await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 2, exchange_rate: 1400,
        upcoming_events: [
          // a clearly-past date -> eventDday days < 0 -> "D+N" arm.
          { date: "2000-01-01", event_type: "earnings", ticker: "OLD", description: "past ev", importance: 1 },
        ],
      },
      "/api/portfolio": {
        count: 2,
        holdings: [
          { ticker: "WINR", account: "Brokerage Alpha", quantity: 1, avg_price: 100, latest_price: 150, currency: "USD" },
          { ticker: "LOSR", account: "Brokerage Alpha", quantity: 1, avg_price: 100, latest_price: 50, currency: "USD" },
        ],
        cash: { total_cash_usd: 0 },
      },
    });
    expect(container.textContent || "").toContain("LOSR");
  });

  // L599 arm — freshness with NEITHER items nor details non-empty: the footer
  // `(items.length>0 || details.length>0)` is FALSE so FreshnessBar is hidden;
  // this drives the AND short-circuit / OR-both-false arms at L599.
  it("hides FreshnessBar when both items and details are empty (L599)", async () => {
    const container = await renderWith({
      "/api/freshness": { items: [], details: [], overall: "FAIL" } as unknown as Json,
    });
    expect(container.querySelector("div.gap-4.h-full")).not.toBeNull();
  });

  // L274 `?? 0` arms — null positionPct in the sort comparator. With total
  // portfolio value 0 (zero-priced holdings + no cash + no account_values),
  // buildEnrichedHoldings yields positionPct === null, so both `a.positionPct ??
  // 0` and `b.positionPct ?? 0` take the 0 fallback.
  it("sorts null-positionPct holdings via the ?? 0 fallback (L274 arms)", async () => {
    const container = await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 2, exchange_rate: 1400,
      },
      "/api/portfolio": {
        count: 2,
        // latest_price 0 -> position value 0 -> totalPortfolioUsd 0 -> positionPct null.
        holdings: [
          { ticker: "ZA", account: "Brokerage Alpha", quantity: 1, avg_price: 100, latest_price: 0, currency: "USD" },
          { ticker: "ZB", account: "Brokerage Alpha", quantity: 1, avg_price: 100, latest_price: 0, currency: "USD" },
        ],
        cash: { total_cash_usd: 0 },
      },
    });
    expect(container.querySelector("div.gap-4.h-full")).not.toBeNull();
  });

  // L246 arm2 + L308 arm1 — (a) a holding with an empty-string account makes
  // `accountLabels[""] || h.account || ""` fall through to the final "" arm;
  // (b) an event whose `date` is null makes fmtEventDate's `... : iso ?? ""`
  // take the `?? ""` arm (iso null, not empty-string).
  it("covers empty account label arm + fmtEventDate iso ?? '' arm (L246/L308)", async () => {
    const container = await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: 1400,
        upcoming_events: [
          // date null -> fmtEventDate hits the `iso ?? ""` arm (L308).
          { date: null as unknown as string, event_type: "earnings", ticker: "NUL", description: "null-date ev", importance: 1 },
        ],
      },
      "/api/portfolio": {
        count: 1,
        // account "" -> labels[""] undefined, h.account "" falsy -> final "" arm (L246).
        holdings: [{ ticker: "EMPACC", account: "", quantity: 1, avg_price: 100, latest_price: 110, currency: "USD" }],
        cash: { total_cash_usd: 0 },
      },
    });
    expect(container.textContent || "").toContain("EMPACC");
  });

  // L367 — trend color ternary: bull arm
  it("renders bull trend with emerald color (L367 arm 1)", async () => {
    await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: 1400,
      },
    });
    expect(document.querySelector("span.text-emerald-400.font-semibold")).not.toBeNull();
  });

  // L367 — trend color ternary: bear arm
  it("renders bear trend with red color (L367 arm 2)", async () => {
    await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bear", trend: "bear", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: 1400,
      },
    });
    expect(document.querySelector("span.text-red-400.font-semibold")).not.toBeNull();
  });

  // L367 — trend color ternary: sideways (else) arm
  it("renders sideways trend with amber color (L367 else arm)", async () => {
    await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "sideways", trend: "sideways", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: 1400,
      },
    });
    expect(document.querySelector("span.text-amber-400.font-semibold")).not.toBeNull();
  });

  // L217 / L218 — holdingsValue reducer falsy defaults (NOPRICE in base fixture).
  it("defaults missing latest_price/quantity to 0 in holdingsValue (L217/L218)", async () => {
    await renderWith({});
    expect(document.body.textContent || "").toContain("AAPL");
  });

  // L495-506 collapsed arm + L544/L546 slice arm — > HOLDINGS_COLLAPSED_LIMIT (8).
  it("renders collapsed holdings toggle (L496 false / L502-503 false / L544 slice arm)", async () => {
    const container = await renderWith({
      "/api/portfolio": { count: 10, holdings: manyHoldings(10), cash: { total_cash_usd: 0 } },
    });
    const toggle = container.querySelector('[data-testid="holdings-toggle"]') as HTMLAnchorElement | null;
    expect(toggle).not.toBeNull();
    expect(toggle!.getAttribute("href")).toBe("/?holdings=expanded");
    // Collapsed -> slice(0, HOLDINGS_COLLAPSED_LIMIT=8): at most 8 rows render
    // (fewer than the 10+ enriched holdings) — proves the L544/L546 slice arm.
    const rows = container.querySelectorAll('[data-testid="holding-row"]').length;
    expect(rows).toBeLessThanOrEqual(8);
    expect(rows).toBeGreaterThan(0);
  });

  // L497/L502-503 expanded arm + L544 `holdingsExpanded ? all` arm.
  it("renders expanded holdings toggle (L497 true / L503 collapse label / L544 all arm)", async () => {
    const container = await renderWith(
      { "/api/portfolio": { count: 10, holdings: manyHoldings(10), cash: { total_cash_usd: 0 } } },
      Promise.resolve({ holdings: "expanded" }),
    );
    const toggle = container.querySelector('[data-testid="holdings-toggle"]') as HTMLAnchorElement | null;
    expect(toggle).not.toBeNull();
    expect(toggle!.getAttribute("href")).toBe("/");
    // Expanded -> ALL rows render (the `holdingsExpanded ? all` L544 arm),
    // i.e. more than the collapsed slice's HOLDINGS_COLLAPSED_LIMIT (8).
    expect(container.querySelectorAll('[data-testid="holding-row"]').length).toBeGreaterThan(8);
  });

  // L564/L565 — opportunities section gate (> 0 arm).
  it("renders opportunity section when opportunities present (L564/L565)", async () => {
    await renderWith({
      "/api/portfolio": { count: 10, holdings: manyHoldings(10), cash: { total_cash_usd: 0 } },
      "/api/opportunities": {
        opportunities: [
          { ticker: "NVDA", score: 9, reason: "momentum" },
          { ticker: "AMD", score: 8, reason: "value" },
        ],
      },
    });
    expect(document.body.textContent || "").toContain("기회 탐색");
  });

  // L577/L578 — coverage section gate: coverage present, no error, checks.length > 0.
  it("renders coverage section when coverage has checks (L577/L578)", async () => {
    await renderWith({
      "/api/coverage": {
        error: null,
        checks: [{ name: "prices", status: "PASS", detail: "ok" }],
      } as unknown as Json,
    });
    expect(document.querySelector("div.pt-2")).not.toBeNull();
  });

  // L601-603 — pipeline status color: known (done -> emerald) vs unknown (-> zinc fallback).
  it("maps known + unknown pipeline status colors (L603 both arms)", async () => {
    await renderWith({
      "/api/pipeline/status": {
        steps: [
          { step: "collect", label: "Collect", status: "done", record_count: 100, last_updated: "2026-01-01" },
          { step: "weird", label: "Weird", status: "totally-unknown", record_count: 5, last_updated: "2026-01-01" },
        ],
      },
    });
    expect(document.querySelector("span.bg-emerald-500")).not.toBeNull();
    expect(document.querySelector("span.bg-zinc-500")).not.toBeNull();
  });

  // L610-614 — siege failed severity ternary: "error" (red) vs non-error (amber).
  it("renders siege failures with error + non-error severities (L614 both arms)", async () => {
    await renderWith({
      "/api/certify": {
        certified: false,
        passed: 1,
        total: 3,
        conditions: [
          { passed: false, severity: "error", description: "Hard veto", detail: "risk of ruin" },
          { passed: false, severity: "warn", description: "Soft penalty", detail: "downgrade" },
        ],
      },
    });
    expect(document.querySelectorAll("span.text-red-400").length).toBeGreaterThan(0);
    expect(document.querySelectorAll("span.text-amber-400").length).toBeGreaterThan(0);
  });

  // L213/L214 arm1 + L227 arm1 — fallback arms: unknown verdict_level makes the
  // VerdictBanner 의 verdictLabels/BANNER_STYLES lookup undefined (`?? neutral`),
  // and an empty trend hits `d.regime.trend || "unknown"`.
  it("falls back on unknown verdict_level + empty trend (L213/L214/L227 arm1)", async () => {
    await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "totally-unknown-level",
        regime: { regime: "x", trend: "", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: 1400,
      },
    });
    // trend "" -> "unknown" -> trendKo else branch -> sideways amber color.
    expect(document.querySelector("span.text-amber-400.font-semibold")).not.toBeNull();
  });

  // L274 arm0 (×2) — the sort comparator's `?? 0` nullish arms: holdings whose
  // positionPct is null (no totalPortfolioUsd denominator -> positionPct null in
  // buildEnrichedHoldings) make `b.positionPct ?? 0` / `a.positionPct ?? 0` take
  // the 0 fallback during the desc sort.
  it("sorts holdings with null positionPct via ?? 0 fallback (L274 arm0)", async () => {
    await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 2, exchange_rate: 1400,
      },
      // total cash 0 + no account_values -> totalPortfolioUsd 0 -> positionPct null.
      "/api/portfolio": {
        count: 2,
        holdings: [
          { ticker: "AAA", account: "Brokerage Alpha", quantity: 1, avg_price: 100, latest_price: 110, currency: "USD" },
          { ticker: "BBB", account: "Brokerage Alpha", quantity: 1, avg_price: 100, latest_price: 110, currency: "USD" },
        ],
        cash: { total_cash_usd: 0 },
      },
    });
    expect(document.body.textContent || "").toContain("AAA");
  });

  // L308 arm0 — fmtEventDate `iso && iso.length >= 10` TRUE arm (valid date is
  // sliced to MM-DD). Needs a stripEvents entry with a >= 10-char date.
  it("formats a valid event date via fmtEventDate true arm (L308)", async () => {
    await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 2, exchange_rate: 1400,
        upcoming_events: [
          { date: "2099-12-31", event_type: "earnings", ticker: "AAPL", description: "AAPL earnings", importance: 3 },
        ],
      },
    });
    // "2099-12-31".slice(5,10) === "12-31"
    expect(document.body.textContent || "").toContain("12-31");
  });

  // L357 arm1 + L362/L363 arm1 — "meaningful target" allocation strip: a target
  // with long/short > 0 that differs from actual makes hasMeaningfulTarget true,
  // exercising the L362 OR right side and the L363 inequality.
  it("renders the meaningful target allocation arm (L357/L362/L363 arm1)", async () => {
    const container = await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        actual_allocation: { long: 0, short: 0, cash: 100 },
        target_allocation: { long: 70, short: 0, cash: 30 },
        allocation: { long: 70, short: 0, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: 1400,
      },
    });
    // The 권장(target) span renders only when hasMeaningfulTarget is true.
    expect(container.textContent || "").toContain("권장");
  });

  // L362 arm2 (col 38) — the OR right operand `target.short > 0`: with
  // target.long === 0 the left disjunct is false, forcing evaluation of the
  // short-side operand.
  it("evaluates target.short OR-arm when long is 0 (L362 right operand)", async () => {
    const container = await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        actual_allocation: { long: 0, short: 0, cash: 100 },
        target_allocation: { long: 0, short: 50, cash: 50 },
        allocation: { long: 0, short: 50, cash: 50 },
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: 1400,
      },
    });
    expect(container.textContent || "").toContain("권장");
  });

  // L423 arm1/arm2 — event label fallback `ev.description || ev.ticker || FALLBACK`:
  // one event with no description (uses ticker = arm1), one with neither
  // description nor ticker (uses STRIP.EVENTS_FALLBACK = arm2).
  it("renders event label ticker + fallback arms (L423 arm1/arm2)", async () => {
    await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 1, exchange_rate: 1400,
        upcoming_events: [
          { date: "2099-01-01", event_type: "earnings", ticker: "MSFT", description: "", importance: 2 },
          { date: "2099-02-02", event_type: "earnings", ticker: null, description: "", importance: 1 },
        ],
      },
    });
    // arm1: description "" falsy -> ticker "MSFT" shown.
    expect(document.body.textContent || "").toContain("MSFT");
  });

  // L464 arm1 — pension-hidden separator `(winners > 0 || losers > 0) && " · "`:
  // needs hidden pension holdings AND visible winners/losers so the separator
  // renders between the win/loss count and the pension count.
  it("renders pension-count separator with winners present (L464 arm1)", async () => {
    const container = await renderWith({
      "/api/dashboard": {
        verdict: "Hold", verdict_level: "neutral",
        regime: { regime: "bull", trend: "bull", confidence: 80, vix: 15, fear_greed: 55 },
        macro: { score: 60, interpretation: "n" },
        allocation: { long: 60, short: 10, cash: 30 },
        actions: [], alerts: [], gate_score: 80, n_positions: 2, exchange_rate: 1400,
      },
      "/api/portfolio": {
        count: 2,
        holdings: [
          // visible LOSER only (latest < avg) -> losers.length>0, winners===0,
          // so the L468 separator `(winners>0 || losers>0)` takes its OR-RIGHT
          // operand (losers).
          { ticker: "LOS", account: "Brokerage Alpha", quantity: 1, avg_price: 100, latest_price: 50, currency: "USD" },
          // a Pension holding -> hidden -> hiddenPensionCount > 0. IMPORTANT:
          // winners/losers are computed over ALL holdings (pre-pension-filter),
          // so PEN must NOT be a winner (latest == avg) or it would make
          // winners.length > 0 and the L468 OR would short-circuit on the left.
          { ticker: "PEN", account: "Pension", quantity: 1, avg_price: 100, latest_price: 100, currency: "USD" },
        ],
        cash: { total_cash_usd: 0 },
      },
    });
    // The hidden-pension note (SECTION.PENSION + count) renders next to the loser.
    expect(container.textContent || "").toContain("LOS");
  });

  // L587 arm1 — footer SIEGE quality "pass" line `siegeTotal > 0 &&
  // siegeFailed.length === 0`: all conditions passed.
  it("renders the SIEGE quality-pass footer (L587 arm)", async () => {
    const container = await renderWith({
      "/api/certify": {
        certified: true,
        passed: 3,
        total: 3,
        conditions: [
          { passed: true, severity: "info", description: "ok1", detail: "d" },
          { passed: true, severity: "info", description: "ok2", detail: "d" },
          { passed: true, severity: "info", description: "ok3", detail: "d" },
        ],
      },
    });
    // pass line uses a green check glyph (✓ = ✓) in an emerald span.
    expect(container.querySelector("span.text-emerald-500")).not.toBeNull();
  });

  // L598 arm1 — freshness bar `items.length > 0 || details.length > 0`: provide
  // `details` (not `items`) so the OR right-hand arm renders the FreshnessBar.
  it("renders FreshnessBar via the details arm (L606 items ?? details)", async () => {
    const container = await renderWith({
      // `items` ABSENT (not []) so `freshness?.items ?? freshness?.details` takes
      // the `?? details` arm; details non-empty so the gate `(... || details>0)`
      // is also true and FreshnessBar renders.
      "/api/freshness": {
        details: [{ source: "prices", status: "PASS", age_hours: 1, threshold_hours: 24 }],
        overall: "PASS",
      } as unknown as Json,
    });
    // FreshnessBar rendered -> the footer right cluster is non-empty.
    expect(container.querySelector("div.ml-auto")).not.toBeNull();
  });
});
