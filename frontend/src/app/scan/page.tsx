export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";

interface ScanResult {
  ticker: string; price: number; change_1d: number; change_5d: number;
  volume_ratio: number; rsi: number; signal: string; score: number;
}

interface SwingEntry {
  ticker: string; price: number; scan_signal: string; scan_score: number;
  agent_action: string; agent_confidence: number; approved: boolean; reason: string;
}

function pctColor(v: number) { return v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-zinc-400"; }
function rsiColor(v: number) { return v > 70 ? "text-red-400" : v < 30 ? "text-emerald-400" : "text-zinc-400"; }

const scanCols = [
  { key: "ticker", label: "Ticker", render: (v: string) => <span className="font-medium">{v}</span> },
  { key: "price", label: "Price", align: "right" as const, render: (v: number) => `$${v.toLocaleString()}` },
  { key: "change_1d", label: "1D", align: "right" as const, render: (v: number) => <span className={pctColor(v)}>{v > 0 ? "+" : ""}{v.toFixed(1)}%</span> },
  { key: "change_5d", label: "5D", align: "right" as const, render: (v: number) => <span className={pctColor(v)}>{v > 0 ? "+" : ""}{v.toFixed(1)}%</span> },
  { key: "volume_ratio", label: "Vol", align: "right" as const, render: (v: number) => `${v.toFixed(1)}x` },
  { key: "rsi", label: "RSI", align: "right" as const, render: (v: number) => <span className={rsiColor(v)}>{v.toFixed(0)}</span> },
  { key: "signal", label: "Signal", align: "center" as const, render: (v: string) => <StatusBadge status={v} /> },
  { key: "score", label: "Score", align: "right" as const, render: (v: number) => <span className="font-semibold">{v.toFixed(0)}</span> },
];

const swingCols = [
  { key: "ticker", label: "Ticker", render: (v: string) => <span className="font-medium">{v}</span> },
  { key: "price", label: "Price", align: "right" as const, render: (v: number) => `$${v?.toLocaleString()}` },
  { key: "scan_signal", label: "Signal", align: "center" as const, render: (v: string) => <StatusBadge status={v} /> },
  { key: "scan_score", label: "Score", align: "right" as const },
  { key: "agent_action", label: "Agent", align: "center" as const, render: (v: string) => <StatusBadge status={v} size="md" /> },
  { key: "agent_confidence", label: "Conf", align: "right" as const },
];

async function ScanSection() {
  const data = await fetchAPI<{ results: ScanResult[]; count: number }>("/api/scan?market=us&top=15");
  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardContent className="pt-5">
        <p className="text-xs text-zinc-500 mb-3">Market Scanner — {data.count} signals</p>
        <DataTable columns={scanCols} data={data.results} />
      </CardContent>
    </Card>
  );
}

async function SwingSection() {
  const data = await fetchAPI<{ entries: SwingEntry[]; approved: number; rejected: number }>("/api/swing/entries");
  const approved = data.entries.filter((e) => e.approved);
  const rejected = data.entries.filter((e) => !e.approved);

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardContent className="pt-5">
        <p className="text-xs text-zinc-500 mb-3">
          Swing Entries — <span className="text-emerald-400">{data.approved} approved</span>, {data.rejected} rejected
        </p>
        {approved.length > 0 ? (
          <DataTable columns={swingCols} data={approved} />
        ) : (
          <p className="text-xs text-zinc-600 py-3 text-center">No entries passed agent consensus (BUY + conf ≥ 50)</p>
        )}
        {rejected.length > 0 && (
          <details className="mt-3">
            <summary className="text-[10px] text-zinc-600 cursor-pointer hover:text-zinc-400">
              Rejected ({rejected.length})
            </summary>
            <div className="mt-1.5 space-y-0.5 text-[10px] text-zinc-600 pl-2">
              {rejected.map((e, i) => (
                <p key={i}>{e.ticker}: {e.reason}</p>
              ))}
            </div>
          </details>
        )}
      </CardContent>
    </Card>
  );
}

function Loading() {
  return <div className="h-64 bg-zinc-900 rounded-xl border border-zinc-800 animate-pulse" />;
}

export default function ScanPage() {
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold">Market Scanner</h1>
      <Suspense fallback={<Loading />}><ScanSection /></Suspense>
      <Suspense fallback={<Loading />}><SwingSection /></Suspense>
    </div>
  );
}
