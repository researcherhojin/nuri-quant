export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { ClientTable } from "@/components/ui/client-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Metric } from "@/components/ui/metric";
import { CertificationsCardLazy } from "@/components/ui/certifications-card-lazy";
import type {
  CertificationsListResponse,
  CertificationsSummary,
} from "@/components/ui/certifications-card";

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
export async function GateSection() {
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
export async function ConflictsSection() {
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
// server-side fetch 만 담당; 실제 렌더는 CertificationsCard (unit-testable pure).
export async function CertificationsSection() {
  const [history, summary] = await Promise.all([
    fetchAPI<CertificationsListResponse>("/api/certifications?limit=30"),
    fetchAPI<CertificationsSummary>("/api/certifications/summary?days=30"),
  ]);
  return <CertificationsCardLazy history={history} summary={summary} />;
}

// === Memory Drift Section ===
export async function MemorySection() {
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
      <h1 className="text-2xl font-bold">Certification Engine</h1>

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
