export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { ERRORS } from "@/lib/strings";
import { Card, CardContent } from "@/components/ui/card";
import { ClientTable } from "@/components/ui/client-table";

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

async function ScorecardSection() {
  const data = await fetchAPI<{ scorecard: Scorecard[]; date: string }>("/api/scorecard");
  // 원문 에러 문자열 노출 금지 (design-review F-002)
  if ("error" in data) return <p className="text-red-400 text-sm">{ERRORS.SCORECARD_FAILED}</p>;
  const sorted = [...data.scorecard].sort((a, b) => b.profit_factor - a.profit_factor);

  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-5">
        <p className="text-xs text-muted-foreground mb-3">Signal Scorecard — {data.date}</p>
        <ClientTable variant="scorecard" data={sorted} />
      </CardContent>
    </Card>
  );
}

interface CrossRow {
  regime: string;
  signal_id: string;
  profit_factor: number;
  [key: string]: unknown;
}

async function CrossSection() {
  const data = await fetchAPI<{ data?: CrossRow[]; error?: string }>("/api/cross-analysis");
  if (data.error || !data.data) return null;
  const regimes = [...new Set(data.data.map((d) => d.regime))].sort();

  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-5">
        <p className="text-xs text-muted-foreground mb-3">Signal × Regime</p>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {regimes.map((regime) => {
            const rows = data.data!.filter((d) => d.regime === regime).sort((a, b) => b.profit_factor - a.profit_factor);
            return (
              <div key={regime}>
                <p className="text-[10px] text-muted-foreground mb-1.5 font-medium uppercase tracking-wider">{regime}</p>
                <div className="space-y-1">
                  {rows.slice(0, 5).map((r) => (
                    <div key={r.signal_id} className="flex justify-between text-xs bg-muted/50 rounded px-2.5 py-1.5">
                      <span className="text-foreground/80">{r.signal_id}</span>
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

function Loading() { return <div className="h-48 bg-card rounded-xl border border-border animate-pulse" />; }

export default function SignalsPage() {
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold">Signals</h1>
      <Suspense fallback={<Loading />}><ScorecardSection /></Suspense>
      <Suspense fallback={<Loading />}><CrossSection /></Suspense>
    </div>
  );
}
