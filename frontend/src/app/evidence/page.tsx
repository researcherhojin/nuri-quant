export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { EVIDENCE as E } from "@/lib/strings";
import type {
  FearGreedData,
  HeatmapData,
  RegimeData,
  SellEvidenceData,
  SignalPerformanceData,
} from "@/components/evidence/chart-data";
import {
  FearGreedChartLazy,
  PortfolioTreemapLazy,
  RegimeChartLazy,
  SellEvidenceChartLazy,
  SignalPerformanceChartLazy,
} from "@/components/evidence/evidence-charts-lazy";

// === Loading ===
function Loading() {
  return (
    <div className="space-y-4">
      {[1, 2, 3].map((i) => (
        <div key={i} className="animate-pulse bg-card rounded-xl border border-border h-80" />
      ))}
    </div>
  );
}

// === Chart Card ===
// #1225: iframe(450px) → 네이티브 recharts. 데이터 없으면 1줄 빈 상태.
function ChartCard({
  title,
  testId,
  empty,
  emptyText = E.NO_DATA,
  children,
}: {
  title: string;
  testId: string;
  empty: boolean;
  emptyText?: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="bg-card border-border" data-testid={testId}>
      <CardContent className="pt-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">{title}</h3>
          <span className="text-[10px] text-muted-foreground">{E.LIVE}</span>
        </div>
        {empty ? <p className="text-xs text-muted-foreground">{emptyText}</p> : children}
      </CardContent>
    </Card>
  );
}

// === Main Content ===
async function EvidenceCharts() {
  const [regime, heatmap, signals, fearGreed, sell] = await Promise.all([
    fetchAPI<RegimeData>("/api/evidence/data/regime").catch(() => null),
    fetchAPI<HeatmapData>("/api/evidence/data/portfolio_heatmap").catch(() => null),
    fetchAPI<SignalPerformanceData>("/api/evidence/data/signal_performance").catch(() => null),
    fetchAPI<FearGreedData>("/api/evidence/data/fear_greed").catch(() => null),
    fetchAPI<SellEvidenceData>("/api/evidence/data/sell_evidence").catch(() => null),
  ]);

  if (!regime && !heatmap && !signals && !fearGreed && !sell) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-sm text-muted-foreground">{E.LOAD_FAILED}</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <ChartCard title={E.TITLE_REGIME} testId="card-regime" empty={!regime || regime.count === 0}>
        {regime && <RegimeChartLazy data={regime} />}
      </ChartCard>

      <ChartCard title={E.TITLE_HEATMAP} testId="card-portfolio_heatmap" empty={!heatmap || heatmap.count === 0}>
        {heatmap && <PortfolioTreemapLazy data={heatmap} />}
      </ChartCard>

      <ChartCard title={E.TITLE_SIGNALS} testId="card-signal_performance" empty={!signals || signals.count === 0}>
        {signals && <SignalPerformanceChartLazy data={signals} />}
      </ChartCard>

      <ChartCard title={E.TITLE_FEAR_GREED} testId="card-fear_greed" empty={!fearGreed || fearGreed.count === 0}>
        {fearGreed && <FearGreedChartLazy data={fearGreed} />}
      </ChartCard>

      {/* 위반 0건은 결측이 아니라 정상 신호 — 문구를 구분한다 */}
      <ChartCard
        title={E.TITLE_SELL}
        testId="card-sell_evidence"
        empty={!sell || sell.count === 0}
        emptyText={sell && sell.count === 0 ? E.NO_VIOLATIONS : E.NO_DATA}
      >
        {sell && <SellEvidenceChartLazy data={sell} />}
      </ChartCard>
    </div>
  );
}

// === Page ===
export default function EvidencePage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-lg font-semibold">{E.TITLE}</h1>
        <p className="text-xs text-muted-foreground mt-1">{E.SUBTITLE}</p>
      </div>

      <Suspense fallback={<Loading />}>
        <EvidenceCharts />
      </Suspense>
    </div>
  );
}
