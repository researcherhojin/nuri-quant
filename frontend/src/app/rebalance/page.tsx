export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { ClientTable } from "@/components/ui/client-table";
import { ADVISOR, COMMON, ERRORS, REBALANCE } from "@/lib/strings";
import type { RebalanceAction } from "@/lib/types";
import { AdvisorSection } from "@/app/rebalance/advisor-section";

// #1227 U5c: /advisor 통합 — 룰 위반(매도 우선순위) 섹션이 먼저, 비중(risk-parity) 섹션이 다음.
// 위반은 즉시 행동 대상이고 리밸런싱은 조정 대상이라는 우선순위.

// export: 테스트에서 async Server Component 를 직접 await/render 하기 위함
export async function RebalanceSection() {
  let data: { actions: RebalanceAction[]; method: string; actionable: number } | { error: string };
  try {
    data = await fetchAPI<{ actions: RebalanceAction[]; method: string; actionable: number }>("/api/rebalance?method=rp");
  } catch {
    // #1119 슬롯 shed(503) 포함 — 섹션만 강등, 페이지 shape 유지 (codex #1239 P2)
    return <p className="text-xs text-muted-foreground">{COMMON.DEGRADED}</p>;
  }
  // 원문 에러 문자열 노출 금지 (design-review F-002) — 한국어 카피 + 다음 행동
  if ("error" in data) return <p className="text-red-400 text-sm">{ERRORS.REBALANCE_FAILED}</p>;

  const actionable = data.actions.filter((a) => a.action !== "HOLD");
  const holds = data.actions.filter((a) => a.action === "HOLD");

  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-5">
        <p className="text-xs text-muted-foreground mb-3">
          Regime-Aware Rebalancing — Risk Parity ({data.actionable} actions)
        </p>
        <ClientTable variant="rebalance" data={actionable} />
        {holds.length > 0 && (
          <p className="text-xs text-muted-foreground/70 mt-3">
            HOLD: {holds.map((h) => h.ticker).join(", ")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Loading() {
  return <div className="h-64 bg-card rounded-xl border border-border animate-pulse" />;
}

export default function RebalancePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold">Rebalancing</h1>
        <p className="text-xs text-muted-foreground mt-1">{ADVISOR.SUBTITLE}</p>
      </div>

      <section aria-label={REBALANCE.SECTION_VIOLATIONS}>
        <h2 className="text-sm font-medium mb-3">{REBALANCE.SECTION_VIOLATIONS}</h2>
        <Suspense fallback={<Loading />}>
          <AdvisorSection />
        </Suspense>
      </section>

      <section aria-label={REBALANCE.SECTION_WEIGHTS}>
        <h2 className="text-sm font-medium mb-3">{REBALANCE.SECTION_WEIGHTS}</h2>
        <Suspense fallback={<Loading />}>
          <RebalanceSection />
        </Suspense>
      </section>
    </div>
  );
}
