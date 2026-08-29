export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { ClientTable } from "@/components/ui/client-table";
import { Metric } from "@/components/ui/metric";
import { TARGETS as T, COMMON, NAV } from "@/lib/strings";

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
  take_profit_triggered?: boolean;
  trailing_stop_triggered?: boolean;
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
    return <p className="text-red-400 text-sm">{COMMON.API_ERROR}</p>;
  }

  const valid = data.targets.filter((t: PriceTarget) => !t.error);
  const growth = valid.filter((t: PriceTarget) => t.stock_type === "growth");
  const value = valid.filter((t: PriceTarget) => t.stock_type === "value");
  const tpTriggered = valid.filter((t: PriceTarget) => t.take_profit_triggered);
  const tsTriggered = valid.filter((t: PriceTarget) => t.trailing_stop_triggered);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <Metric label={T.ALL} value={`${valid.length}${T.COUNT_SUFFIX}`} />
        <Metric label={T.GROWTH} value={`${growth.length}${T.COUNT_SUFFIX}`} sub="SL -7% / TP +20%/+40%" color="green" />
        <Metric label={T.VALUE} value={`${value.length}${T.COUNT_SUFFIX}`} sub="SL -10% / TP +15%/+30%" />
        <Metric label={T.TP_TRIGGERED} value={`${tpTriggered.length}${T.COUNT_SUFFIX}`} sub={tpTriggered.length > 0 ? T.SELL_NEEDED : ""} color={tpTriggered.length > 0 ? "green" : "default"} />
        <Metric label={T.TS_TRIGGERED} value={`${tsTriggered.length}${T.COUNT_SUFFIX}`} sub={tsTriggered.length > 0 ? T.SELL_IMMEDIATE : ""} color={tsTriggered.length > 0 ? "red" : "default"} />
      </div>

      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-xs text-muted-foreground mb-3">
            {T.DESCRIPTION}
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
        <h1 className="text-lg font-semibold">{NAV.ROUTE_TARGETS}</h1>
        <p className="text-xs text-muted-foreground mt-1">
          {T.SUBTITLE}
        </p>
      </div>
      <Suspense fallback={<Loading />}>
        <TargetsSection />
      </Suspense>
    </div>
  );
}
