export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";
import { EVIDENCE as E } from "@/lib/strings";

// === Types ===
interface ChartMeta {
  id: string;
  description: string;
  available: boolean;
  date: string;
}

interface EvidenceList {
  charts: ChartMeta[];
  date: string;
}

// === Loading ===
function Loading() {
  return (
    <div className="space-y-4">
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          className="animate-pulse bg-card rounded-xl border border-border h-[500px]"
        />
      ))}
    </div>
  );
}

// === Chart Embed ===
function ChartEmbed({ chart }: { chart: ChartMeta }) {
  if (!chart.available) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium">{chart.description}</h3>
            <StatusBadge status="BLOCKED" />
          </div>
          <p className="text-xs text-muted-foreground">
            {E.NOT_GENERATED} <code>{E.MAKE_EVIDENCE}</code> {E.RUN_REQUIRED}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">{chart.description}</h3>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-muted-foreground">{chart.date}</span>
            <StatusBadge status="READY" />
          </div>
        </div>
        <iframe
          src={`/api/evidence/${chart.id}`}
          className="w-full border-0 rounded-lg bg-background"
          style={{ height: "450px" }}
          title={chart.description}
        />
      </CardContent>
    </Card>
  );
}

// === Main Content ===
async function EvidenceCharts() {
  let data: EvidenceList;
  try {
    data = await fetchAPI<EvidenceList>("/api/evidence");
  } catch {
    return (
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-sm text-muted-foreground">
            {E.LOAD_FAILED}
          </p>
        </CardContent>
      </Card>
    );
  }

  if (!data.charts.length) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-sm text-muted-foreground">
            {E.NO_CHARTS} <code>{E.MAKE_EVIDENCE}</code> {E.OR}{" "}
            <code>{E.MAKE_FULLSCAN}</code> {E.RUN_REQUIRED}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {data.charts.map((chart) => (
        <ChartEmbed key={chart.id} chart={chart} />
      ))}
    </div>
  );
}

// === Page ===
export default function EvidencePage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-lg font-semibold">Evidence Charts</h1>
        <p className="text-xs text-muted-foreground mt-1">
          {E.SUBTITLE}
        </p>
      </div>

      <Suspense fallback={<Loading />}>
        <EvidenceCharts />
      </Suspense>
    </div>
  );
}
