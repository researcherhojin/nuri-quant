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
  return <div className="animate-pulse bg-zinc-900 rounded-xl border border-zinc-800 h-96" />;
}

// === Main ===
async function TargetsSection() {
  let data: { targets: PriceTarget[]; count: number };
  try {
    data = await fetchAPI<{ targets: PriceTarget[]; count: number }>("/api/targets");
  } catch {
    return <p className="text-red-400 text-sm">API 연결 실패. make api 실행 필요.</p>;
  }

  const valid = data.targets.filter((t) => !t.error);
  const growth = valid.filter((t) => t.stock_type === "growth");
  const value = valid.filter((t) => t.stock_type === "value");

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <Metric label="전체 종목" value={`${valid.length}개`} />
        <Metric label="성장주" value={`${growth.length}개`} sub="SL -7% / TP +20%/+40%" color="green" />
        <Metric label="가치주" value={`${value.length}개`} sub="SL -10% / TP +15%/+30%" />
      </div>

      <Card className="bg-zinc-900 border-zinc-800">
        <CardContent className="pt-5">
          <p className="text-xs text-zinc-500 mb-3">
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
        <p className="text-xs text-zinc-500 mt-1">
          전 종목 매수가 · 손절가 · 익절가 · 트레일링 스톱 · 애널리스트 목표가
        </p>
      </div>
      <Suspense fallback={<Loading />}>
        <TargetsSection />
      </Suspense>
    </div>
  );
}
