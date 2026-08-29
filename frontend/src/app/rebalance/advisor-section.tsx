/**
 * AdvisorSection — rules.yaml 위반 감지 → 매도 우선순위 (#1227 U5c).
 *
 * /advisor 페이지에서 이동: /rebalance 와 같은 질문("무엇을 조정/매도할까")을
 * 룰 축·비중 축으로 나눠 두 페이지였다 — 한 페이지 두 섹션으로 통합.
 * 서버 모듈 (not "use client") — page.tsx 와 테스트가 직접 import.
 */
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { ClientTable } from "@/components/ui/client-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Metric } from "@/components/ui/metric";
import { ADVISOR as A, COMMON } from "@/lib/strings";

// === Types ===
export interface Violation {
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

export interface AdvisorReport {
  actions: Violation[];
  total_violations: number;
  total_recovery_usd: number;
  violations_by_type: Record<string, number>;
  violations_by_severity: Record<string, number>;
  has_critical: boolean;
}

// export: 테스트에서 async Server Component 를 직접 await/render 하기 위함 (jsdom 은 중첩 Suspense child 를 commit 안 함)
export async function AdvisorSection() {
  let data: AdvisorReport;
  try {
    data = await fetchAPI<AdvisorReport>("/api/rebalance-advisor");
  } catch {
    return <p className="text-red-400 text-sm">{COMMON.API_ERROR}</p>;
  }

  if (data.total_violations === 0) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <div className="flex items-center gap-2">
            <StatusBadge status="READY" size="md" />
            <span className="text-sm">{A.NO_VIOLATIONS}</span>
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
        <Metric label={A.TOTAL_VIOLATIONS} value={`${data.total_violations}${COMMON.COUNT_SUFFIX}`} color={critical > 0 ? "red" : "default"} />
        <Metric label="Critical" value={`${critical}${COMMON.COUNT_SUFFIX}`} color="red" />
        <Metric label="High" value={`${high}${COMMON.COUNT_SUFFIX}`} color="red" />
        <Metric
          label={A.TOTAL_RECOVERABLE}
          value={`$${data.total_recovery_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
          color="green"
        />
      </div>

      {data.has_critical && (
        <Card className="bg-red-950/30 border-red-900">
          <CardContent className="pt-4 pb-3">
            <p className="text-sm text-red-400 font-medium">
              {A.CRITICAL_PREFIX} {critical}{COMMON.COUNT_SUFFIX} — {A.CRITICAL_SUFFIX}
            </p>
          </CardContent>
        </Card>
      )}

      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-xs text-muted-foreground mb-3">
            {A.DESCRIPTION}
          </p>
          <ClientTable variant="advisor" data={data.actions} compact />
        </CardContent>
      </Card>

      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-xs text-muted-foreground mb-3">{A.VIOLATION_DIST}</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(data.violations_by_type).map(([type, count]) => (
              <span key={type} className="text-xs bg-muted px-2 py-1 rounded-sm">
                {type}: {count}{COMMON.COUNT_SUFFIX}
              </span>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
