"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { API_BASE } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// === Ollama 오류 감지 (HTTP 상태 코드 우선, 문자열 매칭 폴백) ===
function isOllamaError(report: string): boolean {
  const patterns = [
    "LLM 연결 실패",
    "LLM 오류",
    "connection refused",
    "ECONNREFUSED",
    "timeout",
    "connect ETIMEDOUT",
    "ollama",
  ];
  const lower = report.toLowerCase();
  return patterns.some((p) => lower.includes(p.toLowerCase()));
}

// === 경과 시간 표시 훅 ===
function useElapsedTime(running: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (running) {
      setElapsed(0);
      intervalRef.current = setInterval(() => setElapsed(prev => prev + 1), 1000);
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [running]);

  return elapsed;
}

export default function ReportPage() {
  const [report, setReport] = useState<string | null>(null);
  const [context, setContext] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const elapsed = useElapsedTime(loading);

  // 컴포넌트 언마운트 시 진행 중인 fetch 취소
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const generateReport = useCallback(async () => {
    // 이전 요청 취소
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    setLoading(true);
    setReport(null);
    setError(null);
    try {
      // 컨텍스트 먼저 표시
      const ctxRes = await fetch(`${API_BASE}/api/report/context`, { signal });
      if (!ctxRes.ok) {
        throw new Error(`컨텍스트 조회 실패 (${ctxRes.status})`);
      }
      const ctxData = await ctxRes.json();
      setContext(ctxData.prompt || ctxData.context);

      // LLM 리포트 생성
      const res = await fetch(`${API_BASE}/api/report`, { signal });
      if (!res.ok) {
        // HTTP 에러 상태 코드로 Ollama 오류 판별
        if (res.status === 502 || res.status === 503) {
          setError("ollama_not_running");
          return;
        }
        throw new Error(`리포트 생성 실패 (${res.status})`);
      }
      const data = await res.json();

      // Ollama 연결 실패 감지 (응답 본문 문자열 매칭 폴백)
      if (data.report && isOllamaError(data.report)) {
        setError("ollama_not_running");
        setReport(null);
      } else if (data.gate_blocked) {
        setError("gate_blocked");
        setReport(data.context || "데이터 부족으로 리포트 생성이 차단되었습니다.");
      } else {
        setReport(data.report);
      }
    } catch (e) {
      // 취소된 요청은 무시
      if (signal.aborted) return;

      const msg = e instanceof Error ? e.message : "Unknown error";
      // fetch 실패 시 (백엔드 다운 등)
      if (msg.includes("fetch") || msg.includes("Failed") || msg.includes("NetworkError")) {
        setError("api_unreachable");
      } else {
        setError(msg);
      }
    } finally {
      if (!signal.aborted) {
        setLoading(false);
      }
    }
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">AI Investment Report</h1>
        <Button onClick={generateReport} disabled={loading} className="bg-emerald-600 hover:bg-emerald-700">
          {loading ? "생성 중..." : "리포트 생성"}
        </Button>
      </div>

      {/* 로딩 상태 */}
      {loading && (
        <Card className="bg-card border-border">
          <CardContent className="py-8">
            <div className="flex flex-col items-center gap-4">
              {/* 스피너 */}
              <div className="relative w-12 h-12">
                <div className="absolute inset-0 border-2 border-emerald-400/20 rounded-full" />
                <div className="absolute inset-0 border-2 border-transparent border-t-emerald-400 rounded-full animate-spin" />
              </div>
              <div className="text-center">
                <p className="text-sm text-foreground font-medium">
                  {!context ? "데이터 컨텍스트 수집 중..." : "Ollama LLM 리포트 생성 중..."}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  예상 소요 시간: 약 30초 ~ 1분
                </p>
                <p className="text-xs text-muted-foreground/60 mt-0.5">
                  {elapsed}초 경과
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Ollama 미실행 에러 */}
      {error === "ollama_not_running" && (
        <Card className="bg-card border-amber-500/30">
          <CardContent className="py-6">
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-amber-400 text-lg">&#9888;</span>
                <p className="text-sm font-medium text-amber-400">
                  Ollama가 설치되지 않았거나 실행 중이지 않습니다
                </p>
              </div>
              <div className="bg-zinc-900 rounded-lg p-4 font-mono text-xs space-y-2">
                <p className="text-muted-foreground">
                  <span className="text-zinc-500"># 1. Ollama 설치</span>
                </p>
                <p className="text-emerald-400">brew install ollama</p>
                <p className="text-muted-foreground mt-2">
                  <span className="text-zinc-500"># 2. Ollama 서버 실행</span>
                </p>
                <p className="text-emerald-400">ollama serve</p>
                <p className="text-muted-foreground mt-2">
                  <span className="text-zinc-500"># 3. 모델 다운로드 (qwen3.5)</span>
                </p>
                <p className="text-emerald-400">ollama pull qwen3.5</p>
              </div>
              <p className="text-xs text-muted-foreground">
                설치 완료 후 &quot;리포트 생성&quot; 버튼을 다시 눌러주세요.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Gate 차단 에러 */}
      {error === "gate_blocked" && (
        <Card className="bg-card border-red-500/30">
          <CardContent className="py-6">
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-red-400 text-lg">&#10007;</span>
                <p className="text-sm font-medium text-red-400">
                  데이터 완성도 부족으로 리포트 생성 차단
                </p>
              </div>
              <p className="text-xs text-muted-foreground">
                Gate 스코어가 30% 미만입니다. 먼저 데이터를 수집하세요.
              </p>
              <div className="bg-zinc-900 rounded-lg p-4 font-mono text-xs">
                <p className="text-emerald-400">make collect</p>
              </div>
              {report && (
                <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-mono mt-2">{report}</pre>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* API 연결 불가 */}
      {error === "api_unreachable" && (
        <Card className="bg-card border-red-500/30">
          <CardContent className="py-6">
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-red-400 text-lg">&#10007;</span>
                <p className="text-sm font-medium text-red-400">
                  백엔드 API에 연결할 수 없습니다
                </p>
              </div>
              <div className="bg-zinc-900 rounded-lg p-4 font-mono text-xs">
                <p className="text-zinc-500"># API 서버 실행</p>
                <p className="text-emerald-400">make api</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 기타 에러 */}
      {error && error !== "ollama_not_running" && error !== "gate_blocked" && error !== "api_unreachable" && (
        <Card className="bg-card border-red-500/30">
          <CardContent className="py-6">
            <div className="flex items-center gap-2">
              <span className="text-red-400 text-lg">&#10007;</span>
              <p className="text-sm text-red-400">오류: {error}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 컨텍스트 표시 */}
      {context && (
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Data Context (LLM 입력 데이터)</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-mono max-h-[300px] overflow-y-auto">{context}</pre>
          </CardContent>
        </Card>
      )}

      {/* 리포트 표시 (마크다운 렌더링) */}
      {report && !error && (
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">AI Generated Report (Ollama)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="prose prose-sm dark:prose-invert max-w-none prose-headings:text-foreground prose-p:text-muted-foreground prose-strong:text-foreground prose-li:text-muted-foreground prose-hr:border-border">
              <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>{report}</ReactMarkdown>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 초기 상태 (아직 생성하지 않음) */}
      {!report && !loading && !error && (
        <Card className="bg-card border-border">
          <CardContent className="py-12 text-center text-muted-foreground">
            <p>리포트 생성 버튼을 눌러 AI 투자 리포트를 생성하세요.</p>
            <p className="text-xs mt-2 text-muted-foreground/70">
              Ollama 서버가 실행 중이어야 합니다 (ollama serve + qwen3.5 모델)
            </p>
            <p className="text-[10px] mt-1 text-muted-foreground/50">
              소요 시간: 약 30초 ~ 1분 | 8개 섹션 종합 분석
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
