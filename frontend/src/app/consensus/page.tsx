export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";

const agentKeys = ["technical", "fundamental", "macro", "risk", "smart_money", "wallstreet"];
const agentLabels: Record<string,string> = { technical:"Tech", fundamental:"Fund", macro:"Macro", risk:"Risk", smart_money:"Smart", wallstreet:"WallSt" };

function agentCell(verdicts: any[], name: string) {
  const v = verdicts.find((x: any) => x.agent_name === name);
  if (!v) return <span className="text-zinc-700">—</span>;
  const color = v.action === "BUY" ? "text-emerald-400" : v.action === "SELL" ? "text-red-400" : "text-zinc-500";
  return <span className={color} title={v.reasoning}>{v.action[0]}{v.confidence.toFixed(0)}</span>;
}

async function ConsensusSection() {
  const data = await fetchAPI<{ results: any[]; count: number }>("/api/consensus");
  const sorted = [...data.results].sort((a, b) => b.final_confidence - a.final_confidence);

  const cols = [
    { key: "ticker", label: "Ticker", render: (_: any, r: any) => <span className="font-medium">{r.ticker}</span> },
    { key: "final_action", label: "Action", align: "center" as const, render: (v: string) => <StatusBadge status={v} size="md" /> },
    { key: "final_confidence", label: "Conf", align: "right" as const, render: (v: number) => <span className="font-semibold">{v.toFixed(0)}</span> },
    { key: "agreement_rate", label: "Agree", align: "right" as const, render: (v: number) => `${(v * 100).toFixed(0)}%` },
    ...agentKeys.map(name => ({
      key: name, label: agentLabels[name], align: "center" as const, hideOnMobile: true,
      render: (_: any, row: any) => agentCell(row.verdicts, name),
    })),
  ];

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardContent className="pt-5">
        <p className="text-xs text-zinc-500 mb-3">
          6-Agent Consensus — {data.count} tickers × 6 agents = {data.count * 6} verdicts
        </p>
        <DataTable columns={cols} data={sorted} compact />
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
