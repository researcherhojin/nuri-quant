export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { ClientTable } from "@/components/ui/client-table";
import type { RebalanceAction } from "@/lib/types";

async function RebalanceSection() {
  const data = await fetchAPI<{ actions: RebalanceAction[]; method: string; actionable: number }>("/api/rebalance?method=rp");
  if ("error" in data) return <p className="text-red-400 text-sm">{String((data as Record<string, unknown>).error)}</p>;

  const actionable = data.actions.filter((a) => a.action !== "HOLD");
  const holds = data.actions.filter((a) => a.action === "HOLD");

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardContent className="pt-5">
        <p className="text-xs text-zinc-500 mb-3">
          Regime-Aware Rebalancing — Risk Parity ({data.actionable} actions)
        </p>
        <ClientTable variant="rebalance" data={actionable} />
        {holds.length > 0 && (
          <p className="text-xs text-zinc-600 mt-3">
            HOLD: {holds.map((h) => h.ticker).join(", ")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Loading() {
  return <div className="h-64 bg-zinc-900 rounded-xl border border-zinc-800 animate-pulse" />;
}

export default function RebalancePage() {
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold">Rebalancing</h1>
      <Suspense fallback={<Loading />}><RebalanceSection /></Suspense>
    </div>
  );
}
