export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { redirect } from "next/navigation";
import { fetchAPI } from "@/lib/api";

import { StatusBadge } from "@/components/ui/status-badge";
import { FreshnessBar, type FreshnessItem } from "@/components/ui/freshness-bar";
import { HoldingRow, buildEnrichedHoldings, type RawAction, type RawTarget, type RawAdvisorAction, type RawEvent } from "@/components/ui/holding-row";
import {
  DashboardSidebar,
  type SidebarAlert,
  type SidebarEvent,
  type SidebarCandidate,
} from "@/components/ui/dashboard-sidebar";
import Link from "next/link";

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
  aggressive: "공격", neutral: "관망", cautious: "주의", defensive: "방어",
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
function trendKo(t: string) { return t === "bull" ? "상승" : t === "bear" ? "하락" : "횡보"; }
function vixZone(v: number | null): { label: string; color: string } {
  if (v == null) return { label: "—", color: "text-zinc-500" };
  if (v < 12) return { label: "안정", color: "text-blue-400" };
  if (v < 17) return { label: "낮음", color: "text-emerald-400" };
  if (v < 23) return { label: "보통", color: "text-zinc-300" };
  if (v < 33) return { label: "주의", color: "text-orange-400" };
  return { label: "위험", color: "text-red-400" };
}
function fgLabel(fg: number | null): string {
  if (fg == null) return "—";
  if (fg < 25) return "극도 공포"; if (fg < 45) return "공포";
  if (fg <= 55) return "중립"; if (fg <= 75) return "탐욕";
  return "극도 탐욕";
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
  if (s >= 70) return { label: "양호", color: "text-emerald-400" };
  if (s >= 50) return { label: "보통", color: "text-zinc-300" };
  if (s >= 30) return { label: "부진", color: "text-orange-400" };
  return { label: "취약", color: "text-red-400" };
}
function translateAlert(msg: string): string {
  return msg
    .replace("시그널 성과 급락:", "매매 신호 성과 하락:")
    .replace(/BUY\/SELL 충돌 (\d+)건:/, "매수·매도 신호 충돌 $1건:")
    .replace("bb_bounce", "볼린저밴드 반등").replace("macd_bullish_turn", "MACD 상승전환")
    .replace("macd_bearish_turn", "MACD 하락전환").replace("macd_golden", "MACD 골든크로스")
    .replace("macd_dead", "MACD 데드크로스").replace("rsi_oversold", "RSI 과매도")
    .replace("rsi_overbought", "RSI 과매수").replace("sma_golden", "이동평균 골든크로스")
    .replace("sma_dead", "이동평균 데드크로스").replace("volume_spike", "거래량 급증")
    .replace("gap_up", "갭 상승").replace("gap_down", "갭 하락")
    .replace("bb_squeeze_breakout", "볼린저밴드 돌파").replace("near_52w_low_bounce", "52주 저점 반등")
    .replace("volume_profile_resistance", "거래량 저항선");
}
/** 계좌 라벨 한국어 표시 (Pension만 특수, 나머지는 원본 유지) */
function accountKo(label: string | undefined): string {
  if (!label) return "";
  if (label === "Pension") return "연금";
  return label;
}
/** 알림 → {label, href} 파싱 */
function parseAlert(al: { level: string; message: string }): { label: string; href: string } {
  const translated = translateAlert(al.message);
  // 손절 돌파: 티커 → /ticker/{ticker}
  const stopMatch = translated.match(/(\S+)\s+손절선\s+돌파\s+\((-?\d+\.?\d*%)\)/);
  if (stopMatch) return { label: `${stopMatch[1]} ${stopMatch[2]} 손절`, href: `/ticker/${stopMatch[1]}` };
  // 손절 근접
  const nearMatch = translated.match(/(\S+)\s+손절선\s+근접\s+\((-?\d+\.?\d*%)\)/);
  if (nearMatch) return { label: `${nearMatch[1]} ${nearMatch[2]} 근접`, href: `/ticker/${nearMatch[1]}` };
  // 충돌
  const conflictMatch = translated.match(/충돌\s+(\d+)건/);
  if (conflictMatch) return { label: `충돌 ${conflictMatch[1]}건`, href: "/decisions" };
  // 시그널 성과
  if (translated.includes("성과 하락")) return { label: translated.slice(0, 30), href: "/signals" };
  // 기타
  return { label: translated.slice(0, 30), href: "/signals" };
}

/* ══════════════════════════════════════════════════════ */

async function Dashboard() {
  const [d, freshness, pipelineStatus, portfolio, siege, advisor, targets] = await Promise.all([
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
  ]);

  const holdingCount = portfolio?.count ?? portfolio?.holdings?.length ?? 0;
  if (holdingCount === 0) redirect("/portfolio?onboarding=true");

  const style = levelStyles[d.verdict_level] || levelStyles.neutral;
  const verdictLabel = verdictLabels[d.verdict_level] || "관망";
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
  const enrichedHoldings = buildEnrichedHoldings(
    labeledHoldings as any,
    d.actions as RawAction[],
    targets?.targets ?? [],
    (advisor?.actions ?? []) as RawAdvisorAction[],
    (d.upcoming_events ?? []) as RawEvent[],
  );

  // 신규 매수 후보 — 보유하지 않은 ticker의 액션만 (held tickers의 액션은 HoldingRow 상태로 흡수됨)
  const heldTickers = new Set(holdings.map((h: any) => h.ticker));
  const newCandidates = d.actions.filter(a => !heldTickers.has(a.ticker));
  // 연금 계좌는 월말에만 매수 (월간 1회). 비-월말이면 noise 방지를 위해 collapse.
  const now = new Date();
  const isMonthEnd = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate() - now.getDate() <= 3;
  const pensionCandidates = newCandidates.filter(a => a.account === "Pension");
  const visibleCandidates = newCandidates.filter(a => a.account !== "Pension" || isMonthEnd);

  // #214: Sidebar 데이터 prep
  const sidebarAlerts: SidebarAlert[] = d.alerts.map((al) => {
    const parsed = parseAlert(al);
    return { level: al.level, message: parsed.label, href: parsed.href };
  });
  const sidebarEvents: SidebarEvent[] = (d.upcoming_events ?? []).slice(0, 8).map((ev: any) => ({
    date: ev.date,
    description: ev.description,
    ticker: ev.ticker,
  }));
  const sidebarCandidates: SidebarCandidate[] = visibleCandidates.map((a) => ({
    action: a.action,
    ticker: a.ticker,
    name: a.name,
    account: a.account ? accountKo(a.account) : undefined,
    confidence: a.confidence,
  }));

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* ═══ 히어로: 총 자산 (holdings + cash) + 판단 ═══ */}
      <div>
        <p className="text-[10px] text-zinc-500 mb-0.5">총 자산</p>
        <div className="flex items-baseline gap-3">
          <span className="text-4xl font-semibold tabular-nums tracking-tight text-zinc-100">
            ${totalValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </span>
          <StatusBadge status={verdictLabel} size="lg" />
        </div>
        {(cashTotalUsd > 0 || accountValues.length > 0) && (
          <div className="flex items-center gap-3 mt-1 text-[10px] text-zinc-500 flex-wrap">
            {cashTotalUsd > 0 && (
              <>
                <span>보유 <span className="tabular-nums text-zinc-400">${holdingsValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span></span>
                <span>현금 <span className="tabular-nums text-zinc-400">${cashTotalUsd.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span></span>
              </>
            )}
            {accountValues.length > 0 && accountValues.map(av => (
              <span key={av.account}>{av.account} ${av.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
            ))}
          </div>
        )}
      </div>

      {/* ═══ 시장 맥락 — verdict + 숫자 통합 ═══ */}
      <div>
        <p className={`text-xs ${style.text} leading-relaxed`}>{d.verdict}</p>
        <div className="flex items-center gap-3 mt-1 text-[10px] text-zinc-500 flex-wrap">
          <span className={trend === "bull" ? "text-emerald-400" : trend === "bear" ? "text-red-400" : "text-amber-400"}>
            {trendKo(trend)}
          </span>
          <span>VIX <span className={`font-semibold tabular-nums ${vixInfo.color}`}>{vix != null ? Math.round(vix * 10) / 10 : "—"}</span> <span className={vixInfo.color}>{vixInfo.label}</span></span>
          <span>심리 <span className={`inline-flex items-center justify-center h-4 w-4 rounded-full text-[9px] font-bold tabular-nums ${fgColor(fg)}`}>{fg ?? "—"}</span> <span className="text-zinc-600">{fgLabel(fg)}</span></span>
          <span>경제 <span className={`font-semibold tabular-nums ${macroInfo.color}`}>{d.macro.score}</span> <span className={macroInfo.color}>{macroInfo.label}</span></span>
        </div>
      </div>

      {/* 비중 바 — 실제 (holdings+cash 기반) + 권장 (regime 기반) 2줄 */}
      {(() => {
        const actual = d.actual_allocation ?? { long: 0, short: 0, cash: 100 };
        const target = d.target_allocation ?? d.allocation;
        return (
          <div className="space-y-1.5">
            {/* 실제 */}
            <div>
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-[9px] text-zinc-500">실제</span>
                <span className="text-[9px] text-zinc-600 tabular-nums">투자 {actual.long}% · 현금 {actual.cash}%</span>
              </div>
              <div className="flex h-3 rounded overflow-hidden text-[9px] font-medium">
                {actual.long > 0 && (
                  <div className="bg-emerald-600/80 flex items-center justify-center text-emerald-100" style={{ width: `${actual.long}%` }}>
                    {actual.long >= 20 && `${actual.long}%`}
                  </div>
                )}
                {actual.short > 0 && (
                  <div className="bg-red-600/80 flex items-center justify-center text-red-100" style={{ width: `${actual.short}%` }}>
                    {actual.short >= 10 && `${actual.short}%`}
                  </div>
                )}
                {actual.cash > 0 && (
                  <div className="bg-zinc-800 flex items-center justify-center text-zinc-400" style={{ width: `${actual.cash}%` }}>
                    {actual.cash >= 20 && `${actual.cash}%`}
                  </div>
                )}
              </div>
            </div>
            {/* 권장 (regime) */}
            <div>
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-[9px] text-zinc-600">권장 (레짐)</span>
                <span className="text-[9px] text-zinc-700 tabular-nums">투자 {target.long}% · 현금 {target.cash}%</span>
              </div>
              <div className="flex h-1.5 rounded overflow-hidden text-[9px] font-medium opacity-60">
                {target.long > 0 && (
                  <div className="bg-emerald-700/60" style={{ width: `${target.long}%` }} />
                )}
                {target.short > 0 && (
                  <div className="bg-red-700/60" style={{ width: `${target.short}%` }} />
                )}
                {target.cash > 0 && (
                  <div className="bg-zinc-700" style={{ width: `${target.cash}%` }} />
                )}
              </div>
            </div>
          </div>
        );
      })()}

      {/* ═══ 2-column 본문: main (holdings) + sidebar (알림/이벤트/후보) ═══ */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_280px] gap-4">
        {/* ─── main ─── */}
        <main className="min-w-0 min-h-0 flex flex-col gap-3">
          {/* 보유 종목 통합 뷰 */}
          {enrichedHoldings.length > 0 && (
            <section>
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-semibold text-zinc-200">보유 종목</h2>
                  <span className="text-[10px] text-zinc-600">
                    {winners.length > 0 && `수익 ${winners.length}`}
                    {winners.length > 0 && losers.length > 0 && " · "}
                    {losers.length > 0 && `손실 ${losers.length}`}
                  </span>
                </div>
                <Link href="/portfolio" className="text-[9px] text-zinc-600 hover:text-zinc-400">상세 &rarr;</Link>
              </div>
              {/* 컬럼 헤더 (sm+) */}
              <div className="hidden sm:flex items-center gap-2 px-2 pb-1 text-[9px] text-zinc-600 uppercase">
                <span className="w-10 shrink-0">계좌</span>
                <span className="w-20 shrink-0">종목</span>
                <span className="w-14 text-right shrink-0">손익</span>
                <span className="w-12 text-right shrink-0">일변</span>
                <span className="w-[68px] text-center shrink-0">상태</span>
                <span className="w-[72px] text-right shrink-0">손절</span>
                <span className="w-[72px] text-right shrink-0">1차익절</span>
                <span className="w-[72px] text-right shrink-0">2차익절</span>
                <span className="w-[80px] text-center shrink-0">30일 추세</span>
                <span className="flex-1 text-right">워치</span>
              </div>
              <div className="space-y-0.5">
                {enrichedHoldings.map((h, i) => (
                  <HoldingRow key={`${h.account}-${h.ticker}-${i}`} holding={h} />
                ))}
              </div>
            </section>
          )}
        </main>

        {/* ─── sidebar (lg+ 고정, narrow는 stack 아래로) ─── */}
        <div className="lg:border-l lg:border-zinc-800/60 lg:pl-4 lg:-mr-1">
          <DashboardSidebar
            alerts={sidebarAlerts}
            events={sidebarEvents}
            candidates={sidebarCandidates}
            pensionCandidatesCount={pensionCandidates.length}
            isMonthEnd={isMonthEnd}
          />
        </div>
      </div>

      {/* ═══ 푸터: 품질 + 이벤트 + 파이프라인 ═══ */}
      <div className="mt-auto pt-2 border-t border-zinc-800/60 space-y-1">
        <div className="flex items-center gap-3 flex-wrap text-[10px]">
          {siegeTotal > 0 && siegeFailed.length === 0 && (
            <span className="text-zinc-400"><span className="text-emerald-500">&#10003;</span> 품질 {siege?.passed || 0}/{siegeTotal}</span>
          )}
          {siegeTotal > 0 && siegeFailed.length > 0 && (
            <span className="text-red-400"><span className="text-red-500">&#10007;</span> 품질 미통과 {siegeFailed.length}건</span>
          )}
          {(advisor?.total_violations || 0) > 0 && (
            <span className="text-red-400">규칙 위반 {advisor.total_violations}건</span>
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

export default function OverviewPage() {
  return (
    <Suspense fallback={<LoadingSkeleton />}>
      <Dashboard />
    </Suspense>
  );
}
