export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Metric } from "@/components/ui/metric";
import { PriceChartLazy as PriceChart } from "@/components/ui/price-chart-lazy";
import { TICKER_DETAIL as TD } from "@/lib/strings";

async function TickerDetail({ symbol }: { symbol: string }) {
  const [data, priceData, targets, external] = await Promise.all([
    fetchAPI<any>(`/api/ticker/${symbol}`),
    fetchAPI<any>(`/api/ticker/${symbol}/prices?days=365`),
    fetchAPI<any>(`/api/targets/${symbol}`).catch(() => null),
    fetchAPI<any>(`/api/external/${symbol}`).catch(() => null),
  ]);

  const consensus = data.consensus || {};
  const verdicts = consensus.verdicts || [];
  const ratings = data.analyst_ratings || [];
  const earnings = data.earnings || [];
  const insiders = data.insider_trades || [];
  const supers = data.superinvestors || [];
  const fund = data.fundamentals;

  // Pre-format earnings data (no render functions — Next.js 16 forbids
  // passing functions from Server to Client Components)
  const earningsFormatted = earnings.map((e: any) => ({
    quarter: e.quarter?.slice(0, 7) ?? "—",
    eps_actual: e.eps_actual?.toFixed(2) ?? "—",
    eps_estimate: e.eps_estimate?.toFixed(2) ?? "—",
    surprise_pct: e.surprise_pct ? `${(e.surprise_pct * 100).toFixed(0)}%` : "—",
    _surprise_positive: (e.surprise_pct || 0) > 0,
  }));
  const earningsCols = [
    { key: "quarter", label: "Quarter" },
    { key: "eps_actual", label: "Actual", align: "right" as const },
    { key: "eps_estimate", label: "Est", align: "right" as const },
    { key: "surprise_pct", label: "Surprise", align: "right" as const },
  ];

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-4 flex-wrap">
        <h1 className="text-3xl font-bold">{data.name || data.ticker}</h1>
        {data.name && <span className="text-lg text-muted-foreground">{data.ticker}</span>}
        {data.price?.close && (
          <span className="text-2xl text-foreground/80">${Number(data.price.close).toLocaleString()}</span>
        )}
        {consensus.final_action && (
          <StatusBadge status={consensus.final_action} size="md" />
        )}
        {consensus.final_confidence != null && (
          <span className="text-sm text-muted-foreground font-semibold">{consensus.final_confidence.toFixed(0)}</span>
        )}
        {consensus.agreement_rate != null && (
          <span className="text-xs text-muted-foreground/70">{(consensus.agreement_rate * 100).toFixed(0)}% agree</span>
        )}
      </div>

      {/* Price Chart */}
      {priceData.prices?.length > 0 && (
        <Card className="bg-card border-border">
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground mb-3">Price History</p>
            <PriceChart data={priceData.prices} ticker={data.ticker} />
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Agent Verdicts */}
        <Card className="bg-card border-border">
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground mb-3">10-Agent Analysis</p>
            <div className="space-y-2">
              {verdicts.map((v: any) => (
                <div key={v.agent_name} className="flex items-center justify-between">
                  <span className="text-sm capitalize">{v.agent_name}</span>
                  <div className="flex items-center gap-2">
                    <StatusBadge status={v.action} size="sm" />
                    <span className="text-xs text-muted-foreground">{v.confidence.toFixed(0)}</span>
                  </div>
                </div>
              ))}
            </div>
            {consensus.dissent?.length > 0 && (
              <div className="mt-3 pt-3 border-t border-border">
                <p className="text-[10px] text-muted-foreground/70 mb-1">Dissent:</p>
                {consensus.dissent.slice(0, 3).map((d: string, i: number) => (
                  <p key={i} className="text-[10px] text-muted-foreground/70 leading-tight">{d}</p>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Analyst Ratings */}
        <Card className="bg-card border-border">
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground mb-3">Analyst Ratings ({ratings.length})</p>
            {ratings.length > 0 ? (
              <div className="space-y-1.5 max-h-64 overflow-y-auto">
                {ratings.map((r: any, i: number) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <div>
                      <span className="text-foreground/80">{r.firm}</span>
                      <span className="text-muted-foreground/70 ml-1">{r.date?.slice(5)}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <StatusBadge
                        status={
                          r.action === "up" || r.action === "upgrade" ? "BUY" :
                          r.action === "down" || r.action === "downgrade" ? "SELL" : "HOLD"
                        }
                        size="sm"
                      />
                      {r.target_price && <span className="text-muted-foreground">${r.target_price}</span>}
                    </div>
                  </div>
                ))}
              </div>
            ) : <p className="text-xs text-muted-foreground/70 text-center py-3">No rating data</p>}
          </CardContent>
        </Card>

        {/* Earnings Surprise */}
        <Card className="bg-card border-border">
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground mb-3">Earnings ({earnings.length}Q)</p>
            {earningsFormatted.length > 0 ? (
              <DataTable columns={earningsCols} data={earningsFormatted} compact />
            ) : <p className="text-xs text-muted-foreground/70 text-center py-3">No earnings data</p>}
          </CardContent>
        </Card>

        {/* Insider Trades */}
        <Card className="bg-card border-border">
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground mb-3">Insider Activity ({insiders.length})</p>
            {insiders.length > 0 ? (
              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {insiders.map((ins: any, i: number) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1.5">
                      <StatusBadge status={ins.transaction_type === "sale" ? "SELL" : "BUY"} size="sm" />
                      <span className="text-muted-foreground">{ins.insider_name?.split(" ").slice(0, 2).join(" ")}</span>
                    </div>
                    <span className="text-muted-foreground">
                      {ins.value ? `$${(ins.value / 1000000).toFixed(1)}M` : `${ins.shares?.toLocaleString()} sh`}
                    </span>
                  </div>
                ))}
              </div>
            ) : <p className="text-xs text-muted-foreground/70 text-center py-3">No insider data</p>}
          </CardContent>
        </Card>

        {/* Fundamentals */}
        {fund && (
          <Card className="bg-card border-border">
            <CardContent className="pt-5">
              <p className="text-xs text-muted-foreground mb-3">Fundamentals</p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                {fund.pe_ratio && <Metric label="PE" value={fund.pe_ratio.toFixed(1)} />}
                {fund.roe && <Metric label="ROE" value={`${(fund.roe * 100).toFixed(1)}%`} color={fund.roe > 0.15 ? "green" : "default"} />}
                {fund.revenue_growth && (
                  <Metric label="Rev Growth" value={`${(fund.revenue_growth * 100).toFixed(0)}%`} color={fund.revenue_growth > 0 ? "green" : "red"} />
                )}
                {fund.debt_to_equity && <Metric label="D/E" value={`${fund.debt_to_equity.toFixed(1)}x`} />}
                {fund.profit_margin && (
                  <Metric label="Margin" value={`${(fund.profit_margin * 100).toFixed(1)}%`} color={fund.profit_margin > 0.1 ? "green" : "default"} />
                )}
                {fund.beta && <Metric label="Beta" value={fund.beta.toFixed(2)} />}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Smart Money */}
        {supers.length > 0 && (
          <Card className="bg-card border-border">
            <CardContent className="pt-5">
              <p className="text-xs text-muted-foreground mb-3">Smart Money ({supers.length})</p>
              <div className="space-y-1.5">
                {supers.map((s: any, i: number) => (
                  <div key={i} className="flex justify-between text-xs bg-muted/50 rounded px-2.5 py-1.5">
                    <span className="text-foreground/80">{s.investor}</span>
                    <span className="text-muted-foreground font-medium">{s.portfolio_pct?.toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
        {/* 가격 타겟 */}
        {targets && !targets.error && (
          <Card className="bg-card border-border">
            <CardContent className="pt-5">
              <p className="text-xs text-muted-foreground mb-3">Price Targets ({targets.stock_type})</p>
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">{TD.STOP_LOSS}</span><span className="text-red-400">${targets.stop_loss?.toFixed(2)} ({targets.stop_loss_pct}%)</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">{TD.TARGET_1}</span><span className="text-emerald-400">${targets.target_1?.toFixed(2)} (+{targets.target_1_pct}%)</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">{TD.TARGET_2}</span><span className="text-emerald-400">${targets.target_2?.toFixed(2)} (+{targets.target_2_pct}%)</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">{TD.TRAILING}</span><span className="text-muted-foreground">{targets.trailing_stop_pct}% from high</span></div>
                {targets.analyst_target && (
                  <div className="flex justify-between"><span className="text-muted-foreground">{TD.ANALYST}</span><span className="text-blue-400">${targets.analyst_target?.toFixed(2)} ({targets.analyst_upside_pct > 0 ? "+" : ""}{targets.analyst_upside_pct}%)</span></div>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* 외부 데이터 */}
        {external && external.count > 0 && (
          <Card className="bg-card border-border">
            <CardContent className="pt-5">
              <p className="text-xs text-muted-foreground mb-3">External Data ({external.count})</p>
              <div className="space-y-1.5 text-xs">
                {external.data?.slice(0, 8).map((d: any, i: number) => (
                  <div key={i} className="flex justify-between bg-muted/50 rounded px-2.5 py-1">
                    <span className="text-muted-foreground">{d.source}/{d.data_type}</span>
                    <span className="text-foreground/80">{d.value}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

function Loading() {
  return (
    <div className="space-y-5">
      <div className="h-10 bg-card rounded w-48 animate-pulse" />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="h-48 bg-card rounded-xl border border-border animate-pulse" />
        ))}
      </div>
    </div>
  );
}

export default async function TickerPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  return (
    <Suspense fallback={<Loading />}>
      <TickerDetail symbol={symbol} />
    </Suspense>
  );
}
