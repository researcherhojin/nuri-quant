/**
 * CertificationsCard — server page 에서 fetch 한 history + summary 를 렌더만 담당
 * 하는 pure component. Server component 는 async fetch 만 수행 → 이 컴포넌트에
 * props 로 전달 → vitest 로 rendering 단독 검증 가능.
 */
import { Card, CardContent } from "@/components/ui/card";
import { GateFailureChart } from "@/components/ui/gate-failure-chart";
import { Metric } from "@/components/ui/metric";
import { SiegeTimelineChart, type CertificationPoint } from "@/components/ui/siege-timeline-chart";
import { StatusBadge } from "@/components/ui/status-badge";

export interface CertificationsListResponse {
  items: CertificationPoint[];
  count: number;
  total_in_db: number;
}

export interface CertificationsSummary {
  days: number;
  count: number;
  certified_rate: number | null;
  avg_score: number | null;
  by_caller: Record<string, number>;
  by_regime: Record<string, number>;
  latest: {
    timestamp: string;
    certified: boolean;
    score: number;
    regime: string | null;
    caller: string | null;
  } | null;
}

/** 30-day certified_rate 에 색상 부여 — <50% 는 red, 나머지는 default. */
export function rateColor(rate: number | null): "default" | "red" {
  if (rate === null) return "default";
  return rate < 50 ? "red" : "default";
}

export function formatRate(rate: number | null): string {
  return rate !== null ? `${rate}%` : "—";
}

export function formatAvgScore(avg: number | null): string {
  return avg !== null ? avg.toFixed(1) : "—";
}

/**
 * V2.1 #2 — distinct portfolio_hash count. null hash 는 별도 "(none)" bucket.
 * "21 runs but 1 portfolio state" 같은 degenerate 데이터에서도 가시화.
 */
export function countDistinctStates(items: CertificationPoint[]): number {
  const seen = new Set<string>();
  for (const it of items) {
    seen.add(it.portfolio_hash ?? "(none)");
  }
  return seen.size;
}

interface CertificationsCardProps {
  history: CertificationsListResponse;
  summary: CertificationsSummary;
}

export function CertificationsCard({ history, summary }: CertificationsCardProps) {
  if (history.total_in_db === 0) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-xs text-muted-foreground mb-3">Certification History</p>
          <p className="text-xs text-muted-foreground/70 py-6 text-center">
            아직 certification 기록이 없습니다. <code className="mx-1">make certify</code> 또는 scheduler 대기.
          </p>
        </CardContent>
      </Card>
    );
  }

  const distinctStates = countDistinctStates(history.items);

  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-5 space-y-4">
        {/* Summary row */}
        <div className="flex items-center justify-between">
          <div className="flex gap-3 flex-wrap">
            <Metric
              label="Certified rate (30d)"
              value={formatRate(summary.certified_rate)}
              size="sm"
              color={rateColor(summary.certified_rate)}
            />
            <Metric label="Avg score" value={formatAvgScore(summary.avg_score)} size="sm" />
            <Metric label="Runs (30d)" value={summary.count} size="sm" />
            <Metric label="Total in DB" value={history.total_in_db} size="sm" />
            <Metric
              label="Distinct states"
              value={distinctStates}
              size="sm"
              color={distinctStates <= 1 ? "red" : "default"}
            />
          </div>
          {summary.latest && (
            <StatusBadge status={summary.latest.certified ? "READY" : "BLOCKED"} size="sm" />
          )}
        </div>

        {/* Timeline chart */}
        <SiegeTimelineChart items={history.items} />

        {/* Gate breakdown — V2.1 #1 정보 밀도 강화 */}
        <GateFailureChart items={history.items} />

        {/* Caller / regime distributions */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="text-[10px] text-muted-foreground mb-1">By caller</p>
            <div className="flex flex-wrap gap-2 text-[10px]">
              {Object.entries(summary.by_caller).map(([k, v]) => (
                <span key={k} className="bg-muted/60 px-2 py-0.5 rounded-sm">
                  {k} <span className="text-muted-foreground/70">×{v}</span>
                </span>
              ))}
            </div>
          </div>
          <div>
            <p className="text-[10px] text-muted-foreground mb-1">By regime</p>
            <div className="flex flex-wrap gap-2 text-[10px]">
              {Object.entries(summary.by_regime).map(([k, v]) => (
                <span key={k} className="bg-muted/60 px-2 py-0.5 rounded-sm">
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
