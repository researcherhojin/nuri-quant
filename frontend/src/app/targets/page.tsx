export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
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

// === Price color ===
function PriceCell({ value, current }: { value: number; current: number }) {
  const isKr = value > 10000;
  const prefix = isKr ? "₩" : "$";
  const formatted = isKr ? value.toLocaleString() : value.toFixed(2);
  const color = value > current ? "text-emerald-400" : value < current ? "text-red-400" : "text-zinc-300";
  return <span className={color}>{prefix}{formatted}</span>;
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

  const cols = [
    {
      key: "ticker", label: "Ticker",
      render: (v: string) => <span className="font-medium">{v}</span>,
    },
    {
      key: "stock_type", label: "Type", align: "center" as const,
      render: (v: string) => (
        <StatusBadge status={v === "growth" ? "momentum" : "HOLD"} size="sm" />
      ),
    },
    {
      key: "current_price", label: "현재가", align: "right" as const,
      render: (v: number) => {
        const isKr = v > 10000;
        return <span>{isKr ? `₩${v.toLocaleString()}` : `$${v.toFixed(2)}`}</span>;
      },
    },
    {
      key: "stop_loss", label: "손절가", align: "right" as const,
      render: (v: number, row: PriceTarget) => <PriceCell value={v} current={row.current_price} />,
    },
    {
      key: "target_1", label: "1차 익절", align: "right" as const,
      render: (v: number, row: PriceTarget) => <PriceCell value={v} current={row.current_price} />,
    },
    {
      key: "target_2", label: "2차 익절", align: "right" as const,
      render: (v: number, row: PriceTarget) => <PriceCell value={v} current={row.current_price} />,
    },
    {
      key: "analyst_target", label: "목표가", align: "right" as const,
      render: (v: number | null, row: PriceTarget) => {
        if (!v) return <span className="text-zinc-600">—</span>;
        const isKr = v > 10000;
        const prefix = isKr ? "₩" : "$";
        return (
          <span className="text-blue-400">
            {prefix}{isKr ? v.toLocaleString() : v.toFixed(2)}
            {row.analyst_upside_pct != null && (
              <span className="text-[10px] ml-1">({row.analyst_upside_pct > 0 ? "+" : ""}{row.analyst_upside_pct}%)</span>
            )}
          </span>
        );
      },
    },
  ];

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
          <DataTable columns={cols} data={valid} compact />
        </CardContent>
      </Card>
    </div>
  );
}

export default function TargetsPage() {
  return (
    <main className="container mx-auto px-4 py-6 max-w-7xl">
      <div className="mb-6">
        <h1 className="text-lg font-semibold">Price Targets</h1>
        <p className="text-xs text-zinc-500 mt-1">
          전 종목 매수가 · 손절가 · 익절가 · 트레일링 스톱 · 애널리스트 목표가
        </p>
      </div>
      <Suspense fallback={<Loading />}>
        <TargetsSection />
      </Suspense>
    </main>
  );
}
