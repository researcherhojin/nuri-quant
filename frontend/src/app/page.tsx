export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { redirect } from "next/navigation";
import { fetchAPI } from "@/lib/api";

import { StatusBadge } from "@/components/ui/status-badge";
import { FreshnessBar, type FreshnessItem } from "@/components/ui/freshness-bar";
import { HoldingRow, buildEnrichedHoldings, type RawAction, type RawTarget, type RawAdvisorAction, type RawEvent } from "@/components/ui/holding-row";
import { CollapsibleStrip } from "@/components/ui/collapsible-strip";
import { HoldingsSummaryPanel } from "@/components/ui/holdings-summary-panel";
import { summarizeHoldings } from "@/lib/holdings-summary";
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

// #214 polish: sparkline period options shown as URL-driven toggle (?period=14|30|60|90)
const SPARKLINE_PERIOD_OPTIONS = [14, 30, 60, 90] as const;
type SparklinePeriod = (typeof SPARKLINE_PERIOD_OPTIONS)[number];

function parseSparklinePeriod(raw: string | undefined): SparklinePeriod {
  const n = parseInt(raw ?? "30", 10);
  if (SPARKLINE_PERIOD_OPTIONS.includes(n as SparklinePeriod)) return n as SparklinePeriod;
  return 30;
}

async function Dashboard({
  searchParams,
}: {
  searchParams?: Promise<{ period?: string }> | undefined;
}) {
  // Defensive: searchParams may be undefined when rendered outside the page boundary
  // (e.g. some error paths in dev). Default to an empty object.
  const params = (searchParams ? await searchParams : undefined) ?? {};
  const sparklinePeriod = parseSparklinePeriod(params.period);

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
  const isPensionLabel = (label: string) => label.startsWith("연금") || label.startsWith("Pension");
  const enrichedHoldings = allEnrichedHoldings.filter((h) => !isPensionLabel(h.account));
  const hiddenPensionCount = allEnrichedHoldings.length - enrichedHoldings.length;

  // 신규 매수 후보 — 보유하지 않은 ticker의 액션만 (held tickers의 액션은 HoldingRow 상태로 흡수됨)
  const heldTickers = new Set(holdings.map((h: any) => h.ticker));
  const newCandidates = d.actions.filter(a => !heldTickers.has(a.ticker));
  // 연금 계좌는 월말에만 매수 (월간 1회). 비-월말이면 noise 방지를 위해 collapse.
  const now = new Date();
  const isMonthEnd = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate() - now.getDate() <= 3;
  const pensionCandidates = newCandidates.filter(a => a.account === "Pension");
  const visibleCandidates = newCandidates.filter(a => a.account !== "Pension" || isMonthEnd);

  // #214 polish (A): inline context strips 대신 사이드바 제거 → 데이터 prep
  const stripAlerts = d.alerts.map((al) => ({
    level: al.level,
    parsed: parseAlert(al),
  }));
  const stripEvents = (d.upcoming_events ?? [])
    .slice(0, 5)
    .map((ev: any) => ({ date: ev.date as string, description: ev.description as string | undefined, ticker: ev.ticker as string | null }));
  const stripCandidates = visibleCandidates.slice(0, 5);

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

      {/* ═══ 인라인 context strips — 알림 / 이벤트 / 후보 (각각 collapsible) ═══ */}
      <div className="flex flex-col gap-1">
        {/* 알림 strip */}
        <CollapsibleStrip
          id="alerts"
          title="알림"
          icon="⚠"
          count={stripAlerts.length}
          emptyText="위험 요소 없음"
        >
          <div className="flex items-start gap-2 px-2 py-1 rounded bg-red-950/20 border border-red-900/30 pr-6">
            <span className="text-[10px] text-red-400 font-semibold shrink-0">⚠ 주의 {stripAlerts.length}건</span>
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 flex-1 min-w-0">
              {stripAlerts.map((al, i) => (
                <Link
                  key={i}
                  href={al.parsed.href}
                  className="flex items-center gap-1 text-[10px] hover:text-zinc-100 transition-colors"
                >
                  <span className={al.level === "critical" ? "text-red-400" : "text-amber-400"}>
                    {al.level === "critical" ? "\u2716" : "\u25B3"}
                  </span>
                  <span className="text-zinc-300 truncate">{al.parsed.label}</span>
                </Link>
              ))}
            </div>
          </div>
        </CollapsibleStrip>

        {/* 이벤트 strip */}
        <CollapsibleStrip
          id="events"
          title="이벤트"
          icon="📅"
          count={stripEvents.length}
          emptyText="예정된 이벤트 없음"
        >
          <div className="flex items-start gap-2 px-2 py-1 rounded bg-zinc-900/40 border border-zinc-800/60 pr-6">
            <span className="text-[10px] text-zinc-400 font-semibold shrink-0">📅 다음 이벤트 {stripEvents.length}건</span>
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 flex-1 min-w-0">
              {stripEvents.map((ev, i) => {
                const dday = eventDday(ev.date);
                return (
                  <span key={`${ev.date}-${i}`} className="text-[10px] text-zinc-400 truncate">
                    <span className="text-zinc-600 tabular-nums">{fmtEventDate(ev.date)}</span>{" "}
                    {ev.description || ev.ticker || "이벤트"}
                    {dday && <span className="text-zinc-600 ml-1">({dday})</span>}
                  </span>
                );
              })}
            </div>
          </div>
        </CollapsibleStrip>

        {/* 신규 매수 후보 strip */}
        <CollapsibleStrip
          id="candidates"
          title="신규 후보"
          icon="🎯"
          count={stripCandidates.length}
          emptyText={
            pensionCandidates.length > 0 && !isMonthEnd
              ? `연금 ${pensionCandidates.length}건 — 월말 매수 대기`
              : "신규 매수 후보 없음"
          }
        >
          <div className="flex items-start gap-2 px-2 py-1 rounded bg-zinc-900/40 border border-zinc-800/60 pr-6">
            <span className="text-[10px] text-emerald-400 font-semibold shrink-0">🎯 신규 후보 {stripCandidates.length}건</span>
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 flex-1 min-w-0">
              {stripCandidates.map((c, i) => (
                <Link
                  key={`${c.ticker}-${i}`}
                  href={`/ticker/${c.ticker}`}
                  className="flex items-center gap-1 text-[10px] hover:text-zinc-100 transition-colors"
                >
                  {c.account && <span className="text-zinc-600">{accountKo(c.account)}</span>}
                  <span className="text-zinc-200">{c.name || c.ticker}</span>
                  <span
                    className={`tabular-nums font-semibold ${
                      c.confidence >= 80
                        ? "text-emerald-400"
                        : c.confidence >= 50
                        ? "text-amber-400"
                        : "text-red-400"
                    }`}
                  >
                    {c.action === "BUY" ? "매수" : "매도"} {c.confidence}
                  </span>
                </Link>
              ))}
              {pensionCandidates.length > 0 && !isMonthEnd && (
                <span className="text-[10px] text-zinc-600">연금 {pensionCandidates.length}건 월말 대기</span>
              )}
            </div>
          </div>
        </CollapsibleStrip>
      </div>

      {/* ═══ 보유 종목 — full-width (사이드바 제거 후) ═══
          3xl+ (≥1680px) 에서는 우측에 <HoldingsSummaryPanel> 을 나란히 띄운다 (#221).
          1680 미만 2xl 에서는 panel 숨김 — 가로 폭이 부족해 겹치므로. */}
      {enrichedHoldings.length > 0 && (
        <section className="flex-1 min-h-0 flex flex-col items-start min-[1680px]:flex-row min-[1680px]:items-start min-[1680px]:gap-4">
          {/*
            w-fit wrapper — 제목 바 + 테이블 이 모두 테이블의 natural width (현재 breakpoint 의
            column sum)에 맞춰 shrink 한다. 덕분에 period toggle + 상세 링크가 테이블의 우측
            가장자리에 정확히 정렬되어, 우측에 떠 있는 "disconnected toolbar" 문제가 사라진다.
            max-w-full 은 narrow viewport safety net.
          */}
          <div className="w-fit max-w-full">
          <div className="flex items-center justify-between mb-1.5 gap-3">
            <div className="flex items-center gap-2 min-w-0">
              <h2 className="text-sm font-semibold text-zinc-200">보유 종목</h2>
              <span className="text-[10px] text-zinc-600 truncate">
                {winners.length > 0 && `수익 ${winners.length}`}
                {winners.length > 0 && losers.length > 0 && " · "}
                {losers.length > 0 && `손실 ${losers.length}`}
                {hiddenPensionCount > 0 && (
                  <>
                    {(winners.length > 0 || losers.length > 0) && " · "}
                    <span className="text-zinc-700">연금 {hiddenPensionCount}건 숨김</span>
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
                <span className="text-zinc-700 mr-1 normal-case">추세</span>
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
                <span className="text-zinc-700 normal-case">일</span>
              </div>
              <Link href="/portfolio" className="text-[9px] text-zinc-600 hover:text-zinc-400">상세 &rarr;</Link>
            </div>
          </div>
          {/* Responsive column tiers — 헤더와 rows가 동일 breakpoint·width로 정렬.
              base (<sm):  계좌·종목·손익·상태·워치 (~380px)
              sm+  (640+): + 일변 (~438px)
              md+  (768+): + 현재/평단·손절 (~594px)
              lg+  (1024+): + 1차익절·2차익절 (~746px, 752 content budget)
              xl+  (1280+): + sparkline 80px (~834px)
              2xl+ (1536+): sparkline 240px + 섹터 96px + 비중 56px (~1240px, 27" 전용)
              overflow-x-auto는 narrow viewport safety net. */}
          <div className="overflow-x-auto">
            <div className="min-w-0">
              {/* 컬럼 헤더 — sm+ (< sm은 헤더 없이 row aria-label 만으로 충분).
                  w-fit 이라 rows 의 w-fit 과 정확히 같은 폭을 차지 → hover 정렬 + 우측 dead zone 제거. */}
              <div className="hidden sm:flex w-fit items-center gap-2 px-2 pb-1 text-[9px] text-zinc-600 uppercase">
                <span className="w-10 2xl:w-16 shrink-0">계좌</span>
                <span className="w-20 shrink-0">종목</span>
                <span className="hidden md:flex w-[72px] text-right shrink-0 leading-tight justify-end">
                  현재/<span className="text-zinc-700">평단</span>
                </span>
                <span className="w-14 text-right shrink-0">손익</span>
                <span className="w-12 text-right shrink-0">일변</span>
                <span className="w-[68px] text-center shrink-0">상태</span>
                <span className="w-[90px] text-right shrink-0 truncate">워치</span>
                <span className="hidden md:inline-block w-[68px] text-right shrink-0">손절</span>
                <span className="hidden lg:inline-block w-[68px] text-right shrink-0">1차익절</span>
                <span className="hidden lg:inline-block w-[68px] text-right shrink-0">2차익절</span>
                {/* sparkline column label — xl: 80px / 2xl: 240px (둘 다 고정) */}
                <span className="hidden xl:inline-block w-20 2xl:w-60 text-left shrink-0">
                  추세
                </span>
                {/* #218 (PR #219): 2xl+ 27" 전용 초광폭 컬럼. Sector 는 label 이라 text-left. */}
                <span className="hidden 2xl:inline-block w-[96px] text-left shrink-0">섹터</span>
                <span className="hidden 2xl:inline-block w-[56px] text-right shrink-0">비중</span>
              </div>
              <div className="space-y-0.5">
                {enrichedHoldings.map((h, i) => (
                  <HoldingRow key={`${h.account}-${h.ticker}-${i}`} holding={h} />
                ))}
              </div>
            </div>
          </div>
          </div>
          {/* #221: 3xl+ 우측 요약 패널 (Today / Sector / Movers / Concentration) */}
          <HoldingsSummaryPanel
            summary={summarizeHoldings(enrichedHoldings, { totalPortfolioUsd: totalValue })}
            className="hidden min-[1680px]:flex w-[200px] shrink-0 sticky top-0"
          />
        </section>
      )}

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
