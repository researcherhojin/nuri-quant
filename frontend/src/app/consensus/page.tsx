export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { ClientTable } from "@/components/ui/client-table";
import { StatusBadge } from "@/components/ui/status-badge";

async function ConsensusSection() {
  const data = await fetchAPI<{ results: any[]; count: number }>("/api/consensus");
  const sorted = [...data.results].sort((a, b) => b.final_confidence - a.final_confidence);

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardContent className="pt-5">
        <p className="text-xs text-zinc-500 mb-3">
          6-Agent Consensus — {data.count} tickers × 6 agents = {data.count * 6} verdicts
        </p>
        <ClientTable variant="consensus" data={sorted} compact />
      </CardContent>
    </Card>
  );
}

async function DissentSection() {
  const data = await fetchAPI<{ results: any[] }>("/api/consensus");
  const withDissent = data.results.filter((r) => r.dissent.length > 0).slice(0, 6);
  if (!withDissent.length) return null;

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardContent className="pt-5">
        <p className="text-xs text-zinc-500 mb-3">Dissent — Agent Disagreements</p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {withDissent.map((r) => (
            <div key={r.ticker} className="bg-zinc-800/40 rounded-lg p-2.5">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-medium text-sm">{r.ticker}</span>
                <StatusBadge status={r.final_action} />
                <span className="text-[10px] text-zinc-600">{(r.agreement_rate * 100).toFixed(0)}% agree</span>
              </div>
              {r.dissent.slice(0, 2).map((d: string, i: number) => (
                <p key={i} className="text-[10px] text-zinc-500 leading-tight">{d.slice(0, 80)}</p>
              ))}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function Loading() { return <div className="h-48 bg-zinc-900 rounded-xl border border-zinc-800 animate-pulse" />; }

export default function ConsensusPage() {
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold">Agents</h1>
      <Suspense fallback={<Loading />}><ConsensusSection /></Suspense>
      <Suspense fallback={<Loading />}><DissentSection /></Suspense>
    </div>
  );
}
