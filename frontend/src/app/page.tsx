export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { redirect } from "next/navigation";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";
import { FreshnessBar, type FreshnessItem } from "@/components/ui/freshness-bar";
import Link from "next/link";

interface DashboardData {
  verdict: string;
  verdict_level: string;
  regime: { regime: string; trend: string; volatility?: string; confidence: number; vix?: number; fear_greed?: number };
  macro: { score: number; interpretation: string };
  allocation: { long: number; short: number; cash: number };
  actions: Array<{ action: string; ticker: string; name?: string | null; confidence: number; agreement: number; reason: string }>;
  alerts: Array<{ level: string; message: string }>;
  gate_score: number;
  n_positions: number;
  exchange_rate: number | null;
}

interface FreshnessData {
  items?: FreshnessItem[];
  details?: FreshnessItem[];
  overall?: "PASS" | "WARN" | "FAIL";
  pass?: number;
  warn?: number;
  fail?: number;
}

interface PipelineStatusData {
  steps: Array<{ step: string; label: string; status: string; record_count: number; last_updated: string | null }>;
}

const verdictLabels: Record<string, string> = {
  aggressive: "공격", neutral: "관망", cautious: "주의", defensive: "방어",
};

const levelStyles: Record<string, { bg: string; border: string; text: string }> = {
  aggressive: { bg: "bg-emerald-950/50", border: "border-emerald-700", text: "text-emerald-400" },
  neutral:    { bg: "bg-card",           border: "border-input",       text: "text-muted-foreground" },
  cautious:   { bg: "bg-amber-950/50",   border: "border-amber-700",   text: "text-amber-400" },
  defensive:  { bg: "bg-red-950/50",     border: "border-red-700",     text: "text-red-400" },
};

const pipelineStatusColors: Record<string, string> = {
  idle: "bg-zinc-500", running: "bg-blue-500 animate-pulse", done: "bg-emerald-500", error: "bg-red-500",
};

/* ── Gauge bar component ── */
function Gauge({ value, max, color, label, sub }: { value: number; max: number; color: string; label: string; sub: string }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-[10px] text-muted-foreground">{label}</span>
        <span className={`text-sm font-semibold ${color}`}>{value}</span>
      </div>
      <div className="h-1.5 bg-muted/50 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color.replace("text-", "bg-")}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-[10px] text-muted-foreground/70 mt-0.5">{sub}</p>
    </div>
  );
}

/* ── Confidence bar (inline) ── */
function ConfBar({ value }: { value: number }) {
  const pct = Math.min(100, value);
  const color = pct >= 80 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1 w-12 bg-muted/50 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-semibold tabular-nums">{value}</span>
    </div>
  );
}

/* ── Alert message translation ── */
function translateAlert(msg: string): string {
  return msg
    .replace("시그널 성과 급락:", "매매 신호 성과 하락:")
    .replace(/BUY\/SELL 충돌 (\d+)건:/, "매수·매도 신호 충돌 $1건:")
    .replace("bb_bounce", "볼린저밴드 반등")
    .replace("macd_bullish_turn", "MACD 상승전환")
    .replace("macd_bearish_turn", "MACD 하락전환")
    .replace("macd_golden", "MACD 골든크로스")
    .replace("macd_dead", "MACD 데드크로스")
    .replace("rsi_oversold", "RSI 과매도")
    .replace("rsi_overbought", "RSI 과매수")
    .replace("sma_golden", "이동평균 골든크로스")
    .replace("sma_dead", "이동평균 데드크로스")
    .replace("volume_spike", "거래량 급증")
    .replace("gap_up", "갭 상승")
    .replace("gap_down", "갭 하락")
    .replace("bb_squeeze_breakout", "볼린저밴드 돌파")
    .replace("near_52w_low_bounce", "52주 저점 반등")
    .replace("volume_profile_resistance", "거래량 저항선");
}

/* ── Market helpers ── */
function trendKo(t: string): string {
  return t === "bull" ? "상승" : t === "bear" ? "하락" : "횡보";
}
function vixDesc(v: number | null): string {
  if (v == null) return "데이터 없음";
  if (v < 15) return "안정 — 매수에 유리한 구간";
  if (v > 30) return "극도 불안 — 신규 매수 자제";
  if (v > 25) return "불안정 — 주의 필요";
  return "보통 — 정상 범위";
}
function fgDesc(fg: number | null): string {
  if (fg == null) return "데이터 없음";
  if (fg < 25) return "극도 공포 — 역발상 매수 구간";
  if (fg < 45) return "공포 — 매수 기회 가능";
  if (fg <= 55) return "중립";
  if (fg <= 75) return "탐욕 — 과열 주의";
  return "극도 탐욕 — 매수 자제";
}

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
  if (holdingCount === 0) {
    redirect("/portfolio?onboarding=true");
  }

  const style = levelStyles[d.verdict_level] || levelStyles.neutral;
  const verdictLabel = verdictLabels[d.verdict_level] || "관망";

  const KRW_RATE = d.exchange_rate || 1400;
  const totalValue = portfolio?.holdings?.reduce((sum: number, h: any) => {
    const price = h.latest_price || 0;
    const qty = h.quantity || 0;
    const isKr = h.ticker?.endsWith(".KS");
    return sum + (isKr ? price * qty / KRW_RATE : price * qty);
  }, 0) || 0;

  const vix = d.regime.vix ?? null;
  const fg = d.regime.fear_greed ?? null;
  const trend = d.regime.trend || "unknown";
  const alertCount = d.alerts.length;
  const siegeFailed = siege?.conditions?.filter((c: any) => !c.passed) || [];
  const siegeTotal = siege?.total || 0;
  const nBuys = d.actions.filter(a => a.action === "BUY").length;
  const nSells = d.actions.filter(a => a.action === "SELL").length;

  // 수익/손실 종목 요약
  const holdings = portfolio?.holdings || [];
  const winners = holdings.filter((h: any) => h.latest_price && h.avg_price && h.latest_price > h.avg_price);
  const losers = holdings.filter((h: any) => h.latest_price && h.avg_price && h.latest_price < h.avg_price);
  const topWinner = winners.sort((a: any, b: any) => ((b.latest_price / b.avg_price) - (a.latest_price / a.avg_price)))[0];
  const topLoser = losers.sort((a: any, b: any) => ((a.latest_price / a.avg_price) - (b.latest_price / b.avg_price)))[0];
  // 종목 표시명: name 필드 → ticker에서 .KS 제거 → ticker 그대로
  const displayName = (h: any) => h?.name || (h?.ticker?.endsWith(".KS") ? h.ticker.replace(".KS", "") : h?.ticker) || "";

  return (
    <div className="space-y-3">
      {/* ── 데이터 상태 ── */}
      <div className="flex items-center gap-4 flex-wrap">
        {((freshness?.items?.length ?? 0) > 0 || (freshness?.details?.length ?? 0) > 0) && (
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-muted-foreground/70 shrink-0">데이터</span>
            <FreshnessBar items={freshness?.items ?? freshness?.details ?? []} />
          </div>
        )}
        {pipelineStatus.steps.length > 0 && (
          <div className="flex items-center gap-1.5">
            {pipelineStatus.steps.map((s, i) => (
              <div key={s.step} className="flex items-center gap-1">
                <div className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted/30" title={`${s.label}: ${s.record_count.toLocaleString()}건`}>
                  <span className={`inline-flex h-1.5 w-1.5 rounded-full ${pipelineStatusColors[s.status] || "bg-zinc-500"}`} />
                  <span className="text-[10px] text-muted-foreground">{s.label}</span>
                </div>
                {i < pipelineStatus.steps.length - 1 && <span className="text-muted-foreground/30 text-[10px]">&rarr;</span>}
              </div>
            ))}
            <Link href="/pipeline" className="text-[10px] text-muted-foreground/50 hover:text-muted-foreground ml-1">&rarr;</Link>
          </div>
        )}
      </div>

      {/* ── 오늘의 판단 + 시장 현황 ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* 오늘의 판단 — 3/5 width */}
        <Card className={`${style.bg} ${style.border} border`}>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold text-foreground/80">오늘의 판단</span>
            </div>
            <div className="flex items-center gap-3 mb-2">
              <StatusBadge status={verdictLabel} size="lg" />
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span>총 평가액 <span className="font-semibold text-foreground">${totalValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span></span>
                {siegeTotal > 0 && (
                  <span>품질검증 <span className={`font-semibold ${siege?.certified ? "text-emerald-400" : "text-red-400"}`}>{siege?.certified ? "통과" : "미통과"}</span> <span className="text-muted-foreground/70">{siege?.passed || 0}/{siegeTotal}</span></span>
                )}
                {(advisor?.total_violations || 0) > 0 && (
                  <span>규칙 위반 <span className="font-semibold text-red-400">{advisor.total_violations}건</span></span>
                )}
              </div>
            </div>

            {/* 판단 이유 + 요약 */}
            <p className={`text-sm ${style.text} mb-1`}>{d.verdict}</p>
            {/* 포트폴리오 수익/손실 요약 */}
            <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] mb-3">
              {winners.length > 0 && (
                <span className="text-emerald-400/80">
                  수익 {winners.length}종목
                  {topWinner && ` (최고 ${displayName(topWinner)} +${((topWinner.latest_price / topWinner.avg_price - 1) * 100).toFixed(0)}%)`}
                </span>
              )}
              {losers.length > 0 && (
                <span className="text-red-400/80">
                  손실 {losers.length}종목
                  {topLoser && ` (최대 ${displayName(topLoser)} ${((topLoser.latest_price / topLoser.avg_price - 1) * 100).toFixed(0)}%)`}
                </span>
              )}
              {nBuys > 0 && <span className="text-muted-foreground/60">매수 신호 {nBuys}건</span>}
              {nSells > 0 && <span className="text-muted-foreground/60">매도 신호 {nSells}건</span>}
              {alertCount > 0 && <span className="text-amber-400/60">위험 {alertCount}건</span>}
            </div>

            {/* 비중 바 */}
            <div className="flex h-4 rounded overflow-hidden text-[10px] font-medium">
              {d.allocation.long > 0 && (
                <div className="bg-emerald-600 flex items-center justify-center" style={{ width: `${d.allocation.long}%` }}>
                  {d.allocation.long >= 15 && `투자 ${d.allocation.long}%`}
                </div>
              )}
              {d.allocation.short > 0 && (
                <div className="bg-red-600 flex items-center justify-center" style={{ width: `${d.allocation.short}%` }}>
                  {d.allocation.short >= 10 && `숏 ${d.allocation.short}%`}
                </div>
              )}
              {d.allocation.cash > 0 && (
                <div className="bg-muted flex items-center justify-center text-muted-foreground" style={{ width: `${d.allocation.cash}%` }}>
                  현금 {d.allocation.cash}%
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* 시장 현황 — 2/5 width, gauge bars */}
        <Card className="bg-card border-border">
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold text-foreground/80">시장 현황</span>
              <span className={`text-xs font-semibold ${trend === "bull" ? "text-emerald-400" : trend === "bear" ? "text-red-400" : "text-muted-foreground"}`}>
                {trendKo(trend)} {trend === "bull" ? "\u2197" : trend === "bear" ? "\u2198" : "\u2194"}
              </span>
            </div>
            <div className="space-y-3">
              <Gauge
                label="변동성 지수 (VIX)"
                value={vix != null ? Math.round(vix * 10) / 10 : 0}
                max={50}
                color={vix == null ? "text-zinc-400" : vix < 15 ? "text-emerald-400" : vix > 25 ? "text-red-400" : "text-zinc-200"}
                sub={vixDesc(vix)}
              />
              <Gauge
                label="공포·탐욕 지수"
                value={fg ?? 0}
                max={100}
                color={fg == null ? "text-zinc-400" : fg < 25 ? "text-red-400" : fg > 75 ? "text-red-400" : fg >= 40 && fg <= 60 ? "text-emerald-400" : "text-zinc-200"}
                sub={fgDesc(fg)}
              />
              <div className="flex items-baseline justify-between">
                <span className="text-[10px] text-muted-foreground">경제 지표</span>
                <span className={`text-sm font-semibold ${d.macro.score >= 60 ? "text-emerald-400" : d.macro.score < 40 ? "text-red-400" : "text-zinc-200"}`}>
                  {d.macro.score}<span className="text-muted-foreground/50 font-normal text-xs">/100</span>
                </span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── 오늘의 매매 + 위험 관리 ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* 오늘의 매매 — 3/5 */}
        <Card className="bg-card border-border">
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold text-foreground/80">
                오늘의 매매
                {d.actions.length > 0 && <span className="ml-1.5 text-muted-foreground font-normal">{d.actions.length}건</span>}
              </p>
              {d.actions.length > 0 && <span className="text-[10px] text-muted-foreground/50">클릭하면 상세 분석</span>}
            </div>
            {d.actions.length > 0 ? (
              <div className="space-y-1">
                {d.actions.map((a, i) => (
                  <Link key={`${a.ticker}-${i}`} href={`/ticker/${a.ticker}`}
                    className="block px-2.5 py-2 rounded-lg hover:bg-muted/50 transition-colors group">
                    <div className="flex items-center gap-2">
                      <StatusBadge status={a.action === "BUY" ? "매수" : "매도"} />
                      <span className="font-medium text-sm group-hover:text-white transition-colors">
                        {a.name || a.ticker}
                      </span>
                      {a.name && <span className="text-[10px] text-muted-foreground/40">{a.ticker}</span>}
                      <div className="ml-auto flex items-center gap-3">
                        <div className="text-right">
                          <ConfBar value={a.confidence} />
                          <p className="text-[9px] text-muted-foreground/50 mt-0.5">신뢰도</p>
                        </div>
                        <div className="text-right" title="10개 AI 에이전트 중 동의한 수">
                          <span className="text-xs font-semibold tabular-nums">{Math.round((a.agreement || 0) / 10)}/10</span>
                          <p className="text-[9px] text-muted-foreground/50">AI 동의</p>
                        </div>
                      </div>
                    </div>
                    {a.reason && (
                      <p className="text-[11px] text-muted-foreground/60 mt-1 pl-[52px] line-clamp-1">{a.reason}</p>
                    )}
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground/70 py-6 text-center">매매 신호 없음 &mdash; 현재 포지션 유지</p>
            )}
          </CardContent>
        </Card>

        {/* 위험 관리 — 2/5 */}
        <Card className="bg-card border-border">
          <CardContent className="pt-4 pb-3">
            <p className="text-xs font-semibold text-foreground/80 mb-2">
              위험 관리
              {alertCount > 0 && <span className="ml-1.5 text-red-400 font-normal">{alertCount}건</span>}
            </p>
            {alertCount > 0 ? (
              <div className="space-y-1.5">
                {d.alerts.map((al, i) => (
                  <div key={i} className={`text-xs px-2 py-1.5 rounded ${
                    al.level === "critical" ? "bg-red-500/10 text-red-400" :
                    al.level === "warning" ? "bg-amber-500/10 text-amber-400" :
                    "bg-muted text-muted-foreground"
                  }`}>
                    <span>{translateAlert(al.message)}</span>
                    {al.level === "critical" && al.message.includes("손절") && (
                      <span className="block text-[10px] mt-0.5 opacity-70">조치: 매도 검토하여 손실 제한</span>
                    )}
                    {al.level === "warning" && al.message.includes("손절") && (
                      <span className="block text-[10px] mt-0.5 opacity-70">조치: 추가 하락 시 매도 준비</span>
                    )}
                    {al.message.includes("시그널") && (
                      <span className="block text-[10px] mt-0.5 opacity-70">조치: 시그널 신뢰도 재확인</span>
                    )}
                    {al.message.includes("충돌") && (
                      <span className="block text-[10px] mt-0.5 opacity-70">조치: 신호 충돌 — 명확해질 때까지 대기</span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-xs text-emerald-400/70 py-2 flex items-center gap-1.5">
                <span className="inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
                위험 요소 없음 &mdash; 모든 규칙 준수 중
              </div>
            )}

            {siegeFailed.length > 0 && (
              <div className="mt-3 pt-3 border-t border-border/40">
                <p className="text-[10px] text-red-400/80 mb-1.5">품질검증 미통과 ({siegeFailed.length}건)</p>
                <div className="space-y-0.5">
                  {siegeFailed.slice(0, 5).map((c: any, i: number) => (
                    <p key={i} className="text-[11px] text-muted-foreground">
                      <span className={c.severity === "error" ? "text-red-400" : "text-amber-400"}>
                        {c.severity === "error" ? "\u2716" : "\u25B3"}
                      </span>{" "}
                      {c.description} &mdash; {c.detail}
                    </p>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-3">
      <div className="h-7 bg-card rounded border border-border animate-pulse" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="h-36 bg-card rounded-xl border border-border animate-pulse" />
        <div className="h-36 bg-card rounded-xl border border-border animate-pulse" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="h-48 bg-card rounded-xl border border-border animate-pulse" />
        <div className="h-48 bg-card rounded-xl border border-border animate-pulse" />
      </div>
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
