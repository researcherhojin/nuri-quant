export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { ClientTable } from "@/components/ui/client-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Metric } from "@/components/ui/metric";
import { SiegeTimelineChart, type CertificationPoint } from "@/components/ui/siege-timeline-chart";

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

// === Certifications (V2 — E4-0a observation loop) ===
interface CertificationsListResponse {
  items: CertificationPoint[];
  count: number;
  total_in_db: number;
}

interface CertificationsSummary {
  days: number;
  count: number;
  certified_rate: number | null;
  avg_score: number | null;
  by_caller: Record<string, number>;
  by_regime: Record<string, number>;
  latest: { timestamp: string; certified: boolean; score: number; regime: string | null; caller: string | null } | null;
}

// === Gate Section ===
async function GateSection() {
  const gates = await fetchAPI<Record<string, GateResult>>("/api/gate");

  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-5 space-y-4">
        <p className="text-xs text-muted-foreground mb-1">Pipeline Gate — Data Readiness</p>
        {Object.entries(gates).map(([phase, result]) => (
          <div key={phase}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium capitalize">{phase}</span>
              <StatusBadge
                status={result.ready ? "READY" : "BLOCKED"}
                size="md"
              />
            </div>
            <div className="w-full bg-muted rounded-full h-1.5 mb-2">
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
                    <span className="text-foreground/80">{c.description}</span>
                    {!c.passed && <p className="text-muted-foreground/70 mt-0.5">{c.detail}</p>}
                  </div>
                </div>
              ))}
            </div>
            {phase !== Object.keys(gates).at(-1) && (
              <div className="border-b border-border/60 mt-3" />
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
    <Card className="bg-card border-border">
      <CardContent className="pt-5">
        <div className="flex items-center gap-3 mb-3">
          <p className="text-xs text-muted-foreground">Signal Conflicts</p>
          <div className="flex gap-2">
            <Metric label="Total" value={data.count} size="sm" />
            <Metric label="High" value={data.high} size="sm" color={data.high > 0 ? "red" : "default"} />
          </div>
        </div>
        {data.conflicts.length === 0 ? (
          <p className="text-xs text-muted-foreground/70 py-3 text-center">No signal conflicts detected</p>
        ) : (
          <div className="space-y-2">
            {data.conflicts.map((c, i) => (
              <div key={`${c.ticker}-${i}`} className="bg-muted/50 rounded-lg p-2.5">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-medium">{c.ticker}</span>
                  <StatusBadge status={c.severity === "high" ? "SELL" : c.severity === "medium" ? "WATCH" : "HOLD"} size="sm" />
                  <span className="text-[10px] text-muted-foreground/70">{c.conflict_type}</span>
                </div>
                <p className="text-xs text-muted-foreground">{c.detail}</p>
                <p className="text-[10px] text-emerald-400/80 mt-1">→ {c.recommendation}</p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// === Certifications History Section (V2 — E4-0a observation loop) ===
async function CertificationsSection() {
  const [history, summary] = await Promise.all([
    fetchAPI<CertificationsListResponse>("/api/certifications?limit=30"),
    fetchAPI<CertificationsSummary>("/api/certifications/summary?days=30"),
  ]);

  if (history.total_in_db === 0) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-xs text-muted-foreground mb-3">SIEGE History</p>
          <p className="text-xs text-muted-foreground/70 py-6 text-center">
            아직 certification 기록이 없습니다. <code className="mx-1">make certify</code> 또는 scheduler 대기.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-5 space-y-4">
        {/* Summary row */}
        <div className="flex items-center justify-between">
          <div className="flex gap-3">
            <Metric
              label="Certified rate (30d)"
              value={summary.certified_rate !== null ? `${summary.certified_rate}%` : "—"}
              size="sm"
              color={
                summary.certified_rate === null
                  ? "default"
                  : summary.certified_rate >= 80
                  ? "default"
                  : summary.certified_rate >= 50
                  ? "default"
                  : "red"
              }
            />
            <Metric
              label="Avg score"
              value={summary.avg_score !== null ? summary.avg_score.toFixed(1) : "—"}
              size="sm"
            />
            <Metric
              label="Runs (30d)"
              value={summary.count}
              size="sm"
            />
            <Metric
              label="Total in DB"
              value={history.total_in_db}
              size="sm"
            />
          </div>
          {summary.latest && (
            <StatusBadge
              status={summary.latest.certified ? "READY" : "BLOCKED"}
              size="sm"
            />
          )}
        </div>

        {/* Timeline chart */}
        <SiegeTimelineChart items={history.items} />

        {/* Caller / regime distributions */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="text-[10px] text-muted-foreground mb-1">By caller</p>
            <div className="flex flex-wrap gap-2 text-[10px]">
              {Object.entries(summary.by_caller).map(([k, v]) => (
                <span key={k} className="bg-muted/60 px-2 py-0.5 rounded">
                  {k} <span className="text-muted-foreground/70">×{v}</span>
                </span>
              ))}
            </div>
          </div>
          <div>
            <p className="text-[10px] text-muted-foreground mb-1">By regime</p>
            <div className="flex flex-wrap gap-2 text-[10px]">
              {Object.entries(summary.by_regime).map(([k, v]) => (
                <span key={k} className="bg-muted/60 px-2 py-0.5 rounded">
                  {k} <span className="text-muted-foreground/70">×{v}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// === Memory Drift Section ===
async function MemorySection() {
  const data = await fetchAPI<{ drifts: Drift[]; critical: number; degrading: number }>("/api/memory");


  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-5">
        <div className="flex items-center gap-3 mb-3">
          <p className="text-xs text-muted-foreground">Learning Memory — Drift</p>
          <div className="flex gap-2">
            <Metric label="Critical" value={data.critical} size="sm" color={data.critical > 0 ? "red" : "default"} />
            <Metric label="Degrading" value={data.degrading} size="sm" color={data.degrading > 0 ? "red" : "default"} />
          </div>
        </div>
        {data.drifts.length === 0 ? (
          <p className="text-xs text-muted-foreground/70 py-3 text-center">No drift data (run: make validate first)</p>
        ) : (
          <ClientTable variant="drift" data={data.drifts} compact />
        )}
      </CardContent>
    </Card>
  );
}

function Loading() {
  return <div className="h-48 bg-card rounded-xl border border-border animate-pulse" />;
}

export default function EnginePage() {
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold">SIEGE Engine</h1>

      {/* V2 — SIEGE history 관찰 loop (E4-0a persist + V1 API 소비) */}
      <Suspense fallback={<Loading />}>
        <CertificationsSection />
      </Suspense>

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
