export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { ConsensusTable } from "@/components/ui/consensus-table";
import { StatusBadge } from "@/components/ui/status-badge";

function VixBanner({ vix }: { vix: number | null }) {
  if (!vix || vix < 25) return null;

  const isBlocked = vix >= 30;
  return (
    <div className={`rounded-lg px-4 py-2.5 text-sm flex items-center gap-2 ${
      isBlocked ? "bg-red-500/10 border border-red-500/20 text-red-400"
                : "bg-amber-500/10 border border-amber-500/20 text-amber-400"
    }`}>
      <span className="font-medium">
        {isBlocked ? `VIX ${vix.toFixed(1)} > 30 — 신규 매수 차단` : `VIX ${vix.toFixed(1)} (25-30) — 반포지션 적용 중`}
      </span>
      <span className="text-xs opacity-70">
        {isBlocked ? "win rate 붕괴 구간, 모든 BUY 차단" : "BUY 종목 confidence ×0.5, 수량 절반만 진입"}
      </span>
    </div>
  );
}

async function ConsensusSection() {
  const data = await fetchAPI<{ regime: any; results: any[]; count: number }>("/api/consensus");
  const sorted = [...data.results].sort((a, b) => b.final_confidence - a.final_confidence);

  return (
    <>
      <VixBanner vix={data.regime?.vix ?? null} />
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-xs text-muted-foreground mb-3">
            10-Agent Consensus — {data.count} tickers × 10 agents = {data.count * 10} verdicts
          </p>
          <ConsensusTable data={sorted} />
        </CardContent>
      </Card>
    </>
  );
}

async function DissentSection() {
  const data = await fetchAPI<{ results: any[] }>("/api/consensus");
  const withDissent = data.results.filter((r) => r.dissent.length > 0).slice(0, 6);
  if (!withDissent.length) return null;

  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-5">
        <p className="text-xs text-muted-foreground mb-3">Dissent — Agent Disagreements</p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {withDissent.map((r) => (
            <div key={r.ticker} className="bg-muted/50 rounded-lg p-2.5">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-medium text-sm">{r.ticker}</span>
                <StatusBadge status={r.final_action} />
                <span className="text-[10px] text-muted-foreground/70">{(r.agreement_rate * 100).toFixed(0)}% agree</span>
              </div>
              {r.dissent.slice(0, 2).map((d: string, i: number) => (
                <p key={i} className="text-[10px] text-muted-foreground leading-tight">{d.slice(0, 80)}</p>
              ))}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function Loading() { return <div className="h-48 bg-card rounded-xl border border-border animate-pulse" />; }

export default function ConsensusPage() {
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold">Agents</h1>
      <Suspense fallback={<Loading />}><ConsensusSection /></Suspense>
      <Suspense fallback={<Loading />}><DissentSection /></Suspense>
    </div>
  );
}
