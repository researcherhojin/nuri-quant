export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { ClientTable } from "@/components/ui/client-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Metric } from "@/components/ui/metric";

// === Types ===
interface Violation {
  ticker: string;
  violation_type: string;
  priority: number;
  current_value: number;
  limit_value: number;
  severity: string;
  action: string;
  sell_shares: number;
  sell_value_usd: number;
  reason: string;
}

interface AdvisorReport {
  actions: Violation[];
  total_violations: number;
  total_recovery_usd: number;
  violations_by_type: Record<string, number>;
  violations_by_severity: Record<string, number>;
  has_critical: boolean;
}

// === Loading ===
function Loading() {
  return <div className="animate-pulse bg-card rounded-xl border border-border h-96" />;
}

// === Main ===
async function AdvisorSection() {
  let data: AdvisorReport;
  try {
    data = await fetchAPI<AdvisorReport>("/api/rebalance-advisor");
  } catch {
    return <p className="text-red-400 text-sm">API 연결 실패. make api 실행 필요.</p>;
  }

  if (data.total_violations === 0) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <div className="flex items-center gap-2">
            <StatusBadge status="READY" size="md" />
            <span className="text-sm">모든 투자 규칙 준수 중. 위반 사항 없음.</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  const critical = data.violations_by_severity.critical || 0;
  const high = data.violations_by_severity.high || 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-3">
        <Metric label="총 위반" value={`${data.total_violations}건`} color={critical > 0 ? "red" : "default"} />
        <Metric label="Critical" value={`${critical}건`} color="red" />
        <Metric label="High" value={`${high}건`} color="red" />
        <Metric
          label="총 회수 가능"
          value={`$${data.total_recovery_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
          color="green"
        />
      </div>

      {data.has_critical && (
        <Card className="bg-red-950/30 border-red-900">
          <CardContent className="pt-4 pb-3">
            <p className="text-sm text-red-400 font-medium">
              ⚠ CRITICAL 위반 {critical}건 — 즉시 조치 필요
            </p>
          </CardContent>
        </Card>
      )}

      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-xs text-muted-foreground mb-3">
            Rebalance Advisor — 매도 우선순위 순 (rules.yaml 기반)
          </p>
          <ClientTable variant="advisor" data={data.actions} compact />
        </CardContent>
      </Card>

      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-xs text-muted-foreground mb-3">위반 유형별 분포</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(data.violations_by_type).map(([type, count]) => (
              <span key={type} className="text-xs bg-muted px-2 py-1 rounded">
                {type}: {count}건
              </span>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default function AdvisorPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-lg font-semibold">Rebalance Advisor</h1>
        <p className="text-xs text-muted-foreground mt-1">
          투자 규칙 위반 감지 · 매도 수량 계산 · 회수 금액 · 우선순위 정렬
        </p>
      </div>
      <Suspense fallback={<Loading />}>
        <AdvisorSection />
      </Suspense>
    </div>
  );
}
