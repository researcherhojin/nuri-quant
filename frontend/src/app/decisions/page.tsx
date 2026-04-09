export const dynamic = "force-dynamic";

import { Suspense } from "react";
import Link from "next/link";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";
import { Metric } from "@/components/ui/metric";

// === Types ===
interface Decision {
  id: number;
  date: string;
  ticker: string;
  action: string;
  confidence: number;
  regime: string | null;
  macro_score: number | null;
  vix: number | null;
  fear_greed: number | null;
  agreement_rate: number | null;
  entry_price: number | null;
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  pnl_7d: number | null;
  pnl_30d: number | null;
  pnl_60d: number | null;
  pnl_90d: number | null;
  outcome: string;
  reasoning: string | null;
}

interface DecisionSummary {
  total: number;
  pending: number;
  success: number;
  failure: number;
  neutral: number;
}

interface DecisionResponse {
  decisions: Decision[];
  count: number;
  summary: DecisionSummary;
}

// === Loading ===
function Loading() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="animate-pulse bg-card rounded-xl border border-border h-20" />
        ))}
      </div>
      <div className="animate-pulse bg-card rounded-xl border border-border h-96" />
    </div>
  );
}

// === Metric Cards ===
function SummaryCards({ summary }: { summary: DecisionSummary }) {
  const successRate = summary.total - summary.pending > 0
    ? Math.round((summary.success / (summary.success + summary.failure)) * 100)
    : 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <Metric label="Total" value={summary.total} />
        </CardContent>
      </Card>
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <Metric label="Pending" value={summary.pending} color="default" />
        </CardContent>
      </Card>
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <Metric label="Success" value={summary.success} color="green" />
        </CardContent>
      </Card>
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <Metric label="Failure" value={summary.failure} color="red" />
        </CardContent>
      </Card>
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <Metric
            label="Hit Rate"
            value={successRate > 0 ? `${successRate}%` : "—"}
            color={successRate >= 50 ? "green" : successRate > 0 ? "red" : "default"}
          />
        </CardContent>
      </Card>
    </div>
  );
}

// === PnL Cell ===
function PnlCell({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted-foreground">—</span>;
  const color = value > 0 ? "text-emerald-400" : value < 0 ? "text-red-400" : "text-muted-foreground";
  return <span className={`${color} font-mono text-xs`}>{value > 0 ? "+" : ""}{value.toFixed(1)}%</span>;
}

// === Decision Table ===
function DecisionTable({ decisions }: { decisions: Decision[] }) {
  if (decisions.length === 0) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-sm text-muted-foreground">
            아직 기록된 의사결정 없음. <code className="text-xs bg-muted px-1 rounded">make consensus</code> 실행 필요.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-card border-border overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
              <th className="px-3 py-2">Date</th>
              <th className="px-3 py-2">Ticker</th>
              <th className="px-3 py-2">Action</th>
              <th className="px-3 py-2 text-right">Conf</th>
              <th className="px-3 py-2 hidden md:table-cell">Regime</th>
              <th className="px-3 py-2 text-right hidden md:table-cell">Entry</th>
              <th className="px-3 py-2 text-right hidden lg:table-cell">7D</th>
              <th className="px-3 py-2 text-right">30D</th>
              <th className="px-3 py-2 text-right hidden lg:table-cell">90D</th>
              <th className="px-3 py-2">Outcome</th>
            </tr>
          </thead>
          <tbody>
            {decisions.map((d) => (
              <tr
                key={d.id}
                className="border-b border-border/40 hover:bg-muted/30 transition-colors"
              >
                <td className="px-3 py-2 text-xs text-muted-foreground font-mono">{d.date}</td>
                <td className="px-3 py-2">
                  <Link
                    href={`/ticker/${d.ticker}`}
                    className="text-emerald-400 hover:underline font-medium"
                  >
                    {d.ticker}
                  </Link>
                </td>
                <td className="px-3 py-2"><StatusBadge status={d.action} size="sm" /></td>
                <td className="px-3 py-2 text-right font-mono text-xs">{d.confidence?.toFixed(0)}</td>
                <td className="px-3 py-2 hidden md:table-cell text-xs text-muted-foreground">
                  {d.regime ?? "—"}
                </td>
                <td className="px-3 py-2 text-right hidden md:table-cell font-mono text-xs">
                  {d.entry_price ? `$${d.entry_price.toFixed(2)}` : "—"}
                </td>
                <td className="px-3 py-2 text-right hidden lg:table-cell"><PnlCell value={d.pnl_7d} /></td>
                <td className="px-3 py-2 text-right"><PnlCell value={d.pnl_30d} /></td>
                <td className="px-3 py-2 text-right hidden lg:table-cell"><PnlCell value={d.pnl_90d} /></td>
                <td className="px-3 py-2">
                  <StatusBadge
                    status={d.outcome === "success" ? "BUY" : d.outcome === "failure" ? "SELL" : "HOLD"}
                    size="sm"
                  />
                  <span className="text-[10px] text-muted-foreground ml-1">{d.outcome}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// === Main ===
async function DecisionsSection() {
  let data: DecisionResponse;
  try {
    data = await fetchAPI<DecisionResponse>("/api/decisions?limit=100");
  } catch {
    return <p className="text-red-400 text-sm">API 연결 실패. make api 실행 필요.</p>;
  }

  return (
    <>
      <SummaryCards summary={data.summary} />
      <DecisionTable decisions={data.decisions} />
    </>
  );
}

export default function DecisionsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-bold">Decision Intelligence</h1>
        <p className="text-xs text-muted-foreground">
          의사결정 저널 — 모든 BUY/SELL 판단의 근거와 결과를 추적합니다.
        </p>
      </div>
      <Suspense fallback={<Loading />}>
        <DecisionsSection />
      </Suspense>
    </div>
  );
}
