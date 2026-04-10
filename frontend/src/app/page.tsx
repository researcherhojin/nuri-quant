export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { redirect } from "next/navigation";
import { fetchAPI } from "@/lib/api";

import { StatusBadge } from "@/components/ui/status-badge";
import { FreshnessBar, type FreshnessItem } from "@/components/ui/freshness-bar";
import Link from "next/link";

interface DashboardData {
  verdict: string;
  verdict_level: string;
  regime: { regime: string; trend: string; volatility?: string; confidence: number; vix?: number; fear_greed?: number };
  macro: { score: number; interpretation: string };
  allocation: { long: number; short: number; cash: number };
  actions: Array<{ action: string; ticker: string; name?: string | null; confidence: number; agreement: number; reason: string; account?: string }>;
  alerts: Array<{ level: string; message: string }>;
  gate_score: number;
  n_positions: number;
  exchange_rate: number | null;
  account_values?: Array<{ account: string; value: number }>;
  upcoming_events?: Array<{ date: string; event_type: string; ticker: string | null; description: string; importance: number }>;
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
function displayName(h: { name?: string | null; ticker?: string }) {
  return h?.name || (h?.ticker?.endsWith(".KS") ? h.ticker.replace(".KS", "") : h?.ticker) || "";
}

/* ══════════════════════════════════════════════════════ */

async function Dashboard() {
  const [d, freshness, pipelineStatus, portfolio, siege, advisor] = await Promise.all([
    fetchAPI<DashboardData>("/api/dashboard"),
    fetchAPI<FreshnessData>("/api/freshness").catch((): FreshnessData => ({ items: [], details: [], overall: "FAIL", pass: 0, warn: 0, fail: 0 })),
    fetchAPI<PipelineStatusData>("/api/pipeline/status").catch((): PipelineStatusData => ({ steps: [] })),
    fetchAPI<any>("/api/portfolio").catch(() => null),
    Promise.race([
      fetchAPI<any>("/api/certify"),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 3000)),
    ]).catch(() => null),
    fetchAPI<any>("/api/rebalance-advisor").catch(() => null),
  ]);

  const holdingCount = portfolio?.count ?? portfolio?.holdings?.length ?? 0;
  if (holdingCount === 0) redirect("/portfolio?onboarding=true");

  const style = levelStyles[d.verdict_level] || levelStyles.neutral;
  const verdictLabel = verdictLabels[d.verdict_level] || "관망";
  const KRW_RATE = d.exchange_rate || 1400;
  const totalValue = portfolio?.holdings?.reduce((sum: number, h: any) => {
    const price = h.latest_price || 0;
    const qty = h.quantity || 0;
    return sum + (h.ticker?.endsWith(".KS") ? price * qty / KRW_RATE : price * qty);
  }, 0) || 0;

  const vix = d.regime.vix ?? null;
  const fg = d.regime.fear_greed ?? null;
  const trend = d.regime.trend || "unknown";
  const alertCount = d.alerts.length;
  const siegeFailed = siege?.conditions?.filter((c: any) => !c.passed) || [];
  const siegeTotal = siege?.total || 0;
  const nBuys = d.actions.filter(a => a.action === "BUY").length;
  const nSells = d.actions.filter(a => a.action === "SELL").length;

  const holdings = portfolio?.holdings || [];
  const winners = holdings.filter((h: any) => h.latest_price && h.avg_price && h.latest_price > h.avg_price);
  const losers = holdings.filter((h: any) => h.latest_price && h.avg_price && h.latest_price < h.avg_price);
  const topWinner = winners.sort((a: any, b: any) => ((b.latest_price / b.avg_price) - (a.latest_price / a.avg_price)))[0];
  const topLoser = losers.sort((a: any, b: any) => ((a.latest_price / a.avg_price) - (b.latest_price / b.avg_price)))[0];
  const vixInfo = vixZone(vix);
  const macroInfo = macroLevel(d.macro.score);
  const accountValues = d.account_values || [];

  // 계좌별 액션 그룹핑
  const mainActions = d.actions.filter(a => a.account === "Main" || a.account === "Sub");
  const pensionActions = d.actions.filter(a => a.account === "Pension");
  const otherActions = d.actions.filter(a => !a.account || (a.account !== "Main" && a.account !== "Sub" && a.account !== "Pension"));
  const now = new Date();
  const isMonthEnd = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate() - now.getDate() <= 3;

  return (
    <div className="flex flex-col gap-4 min-h-0">
      {/* ── 파이프라인 + 시장 온도 (1줄 통합) ── */}
      <div className="flex items-center gap-3 flex-wrap">
        {((freshness?.items?.length ?? 0) > 0 || (freshness?.details?.length ?? 0) > 0) && (
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-zinc-600 shrink-0">데이터</span>
            <FreshnessBar items={freshness?.items ?? freshness?.details ?? []} />
          </div>
        )}
        {pipelineStatus.steps.length > 0 && (
          <div className="flex items-center gap-1">
            {pipelineStatus.steps.map((s, i) => (
              <div key={s.step} className="flex items-center gap-0.5">
                <div className="flex items-center gap-0.5 px-1 py-0.5 rounded bg-zinc-800/50" title={`${s.label}: ${s.record_count.toLocaleString()}건`}>
                  <span className={`inline-flex h-1.5 w-1.5 rounded-full ${pipelineStatusColors[s.status] || "bg-zinc-500"}`} />
                  <span className="text-[9px] text-zinc-500">{s.label}</span>
                </div>
                {i < pipelineStatus.steps.length - 1 && <span className="text-zinc-700 text-[9px]">&rarr;</span>}
              </div>
            ))}
            <Link href="/pipeline" className="text-[9px] text-zinc-600 hover:text-zinc-400 ml-0.5">&rarr;</Link>
          </div>
        )}
      </div>

      {/* ═══ 히어로: 총 평가액 + 판단 (전폭) ═══ */}
      <div>
        <p className="text-[10px] text-zinc-500 mb-0.5">총 평가액</p>
        <div className="flex items-baseline gap-3">
          <span className="text-4xl font-semibold tabular-nums tracking-tight text-zinc-100">
            ${totalValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </span>
          <StatusBadge status={verdictLabel} size="lg" />
        </div>
        {/* 계좌별 평가액 */}
        {accountValues.length > 0 && (
          <div className="flex items-center gap-3 mt-1 text-[10px] text-zinc-500">
            {accountValues.map(av => (
              <span key={av.account}>{av.account} ${av.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
            ))}
          </div>
        )}
        <p className={`text-xs ${style.text} mt-1.5 line-clamp-1`}>{d.verdict}</p>
        <div className="flex items-center gap-3 mt-1 text-[10px]">
          {winners.length > 0 && (
            <span className="text-emerald-400/80">
              수익 {winners.length}종목
              {topWinner && <span className="text-zinc-500"> &middot; {displayName(topWinner)} +{((topWinner.latest_price / topWinner.avg_price - 1) * 100).toFixed(0)}%</span>}
            </span>
          )}
          {losers.length > 0 && (
            <span className="text-red-400/80">
              손실 {losers.length}종목
              {topLoser && <span className="text-zinc-500"> &middot; {displayName(topLoser)} {((topLoser.latest_price / topLoser.avg_price - 1) * 100).toFixed(0)}%</span>}
            </span>
          )}
        </div>
      </div>

      {/* 시장 온도 — 인라인 스트립 */}
      <div className="flex items-center gap-4 text-xs flex-wrap">
        <span className={`font-semibold ${trend === "bull" ? "text-emerald-400" : trend === "bear" ? "text-red-400" : "text-amber-400"}`}>
          {trendKo(trend)}
        </span>
        <span className="text-zinc-600">&middot;</span>
        <span className="flex items-center gap-1">
          <span className="text-zinc-500">VIX</span>
          <span className={`font-semibold tabular-nums ${vixInfo.color}`}>{vix != null ? Math.round(vix * 10) / 10 : "—"}</span>
          <span className={`text-[9px] ${vixInfo.color}`}>{vixInfo.label}</span>
        </span>
        <span className="text-zinc-600">&middot;</span>
        <span className="flex items-center gap-1">
          <span className="text-zinc-500">심리</span>
          <span className={`inline-flex items-center justify-center h-5 w-5 rounded-full text-[10px] font-bold tabular-nums ${fgColor(fg)}`}>{fg ?? "—"}</span>
          <span className="text-[9px] text-zinc-500">{fgLabel(fg)}</span>
        </span>
        <span className="text-zinc-600">&middot;</span>
        <span className="flex items-center gap-1">
          <span className="text-zinc-500">경제</span>
          <span className={`font-semibold tabular-nums ${macroInfo.color}`}>{d.macro.score}</span>
          <span className={`text-[9px] ${macroInfo.color}`}>{macroInfo.label}</span>
        </span>
        <span className="text-zinc-600">&middot;</span>
        <span className="text-[10px] text-zinc-600">{d.regime.regime}</span>
      </div>

      {/* 비중 바 */}
      <div className="flex h-4 rounded overflow-hidden text-[9px] font-medium">
        {d.allocation.long > 0 && (
          <div className="bg-emerald-600/80 flex items-center justify-center text-emerald-100" style={{ width: `${d.allocation.long}%` }}>
            {d.allocation.long >= 15 && `투자 ${d.allocation.long}%`}
          </div>
        )}
        {d.allocation.short > 0 && (
          <div className="bg-red-600/80 flex items-center justify-center text-red-100" style={{ width: `${d.allocation.short}%` }}>
            {d.allocation.short >= 10 && `숏 ${d.allocation.short}%`}
          </div>
        )}
        {d.allocation.cash > 0 && (
          <div className="bg-zinc-800 flex items-center justify-center text-zinc-400" style={{ width: `${d.allocation.cash}%` }}>
            현금 {d.allocation.cash}%
          </div>
        )}
      </div>

      {/* ═══ 알림 배너 (alertCount > 0 일 때만) ═══ */}
      {alertCount > 0 && (
        <div className="px-3 py-2 rounded-lg bg-red-950/30 border border-red-900/50">
          <p className="text-[10px] font-semibold text-red-400 mb-1">주의 {alertCount}건</p>
          <div className="space-y-0.5">
            {d.alerts.map((al, i) => (
              <p key={i} className={`text-[10px] ${al.level === "critical" ? "text-red-400" : "text-amber-400"}`}>
                {translateAlert(al.message)}
                {al.level === "critical" && al.message.includes("손절") && (
                  <span className="text-zinc-500"> &mdash; 매도 검토</span>
                )}
              </p>
            ))}
          </div>
        </div>
      )}

      {/* ═══ 오늘의 할 일 — 계좌별 그룹핑 ═══ */}
      <div className="flex-1 min-h-0">
        <div className="flex items-center justify-between mb-1.5">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-zinc-200">오늘의 할 일</h2>
            {d.actions.length > 0 && (
              <span className="text-[10px] text-zinc-600">
                {nBuys > 0 && `매수 ${nBuys}`}{nBuys > 0 && nSells > 0 && " \u00B7 "}{nSells > 0 && `매도 ${nSells}`}
              </span>
            )}
          </div>
          {d.actions.length > 0 && (
            <Link href="/decisions" className="text-[9px] text-zinc-600 hover:text-zinc-400">기록 &rarr;</Link>
          )}
        </div>

        {d.actions.length > 0 ? (
          <div className="space-y-2">
            {/* Main + Sub 액션 */}
            {mainActions.length > 0 && (
              <div>
                {mainActions.map((a, i) => (
                  <Link key={`${a.ticker}-${i}`} href={`/ticker/${a.ticker}`}
                    className={`flex items-center gap-2 px-2 py-1.5 rounded border-l-2 hover:bg-zinc-800/50 transition-colors ${
                      a.action === "BUY" ? "border-emerald-500" : "border-red-500"
                    }`}>
                    <StatusBadge status={a.action === "BUY" ? "매수" : "매도"} />
                    {a.account && <span className="text-[9px] text-zinc-600 min-w-[2rem]">{a.account}</span>}
                    <span className="font-medium text-xs text-zinc-100 truncate">{a.name || a.ticker}</span>
                    {a.name && <span className="text-[10px] text-zinc-600 shrink-0">{a.ticker}</span>}
                    {a.reason && <span className="text-[10px] text-zinc-600 truncate hidden lg:inline">{a.reason}</span>}
                    <div className="ml-auto flex items-center gap-2 shrink-0">
                      <span className={`inline-flex items-center justify-center w-7 h-5 rounded text-[10px] font-bold tabular-nums ${
                        a.confidence >= 80 ? "bg-emerald-500/15 text-emerald-400" :
                        a.confidence >= 50 ? "bg-amber-500/15 text-amber-400" :
                        "bg-red-500/15 text-red-400"
                      }`}>{a.confidence}</span>
                      <span className="text-[10px] text-zinc-500 tabular-nums">{Math.round((a.agreement || 0) / 10)}/10</span>
                    </div>
                  </Link>
                ))}
              </div>
            )}

            {/* Other 액션 (Toss 등) */}
            {otherActions.length > 0 && otherActions.map((a, i) => (
              <Link key={`o-${a.ticker}-${i}`} href={`/ticker/${a.ticker}`}
                className={`flex items-center gap-2 px-2 py-1.5 rounded border-l-2 hover:bg-zinc-800/50 transition-colors ${
                  a.action === "BUY" ? "border-emerald-500" : "border-red-500"
                }`}>
                <StatusBadge status={a.action === "BUY" ? "매수" : "매도"} />
                {a.account && <span className="text-[9px] text-zinc-600 min-w-[2rem]">{a.account}</span>}
                <span className="font-medium text-xs text-zinc-100 truncate">{a.name || a.ticker}</span>
                <div className="ml-auto flex items-center gap-2 shrink-0">
                  <span className={`inline-flex items-center justify-center w-7 h-5 rounded text-[10px] font-bold tabular-nums ${
                    a.confidence >= 80 ? "bg-emerald-500/15 text-emerald-400" :
                    a.confidence >= 50 ? "bg-amber-500/15 text-amber-400" :
                    "bg-red-500/15 text-red-400"
                  }`}>{a.confidence}</span>
                  <span className="text-[10px] text-zinc-500 tabular-nums">{Math.round((a.agreement || 0) / 10)}/10</span>
                </div>
              </Link>
            ))}

            {/* Pension — 월말 아니면 축소 */}
            {pensionActions.length > 0 && !isMonthEnd && (
              <p className="text-[10px] text-zinc-600 px-2">연금 {pensionActions.length}건 &mdash; 월말 매수 대기</p>
            )}
            {pensionActions.length > 0 && isMonthEnd && pensionActions.map((a, i) => (
              <Link key={`p-${a.ticker}-${i}`} href={`/ticker/${a.ticker}`}
                className={`flex items-center gap-2 px-2 py-1.5 rounded border-l-2 hover:bg-zinc-800/50 transition-colors ${
                  a.action === "BUY" ? "border-emerald-500" : "border-red-500"
                }`}>
                <StatusBadge status={a.action === "BUY" ? "매수" : "매도"} />
                <span className="text-[9px] text-zinc-600">연금</span>
                <span className="font-medium text-xs text-zinc-100 truncate">{a.name || a.ticker}</span>
                <div className="ml-auto flex items-center gap-2 shrink-0">
                  <span className={`inline-flex items-center justify-center w-7 h-5 rounded text-[10px] font-bold tabular-nums ${
                    a.confidence >= 80 ? "bg-emerald-500/15 text-emerald-400" :
                    a.confidence >= 50 ? "bg-amber-500/15 text-amber-400" :
                    "bg-red-500/15 text-red-400"
                  }`}>{a.confidence}</span>
                  <span className="text-[10px] text-zinc-500 tabular-nums">{Math.round((a.agreement || 0) / 10)}/10</span>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-zinc-500 text-center">매매 신호 없음 &mdash; 현재 포지션 유지</p>

            {/* 보유 종목 현황 */}
            {holdings.length > 0 && (
              <div>
                <p className="text-[10px] text-zinc-500 mb-1">보유 종목 현황</p>
                <div className="space-y-0.5">
                  {holdings.slice(0, 5).map((h: any) => {
                    const pnl = h.latest_price && h.avg_price ? ((h.latest_price / h.avg_price - 1) * 100) : 0;
                    return (
                      <Link key={h.ticker} href={`/ticker/${h.ticker}`}
                        className="flex items-center gap-2 px-2 py-1 rounded hover:bg-zinc-800/50 text-xs">
                        <span className="text-zinc-100 font-medium w-16 truncate">{displayName(h)}</span>
                        <span className="text-zinc-600 text-[10px] w-12">{h.ticker}</span>
                        <span className="text-zinc-500 text-[10px]">{h.quantity}주</span>
                        <span className={`ml-auto font-semibold tabular-nums ${pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                          {pnl >= 0 ? "+" : ""}{pnl.toFixed(1)}%
                        </span>
                      </Link>
                    );
                  })}
                </div>
              </div>
            )}

            {/* 다음 이벤트 */}
            {(d.upcoming_events?.length ?? 0) > 0 && (
              <div>
                <p className="text-[10px] text-zinc-500 mb-1">다음 이벤트</p>
                <div className="flex items-center gap-3 flex-wrap text-[10px]">
                  {d.upcoming_events!.slice(0, 5).map((ev: any, i: number) => (
                    <span key={i} className="text-zinc-400">
                      <span className="text-zinc-600">{ev.date?.slice(5)}</span>{" "}
                      {ev.description || ev.ticker}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* 푸터 */}
        <div className="mt-2 pt-2 border-t border-zinc-800/60 flex items-center gap-3 flex-wrap text-[10px]">
          {siegeTotal > 0 && siegeFailed.length === 0 && (
            <span className="text-zinc-400"><span className="text-emerald-500">&#10003;</span> 품질 검증 {siege?.passed || 0}/{siegeTotal} 통과</span>
          )}
          {siegeTotal > 0 && siegeFailed.length > 0 && (
            <span className="text-red-400"><span className="text-red-500">&#10007;</span> 품질 검증 미통과 ({siegeFailed.length}건) <span className="text-zinc-600">{siege?.passed || 0}/{siegeTotal}</span></span>
          )}
          {(advisor?.total_violations || 0) > 0 && (
            <span className="text-red-400">규칙 위반 {advisor.total_violations}건</span>
          )}
          <Link href="/portfolio" className="text-zinc-600 hover:text-zinc-400 ml-auto">포트폴리오 상세 &rarr;</Link>
        </div>
        {siegeTotal > 0 && siegeFailed.length > 0 && (
          <div className="mt-1 space-y-0.5">
            {siegeFailed.slice(0, 3).map((c: any, i: number) => (
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
    <div className="flex flex-col gap-4">
      <div className="h-6 bg-zinc-900 rounded animate-pulse" />
      <div className="h-16 bg-zinc-900/50 rounded animate-pulse" />
      <div className="h-5 bg-zinc-800/50 rounded animate-pulse" />
      <div className="h-4 bg-zinc-800 rounded animate-pulse" />
      <div className="h-48 bg-zinc-900/50 rounded animate-pulse" />
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
