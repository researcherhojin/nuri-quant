export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { ClientTable } from "@/components/ui/client-table";
import { StatusBadge } from "@/components/ui/status-badge";
import { Metric } from "@/components/ui/metric";
import { ADVISOR as A, COMMON } from "@/lib/strings";

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
              <span key={type} className="text-xs bg-muted px-2 py-1 rounded">
                {type}: {count}{COMMON.COUNT_SUFFIX}
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
          {A.SUBTITLE}
        </p>
      </div>
      <Suspense fallback={<Loading />}>
        <AdvisorSection />
      </Suspense>
    </div>
  );
}
