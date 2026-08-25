export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { redirect } from "next/navigation";
import { fetchAPI } from "@/lib/api";

import { type FreshnessItem } from "@/components/ui/freshness-bar";
import { CoverageStatus } from "@/components/ui/coverage-status";
import { buildEnrichedHoldings, type RawAction, type RawTarget, type RawAdvisorAction, type RawEvent } from "@/components/ui/holding-row";
import { HeroStats } from "@/components/ui/hero-stats";
import { CompositionSectionLazy as CompositionSection } from "@/components/ui/composition-section-lazy";
import { parseCompositionTab } from "@/components/ui/composition-section";
import { ActionItems, type ActionItem } from "@/components/ui/action-items";
import { OpportunityExplorer, type Opportunity } from "@/components/ui/opportunity-explorer";
import { type MacroEvent, type SystemHealth } from "@/components/ui/market-context";
import { SystemHealthRail, MacroEventsCard, RegimeShiftBanner } from "@/components/dashboard/system-rail";
import { summarizeHoldings } from "@/lib/holdings-summary";
import { getMacroImpactedSectors } from "@/lib/macro-impact";
import Link from "next/link";
import { SECTION, ACTION } from "@/lib/strings";

// #1204 U2a: 섹션·헬퍼는 components/dashboard/ 로 추출 — 이 파일은 데이터 fetch +
// enrichment + 조립만 담당한다. 동작·마크업 불변.
import {
  trendKo, vixZone, fgLabel, fgColor, macroLevel, accountKo,
  parseSparklinePeriod,
} from "@/components/dashboard/helpers";
import { MarketStrip } from "@/components/dashboard/market-strip";
import { VerdictBanner } from "@/components/dashboard/verdict-banner";
import { EventsStrip } from "@/components/dashboard/events-strip";
import { HoldingsSection } from "@/components/dashboard/holdings-section";
import { DashboardFooter, type FooterCondition } from "@/components/dashboard/dashboard-footer";

// 헬퍼 re-export — 기존 소비자(테스트 포함)의 "@/app/page" import 경로 유지 (#1204)
export { trendKo, vixZone, fgLabel, fgColor, macroLevel, accountKo, parseSparklinePeriod };

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

interface PortfolioHolding {
  ticker: string;
  account?: string;
  quantity?: number;
  avg_price?: number;
  latest_price?: number;
  currency?: string;
  sector?: string;
  [key: string]: unknown;
}

interface PortfolioData {
  count?: number;
  holdings?: PortfolioHolding[];
  cash?: { total_cash_usd?: number };
}

type CertifyCondition = FooterCondition;

interface CertifyData {
  conditions?: CertifyCondition[];
  total?: number;
  passed?: number;
}

interface AdvisorData {
  actions?: RawAdvisorAction[];
  total_violations?: number;
}

interface ActionsData {
  urgent: ActionItem[];
  check: ActionItem[];
  hold: ActionItem[];
  portfolio: ActionItem[];
}

interface OpportunitiesData {
  opportunities: Opportunity[];
}

interface MarketContextData {
  macro_events: MacroEvent[];
  system_health: Partial<SystemHealth>;
}

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

  const [d, freshness, pipelineStatus, portfolio, siege, advisor, targets, actionsData, opportunitiesData, marketCtx, coverage] = await Promise.all([
    fetchAPI<DashboardData>("/api/dashboard"),
    fetchAPI<FreshnessData>("/api/freshness").catch((): FreshnessData => ({ items: [], details: [], overall: "FAIL", pass: 0, warn: 0, fail: 0 })),
    fetchAPI<PipelineStatusData>("/api/pipeline/status").catch((): PipelineStatusData => ({ steps: [] })),
    fetchAPI<PortfolioData>("/api/portfolio").catch(() => null),
    Promise.race([
      fetchAPI<CertifyData>("/api/certify"),
      // 3s 타임아웃 방어용 fallback. jsdom+fake-timer 하네스에서 RSC await 가 settle
      // 안 돼 setTimeout 콜백이 결정적으로 실행되지 않음 → 커버리지 제외.
      new Promise<null>((resolve) => {
        // setTimeout 콜백은 jsdom+fake-timer 하네스에서 결정적 실행 불가 → 함수째 커버리지 제외
        /* v8 ignore next 3 */
        setTimeout(() => {
          resolve(null);
        }, 3000);
      }),
    ]).catch(() => null),
    fetchAPI<AdvisorData>("/api/rebalance-advisor").catch(() => null),
    fetchAPI<{ targets: RawTarget[] }>("/api/targets").catch(() => ({ targets: [] as RawTarget[] })),
    fetchAPI<ActionsData>("/api/actions").catch((): ActionsData => ({ urgent: [], check: [], hold: [], portfolio: [] })),
    fetchAPI<OpportunitiesData>("/api/opportunities").catch((): OpportunitiesData => ({ opportunities: [] })),
    fetchAPI<MarketContextData>("/api/market-context").catch((): MarketContextData => ({ macro_events: [], system_health: {} })),
    fetchAPI<import("@/components/ui/coverage-status").CoverageData>("/api/coverage").catch(() => null),
  ]);

  const holdingCount = portfolio?.count ?? portfolio?.holdings?.length ?? 0;
  if (holdingCount === 0) redirect("/explore");

  const KRW_RATE = d.exchange_rate || 1400;
  const holdingsValue = portfolio?.holdings?.reduce((sum: number, h: PortfolioHolding) => {
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
  const _alertCount = d.alerts.length;
  const siegeFailed: CertifyCondition[] = siege?.conditions?.filter((c) => !c.passed) || [];
  const siegeTotal = siege?.total || 0;

  const holdings: PortfolioHolding[] = portfolio?.holdings || [];
  const winners = holdings.filter((h: PortfolioHolding) => h.latest_price && h.avg_price && h.latest_price > h.avg_price);
  const losers = holdings.filter((h: PortfolioHolding) => h.latest_price && h.avg_price && h.latest_price < h.avg_price);
  const accountValues = d.account_values || [];

  // 통합 보유 종목 — 매매 상태 + 가격 타겟 + 워치 트리거 결합
  // account_labels: raw broker → 익명 label (per-account 매핑). 다계좌 ticker는
  // ticker_accounts(ticker→label, 단일 매핑)로 풀 수 없어서 collision이 발생했음 — 각
  // holding의 raw account를 key로 라벨을 lookup하여 fix.
  const accountLabels = d.account_labels || {};
  const labeledHoldings = holdings.map((h: PortfolioHolding) => ({
    ...h,
    accountLabel: accountKo(accountLabels[h.account ?? ""] || h.account || ""),
  }));
  const builtHoldings = buildEnrichedHoldings(
    labeledHoldings as Parameters<typeof buildEnrichedHoldings>[0],
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
    // `?? 0` arms are unreachable in practice: positionPct is only null when
    // totalValue === 0, but a zero-total portfolio yields no renderable rows to
    // sort, so the comparator never sees a null positionPct.
    /* v8 ignore next */
    .sort((a, b) => (b.positionPct ?? 0) - (a.positionPct ?? 0));
  const hiddenPensionCount = allEnrichedHoldings.length - enrichedHoldings.length;

  // #503 Phase C — 24h 내 high-conf macro 이벤트의 영향 sector keyword set.
  const macroAwareSectors = getMacroImpactedSectors(marketCtx?.macro_events ?? []);

  // heldTickers: used by HoldingRow enrichment for action matching
  const _heldTickers = new Set(holdings.map((h: PortfolioHolding) => h.ticker));

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
    .map((ev) => ({ date: ev.date as string, description: ev.description as string | undefined, ticker: ev.ticker as string | null }));

  // 원본 게이트 보존 (#1204): items=[] 이고 details 만 있어도 빈 FreshnessBar 를 렌더.
  const showFreshness = (freshness?.items?.length ?? 0) > 0 || (freshness?.details?.length ?? 0) > 0;
  /* v8 ignore next */
  const freshnessItems = freshness?.items ?? freshness?.details ?? [];

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* ═══ #1206 U2b-1: 한 줄 판단이 첫 픽셀 — "오늘의 답" 배너 ═══ */}
      <VerdictBanner verdict={d.verdict} level={d.verdict_level} />

      {/* ═══ #223 HERO: 4 metrics row — U2b-1 에서 컴팩트로 축소 ═══ */}
      <HeroStats
        totalUsd={totalValue}
        cashTotalUsd={cashTotalUsd}
        holdingsValueUsd={holdingsValue}
        summary={summary}
      />

      {/* ═══ #1208 U2b-2: 좌 2/3 액션 테이블 · 우 1/3 시스템 레일 (lg 미만 스택) ═══ */}
      <RegimeShiftBanner regime={marketCtx?.system_health?.regime ?? {}} />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 items-start">
        <div className="lg:col-span-2 min-w-0">
          <h2 className="text-sm font-semibold text-zinc-300 mb-2">{ACTION.TITLE}</h2>
          <ActionItems
            urgent={actionsData?.urgent ?? []}
            check={actionsData?.check ?? []}
            hold={actionsData?.hold ?? []}
            portfolio={actionsData?.portfolio ?? []}
          />
        </div>
        <div className="flex flex-col gap-3 min-w-0">
          <SystemHealthRail health={marketCtx?.system_health ?? {}} />
          <MacroEventsCard
            events={marketCtx?.macro_events ?? []}
            regimeTrend={marketCtx?.system_health?.regime?.trend}
          />
        </div>
      </div>

      {/* ═══ #223 iter 7c: market + allocation compact strip (1 row) ═══ */}
      <MarketStrip
        trend={trend}
        vix={vix}
        fg={fg}
        macroScore={d.macro?.score}
        actualAllocation={d.actual_allocation}
        targetAllocation={d.target_allocation}
        fallbackAllocation={d.allocation}
      />

      {/* ═══ Collapsible strips removed — replaced by Action-First sections above.
          Alerts → ActionItems 🔴 urgent, Candidates → ActionItems 🟡 check/✅ hold,
          Events → MarketContext macro events. Only upcoming earnings strip retained. ═══ */}
      <EventsStrip events={stripEvents} />

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

      {/* ═══ 보유 종목 — drilldown 위치 (#223 restructure) ═══ */}
      <HoldingsSection
        holdings={enrichedHoldings}
        winnersCount={winners.length}
        losersCount={losers.length}
        hiddenPensionCount={hiddenPensionCount}
        sparklinePeriod={sparklinePeriod}
        expanded={holdingsExpanded}
        macroAwareSectors={macroAwareSectors}
      />

      {/* ═══ 기회 탐색 — 보유 종목 아래, 상위 3개 + /scan 링크 ═══ */}
      {(opportunitiesData?.opportunities?.length ?? 0) > 0 && (() => {
        // `?? []` right arm unreachable: the gate above already proved
        // opportunities is a non-empty array. Extracted to a const so the v8
        // ignore lands on a plain statement (JSX-attribute ignores are flaky).
        /* v8 ignore next */
        const topOpportunities = (opportunitiesData?.opportunities ?? []).slice(0, 3);
        return (
          <div>
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-semibold text-zinc-300">🔍 기회 탐색</h2>
              <Link href="/scan" className="text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors">
                전체 {opportunitiesData.opportunities.length}건 →
              </Link>
            </div>
            <OpportunityExplorer opportunities={topOpportunities} />
          </div>
        );
      })()}

      {/* ═══ Data Coverage (#272 Phase 4) ═══ */}
      {coverage && !coverage.error && coverage.checks?.length > 0 && (
        <div className="pt-2">
          <CoverageStatus data={coverage} />
        </div>
      )}

      {/* ═══ 푸터: 품질 + 이벤트 + 파이프라인 ═══ */}
      <DashboardFooter
        siegeTotal={siegeTotal}
        siegePassed={siege?.passed || 0}
        siegeFailed={siegeFailed}
        advisorViolations={advisor?.total_violations || 0}
        showFreshness={showFreshness}
        freshnessItems={freshnessItems}
        pipelineSteps={pipelineStatus.steps}
      />
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
