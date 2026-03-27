export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Metric } from "@/components/ui/metric";
import { PriceChart } from "@/components/ui/price-chart";

async function TickerDetail({ symbol }: { symbol: string }) {
  const [data, priceData] = await Promise.all([
    fetchAPI<any>(`/api/ticker/${symbol}`),
    fetchAPI<any>(`/api/ticker/${symbol}/prices?days=365`),
  ]);

  const consensus = data.consensus || {};
  const verdicts = consensus.verdicts || [];
  const ratings = data.analyst_ratings || [];
  const earnings = data.earnings || [];
  const insiders = data.insider_trades || [];
  const supers = data.superinvestors || [];
  const fund = data.fundamentals;

  const earningsCols = [
    { key: "quarter", label: "Quarter", render: (v: string) => v?.slice(0, 7) },
    { key: "eps_actual", label: "Actual", align: "right" as const, render: (v: number) => v?.toFixed(2) },
    { key: "eps_estimate", label: "Est", align: "right" as const, render: (v: number) => <span className="text-zinc-500">{v?.toFixed(2)}</span> },
    {
      key: "surprise_pct", label: "Surprise", align: "right" as const,
      render: (v: number) => (
        <span className={`font-medium ${(v || 0) > 0 ? "text-emerald-400" : "text-red-400"}`}>
          {v ? `${(v * 100).toFixed(0)}%` : "—"}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-4 flex-wrap">
        <h1 className="text-3xl font-bold">{data.ticker}</h1>
        {data.price?.close && (
          <span className="text-2xl text-zinc-300">${Number(data.price.close).toLocaleString()}</span>
        )}
        {consensus.final_action && (
          <StatusBadge status={consensus.final_action} size="md" />
        )}
        {consensus.final_confidence != null && (
          <span className="text-sm text-zinc-400 font-semibold">{consensus.final_confidence.toFixed(0)}</span>
        )}
        {consensus.agreement_rate != null && (
          <span className="text-xs text-zinc-600">{(consensus.agreement_rate * 100).toFixed(0)}% agree</span>
        )}
      </div>

      {/* Price Chart */}
      {priceData.prices?.length > 0 && (
        <Card className="bg-zinc-900 border-zinc-800">
          <CardContent className="pt-5">
            <p className="text-xs text-zinc-500 mb-3">Price History</p>
            <PriceChart data={priceData.prices} ticker={data.ticker} />
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Agent Verdicts */}
        <Card className="bg-zinc-900 border-zinc-800">
          <CardContent className="pt-5">
            <p className="text-xs text-zinc-500 mb-3">6-Agent Analysis</p>
            <div className="space-y-2">
              {verdicts.map((v: any) => (
                <div key={v.agent_name} className="flex items-center justify-between">
                  <span className="text-sm capitalize">{v.agent_name}</span>
                  <div className="flex items-center gap-2">
                    <StatusBadge status={v.action} size="sm" />
                    <span className="text-xs text-zinc-500">{v.confidence.toFixed(0)}</span>
                  </div>
                </div>
              ))}
            </div>
            {consensus.dissent?.length > 0 && (
              <div className="mt-3 pt-3 border-t border-zinc-800">
                <p className="text-[10px] text-zinc-600 mb-1">Dissent:</p>
                {consensus.dissent.slice(0, 3).map((d: string, i: number) => (
                  <p key={i} className="text-[10px] text-zinc-600 leading-tight">{d}</p>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Analyst Ratings */}
        <Card className="bg-zinc-900 border-zinc-800">
          <CardContent className="pt-5">
            <p className="text-xs text-zinc-500 mb-3">Analyst Ratings ({ratings.length})</p>
            {ratings.length > 0 ? (
              <div className="space-y-1.5 max-h-64 overflow-y-auto">
                {ratings.map((r: any, i: number) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <div>
                      <span className="text-zinc-300">{r.firm}</span>
                      <span className="text-zinc-600 ml-1">{r.date?.slice(5)}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <StatusBadge
                        status={
                          r.action === "up" || r.action === "upgrade" ? "BUY" :
                          r.action === "down" || r.action === "downgrade" ? "SELL" : "HOLD"
                        }
                        size="sm"
                      />
                      {r.target_price && <span className="text-zinc-500">${r.target_price}</span>}
                    </div>
                  </div>
                ))}
              </div>
            ) : <p className="text-xs text-zinc-600 text-center py-3">No rating data</p>}
          </CardContent>
        </Card>

        {/* Earnings Surprise */}
        <Card className="bg-zinc-900 border-zinc-800">
          <CardContent className="pt-5">
            <p className="text-xs text-zinc-500 mb-3">Earnings ({earnings.length}Q)</p>
            {earnings.length > 0 ? (
              <DataTable columns={earningsCols} data={earnings} compact />
            ) : <p className="text-xs text-zinc-600 text-center py-3">No earnings data</p>}
          </CardContent>
        </Card>

        {/* Insider Trades */}
        <Card className="bg-zinc-900 border-zinc-800">
          <CardContent className="pt-5">
            <p className="text-xs text-zinc-500 mb-3">Insider Activity ({insiders.length})</p>
            {insiders.length > 0 ? (
              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {insiders.map((ins: any, i: number) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1.5">
                      <StatusBadge status={ins.transaction_type === "sale" ? "SELL" : "BUY"} size="sm" />
                      <span className="text-zinc-400">{ins.insider_name?.split(" ").slice(0, 2).join(" ")}</span>
                    </div>
                    <span className="text-zinc-500">
                      {ins.value ? `$${(ins.value / 1000000).toFixed(1)}M` : `${ins.shares?.toLocaleString()} sh`}
                    </span>
                  </div>
                ))}
              </div>
            ) : <p className="text-xs text-zinc-600 text-center py-3">No insider data</p>}
          </CardContent>
        </Card>

        {/* Fundamentals */}
        {fund && (
          <Card className="bg-zinc-900 border-zinc-800">
            <CardContent className="pt-5">
              <p className="text-xs text-zinc-500 mb-3">Fundamentals</p>
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
          <Card className="bg-zinc-900 border-zinc-800">
            <CardContent className="pt-5">
              <p className="text-xs text-zinc-500 mb-3">Smart Money ({supers.length})</p>
              <div className="space-y-1.5">
                {supers.map((s: any, i: number) => (
                  <div key={i} className="flex justify-between text-xs bg-zinc-800/40 rounded px-2.5 py-1.5">
                    <span className="text-zinc-300">{s.investor}</span>
                    <span className="text-zinc-500 font-medium">{s.portfolio_pct?.toFixed(1)}%</span>
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
      <div className="h-10 bg-zinc-900 rounded w-48 animate-pulse" />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="h-48 bg-zinc-900 rounded-xl border border-zinc-800 animate-pulse" />
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
