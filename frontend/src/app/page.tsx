export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { redirect } from "next/navigation";
import { fetchAPI } from "@/lib/api";

import { StatusBadge } from "@/components/ui/status-badge";
import { FreshnessBar, type FreshnessItem } from "@/components/ui/freshness-bar";
import { HoldingRow, buildEnrichedHoldings, type RawAction, type RawTarget, type RawAdvisorAction, type RawEvent } from "@/components/ui/holding-row";
import { CollapsibleStrip } from "@/components/ui/collapsible-strip";
import { HeroStats } from "@/components/ui/hero-stats";
import { CompositionSection, parseCompositionTab } from "@/components/ui/composition-section";
import { ActionItems } from "@/components/ui/action-items";
import { OpportunityExplorer } from "@/components/ui/opportunity-explorer";
import { MarketContext } from "@/components/ui/market-context";
import { summarizeHoldings } from "@/lib/holdings-summary";
import Link from "next/link";
import { VERDICT, TREND, VIX_ZONE, FEAR_GREED, MACRO_LEVEL, SECTION, STRIP, MARKET, FOOTER, COL, SPARKLINE as SPARK, COMMON, ACTION, CONTEXT } from "@/lib/strings";

interface DashboardData {
  verdict: string;
  verdict_level: string;
  regime: { regime: string; trend: string; volatility?: string; confidence: number; vix?: number; fear_greed?: number };
  macro: { score: number; interpretation: string };
  allocation: { long: number; short: number; cash: number };
  target_allocation?: { long: number; short: number; cash: number };
  actual_allocation?: { long: number; short: number; cash: number };
  cash_summary?: {
    accounts: Array<{ account: string; cash_usd: number; cash_krw: number; total_usd: number }>;
    total_cash_usd: number;
  };
  actions: Array<{ action: string; ticker: string; name?: string | null; confidence: number; agreement: number; reason: string; account?: string }>;
  alerts: Array<{ level: string; message: string }>;
  gate_score: number;
  n_positions: number;
  exchange_rate: number | null;
  account_values?: Array<{ account: string; value: number }>;
  upcoming_events?: Array<{ date: string; event_type: string; ticker: string | null; description: string; importance: number }>;
  ticker_accounts?: Record<string, string>;
  account_labels?: Record<string, string>;
}

interface FreshnessData {
  items?: FreshnessItem[];
  details?: FreshnessItem[];
  overall?: "PASS" | "WARN" | "FAIL";
  pass?: number; warn?: number; fail?: number;
}

interface PipelineStatusData {
  steps: Array<{ step: string; label: string; status: string; record_count: number; last_updated: string | null }>;
}

const verdictLabels: Record<string, string> = {
  aggressive: VERDICT.AGGRESSIVE, neutral: VERDICT.NEUTRAL, cautious: VERDICT.CAUTIOUS, defensive: VERDICT.DEFENSIVE,
};
const levelStyles: Record<string, { text: string }> = {
  aggressive: { text: "text-emerald-400" },
  neutral:    { text: "text-zinc-400" },
  cautious:   { text: "text-amber-400" },
  defensive:  { text: "text-red-400" },
};
const pipelineStatusColors: Record<string, string> = {
  idle: "bg-zinc-500", running: "bg-blue-500 animate-pulse", done: "bg-emerald-500", error: "bg-red-500",
};

/* ── 헬퍼 ── */
function trendKo(t: string) { return t === "bull" ? TREND.BULL : t === "bear" ? TREND.BEAR : TREND.SIDEWAYS; }
function vixZone(v: number | null): { label: string; color: string } {
  if (v == null) return { label: "—", color: "text-zinc-500" };
  if (v < 12) return { label: VIX_ZONE.CALM, color: "text-blue-400" };
  if (v < 17) return { label: VIX_ZONE.LOW, color: "text-emerald-400" };
  if (v < 23) return { label: VIX_ZONE.NORMAL, color: "text-zinc-300" };
  if (v < 33) return { label: VIX_ZONE.CAUTION, color: "text-orange-400" };
  return { label: VIX_ZONE.DANGER, color: "text-red-400" };
}
function fgLabel(fg: number | null): string {
  if (fg == null) return "—";
  if (fg < 25) return FEAR_GREED.EXTREME_FEAR; if (fg < 45) return FEAR_GREED.FEAR;
  if (fg <= 55) return FEAR_GREED.NEUTRAL; if (fg <= 75) return FEAR_GREED.GREED;
  return FEAR_GREED.EXTREME_GREED;
}
function fgColor(fg: number | null): string {
  if (fg == null) return "bg-zinc-700 text-zinc-400";
  if (fg < 25) return "bg-red-500/20 text-red-400";
  if (fg < 45) return "bg-orange-500/20 text-orange-400";
  if (fg <= 55) return "bg-yellow-500/20 text-yellow-400";
  if (fg <= 75) return "bg-lime-500/20 text-lime-400";
  return "bg-emerald-500/20 text-emerald-400";
}
function macroLevel(s: number): { label: string; color: string } {
  if (s >= 70) return { label: MACRO_LEVEL.GOOD, color: "text-emerald-400" };
  if (s >= 50) return { label: MACRO_LEVEL.NORMAL, color: "text-zinc-300" };
  if (s >= 30) return { label: MACRO_LEVEL.WEAK, color: "text-orange-400" };
  return { label: MACRO_LEVEL.FRAGILE, color: "text-red-400" };
}
/** 계좌 라벨 한국어 표시 (Pension만 특수, 나머지는 원본 유지) */
function accountKo(label: string | undefined): string {
  if (!label) return "";
  if (label === "Pension") return SECTION.PENSION;
  return label;
}

/* ══════════════════════════════════════════════════════ */

// #214 polish: sparkline period options shown as URL-driven toggle (?period=14|30|60|90)
const SPARKLINE_PERIOD_OPTIONS = [14, 30, 60, 90] as const;
type SparklinePeriod = (typeof SPARKLINE_PERIOD_OPTIONS)[number];

function parseSparklinePeriod(raw: string | undefined): SparklinePeriod {
  const n = parseInt(raw ?? "30", 10);
  if (SPARKLINE_PERIOD_OPTIONS.includes(n as SparklinePeriod)) return n as SparklinePeriod;
  return 30;
}

// #223 iter 7: holdings drilldown is collapsed by default (top 8 rows + "전체"
// link). The new dashboard centerpiece is the composition section, not the
// holdings table — so the table's role is "drill into details on demand".
const HOLDINGS_COLLAPSED_LIMIT = 8;

async function Dashboard({
  searchParams,
}: {
  searchParams?: Promise<{ period?: string; comp?: string; holdings?: string }> | undefined;
}) {
  // Defensive: searchParams may be undefined when rendered outside the page boundary
  // (e.g. some error paths in dev). Default to an empty object.
  const params = (searchParams ? await searchParams : undefined) ?? {};
  const sparklinePeriod = parseSparklinePeriod(params.period);
  const compositionTab = parseCompositionTab(params.comp);
  const holdingsExpanded = params.holdings === "expanded";

  const [d, freshness, pipelineStatus, portfolio, siege, advisor, targets, actionsData, opportunitiesData, marketCtx] = await Promise.all([
    fetchAPI<DashboardData>("/api/dashboard"),
    fetchAPI<FreshnessData>("/api/freshness").catch((): FreshnessData => ({ items: [], details: [], overall: "FAIL", pass: 0, warn: 0, fail: 0 })),
    fetchAPI<PipelineStatusData>("/api/pipeline/status").catch((): PipelineStatusData => ({ steps: [] })),
    fetchAPI<any>("/api/portfolio").catch(() => null),
    Promise.race([
      fetchAPI<any>("/api/certify"),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 3000)),
    ]).catch(() => null),
    fetchAPI<any>("/api/rebalance-advisor").catch(() => null),
    fetchAPI<{ targets: RawTarget[] }>("/api/targets").catch(() => ({ targets: [] as RawTarget[] })),
    fetchAPI<any>("/api/actions").catch(() => ({ urgent: [], check: [], hold: [] })),
    fetchAPI<any>("/api/opportunities").catch(() => ({ opportunities: [] })),
    fetchAPI<any>("/api/market-context").catch(() => ({ macro_events: [], system_health: {} })),
  ]);

  const holdingCount = portfolio?.count ?? portfolio?.holdings?.length ?? 0;
  if (holdingCount === 0) redirect("/explore");

  const style = levelStyles[d.verdict_level] || levelStyles.neutral;
  const verdictLabel = verdictLabels[d.verdict_level] || VERDICT.NEUTRAL;
  const KRW_RATE = d.exchange_rate || 1400;
  const holdingsValue = portfolio?.holdings?.reduce((sum: number, h: any) => {
    const price = h.latest_price || 0;
    const qty = h.quantity || 0;
    return sum + (h.ticker?.endsWith(".KS") ? price * qty / KRW_RATE : price * qty);
  }, 0) || 0;
  // #213: 총 자산 = holdings + cash. cash는 portfolio.yaml 기반 /api/portfolio에서 옴.
  const cashTotalUsd = portfolio?.cash?.total_cash_usd ?? d.cash_summary?.total_cash_usd ?? 0;
  const totalValue = holdingsValue + cashTotalUsd;

  const vix = d.regime.vix ?? null;
  const fg = d.regime.fear_greed ?? null;
  const trend = d.regime.trend || "unknown";
  const alertCount = d.alerts.length;
  const siegeFailed = siege?.conditions?.filter((c: any) => !c.passed) || [];
  const siegeTotal = siege?.total || 0;

  const holdings = portfolio?.holdings || [];
  const winners = holdings.filter((h: any) => h.latest_price && h.avg_price && h.latest_price > h.avg_price);
  const losers = holdings.filter((h: any) => h.latest_price && h.avg_price && h.latest_price < h.avg_price);
  const vixInfo = vixZone(vix);
  const macroInfo = macroLevel(d.macro.score);
  const accountValues = d.account_values || [];

  // 통합 보유 종목 — 매매 상태 + 가격 타겟 + 워치 트리거 결합
  // account_labels: raw broker → 익명 label (per-account 매핑). 다계좌 ticker는
  // ticker_accounts(ticker→label, 단일 매핑)로 풀 수 없어서 collision이 발생했음 — 각
  // holding의 raw account를 key로 라벨을 lookup하여 fix.
  const accountLabels = d.account_labels || {};
  const labeledHoldings = holdings.map((h: any) => ({
    ...h,
    accountLabel: accountKo(accountLabels[h.account] || h.account || ""),
  }));
  const builtHoldings = buildEnrichedHoldings(
    labeledHoldings as any,
    d.actions as RawAction[],
    targets?.targets ?? [],
    (advisor?.actions ?? []) as RawAdvisorAction[],
    (d.upcoming_events ?? []) as RawEvent[],
    // #218: 2xl+ 초광폭 컬럼(비중 %)을 위해 총 자산 + 환율 전달.
    // totalValue 는 holdings (USD 환산) + cash 합계 — pie denominator 로 사용.
    { totalPortfolioUsd: totalValue, usdKrwRate: KRW_RATE },
  );
  // #214 polish: sparkline은 90일을 backend에서 받고, 선택된 period에 맞춰 최근 N개만 frontend에서 slice
  const allEnrichedHoldings = builtHoldings.map((h) => ({
    ...h,
    sparkline: h.sparkline.slice(-sparklinePeriod),
  }));
  // #214 polish: 연금 holdings은 월 리밸런싱이라 daily dashboard에서 제외.
  // 연금 전용 UI는 별도 페이지(/portfolio)에서 볼 수 있음.
  // "Pension" / "Pension 2" / "연금" / "연금 2" 등 모든 번호 suffix 변형을 prefix로 잡는다.
  const isPensionLabel = (label: string) => label.startsWith(SECTION.PENSION) || label.startsWith("Pension");
  // #223 iter 7c: dashboard view sorts by positionPct desc (largest position first)
  // — overrides the buildEnrichedHoldings default (account → status → pnl) which is
  // useful for /portfolio's grouped view but wrong for the dashboard's "biggest
  // positions first" expectation. The internal builder sort is preserved for other
  // consumers; we just re-sort the visible subset here.
  const enrichedHoldings = allEnrichedHoldings
    .filter((h) => !isPensionLabel(h.account))
    .sort((a, b) => (b.positionPct ?? 0) - (a.positionPct ?? 0));
  const hiddenPensionCount = allEnrichedHoldings.length - enrichedHoldings.length;

  // heldTickers: used by HoldingRow enrichment for action matching
  const heldTickers = new Set(holdings.map((h: any) => h.ticker));

  // #223: composition section needs the same summarized data the old summary
  // panel had. Compute once at page level so HeroStats + CompositionSection
  // share it without recomputing. Merge account_values + cash_summary so
  // every account (including pension/IRP) appears in the breakdown.
  const acctTotals = new Map<string, number>();
  for (const av of accountValues) {
    acctTotals.set(av.account, (acctTotals.get(av.account) ?? 0) + av.value);
  }
  for (const cash of d.cash_summary?.accounts ?? []) {
    acctTotals.set(cash.account, (acctTotals.get(cash.account) ?? 0) + cash.total_usd);
  }
  const mergedAccountValues = Array.from(acctTotals.entries()).map(
    ([account, value]) => ({ account, value }),
  );
  const summary = summarizeHoldings(enrichedHoldings, {
    totalPortfolioUsd: totalValue,
    accountValues: mergedAccountValues,
  });

  // Upcoming events strip — retained as unique data (earnings calendar, not macro news)
  const stripEvents = (d.upcoming_events ?? [])
    .slice(0, 5)
    .map((ev: any) => ({ date: ev.date as string, description: ev.description as string | undefined, ticker: ev.ticker as string | null }));

  // Helper — "MM-DD" format
  const fmtEventDate = (iso: string) => (iso && iso.length >= 10 ? iso.slice(5, 10) : iso ?? "");
  // Helper — D-day from YYYY-MM-DD (local time, timezone-safe)
  const eventDday = (iso: string): string => {
    if (!iso || iso.length < 10) return "";
    const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
    if (!y || !m || !d) return "";
    const eventMs = new Date(y, m - 1, d).getTime();
    const today = new Date();
    const todayMs = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
    const days = Math.round((eventMs - todayMs) / 86_400_000);
    if (days === 0) return "D-DAY";
    return days > 0 ? `D-${days}` : `D+${-days}`;
  };

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* ═══ #223 NEW HERO: 4 big metrics row (총자산 · 오늘 · 누적 · 배당) ═══ */}
      <HeroStats
        totalUsd={totalValue}
        cashTotalUsd={cashTotalUsd}
        holdingsValueUsd={holdingsValue}
        summary={summary}
        verdictLabel={verdictLabel}
      />

      {/* ═══ Action-First: 오늘의 액션 + 시스템 건강 + 시장 컨텍스트 + 기회 탐색 ═══ */}
      <div className="space-y-4">
        {/* 시스템 건강 + 시장 컨텍스트 (#137 UI) */}
        <MarketContext
          events={marketCtx?.macro_events ?? []}
          health={marketCtx?.system_health ?? {}}
        />

        {/* 오늘의 액션 */}
        <div>
          <h2 className="text-sm font-semibold text-zinc-300 mb-2">{ACTION.TITLE}</h2>
          <ActionItems
            urgent={actionsData?.urgent ?? []}
            check={actionsData?.check ?? []}
            hold={actionsData?.hold ?? []}
          />
        </div>

        {/* 기회 탐색 */}
        {(opportunitiesData?.opportunities?.length ?? 0) > 0 && (
          <div>
            <h2 className="text-sm font-semibold text-zinc-300 mb-2 flex items-center gap-1.5">
              🔍 {CONTEXT.TITLE} — 이슈 종목
            </h2>
            <OpportunityExplorer opportunities={opportunitiesData?.opportunities ?? []} />
          </div>
        )}
      </div>

      {/* ═══ #223 iter 7c: market + allocation compact strip (1 row).
          Each metric only renders when it actually has data — no more
          dangling "VIX — —" / "권장 0% / 100%" placeholders. */}
      {(() => {
        // actual: API always provides this in real responses; mock tests
        // sometimes don't, so default to a sentinel that still renders.
        const actual = d.actual_allocation ?? { long: 0, short: 0, cash: 100 };
        const target = d.target_allocation ?? d.allocation ?? null;
        // Hide 권장 entirely when it's the meaningless 0/100 default
        // (means "no regime data") or matches actual.
        const hasMeaningfulTarget =
          target != null &&
          (target.long > 0 || target.short > 0) &&
          !(target.long === actual.long && target.cash === actual.cash);
        const hasMacroScore = typeof d.macro?.score === "number" && d.macro.score > 0;
        return (
          <div className="flex items-center gap-3 flex-wrap text-[10px] text-zinc-500 px-2 py-1.5 rounded bg-zinc-900/40 border border-zinc-800/60">
            <span className={trend === "bull" ? "text-emerald-400 font-semibold" : trend === "bear" ? "text-red-400 font-semibold" : "text-amber-400 font-semibold"}>
              {trendKo(trend)}
            </span>
            {vix != null && (
              <span>
                VIX <span className={`font-semibold tabular-nums ${vixInfo.color}`}>{Math.round(vix * 10) / 10}</span> <span className={vixInfo.color}>{vixInfo.label}</span>
              </span>
            )}
            {fg != null && (
              <span>
                {MARKET.SENTIMENT} <span className={`inline-flex items-center justify-center h-4 w-4 rounded-full text-[9px] font-bold tabular-nums ${fgColor(fg)}`}>{fg}</span> <span className="text-zinc-600">{fgLabel(fg)}</span>
              </span>
            )}
            {hasMacroScore && (
              <span>
                {MARKET.ECONOMY} <span className={`font-semibold tabular-nums ${macroInfo.color}`}>{d.macro.score}</span> <span className={macroInfo.color}>{macroInfo.label}</span>
              </span>
            )}
            <span className="text-zinc-700">·</span>
            <span>
              {MARKET.ACTUAL} <span className="text-emerald-400 font-semibold tabular-nums">{actual.long}%</span> {MARKET.INVEST} / <span className="text-zinc-300 font-semibold tabular-nums">{actual.cash}%</span> {MARKET.CASH}
            </span>
            {hasMeaningfulTarget && target && (
              <>
                <span className="text-zinc-700">→</span>
                <span className="text-zinc-600">
                  {MARKET.TARGET} <span className="text-emerald-500 tabular-nums">{target.long}%</span> / <span className="text-zinc-500 tabular-nums">{target.cash}%</span>
                </span>
              </>
            )}
            <span className={`ml-auto text-[10px] ${style.text} truncate max-w-[40%]`} title={d.verdict}>
              {d.verdict}
            </span>
          </div>
        );
      })()}

      {/* ═══ Collapsible strips removed — replaced by Action-First sections above.
          Alerts → ActionItems 🔴 urgent, Candidates → ActionItems 🟡 check/✅ hold,
          Events → MarketContext macro events. Only upcoming earnings strip retained. ═══ */}
      {stripEvents.length > 0 && (
        <CollapsibleStrip
          id="events"
          title={STRIP.EVENTS_TITLE}
          icon="📅"
          count={stripEvents.length}
          emptyText={STRIP.EVENTS_EMPTY}
        >
          <div className="flex items-start gap-2 px-2 py-1 rounded bg-zinc-900/40 border border-zinc-800/60 pr-6">
            <span className="text-[10px] text-zinc-400 font-semibold shrink-0">{STRIP.EVENTS_PREFIX} {stripEvents.length}{COMMON.COUNT_SUFFIX}</span>
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 flex-1 min-w-0">
              {stripEvents.map((ev, i) => {
                const dday = eventDday(ev.date);
                return (
                  <span key={`${ev.date}-${i}`} className="text-[10px] text-zinc-400 truncate">
                    <span className="text-zinc-600 tabular-nums">{fmtEventDate(ev.date)}</span>{" "}
                    {ev.description || ev.ticker || STRIP.EVENTS_FALLBACK}
                    {dday && <span className="text-zinc-600 ml-1">({dday})</span>}
                  </span>
                );
              })}
            </div>
          </div>
        </CollapsibleStrip>
      )}

      {/* ═══ #223 NEW: Composition section (donut + tabs + legend).
          Sits between status strips and the holdings drilldown table.
          Hidden when there's nothing visible to show. */}
      {enrichedHoldings.length > 0 && (
        <CompositionSection
          summary={summary}
          totalUsd={totalValue}
          activeTab={compositionTab}
        />
      )}

      {/* ═══ 보유 종목 — drilldown 위치 (#223 restructure).
          이전엔 메인이었지만 이제 composition 아래의 detail 뷰. */}
      {enrichedHoldings.length > 0 && (
        <section className="flex flex-col items-start" data-testid="holdings-section">
          {/*
            w-fit wrapper — 제목 바 + 테이블 이 모두 테이블의 natural width (현재 breakpoint 의
            column sum)에 맞춰 shrink 한다. 덕분에 period toggle + 상세 링크가 테이블의 우측
            가장자리에 정확히 정렬되어, 우측에 떠 있는 "disconnected toolbar" 문제가 사라진다.
            max-w-full 은 narrow viewport safety net.
          */}
          <div className="w-fit max-w-full">
          <div className="flex items-center justify-between mb-1.5 gap-3">
            <div className="flex items-center gap-2 min-w-0">
              <h2 className="text-sm font-semibold text-zinc-200">{SECTION.HOLDINGS}</h2>
              <span className="text-[10px] text-zinc-600 truncate">
                {winners.length > 0 && `${SECTION.WINNERS} ${winners.length}`}
                {winners.length > 0 && losers.length > 0 && " · "}
                {losers.length > 0 && `${SECTION.LOSERS} ${losers.length}`}
                {hiddenPensionCount > 0 && (
                  <>
                    {(winners.length > 0 || losers.length > 0) && " · "}
                    <span className="text-zinc-700">{SECTION.PENSION} {hiddenPensionCount}{SECTION.PENSION_HIDDEN_SUFFIX}</span>
                  </>
                )}
              </span>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              {/* sparkline period toggle — xl+에서만 의미 있음 (<xl에서는 sparkline 숨김) */}
              <div
                className="hidden xl:inline-flex items-center gap-0.5 text-[9px] text-zinc-600 uppercase"
                data-testid="sparkline-period-toggle"
              >
                <span className="text-zinc-700 mr-1 normal-case">{SPARK.PERIOD_LABEL}</span>
                {SPARKLINE_PERIOD_OPTIONS.map((p) => (
                  <Link
                    key={p}
                    href={p === 30 ? "/" : `/?period=${p}`}
                    scroll={false}
                    className={`px-1 rounded normal-case ${
                      p === sparklinePeriod
                        ? "text-zinc-300 bg-zinc-800/80"
                        : "text-zinc-600 hover:text-zinc-400"
                    }`}
                  >
                    {p}
                  </Link>
                ))}
                <span className="text-zinc-700 normal-case">{SPARK.PERIOD_SUFFIX}</span>
              </div>
              {/* #223 iter 7: holdings collapse toggle. Default = top 8 visible.
                  Click "전체 N" to expand to all rows; "접기" to collapse back. */}
              {enrichedHoldings.length > HOLDINGS_COLLAPSED_LIMIT && (
                <Link
                  href={holdingsExpanded ? "/" : "/?holdings=expanded"}
                  scroll={false}
                  className="text-[9px] text-zinc-500 hover:text-zinc-300"
                  data-testid="holdings-toggle"
                >
                  {holdingsExpanded
                    ? SECTION.COLLAPSE
                    : `${SECTION.VIEW_ALL} ${enrichedHoldings.length} ${SECTION.VIEW_SUFFIX}`}
                </Link>
              )}
              <Link href="/portfolio" className="text-[9px] text-zinc-600 hover:text-zinc-400">{SECTION.DETAIL} &rarr;</Link>
            </div>
          </div>
          {/* Responsive column tiers — 헤더와 rows가 동일 breakpoint·width로 정렬.
              #221 iter 4: watch column (90px) 제거, 같은 정보는 상단 이벤트 strip 에 있음.
              base (<sm):  계좌·종목·손익·상태         (~300px)
              sm+  (640+): + 일변                       (~350px)
              md+  (768+): + 현재/평단·손절            (~500px)
              lg+  (1024+): + 1차익절·2차익절          (~660px, 752 content budget)
              xl+  (1280+): + sparkline 80px            (~748px)
              2xl+ (1536+): sparkline 240px + 섹터 96px + 비중 56px (~1150px, 27" 전용)
              overflow-x-auto는 narrow viewport safety net. */}
          <div className="overflow-x-auto">
            <div className="min-w-0">
              {/* 컬럼 헤더 — sm+ (< sm은 헤더 없이 row aria-label 만으로 충분).
                  w-fit 이라 rows 의 w-fit 과 정확히 같은 폭을 차지 → hover 정렬 + 우측 dead zone 제거. */}
              <div className="hidden sm:flex w-fit items-center gap-2 px-2 pb-1 text-[9px] text-zinc-600 uppercase">
                <span className="w-10 2xl:w-16 shrink-0">{COL.ACCOUNT}</span>
                <span className="w-20 shrink-0">{COL.TICKER}</span>
                <span className="hidden md:flex w-[72px] text-right shrink-0 leading-tight justify-end">
                  {COL.CURRENT}<span className="text-zinc-700">{COL.AVG}</span>
                </span>
                <span className="w-14 text-right shrink-0">{COL.PNL}</span>
                <span className="w-12 text-right shrink-0">{COL.DAILY}</span>
                <span className="w-[68px] text-center shrink-0">{COL.STATUS}</span>
                <span className="hidden md:inline-block w-[68px] text-right shrink-0">{COL.STOP}</span>
                <span className="hidden lg:inline-block w-[68px] text-right shrink-0">{COL.TP1}</span>
                <span className="hidden lg:inline-block w-[68px] text-right shrink-0">{COL.TP2}</span>
                {/* sparkline column label — xl: 80px / 2xl: 240px (둘 다 고정) */}
                <span className="hidden xl:inline-block w-20 2xl:w-60 text-left shrink-0">
                  {COL.TREND}
                </span>
                {/* #218 (PR #219): 2xl+ 27" 전용 초광폭 컬럼. Sector 는 label 이라 text-left. */}
                <span className="hidden 2xl:inline-block w-[96px] text-left shrink-0">{COL.SECTOR}</span>
                <span className="hidden 2xl:inline-block w-[56px] text-right shrink-0">{COL.WEIGHT}</span>
              </div>
              <div className="space-y-0.5">
                {(holdingsExpanded
                  ? enrichedHoldings
                  : enrichedHoldings.slice(0, HOLDINGS_COLLAPSED_LIMIT)
                ).map((h, i) => (
                  <HoldingRow key={`${h.account}-${h.ticker}-${i}`} holding={h} />
                ))}
              </div>
            </div>
          </div>
          </div>
          {/* #223: HoldingsSummaryPanel 제거. Today/Accounts/Sector/Movers/Concentration
              은 새 HeroStats + CompositionSection 으로 흡수되었음. */}
        </section>
      )}

      {/* ═══ 푸터: 품질 + 이벤트 + 파이프라인 ═══ */}
      <div className="mt-auto pt-2 border-t border-zinc-800/60 space-y-1">
        <div className="flex items-center gap-3 flex-wrap text-[10px]">
          {siegeTotal > 0 && siegeFailed.length === 0 && (
            <span className="text-zinc-400"><span className="text-emerald-500">&#10003;</span> {FOOTER.QUALITY} {siege?.passed || 0}/{siegeTotal}</span>
          )}
          {siegeTotal > 0 && siegeFailed.length > 0 && (
            <span className="text-red-400"><span className="text-red-500">&#10007;</span> {FOOTER.QUALITY_FAIL} {siegeFailed.length}{FOOTER.COUNT_SUFFIX}</span>
          )}
          {(advisor?.total_violations || 0) > 0 && (
            <span className="text-red-400">{FOOTER.RULE_VIOLATION} {advisor.total_violations}{FOOTER.COUNT_SUFFIX}</span>
          )}
          {/* upcoming events moved to sidebar (#214). Footer keeps quality/violations/freshness. */}
          <div className="ml-auto flex items-center gap-2">
            {((freshness?.items?.length ?? 0) > 0 || (freshness?.details?.length ?? 0) > 0) && (
              <FreshnessBar items={freshness?.items ?? freshness?.details ?? []} />
            )}
            {pipelineStatus.steps.length > 0 && (
              <div className="flex items-center gap-0.5">
                {pipelineStatus.steps.map((s) => (
                  <span key={s.step} className={`inline-flex h-1.5 w-1.5 rounded-full ${pipelineStatusColors[s.status] || "bg-zinc-500"}`} title={`${s.label}: ${s.record_count.toLocaleString()}건`} />
                ))}
                <Link href="/pipeline" className="text-[9px] text-zinc-600 hover:text-zinc-400 ml-0.5">&rarr;</Link>
              </div>
            )}
          </div>
        </div>
        {siegeTotal > 0 && siegeFailed.length > 0 && (
          <div className="space-y-0.5">
            {siegeFailed.slice(0, 2).map((c: any, i: number) => (
              <p key={i} className="text-[10px] text-zinc-400 pl-3">
                <span className={c.severity === "error" ? "text-red-400" : "text-amber-400"}>{c.severity === "error" ? "\u2716" : "\u25B3"}</span>{" "}
                {c.description} &mdash; <span className="text-zinc-600">{c.detail}</span>
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <div className="h-16 bg-zinc-900/50 rounded animate-pulse" />
      <div className="h-8 bg-zinc-900/30 rounded animate-pulse" />
      <div className="h-3.5 bg-zinc-800 rounded animate-pulse" />
      <div className="h-24 bg-zinc-900/50 rounded animate-pulse" />
      <div className="h-32 bg-zinc-900/30 rounded animate-pulse" />
      <div className="h-6 bg-zinc-800/30 rounded animate-pulse mt-auto" />
    </div>
  );
}

export default function OverviewPage({
  searchParams,
}: {
  searchParams?: Promise<{ period?: string }>;
} = {}) {
  return (
    <Suspense fallback={<LoadingSkeleton />}>
      <Dashboard searchParams={searchParams} />
    </Suspense>
  );
}
