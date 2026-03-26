export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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
  neutral:    { bg: "bg-zinc-900",       border: "border-zinc-700",    text: "text-zinc-400",    label: "NEUTRAL" },
  cautious:   { bg: "bg-amber-950/50",   border: "border-amber-700",   text: "text-amber-400",   label: "CAUTIOUS" },
  defensive:  { bg: "bg-red-950/50",     border: "border-red-700",     text: "text-red-400",     label: "DEFENSIVE" },
};

const actionStyles: Record<string, string> = {
  BUY:   "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  SELL:  "bg-red-500/20 text-red-400 border-red-500/30",
  WATCH: "bg-blue-500/20 text-blue-400 border-blue-500/30",
};

async function Dashboard() {
  const d = await fetchAPI<DashboardData>("/api/dashboard");
  const style = levelStyles[d.verdict_level] || levelStyles.neutral;

  return (
    <div className="space-y-5">
      {/* ── Hero: 오늘의 판단 ── */}
      <Card className={`${style.bg} ${style.border} border-2`}>
        <CardContent className="pt-6 pb-5">
          <div className="flex items-center gap-3 mb-3">
            <Badge className={`${style.text} bg-transparent border ${style.border} text-xs px-2 py-0.5`}>
              {style.label}
            </Badge>
            <span className="text-xs text-zinc-500">
              {d.regime.regime} | Macro {d.macro.score}/100 | Gate {d.gate_score}%
            </span>
          </div>
          <p className={`text-lg font-medium ${style.text}`}>{d.verdict}</p>

          {/* Allocation Bar — 라벨이 바 안에 표시 */}
          <div className="flex h-6 rounded-lg overflow-hidden mt-4 text-[10px] font-medium">
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
              <div className="bg-zinc-700 flex items-center justify-center text-zinc-400"
                style={{ width: `${d.allocation.cash}%` }}>
                Cash {d.allocation.cash}%
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* ── 왼쪽: 액션 리스트 ── */}
        <Card className="bg-zinc-900 border-zinc-800">
          <CardContent className="pt-5">
            <p className="text-xs text-zinc-500 mb-3">Actions ({d.actions.length})</p>
            {d.actions.length > 0 ? (
              <div className="space-y-2.5">
                {d.actions.map((a, i) => (
                  <Link key={`${a.ticker}-${i}`} href={`/ticker/${a.ticker}`}
                    className="flex items-center justify-between p-2.5 rounded-lg bg-zinc-800/50 hover:bg-zinc-800 transition-colors group">
                    <div className="flex items-center gap-2.5">
                      <Badge className={`${actionStyles[a.action]} border text-[11px] px-1.5 py-0`}>
                        {a.action}
                      </Badge>
                      <div>
                        <span className="font-medium text-sm group-hover:text-white transition-colors">{a.ticker}</span>
                        <p className="text-[11px] text-zinc-500 mt-0.5 line-clamp-1">{a.reason}</p>
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <span className="text-sm font-medium">{a.confidence}</span>
                      <p className="text-[10px] text-zinc-600">{a.agreement}% agree</p>
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-sm text-zinc-600 py-4 text-center">No actions — hold current positions</p>
            )}
          </CardContent>
        </Card>

        {/* ── 오른쪽: 알림 + 상태 ── */}
        <div className="space-y-4">
          {/* Alerts */}
          {d.alerts.length > 0 && (
            <Card className="bg-zinc-900 border-zinc-800">
              <CardContent className="pt-5">
                <p className="text-xs text-zinc-500 mb-2">Alerts</p>
                <div className="space-y-1.5">
                  {d.alerts.map((al, i) => (
                    <div key={i} className={`text-xs px-2.5 py-1.5 rounded ${
                      al.level === "critical" ? "bg-red-500/10 text-red-400" :
                      al.level === "warning" ? "bg-amber-500/10 text-amber-400" :
                      "bg-zinc-800 text-zinc-400"
                    }`}>
                      {al.message}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Quick Stats */}
          <Card className="bg-zinc-900 border-zinc-800">
            <CardContent className="pt-5">
              <p className="text-xs text-zinc-500 mb-3">Market</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-[10px] text-zinc-600">Regime</p>
                  <p className="text-sm font-medium">{d.regime.trend.toUpperCase()}</p>
                </div>
                <div>
                  <p className="text-[10px] text-zinc-600">Confidence</p>
                  <p className="text-sm font-medium">{d.regime.confidence}%</p>
                </div>
                <div>
                  <p className="text-[10px] text-zinc-600">VIX</p>
                  <p className="text-sm font-medium">{d.regime.vix ?? "—"}</p>
                </div>
                <div>
                  <p className="text-[10px] text-zinc-600">Fear & Greed</p>
                  <p className={`text-sm font-medium ${
                    (d.regime.fear_greed ?? 50) < 25 ? "text-red-400" :
                    (d.regime.fear_greed ?? 50) > 75 ? "text-emerald-400" : ""
                  }`}>{d.regime.fear_greed ?? "—"}</p>
                </div>
                <div>
                  <p className="text-[10px] text-zinc-600">Macro Score</p>
                  <p className="text-sm font-medium">{d.macro.score}/100</p>
                </div>
                <div>
                  <p className="text-[10px] text-zinc-600">Open Positions</p>
                  <p className="text-sm font-medium">{d.n_positions}</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Navigation */}
          <div className="grid grid-cols-3 gap-2">
            {[
              { href: "/strategy", label: "Strategy", sub: "L/S + Backtest" },
              { href: "/consensus", label: "Agents", sub: "6-agent detail" },
              { href: "/scan", label: "Scan", sub: "Market scanner" },
            ].map((item) => (
              <Link key={item.href} href={item.href}
                className="block p-2.5 rounded-lg bg-zinc-900 border border-zinc-800 hover:border-zinc-600 transition-colors text-center">
                <p className="text-xs font-medium">{item.label}</p>
                <p className="text-[10px] text-zinc-600">{item.sub}</p>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-5">
      <div className="h-36 bg-zinc-900 rounded-xl border border-zinc-800 animate-pulse" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="h-64 bg-zinc-900 rounded-xl border border-zinc-800 animate-pulse" />
        <div className="space-y-4">
          <div className="h-28 bg-zinc-900 rounded-xl border border-zinc-800 animate-pulse" />
          <div className="h-32 bg-zinc-900 rounded-xl border border-zinc-800 animate-pulse" />
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
