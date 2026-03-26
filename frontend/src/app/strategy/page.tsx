export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

async function StrategyDashboard() {
  const [status, bt] = await Promise.all([
    fetchAPI<any>("/api/strategy/status"),
    fetchAPI<any>("/api/backtest"),
  ]);

  const regime = status.regime;
  const alloc = status.allocation || {};
  const r = bt.result || {};
  const t = bt.timing;
  const stress = bt.stress || [];
  const actions = status.actions || [];
  const positions = status.positions?.positions || [];

  const long_pct = alloc.long_pct || 0;
  const short_pct = alloc.short_pct || 0;
  const cash_pct = alloc.cash_pct || 0;

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold">Strategy</h1>

      {/* ── Row 1: Regime + Allocation + Actions ── */}
      <Card className="bg-zinc-900 border-zinc-800">
        <CardContent className="pt-5">
          <div className="flex items-center gap-3 mb-3">
            <Badge className="bg-zinc-700 text-zinc-300">{regime?.regime || "unknown"}</Badge>
            <span className="text-xs text-zinc-500">{regime ? `${(regime.confidence * 100).toFixed(0)}% confidence` : ""}</span>
            <span className="text-xs text-zinc-600">|</span>
            <span className="text-xs text-zinc-500">{positions.length} positions open</span>
          </div>

          {/* Allocation Bar */}
          <div className="flex h-7 rounded-lg overflow-hidden text-[11px] font-medium">
            {long_pct > 0 && (
              <div className="bg-emerald-600 flex items-center justify-center" style={{width:`${long_pct}%`}}>
                Long {long_pct}%
              </div>
            )}
            {short_pct > 0 && (
              <div className="bg-red-600 flex items-center justify-center" style={{width:`${short_pct}%`}}>
                Short {short_pct}%
              </div>
            )}
            {cash_pct > 0 && (
              <div className="bg-zinc-700 flex items-center justify-center text-zinc-400" style={{width:`${cash_pct}%`}}>
                Cash {cash_pct}%
              </div>
            )}
          </div>

          {/* Actions */}
          {actions.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-3">
              {actions.map((a: any, i: number) => (
                <div key={i} className="flex items-center gap-1.5 text-xs bg-zinc-800 rounded px-2 py-1">
                  <Badge className={a.action.includes("long") || a.action.includes("open_long")
                    ? "bg-emerald-500/20 text-emerald-400 text-[10px] px-1"
                    : "bg-red-500/20 text-red-400 text-[10px] px-1"}>
                    {a.action.replace("open_", "").toUpperCase()}
                  </Badge>
                  <span className="font-medium">{a.ticker}</span>
                  <span className="text-zinc-500 hidden sm:inline">{a.reason?.slice(0, 30)}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Row 2: Backtest + Stress in one row ── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* Backtest — 3/5 width */}
        <Card className="bg-zinc-900 border-zinc-800 lg:col-span-3">
          <CardContent className="pt-5">
            <p className="text-xs text-zinc-500 mb-3">Backtest — {r.total_days || 0} days, {r.regime_changes || 0} regime switches</p>

            <div className="grid grid-cols-4 gap-3 text-center mb-4">
              <div>
                <p className={`text-lg font-bold ${(r.total_return || 0) > 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {(r.total_return || 0) > 0 ? "+" : ""}{(r.total_return || 0).toFixed(1)}%
                </p>
                <p className="text-[10px] text-zinc-600">Return</p>
                <p className="text-[10px] text-zinc-700">SPY +{(r.spy_total_return || 0).toFixed(1)}%</p>
              </div>
              <div>
                <p className={`text-lg font-bold ${(r.sharpe || 0) > (r.spy_sharpe || 0) ? "text-emerald-400" : "text-zinc-300"}`}>
                  {(r.sharpe || 0).toFixed(2)}
                </p>
                <p className="text-[10px] text-zinc-600">Sharpe</p>
                <p className="text-[10px] text-zinc-700">SPY {(r.spy_sharpe || 0).toFixed(2)}</p>
              </div>
              <div>
                <p className="text-lg font-bold text-emerald-400">{(r.max_drawdown || 0).toFixed(1)}%</p>
                <p className="text-[10px] text-zinc-600">Max DD</p>
                <p className="text-[10px] text-zinc-700">SPY {(r.spy_max_drawdown || 0).toFixed(1)}%</p>
              </div>
              <div>
                <p className="text-lg font-bold text-zinc-300">{(r.transaction_costs || 0).toFixed(1)}%</p>
                <p className="text-[10px] text-zinc-600">Costs</p>
              </div>
            </div>

            {/* Entry Timing */}
            {t && (
              <div className="border-t border-zinc-800 pt-3">
                <p className="text-[10px] text-zinc-500 mb-2">If entered now ({t.current_regime}):</p>
                <div className="flex items-center gap-4 text-sm">
                  <div className="text-center">
                    <span className={`font-medium ${t.avg_forward_30d > 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {t.avg_forward_30d > 0 ? "+" : ""}{t.avg_forward_30d}%
                    </span>
                    <p className="text-[10px] text-zinc-600">30d</p>
                  </div>
                  <div className="text-center">
                    <span className={`font-medium ${t.avg_forward_60d > 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {t.avg_forward_60d > 0 ? "+" : ""}{t.avg_forward_60d}%
                    </span>
                    <p className="text-[10px] text-zinc-600">60d</p>
                  </div>
                  <div className="text-center">
                    <span className={`font-medium ${t.avg_forward_90d > 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {t.avg_forward_90d > 0 ? "+" : ""}{t.avg_forward_90d}%
                    </span>
                    <p className="text-[10px] text-zinc-600">90d</p>
                  </div>
                  <div className="text-[10px] text-zinc-600 ml-auto">
                    → bull {(t.pct_to_bull * 100).toFixed(0)}% / bear {(t.pct_to_bear * 100).toFixed(0)}%
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Stress Test — 2/5 width */}
        <Card className="bg-zinc-900 border-zinc-800 lg:col-span-2">
          <CardContent className="pt-5">
            <p className="text-xs text-zinc-500 mb-3">Crisis Protection</p>
            <div className="space-y-2">
              {stress.map((s: any) => (
                <div key={s.name} className="flex items-center justify-between text-xs">
                  <span className="text-zinc-400 w-28 truncate">{s.name}</span>
                  <span className="text-red-400 w-14 text-right">{s.spy_return}%</span>
                  <span className={`w-14 text-right font-medium ${s.strategy_return > s.spy_return ? "text-emerald-400" : "text-red-400"}`}>
                    {s.strategy_return > 0 ? "+" : ""}{s.strategy_return}%
                  </span>
                  <span className="text-[10px] w-8 text-right">{s.protected ? "✓" : "✗"}</span>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-zinc-700 mt-2">Monte Carlo p&lt;0.01 (99.6th percentile)</p>
          </CardContent>
        </Card>
      </div>

      {/* ── Row 3: Positions (compact, only if exists) ── */}
      {positions.length > 0 && (
        <Card className="bg-zinc-900 border-zinc-800">
          <CardContent className="pt-5">
            <p className="text-xs text-zinc-500 mb-2">Open Positions</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {positions.map((p: any, i: number) => (
                <div key={i} className="flex items-center justify-between bg-zinc-800 rounded px-2.5 py-1.5 text-xs">
                  <div className="flex items-center gap-1.5">
                    <span className={`w-1.5 h-1.5 rounded-full ${p.direction === "long" ? "bg-emerald-500" : "bg-red-500"}`} />
                    <span className="font-medium">{p.ticker}</span>
                  </div>
                  <span className={`${(p.return_pct || 0) > 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {(p.return_pct || 0).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Loading() {
  return (
    <div className="space-y-5">
      <div className="h-8 w-32 bg-zinc-800 rounded animate-pulse" />
      <div className="h-32 bg-zinc-900 rounded-xl border border-zinc-800 animate-pulse" />
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <div className="h-48 bg-zinc-900 rounded-xl border border-zinc-800 animate-pulse lg:col-span-3" />
        <div className="h-48 bg-zinc-900 rounded-xl border border-zinc-800 animate-pulse lg:col-span-2" />
      </div>
    </div>
  );
}

export default function StrategyPage() {
  return (
    <Suspense fallback={<Loading />}>
      <StrategyDashboard />
    </Suspense>
  );
}
