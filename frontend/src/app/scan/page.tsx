export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { ClientTable } from "@/components/ui/client-table";

interface ScanResult {
  ticker: string; price: number; change_1d: number; change_5d: number;
  volume_ratio: number; rsi: number; signal: string; score: number;
}

interface SwingEntry {
  ticker: string; price: number; scan_signal: string; scan_score: number;
  agent_action: string; agent_confidence: number; approved: boolean; reason: string;
}


async function ScanSection() {
  const data = await fetchAPI<{ results: ScanResult[]; count: number }>("/api/scan?market=us&top=15");
  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-5">
        <p className="text-xs text-muted-foreground mb-3">Market Scanner — {data.count} signals</p>
        <ClientTable variant="scan" data={data.results} />
      </CardContent>
    </Card>
  );
}

async function SwingSection() {
  const data = await fetchAPI<{ entries: SwingEntry[]; approved: number; rejected: number }>("/api/swing/entries");
  const approved = data.entries.filter((e) => e.approved);
  const rejected = data.entries.filter((e) => !e.approved);

  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-5">
        <p className="text-xs text-muted-foreground mb-3">
          Swing Entries — <span className="text-emerald-400">{data.approved} approved</span>, {data.rejected} rejected
        </p>
        {approved.length > 0 ? (
          <ClientTable variant="swing" data={approved} />
        ) : (
          <p className="text-xs text-muted-foreground/70 py-3 text-center">No entries passed agent consensus (BUY + conf ≥ 50)</p>
        )}
        {rejected.length > 0 && (
          <details className="mt-3">
            <summary className="text-[10px] text-muted-foreground/70 cursor-pointer hover:text-muted-foreground">
              Rejected ({rejected.length})
            </summary>
            <div className="mt-1.5 space-y-0.5 text-[10px] text-muted-foreground/70 pl-2">
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
  return <div className="h-64 bg-card rounded-xl border border-border animate-pulse" />;
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
