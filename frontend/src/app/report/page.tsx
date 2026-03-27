"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { API_BASE } from "@/lib/api";

export default function ReportPage() {
  const [report, setReport] = useState<string | null>(null);
  const [context, setContext] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function generateReport() {
    setLoading(true);
    setReport(null);
    try {
      // 컨텍스트 먼저 표시
      const ctxRes = await fetch(`${API_BASE}/api/report/context`);
      const ctxData = await ctxRes.json();
      setContext(ctxData.context);

      // LLM 리포트 생성
      const res = await fetch(`${API_BASE}/api/report`);
      const data = await res.json();
      setReport(data.report);
    } catch (e) {
      setReport(`Error: ${e instanceof Error ? e.message : "Unknown error"}`);
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
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader>
            <CardTitle className="text-sm text-zinc-400">Data Context (LLM Input)</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs text-zinc-500 whitespace-pre-wrap font-mono">{context}</pre>
          </CardContent>
        </Card>
      )}

      {report && (
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader>
            <CardTitle className="text-sm text-zinc-400">AI Generated Report (Ollama)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="prose prose-invert prose-sm max-w-none whitespace-pre-wrap">
              {report}
            </div>
          </CardContent>
        </Card>
      )}

      {!report && !loading && (
        <Card className="bg-zinc-900 border-zinc-800">
          <CardContent className="py-12 text-center text-zinc-500">
            <p>Generate Report 버튼을 눌러 AI 투자 리포트를 생성하세요.</p>
            <p className="text-xs mt-2">Ollama가 실행 중이어야 합니다 (ollama serve)</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
