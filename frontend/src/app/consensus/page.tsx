export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { ConsensusTable, type ConsensusRow } from "@/components/ui/consensus-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { COMMON, CONSENSUS as CS, NAV } from "@/lib/strings";

export function VixBanner({ vix }: { vix: number | null }) {
  if (!vix || vix < 25) return null;

  const isBlocked = vix >= 30;
  return (
    <div className={`rounded-lg px-4 py-2.5 text-sm flex items-center gap-2 ${
      isBlocked ? "bg-red-500/10 border border-red-500/20 text-red-400"
                : "bg-amber-500/10 border border-amber-500/20 text-amber-400"
    }`}>
      <span className="font-medium">
        {isBlocked ? `VIX ${vix.toFixed(1)} > 30 — ${CS.VIX_BLOCKED}` : `VIX ${vix.toFixed(1)} (25-30) — ${CS.VIX_CAUTION}`}
      </span>
      <span className="text-xs opacity-70">
        {isBlocked ? CS.VIX_BLOCKED_SUB : CS.VIX_CAUTION_SUB}
      </span>
    </div>
  );
}

interface ConsensusRegime {
  vix?: number | null;
  [key: string]: unknown;
}

export async function ConsensusSection() {
  let data: { regime: ConsensusRegime; results: ConsensusRow[]; count: number };
  try {
    data = await fetchAPI<{ regime: ConsensusRegime; results: ConsensusRow[]; count: number }>("/api/consensus");
  } catch {
    // #1119 슬롯 shed(503) 포함 — 섹션만 강등, 페이지 shape 유지 (codex #1239 P2)
    return <p className="text-xs text-muted-foreground">{COMMON.DEGRADED}</p>;
  }
  const sorted = [...data.results].sort((a, b) => b.final_confidence - a.final_confidence);

  return (
    <>
      <VixBanner vix={data.regime?.vix ?? null} />
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-xs text-muted-foreground mb-3">
            10-Agent Consensus — {data.count} tickers × 10 agents = {data.count * 10} verdicts
          </p>
          <ConsensusTable data={sorted} vix={data.regime?.vix ?? null} />
        </CardContent>
      </Card>
    </>
  );
}

export async function DissentSection() {
  let data: { results: ConsensusRow[] };
  try {
    data = await fetchAPI<{ results: ConsensusRow[] }>("/api/consensus");
  } catch {
    // #1119 슬롯 shed(503) 포함 — 위 ConsensusSection 이 이미 강등 문구를 띄우므로 조용히 생략
    return null;
  }
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
      <h1 className="text-2xl font-bold">{NAV.ROUTE_AGENTS}</h1>
      <Suspense fallback={<Loading />}><ConsensusSection /></Suspense>
      <Suspense fallback={<Loading />}><DissentSection /></Suspense>
    </div>
  );
}
