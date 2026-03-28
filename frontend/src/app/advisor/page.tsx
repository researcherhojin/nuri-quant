export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
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
  return <div className="animate-pulse bg-zinc-900 rounded-xl border border-zinc-800 h-96" />;
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
      <Card className="bg-zinc-900 border-zinc-800">
        <CardContent className="pt-5">
          <div className="flex items-center gap-2">
            <StatusBadge status="READY" size="md" />
            <span className="text-sm">모든 투자 규칙 준수 중. 위반 사항 없음.</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  const cols = [
    {
      key: "priority", label: "#", align: "center" as const,
      render: (v: number) => <span className="text-zinc-500">{v}</span>,
    },
    {
      key: "ticker", label: "Ticker",
      render: (v: string) => <span className="font-medium">{v}</span>,
    },
    {
      key: "severity", label: "심각도", align: "center" as const,
      render: (v: string) => (
        <StatusBadge
          status={v === "critical" ? "SELL" : v === "high" ? "REDUCE" : "WATCH"}
          size="sm"
        />
      ),
    },
    {
      key: "action", label: "조치", align: "center" as const,
      render: (v: string) => (
        <span className={v === "SELL_ALL" ? "text-red-400 font-medium" : "text-amber-400"}>
          {v === "SELL_ALL" ? "전량 매도" : "일부 매도"}
        </span>
      ),
    },
    {
      key: "sell_shares", label: "매도 수량", align: "right" as const,
      render: (v: number) => `${v}주`,
    },
    {
      key: "sell_value_usd", label: "회수 예상", align: "right" as const,
      render: (v: number) => (
        <span className="text-emerald-400">${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
      ),
    },
    {
      key: "reason", label: "사유",
      render: (v: string) => <span className="text-xs text-zinc-400">{v}</span>,
    },
  ];

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

      <Card className="bg-zinc-900 border-zinc-800">
        <CardContent className="pt-5">
          <p className="text-xs text-zinc-500 mb-3">
            Rebalance Advisor — 매도 우선순위 순 (rules.yaml 기반)
          </p>
          <DataTable columns={cols} data={data.actions} compact />
        </CardContent>
      </Card>

      <Card className="bg-zinc-900 border-zinc-800">
        <CardContent className="pt-5">
          <p className="text-xs text-zinc-500 mb-3">위반 유형별 분포</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(data.violations_by_type).map(([type, count]) => (
              <span key={type} className="text-xs bg-zinc-800 px-2 py-1 rounded">
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
    <main className="container mx-auto px-4 py-6 max-w-7xl">
      <div className="mb-6">
        <h1 className="text-lg font-semibold">Rebalance Advisor</h1>
        <p className="text-xs text-zinc-500 mt-1">
          투자 규칙 위반 감지 · 매도 수량 계산 · 회수 금액 · 우선순위 정렬
        </p>
      </div>
      <Suspense fallback={<Loading />}>
        <AdvisorSection />
      </Suspense>
    </main>
  );
}
