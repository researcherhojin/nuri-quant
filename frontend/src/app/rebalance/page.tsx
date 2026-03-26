export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import type { RebalanceAction } from "@/lib/types";

async function RebalanceSection() {
  const data = await fetchAPI<{ actions: RebalanceAction[]; method: string; actionable: number }>("/api/rebalance?method=rp");
  if ("error" in data) return <p className="text-red-400 text-sm">{String((data as Record<string, unknown>).error)}</p>;

  const actionable = data.actions.filter((a) => a.action !== "HOLD");
  const holds = data.actions.filter((a) => a.action === "HOLD");

  const cols = [
    { key: "ticker", label: "Ticker", render: (v: string) => <span className="font-medium">{v}</span> },
    { key: "sector", label: "Sector", render: (v: string) => <span className="text-zinc-500">{v}</span> },
    { key: "action", label: "Action", align: "center" as const, render: (v: string) => <StatusBadge status={v} size="md" /> },
    { key: "current_weight", label: "Current %", align: "right" as const, render: (v: number) => `${v.toFixed(1)}%` },
    { key: "target_weight", label: "Target %", align: "right" as const, render: (v: number) => `${v.toFixed(1)}%` },
    {
      key: "diff", label: "Diff", align: "right" as const,
      render: (_: any, row: RebalanceAction) => {
        const diff = row.target_weight - row.current_weight;
        return (
          <span className={diff > 0 ? "text-emerald-400" : diff < 0 ? "text-red-400" : "text-zinc-400"}>
            {diff > 0 ? "+" : ""}{diff.toFixed(1)}%
          </span>
        );
      },
    },
    {
      key: "signals", label: "Signals", render: (v: string[]) => (
        <span className="text-zinc-500 text-xs">{v?.join(", ") || "—"}</span>
      ),
    },
  ];

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardContent className="pt-5">
        <p className="text-xs text-zinc-500 mb-3">
          Regime-Aware Rebalancing — Risk Parity ({data.actionable} actions)
        </p>
        <DataTable columns={cols} data={actionable} />
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
