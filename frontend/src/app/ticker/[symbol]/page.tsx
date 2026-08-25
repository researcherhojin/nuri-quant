export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Metric } from "@/components/ui/metric";
import { PriceChartLazy as PriceChart } from "@/components/ui/price-chart-lazy";
import { TICKER_DETAIL as TD } from "@/lib/strings";
import { formatMoney, isKrwTicker } from "@/lib/format";

interface AgentVerdict {
  agent_name: string;
  action: string;
  confidence: number;
  [key: string]: unknown;
}

interface AnalystRating {
  firm: string;
  date?: string;
  action?: string;
  target_price?: number;
  [key: string]: unknown;
}

interface EarningsRow {
  quarter?: string;
  eps_actual?: number;
  eps_estimate?: number;
  surprise_pct?: number;
  [key: string]: unknown;
}

interface InsiderTrade {
  insider_name?: string;
  transaction_type: string;
  value?: number;
  shares?: number;
  [key: string]: unknown;
}

interface SuperInvestor {
  investor: string;
  portfolio_pct?: number;
  [key: string]: unknown;
}

interface TickerData {
  ticker: string;
  name?: string;
  price?: { close?: number };
  consensus?: {
    final_action?: string;
    final_confidence?: number;
    agreement_rate?: number;
    verdicts?: AgentVerdict[];
    dissent?: string[];
  };
  analyst_ratings?: AnalystRating[];
  earnings?: EarningsRow[];
  insider_trades?: InsiderTrade[];
  superinvestors?: SuperInvestor[];
  fundamentals?: {
    pe_ratio?: number;
    roe?: number;
    revenue_growth?: number;
    debt_to_equity?: number;
    profit_margin?: number;
    beta?: number;
  };
}

interface PriceData {
  prices: Array<{ date: string; open: number; high: number; low: number; close: number; volume: number }>;
}

interface TickerTargets {
  stock_type: string;
  stop_loss?: number;
  stop_loss_pct?: number;
  target_1?: number;
  target_1_pct?: number;
  target_2?: number;
  target_2_pct?: number;
  trailing_stop_pct?: number;
  analyst_target?: number | null;
  analyst_upside_pct?: number | null;
  error?: string;
}

interface ExternalRow {
  source: string;
  data_type: string;
  value: string;
  [key: string]: unknown;
}

interface ExternalData {
  count: number;
  data?: ExternalRow[];
}

export async function TickerDetail({ symbol }: { symbol: string }) {
  const [data, priceData, targets, external] = await Promise.all([
    fetchAPI<TickerData>(`/api/ticker/${symbol}`),
    fetchAPI<PriceData>(`/api/ticker/${symbol}/prices?days=365`),
    fetchAPI<TickerTargets>(`/api/targets/${symbol}`).catch(() => null),
    fetchAPI<ExternalData>(`/api/external/${symbol}`).catch(() => null),
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
  const earningsFormatted = earnings.map((e: EarningsRow) => ({
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

  // #1218 빈 패널 접기: 데이터 없는 카드는 렌더하지 않고 (KR 티커에서 빈 패널
  // 3개가 ~200px 씩 차지하던 감사 결함) 부재 목록을 한 줄로 병합한다.
  const missingPanels = ([
    ratings.length === 0 ? TD.PANEL_RATINGS : null,
    earningsFormatted.length === 0 ? TD.PANEL_EARNINGS : null,
    insiders.length === 0 ? TD.PANEL_INSIDERS : null,
    !fund ? TD.PANEL_FUNDAMENTALS : null,
    supers.length === 0 ? TD.PANEL_SMART_MONEY : null,
    !targets || targets.error ? TD.PANEL_TARGETS : null,
    !external || external.count === 0 ? TD.PANEL_EXTERNAL : null,
  ] as Array<string | null>).filter((x): x is string => x !== null);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-4 flex-wrap">
        <h1 className="text-3xl font-bold">{data.name || data.ticker}</h1>
        {data.name && <span className="text-lg text-muted-foreground">{data.ticker}</span>}
        {data.price?.close && (
          <span className="text-2xl text-foreground/80">{formatMoney(Number(data.price.close), { ticker: data.ticker })}</span>
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
              {verdicts.map((v: AgentVerdict) => (
                <div key={v.agent_name} className="flex items-center justify-between">
                  <span className="text-sm capitalize">{v.agent_name}</span>
                  <div className="flex items-center gap-2">
                    <StatusBadge status={v.action} size="sm" />
                    <span className="text-xs text-muted-foreground">{v.confidence.toFixed(0)}</span>
                  </div>
                </div>
              ))}
            </div>
            {(consensus.dissent?.length ?? 0) > 0 && (
              <div className="mt-3 pt-3 border-t border-border">
                <p className="text-[10px] text-muted-foreground/70 mb-1">Dissent:</p>
                {consensus.dissent!.slice(0, 3).map((d: string, i: number) => (
                  <p key={i} className="text-[10px] text-muted-foreground/70 leading-tight">{d}</p>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Analyst Ratings — 빈 카드 렌더 금지 (#1218) */}
        {ratings.length > 0 && (
        <Card className="bg-card border-border">
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground mb-3">{TD.PANEL_RATINGS} ({ratings.length})</p>
            <div className="space-y-1.5 max-h-64 overflow-y-auto">
                {ratings.map((r: AnalystRating, i: number) => (
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
                      {/* #1218: 통화는 formatMoney 단일 판정 지점 — KR 레이팅 $300000 표기 결함 */}
                      {r.target_price != null && <span className="text-muted-foreground">{formatMoney(r.target_price, { ticker: data.ticker })}</span>}
                    </div>
                  </div>
                ))}
            </div>
          </CardContent>
        </Card>
        )}

        {/* Earnings Surprise — 빈 카드 렌더 금지 (#1218) */}
        {earningsFormatted.length > 0 && (
        <Card className="bg-card border-border">
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground mb-3">{TD.PANEL_EARNINGS} ({earnings.length}Q)</p>
            <DataTable columns={earningsCols} data={earningsFormatted} compact />
          </CardContent>
        </Card>
        )}

        {/* Insider Trades — 빈 카드 렌더 금지 (#1218) */}
        {insiders.length > 0 && (
        <Card className="bg-card border-border">
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground mb-3">{TD.PANEL_INSIDERS} ({insiders.length})</p>
            <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {insiders.map((ins: InsiderTrade, i: number) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1.5">
                      <StatusBadge status={ins.transaction_type === "sale" ? "SELL" : "BUY"} size="sm" />
                      <span className="text-muted-foreground">{ins.insider_name?.split(" ").slice(0, 2).join(" ")}</span>
                    </div>
                    <span className="text-muted-foreground">
                      {/* #1218: value·shares 모두 부재 시 "undefined sh" 렌더 결함 → — */}
                      {ins.value ? `$${(ins.value / 1000000).toFixed(1)}M` : ins.shares != null ? `${ins.shares.toLocaleString()} sh` : "—"}
                    </span>
                  </div>
                ))}
            </div>
          </CardContent>
        </Card>
        )}

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
                {supers.map((s: SuperInvestor, i: number) => (
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
                <div className="flex justify-between"><span className="text-muted-foreground">{TD.STOP_LOSS}</span><span className="text-red-400">{formatMoney(targets.stop_loss, { ticker: data.ticker })} ({targets.stop_loss_pct}%)</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">{TD.TARGET_1}</span><span className="text-emerald-400">{formatMoney(targets.target_1, { ticker: data.ticker })} (+{targets.target_1_pct}%)</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">{TD.TARGET_2}</span><span className="text-emerald-400">{formatMoney(targets.target_2, { ticker: data.ticker })} (+{targets.target_2_pct}%)</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">{TD.TRAILING}</span><span className="text-muted-foreground">{targets.trailing_stop_pct}% from high</span></div>
                {targets.analyst_target && (
                  <div className="flex justify-between"><span className="text-muted-foreground">{TD.ANALYST}</span><span className="text-blue-400">{formatMoney(targets.analyst_target, { ticker: data.ticker })} ({(targets.analyst_upside_pct ?? 0) > 0 ? "+" : ""}{targets.analyst_upside_pct}%)</span></div>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* 외부 데이터 (#1218: 라벨 strings 경유) */}
        {external && external.count > 0 && (
          <Card className="bg-card border-border">
            <CardContent className="pt-5">
              <p className="text-xs text-muted-foreground mb-3">External Data ({external.count})</p>
              <div className="space-y-1.5 text-xs">
                {external.data?.slice(0, 8).map((d: ExternalRow, i: number) => (
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

      {/* #1218: 부재 패널 한 줄 병합 — 빈 상태 1줄 규칙 */}
      {missingPanels.length > 0 && (
        <p className="text-[11px] text-muted-foreground/70" data-testid="ticker-missing-panels">
          {TD.MISSING_PREFIX} {missingPanels.join(" · ")}{" "}
          {isKrwTicker(data.ticker) && <span className="text-muted-foreground/50">{TD.MISSING_KR_HINT}</span>}
        </p>
      )}
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
