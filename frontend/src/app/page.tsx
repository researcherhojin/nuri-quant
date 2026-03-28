export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";
import { Separator } from "@/components/ui/separator";
import Link from "next/link";

interface DashboardData {
  verdict: string;
  verdict_level: string;
  regime: { regime: string; trend: string; volatility?: string; confidence: number; vix?: number; fear_greed?: number };
  macro: { score: number; interpretation: string };
  allocation: { long: number; short: number; cash: number };
  actions: Array<{ action: string; ticker: string; confidence: number; agreement: number; reason: string }>;
  alerts: Array<{ level: string; message: string }>;
  gate_score: number;
  n_positions: number;
}

const levelStyles: Record<string, { bg: string; border: string; text: string; label: string }> = {
  aggressive: { bg: "bg-emerald-950/50", border: "border-emerald-700", text: "text-emerald-400", label: "AGGRESSIVE" },
  neutral:    { bg: "bg-card",       border: "border-input",    text: "text-muted-foreground",    label: "NEUTRAL" },
  cautious:   { bg: "bg-amber-950/50",   border: "border-amber-700",   text: "text-amber-400",   label: "CAUTIOUS" },
  defensive:  { bg: "bg-red-950/50",     border: "border-red-700",     text: "text-red-400",     label: "DEFENSIVE" },
};

async function Dashboard() {
  const d = await fetchAPI<DashboardData>("/api/dashboard");

  // 포트폴리오만 서버사이드 fetch (빠름). SIEGE/advisor는 사이드바에서 별도 fetch.
  let portfolio: any = null;
  let siege: any = null;
  let advisor: any = null;
  try {
    // portfolio는 빠름 (DB 직접). certify/advisor는 느릴 수 있으므로 3초 타임아웃.
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    [portfolio, siege, advisor] = await Promise.all([
      fetchAPI<any>("/api/portfolio").catch(() => null),
      fetch("http://localhost:8001/api/certify", { signal: controller.signal })
        .then(r => r.json()).catch(() => null),
      fetch("http://localhost:8001/api/rebalance-advisor", { signal: controller.signal })
        .then(r => r.json()).catch(() => null),
    ]);
    clearTimeout(timeout);
  } catch {}

  const style = levelStyles[d.verdict_level] || levelStyles.neutral;

  // 포트폴리오 평가액 계산 (KRW 종목은 환율 적용)
  const KRW_RATE = 1514;
  const totalValue = portfolio?.holdings?.reduce((sum: number, h: any) => {
    const price = h.latest_price || 0;
    const qty = h.quantity || 0;
    const isKr = h.ticker?.endsWith(".KS");
    return sum + (isKr ? price * qty / KRW_RATE : price * qty);
  }, 0) || 0;

  return (
    <div className="space-y-4">
      {/* ── Top Metrics Row ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card className="bg-card border-border">
          <CardContent className="pt-4 pb-3">
            <p className="text-[10px] text-muted-foreground mb-1">Portfolio</p>
            <p className="text-lg font-bold">${totalValue.toLocaleString(undefined, {maximumFractionDigits: 0})}</p>
            <p className="text-[10px] text-muted-foreground/70">{portfolio?.count || 0} holdings</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardContent className="pt-4 pb-3">
            <p className="text-[10px] text-muted-foreground mb-1">SIEGE</p>
            <div className="flex items-center gap-2">
              <p className={`text-lg font-bold ${siege?.certified ? "text-emerald-400" : "text-red-400"}`}>
                {siege?.certified ? "CERTIFIED" : "REJECTED"}
              </p>
            </div>
            <p className="text-[10px] text-muted-foreground/70">{siege?.score || 0}% ({siege?.passed || 0}/{siege?.total || 0})</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardContent className="pt-4 pb-3">
            <p className="text-[10px] text-muted-foreground mb-1">Violations</p>
            <p className={`text-lg font-bold ${(advisor?.has_critical) ? "text-red-400" : "text-emerald-400"}`}>
              {advisor?.total_violations || 0}건
            </p>
            <p className="text-[10px] text-muted-foreground/70">
              {advisor?.total_recovery_usd ? `$${advisor.total_recovery_usd.toLocaleString(undefined, {maximumFractionDigits: 0})} 회수 가능` : "위반 없음"}
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardContent className="pt-4 pb-3">
            <p className="text-[10px] text-muted-foreground mb-1">Market</p>
            <p className="text-lg font-bold">{d.regime.trend?.toUpperCase()}</p>
            <p className="text-[10px] text-muted-foreground/70">
              VIX {d.regime.vix ?? "—"} · F&G {d.regime.fear_greed ?? "—"}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* ── Verdict + Allocation ── */}
      <Card className={`${style.bg} ${style.border} border`}>
        <CardContent className="pt-5 pb-4">
          <div className="flex items-center gap-3 mb-2">
            <StatusBadge status={style.label} size="md" />
            <span className="text-xs text-muted-foreground">
              {d.regime.regime} · Macro {d.macro.score}/100 · Gate {d.gate_score}%
            </span>
          </div>
          <p className={`text-sm font-medium ${style.text}`}>{d.verdict}</p>

          <div className="flex h-5 rounded overflow-hidden mt-3 text-[10px] font-medium">
            {d.allocation.long > 0 && (
              <div className="bg-emerald-600 flex items-center justify-center"
                style={{ width: `${d.allocation.long}%` }}>
                {d.allocation.long >= 15 && `Long ${d.allocation.long}%`}
              </div>
            )}
            {d.allocation.short > 0 && (
              <div className="bg-red-600 flex items-center justify-center"
                style={{ width: `${d.allocation.short}%` }}>
                {d.allocation.short >= 10 && `Short ${d.allocation.short}%`}
              </div>
            )}
            {d.allocation.cash > 0 && (
              <div className="bg-muted flex items-center justify-center text-muted-foreground"
                style={{ width: `${d.allocation.cash}%` }}>
                Cash {d.allocation.cash}%
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* ── 왼쪽: 액션 리스트 ── */}
        <Card className="bg-card border-border">
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground mb-3">Actions ({d.actions.length})</p>
            {d.actions.length > 0 ? (
              <div className="space-y-2.5">
                {d.actions.map((a, i) => (
                  <Link key={`${a.ticker}-${i}`} href={`/ticker/${a.ticker}`}
                    className="flex items-center justify-between p-2.5 rounded-lg bg-muted/50 hover:bg-muted transition-colors group">
                    <div className="flex items-center gap-2.5">
                      <StatusBadge status={a.action} />
                      <div>
                        <span className="font-medium text-sm group-hover:text-white transition-colors">{a.ticker}</span>
                        <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-1">{a.reason}</p>
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <span className="text-sm font-medium">{a.confidence}</span>
                      <p className="text-[10px] text-muted-foreground/70">{a.agreement}% agree</p>
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground/70 py-4 text-center">No actions — hold current positions</p>
            )}
          </CardContent>
        </Card>

        {/* ── 오른쪽: 알림 + 상태 ── */}
        <div className="space-y-4">
          {/* Alerts */}
          {d.alerts.length > 0 && (
            <Card className="bg-card border-border">
              <CardContent className="pt-5">
                <p className="text-xs text-muted-foreground mb-2">Alerts</p>
                <div className="space-y-1.5">
                  {d.alerts.map((al, i) => (
                    <div key={i} className={`text-xs px-2.5 py-1.5 rounded ${
                      al.level === "critical" ? "bg-red-500/10 text-red-400" :
                      al.level === "warning" ? "bg-amber-500/10 text-amber-400" :
                      "bg-muted text-muted-foreground"
                    }`}>
                      {al.message}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Quick Stats */}
          <Card className="bg-card border-border">
            <CardContent className="pt-5">
              <p className="text-xs text-muted-foreground mb-3">Market</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-[10px] text-muted-foreground/70">Regime</p>
                  <p className="text-sm font-medium">{d.regime.trend.toUpperCase()}</p>
                </div>
                <div>
                  <p className="text-[10px] text-muted-foreground/70">Confidence</p>
                  <p className="text-sm font-medium">{d.regime.confidence}%</p>
                </div>
                <div>
                  <p className="text-[10px] text-muted-foreground/70">VIX</p>
                  <p className="text-sm font-medium">{d.regime.vix ?? "—"}</p>
                </div>
                <div>
                  <p className="text-[10px] text-muted-foreground/70">Fear & Greed</p>
                  <p className={`text-sm font-medium ${
                    (d.regime.fear_greed ?? 50) < 25 ? "text-red-400" :
                    (d.regime.fear_greed ?? 50) > 75 ? "text-emerald-400" : ""
                  }`}>{d.regime.fear_greed ?? "—"}</p>
                </div>
                <div>
                  <p className="text-[10px] text-muted-foreground/70">Macro Score</p>
                  <p className="text-sm font-medium">{d.macro.score}/100</p>
                </div>
                <div>
                  <p className="text-[10px] text-muted-foreground/70">Open Positions</p>
                  <p className="text-sm font-medium">{d.n_positions}</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* SIEGE Conditions (if rejected) */}
          {siege && !siege.certified && (
            <Card className="bg-red-950/20 border-red-900/50">
              <CardContent className="pt-4 pb-3">
                <p className="text-xs text-red-400 font-medium mb-2">SIEGE 미충족 조건</p>
                <div className="space-y-1">
                  {siege.conditions?.filter((c: any) => !c.passed).slice(0, 4).map((c: any, i: number) => (
                    <p key={i} className="text-[11px] text-muted-foreground">
                      {c.severity === "error" ? "❌" : "⚠️"} {c.description} — {c.detail}
                    </p>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-5">
      <div className="h-36 bg-card rounded-xl border border-border animate-pulse" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="h-64 bg-card rounded-xl border border-border animate-pulse" />
        <div className="space-y-4">
          <div className="h-28 bg-card rounded-xl border border-border animate-pulse" />
          <div className="h-32 bg-card rounded-xl border border-border animate-pulse" />
        </div>
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
