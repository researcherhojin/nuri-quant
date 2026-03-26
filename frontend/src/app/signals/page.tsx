export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";

interface Scorecard {
  signal_id: string; total_trades: number; win_rate: number; avg_return: number;
  profit_factor: number; max_return: number; max_loss: number;
}

function pf(v: number) {
  if (v >= 99) return "∞";
  return v.toFixed(1);
}

function pfColor(v: number) {
  return v >= 1.5 ? "text-emerald-400" : v >= 1.0 ? "text-amber-400" : "text-red-400";
}

const scorecardCols = [
  { key: "signal_id", label: "Signal", render: (v: string) => <span className="font-medium">{v}</span> },
  { key: "total_trades", label: "Trades", align: "right" as const },
  { key: "win_rate", label: "Win Rate", align: "right" as const, render: (v: number) => <span className={v > 0.5 ? "text-emerald-400" : "text-red-400"}>{(v * 100).toFixed(0)}%</span> },
  { key: "avg_return", label: "Avg Ret", align: "right" as const, render: (v: number) => <span className={v > 0 ? "text-emerald-400" : "text-red-400"}>{v > 0 ? "+" : ""}{v.toFixed(1)}%</span> },
  { key: "profit_factor", label: "PF", align: "right" as const, render: (v: number) => <span className={`font-semibold ${pfColor(v)}`}>{pf(v)}</span> },
  { key: "max_return", label: "Best", align: "right" as const, render: (v: number) => <span className="text-emerald-400">+{v.toFixed(1)}%</span> },
  { key: "max_loss", label: "Worst", align: "right" as const, render: (v: number) => <span className="text-red-400">{v.toFixed(1)}%</span> },
];

async function ScorecardSection() {
  const data = await fetchAPI<{ scorecard: Scorecard[]; date: string }>("/api/scorecard");
  if ("error" in data) return <p className="text-red-400 text-sm">{String((data as any).error)}</p>;
  const sorted = [...data.scorecard].sort((a, b) => b.profit_factor - a.profit_factor);

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardContent className="pt-5">
        <p className="text-xs text-zinc-500 mb-3">Signal Scorecard — {data.date}</p>
        <DataTable columns={scorecardCols} data={sorted} />
      </CardContent>
    </Card>
  );
}

async function CrossSection() {
  const data = await fetchAPI<{ data?: any[]; error?: string }>("/api/cross-analysis");
  if (data.error || !data.data) return null;
  const regimes = [...new Set(data.data.map((d) => d.regime))].sort();

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardContent className="pt-5">
        <p className="text-xs text-zinc-500 mb-3">Signal × Regime</p>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {regimes.map((regime) => {
            const rows = data.data!.filter((d) => d.regime === regime).sort((a, b) => b.profit_factor - a.profit_factor);
            return (
              <div key={regime}>
                <p className="text-[10px] text-zinc-500 mb-1.5 font-medium uppercase tracking-wider">{regime}</p>
                <div className="space-y-1">
                  {rows.slice(0, 5).map((r) => (
                    <div key={r.signal_id} className="flex justify-between text-xs bg-zinc-800/40 rounded px-2.5 py-1.5">
                      <span className="text-zinc-300">{r.signal_id}</span>
                      <span className={pfColor(r.profit_factor)}>PF {pf(r.profit_factor)}</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function Loading() { return <div className="h-48 bg-zinc-900 rounded-xl border border-zinc-800 animate-pulse" />; }

export default function SignalsPage() {
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold">Signals</h1>
      <Suspense fallback={<Loading />}><ScorecardSection /></Suspense>
      <Suspense fallback={<Loading />}><CrossSection /></Suspense>
    </div>
  );
}
