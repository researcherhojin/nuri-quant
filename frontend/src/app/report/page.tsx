"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ERRORS, REPORT } from "@/lib/strings";

export default function ReportPage() {
  const [report, setReport] = useState<string | null>(null);
  const [context, setContext] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function generateReport() {
    setLoading(true);
    setReport(null);
    try {
      // 컨텍스트 먼저 표시
      const ctxRes = await fetch(`/api/report/context`);
      const ctxData = await ctxRes.json();
      setContext(ctxData.context);

      // LLM 리포트 생성
      const res = await fetch(`/api/report`);
      const data = await res.json();
      setReport(data.report);
    } catch (e) {
      // 원문 에러는 콘솔로 — 리포트 본문에 transport 텍스트를 싣지 않는다 (design-review F-002)
      console.error("report generation failed:", e);
      setReport(ERRORS.REPORT_FAILED);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">AI Investment Report</h1>
        <Button onClick={generateReport} disabled={loading} className="bg-emerald-600 hover:bg-emerald-700">
          {loading ? "Generating..." : "Generate Report"}
        </Button>
      </div>

      {context && (
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Data Context (LLM Input)</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-mono">{context}</pre>
          </CardContent>
        </Card>
      )}

      {report && (
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">AI Generated Report (Ollama)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="prose dark:prose-invert prose-sm max-w-none whitespace-pre-wrap">
              {report}
            </div>
          </CardContent>
        </Card>
      )}

      {!report && !loading && (
        <Card className="bg-card border-border">
          <CardContent className="py-12 text-center text-muted-foreground">
            <p>{REPORT.PLACEHOLDER}</p>
            <p className="text-xs mt-2">{REPORT.OLLAMA_REQUIRED}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
