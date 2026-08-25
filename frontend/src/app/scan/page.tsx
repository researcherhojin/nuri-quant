export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { ClientTable } from "@/components/ui/client-table";
import { SCAN } from "@/lib/strings";
import { type ScanResult, type SwingEntry, mergeScanSwing } from "./helpers";

// #1219 U4b: Market Scanner(top-15)와 Swing Entries(에이전트 합의 뷰)가 15/20 행을
// 중복 렌더하던 두 테이블을 ticker union 단일 테이블로 병합. 미승인 사유는 접기 유지.
async function ScannerSection() {
  const [scanData, swingData] = await Promise.all([
    fetchAPI<{ results: ScanResult[]; count: number }>("/api/scan?market=us&top=15"),
    fetchAPI<{ entries: SwingEntry[]; approved: number; rejected: number }>("/api/swing/entries").catch(
      () => ({ entries: [] as SwingEntry[], approved: 0, rejected: 0 }),
    ),
  ]);
  const rows = mergeScanSwing(scanData.results, swingData.entries);
  const rejected = swingData.entries.filter((e) => !e.approved);

  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-5">
        <p className="text-xs text-muted-foreground mb-3">
          {SCAN.TITLE} — {rows.length} {SCAN.HEADER_SIGNALS} ·{" "}
          <span className="text-emerald-400">{SCAN.HEADER_APPROVED} {swingData.approved}</span> ·{" "}
          {SCAN.HEADER_REJECTED} {swingData.rejected}
        </p>
        {rows.length === 0 ? (
          <p className="text-xs text-muted-foreground/70 py-3 text-center">{SCAN.EMPTY}</p>
        ) : (
          <ClientTable variant="scanner" data={rows} />
        )}
        {rejected.length > 0 && (
          <details className="mt-3">
            <summary className="text-[10px] text-muted-foreground/70 cursor-pointer hover:text-muted-foreground">
              {SCAN.REJECTED_FOLD} ({rejected.length})
            </summary>
            <div className="mt-1.5 space-y-0.5 text-[10px] text-muted-foreground/70 pl-2">
              {rejected.map((e, i) => (
                <p key={i}>{e.ticker}: {e.reason}</p>
              ))}
            </div>
          </details>
        )}
      </CardContent>
    </Card>
  );
}

function Loading() {
  return <div className="h-64 bg-card rounded-xl border border-border animate-pulse" />;
}

export default function ScanPage() {
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold">{SCAN.TITLE}</h1>
      <Suspense fallback={<Loading />}><ScannerSection /></Suspense>
    </div>
  );
}
