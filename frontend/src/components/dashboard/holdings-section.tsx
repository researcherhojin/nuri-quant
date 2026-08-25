/**
 * HoldingsSection (#1204 U2a) — 보유 종목 drilldown 테이블. page.tsx 에서 추출, 동작 불변.
 * #223 restructure: composition 아래의 detail 뷰 (메인 아님).
 */
import Link from "next/link";
import { HoldingRow, type EnrichedHolding } from "@/components/ui/holding-row";
import { SECTION, SPARKLINE as SPARK, COL } from "@/lib/strings";
import { SPARKLINE_PERIOD_OPTIONS, type SparklinePeriod } from "./helpers";

// #223 iter 7: holdings drilldown is collapsed by default (top 8 rows + "전체"
// link). The new dashboard centerpiece is the composition section, not the
// holdings table — so the table's role is "drill into details on demand".
export const HOLDINGS_COLLAPSED_LIMIT = 8;

interface HoldingsSectionProps {
  holdings: EnrichedHolding[];
  winnersCount: number;
  losersCount: number;
  hiddenPensionCount: number;
  sparklinePeriod: SparklinePeriod;
  expanded: boolean;
  macroAwareSectors: Set<string>;
}

export function HoldingsSection({
  holdings, winnersCount, losersCount, hiddenPensionCount,
  sparklinePeriod, expanded, macroAwareSectors,
}: HoldingsSectionProps) {
  if (holdings.length === 0) return null;
  return (
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
            {winnersCount > 0 && `${SECTION.WINNERS} ${winnersCount}`}
            {winnersCount > 0 && losersCount > 0 && " · "}
            {losersCount > 0 && `${SECTION.LOSERS} ${losersCount}`}
            {hiddenPensionCount > 0 && (
              <>
                {(winnersCount > 0 || losersCount > 0) && " · "}
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
          {holdings.length > HOLDINGS_COLLAPSED_LIMIT && (
            <Link
              href={expanded ? "/" : "/?holdings=expanded"}
              scroll={false}
              className="text-[9px] text-zinc-500 hover:text-zinc-300"
              data-testid="holdings-toggle"
            >
              {expanded
                ? SECTION.COLLAPSE
                : `${SECTION.VIEW_ALL} ${holdings.length} ${SECTION.VIEW_SUFFIX}`}
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
            <span className="hidden md:flex w-18 text-right shrink-0 leading-tight justify-end">
              {COL.CURRENT}<span className="text-zinc-700">{COL.AVG}</span>
            </span>
            <span className="w-14 text-right shrink-0">{COL.PNL}</span>
            <span className="w-12 text-right shrink-0">{COL.DAILY}</span>
            <span className="w-17 text-center shrink-0">{COL.STATUS}</span>
            <span className="hidden md:inline-block w-17 text-right shrink-0">{COL.STOP}</span>
            <span className="hidden lg:inline-block w-17 text-right shrink-0">{COL.TP1}</span>
            <span className="hidden lg:inline-block w-17 text-right shrink-0">{COL.TP2}</span>
            {/* sparkline column label — xl: 80px / 2xl: 240px (둘 다 고정) */}
            <span className="hidden xl:inline-block w-20 2xl:w-60 text-left shrink-0">
              {COL.TREND}
            </span>
            {/* #218 (PR #219): 2xl+ 27" 전용 초광폭 컬럼. Sector 는 label 이라 text-left. */}
            <span className="hidden 2xl:inline-block w-24 text-left shrink-0">{COL.SECTOR}</span>
            <span className="hidden 2xl:inline-block w-14 text-right shrink-0">{COL.WEIGHT}</span>
          </div>
          <div className="space-y-0.5">
            {(expanded ? holdings : holdings.slice(0, HOLDINGS_COLLAPSED_LIMIT)).map((h, i) => (
              <HoldingRow
                key={`${h.account}-${h.ticker}-${i}`}
                holding={h}
                macroAwareSectors={macroAwareSectors}
              />
            ))}
          </div>
        </div>
      </div>
      </div>
      {/* #223: HoldingsSummaryPanel 제거. Today/Accounts/Sector/Movers/Concentration
          은 새 HeroStats + CompositionSection 으로 흡수되었음. */}
    </section>
  );
}
