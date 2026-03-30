export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { ClientTable } from "@/components/ui/client-table";
import { Metric } from "@/components/ui/metric";

// === Types ===
interface PriceTarget {
  ticker: string;
  stock_type: string;
  current_price: number;
  entry_price: number;
  stop_loss: number;
  stop_loss_pct: number;
  target_1: number;
  target_1_pct: number;
  target_1_sell_pct: number;
  target_2: number;
  target_2_pct: number;
  target_2_sell_pct: number;
  trailing_stop_pct: number;
  analyst_target: number | null;
  analyst_upside_pct: number | null;
  error?: string;
}

// === Loading ===
function Loading() {
  return <div className="animate-pulse bg-card rounded-xl border border-border h-96" />;
}

// === Main ===
async function TargetsSection() {
  let data: { targets: PriceTarget[]; count: number };
  try {
    data = await fetchAPI<{ targets: PriceTarget[]; count: number }>("/api/targets");
  } catch {
    return <p className="text-red-400 text-sm">API 연결 실패. make api 실행 필요.</p>;
  }

  const valid = data.targets.filter((t: any) => !t.error);
  const growth = valid.filter((t: any) => t.stock_type === "growth");
  const value = valid.filter((t: any) => t.stock_type === "value");
  const tpTriggered = valid.filter((t: any) => t.take_profit_triggered);
  const tsTriggered = valid.filter((t: any) => t.trailing_stop_triggered);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <Metric label="전체 종목" value={`${valid.length}개`} />
        <Metric label="성장주" value={`${growth.length}개`} sub="SL -7% / TP +20%/+40%" color="green" />
        <Metric label="가치주" value={`${value.length}개`} sub="SL -10% / TP +15%/+30%" />
        <Metric label="익절 도달" value={`${tpTriggered.length}개`} sub={tpTriggered.length > 0 ? "매도 필요" : ""} color={tpTriggered.length > 0 ? "green" : "default"} />
        <Metric label="트레일링 스톱" value={`${tsTriggered.length}개`} sub={tsTriggered.length > 0 ? "즉시 매도" : ""} color={tsTriggered.length > 0 ? "red" : "default"} />
      </div>

      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-xs text-muted-foreground mb-3">
            가격 타겟 — rules.yaml 기반 (O'Neil + Minervini)
          </p>
          <ClientTable variant="targets" data={valid} compact />
        </CardContent>
      </Card>
    </div>
  );
}

export default function TargetsPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-lg font-semibold">Price Targets</h1>
        <p className="text-xs text-muted-foreground mt-1">
          전 종목 매수가 · 손절가 · 익절가 · 트레일링 스톱 · 애널리스트 목표가
        </p>
      </div>
      <Suspense fallback={<Loading />}>
        <TargetsSection />
      </Suspense>
    </div>
  );
}
