export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Metric } from "@/components/ui/metric";

// === Types ===
interface GateCondition {
  id: string;
  phase: string;
  description: string;
  passed: boolean;
  detail: string;
}

interface GateResult {
  phase: string;
  total: number;
  passed: number;
  score: number;
  ready: boolean;
  conditions: GateCondition[];
}

interface Conflict {
  ticker: string;
  conflict_type: string;
  severity: string;
  buy_signals: string[];
  sell_signals: string[];
  detail: string;
  recommendation: string;
}

interface Drift {
  signal_id: string;
  regime: string | null;
  all_time_wr: number;
  recent_wr: number;
  drift_pct: number;
  status: string;
  detail: string;
}

// === Gate Section ===
async function GateSection() {
  const gates = await fetchAPI<Record<string, GateResult>>("/api/gate");

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardContent className="pt-5 space-y-4">
        <p className="text-xs text-zinc-500 mb-1">Pipeline Gate — Data Readiness</p>
        {Object.entries(gates).map(([phase, result]) => (
          <div key={phase}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium capitalize">{phase}</span>
              <StatusBadge
                status={result.ready ? "READY" : "BLOCKED"}
                size="md"
              />
            </div>
            <div className="w-full bg-zinc-800 rounded-full h-1.5 mb-2">
              <div
                className={`h-1.5 rounded-full transition-all ${
                  result.score >= 0.7 ? "bg-emerald-500" :
                  result.score >= 0.4 ? "bg-amber-500" : "bg-red-500"
                }`}
                style={{ width: `${result.score * 100}%` }}
              />
            </div>
            <div className="space-y-1">
              {result.conditions.map((c) => (
                <div key={c.id} className="flex items-start gap-2 text-xs">
                  <span className={c.passed ? "text-emerald-400" : "text-red-400"}>
                    {c.passed ? "✓" : "✗"}
                  </span>
                  <div>
                    <span className="text-zinc-300">{c.description}</span>
                    {!c.passed && <p className="text-zinc-600 mt-0.5">{c.detail}</p>}
                  </div>
                </div>
              ))}
            </div>
            {phase !== Object.keys(gates).at(-1) && (
              <div className="border-b border-zinc-800/60 mt-3" />
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// === Conflicts Section ===
async function ConflictsSection() {
  const data = await fetchAPI<{ conflicts: Conflict[]; count: number; high: number }>("/api/conflicts");

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardContent className="pt-5">
        <div className="flex items-center gap-3 mb-3">
          <p className="text-xs text-zinc-500">Signal Conflicts</p>
          <div className="flex gap-2">
            <Metric label="Total" value={data.count} size="sm" />
            <Metric label="High" value={data.high} size="sm" color={data.high > 0 ? "red" : "default"} />
          </div>
        </div>
        {data.conflicts.length === 0 ? (
          <p className="text-xs text-zinc-600 py-3 text-center">No signal conflicts detected</p>
        ) : (
          <div className="space-y-2">
            {data.conflicts.map((c, i) => (
              <div key={`${c.ticker}-${i}`} className="bg-zinc-800/40 rounded-lg p-2.5">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-medium">{c.ticker}</span>
                  <StatusBadge status={c.severity === "high" ? "SELL" : c.severity === "medium" ? "WATCH" : "HOLD"} size="sm" />
                  <span className="text-[10px] text-zinc-600">{c.conflict_type}</span>
                </div>
                <p className="text-xs text-zinc-500">{c.detail}</p>
                <p className="text-[10px] text-emerald-400/80 mt-1">→ {c.recommendation}</p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// === Memory Drift Section ===
async function MemorySection() {
  const data = await fetchAPI<{ drifts: Drift[]; critical: number; degrading: number }>("/api/memory");

  const statusMap: Record<string, string> = {
    critical: "SELL",
    degrading: "WATCH",
    improving: "BUY",
    stable: "HOLD",
  };

  const driftCols = [
    { key: "signal_id", label: "Signal", render: (v: string) => <span className="font-medium">{v}</span> },
    { key: "status", label: "Status", align: "center" as const, render: (v: string) => <StatusBadge status={statusMap[v] || "HOLD"} size="sm" /> },
    { key: "all_time_wr", label: "All-Time WR", align: "right" as const, render: (v: number) => `${(v * 100).toFixed(0)}%` },
    { key: "recent_wr", label: "Recent WR", align: "right" as const, render: (v: number) => `${(v * 100).toFixed(0)}%` },
    {
      key: "drift_pct", label: "Drift", align: "right" as const,
      render: (v: number) => (
        <span className={`font-medium ${v < -15 ? "text-red-400" : v > 15 ? "text-emerald-400" : "text-zinc-400"}`}>
          {v > 0 ? "+" : ""}{v.toFixed(1)}%
        </span>
      ),
    },
  ];

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardContent className="pt-5">
        <div className="flex items-center gap-3 mb-3">
          <p className="text-xs text-zinc-500">Learning Memory — Drift</p>
          <div className="flex gap-2">
            <Metric label="Critical" value={data.critical} size="sm" color={data.critical > 0 ? "red" : "default"} />
            <Metric label="Degrading" value={data.degrading} size="sm" color={data.degrading > 0 ? "red" : "default"} />
          </div>
        </div>
        {data.drifts.length === 0 ? (
          <p className="text-xs text-zinc-600 py-3 text-center">No drift data (run: make validate first)</p>
        ) : (
          <DataTable columns={driftCols} data={data.drifts} compact />
        )}
      </CardContent>
    </Card>
  );
}

function Loading() {
  return <div className="h-48 bg-zinc-900 rounded-xl border border-zinc-800 animate-pulse" />;
}

export default function EnginePage() {
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold">SIEGE Engine</h1>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Suspense fallback={<Loading />}><GateSection /></Suspense>
        <div className="space-y-4">
          <Suspense fallback={<Loading />}><ConflictsSection /></Suspense>
          <Suspense fallback={<Loading />}><MemorySection /></Suspense>
        </div>
      </div>
    </div>
  );
}
