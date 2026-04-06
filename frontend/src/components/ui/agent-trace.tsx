"use client";

/**
 * AgentTrace — 에이전트 reasoning trace 실시간 스트리밍 패널.
 *
 * 10개 에이전트 verdict가 완료 순서대로 표시되고,
 * 최종 합의 결과가 하단에 나타난다.
 */
import { useTraceStream } from "@/lib/use-trace-stream";
import { StatusBadge } from "./status-badge";

const AGENT_ORDER = [
  { key: "technical", label: "Tech" },
  { key: "fundamental", label: "Fund" },
  { key: "macro", label: "Macro" },
  { key: "risk", label: "Risk" },
  { key: "smart_money", label: "Smart" },
  { key: "wallstreet", label: "Wall" },
  { key: "korean_market", label: "KR" },
  { key: "options", label: "Opt" },
  { key: "crypto", label: "Cry" },
  { key: "retail", label: "Ret" },
];

function DataPills({ data }: { data: Record<string, any> }) {
  const entries = Object.entries(data);
  if (!entries.length) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {entries.map(([k, v]) => (
        <span key={k} className="text-[9px] bg-muted/50 rounded px-1.5 py-0.5 text-muted-foreground">
          {k}={typeof v === "number" ? v.toFixed(2) : String(v ?? "")}
        </span>
      ))}
    </div>
  );
}

export function AgentTrace({ ticker }: { ticker: string }) {
  const { verdicts, consensus, isStreaming, error, start, stop } = useTraceStream();
  const hasStarted = isStreaming || verdicts.length > 0;

  const verdictMap = Object.fromEntries(verdicts.map((v) => [v.agent_name, v]));

  return (
    <div className="space-y-3">
      {/* Trace 시작/정지 */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => (isStreaming ? stop() : start(ticker))}
          className="text-xs px-3 py-1 rounded-md border border-border bg-muted/30 hover:bg-muted/50 transition-colors"
        >
          {isStreaming ? "중지" : hasStarted ? "다시 분석" : "Trace"}
        </button>
        {isStreaming && (
          <span className="text-[10px] text-muted-foreground animate-pulse">
            분석 중... ({verdicts.length}/10)
          </span>
        )}
        {error && <span className="text-[10px] text-red-400">{error}</span>}
      </div>

      {/* 10개 에이전트 카드 그리드 */}
      {hasStarted && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
          {AGENT_ORDER.map((a) => {
            const v = verdictMap[a.key];
            return (
              <div
                key={a.key}
                className={`rounded-md p-2 border transition-all duration-300 ${
                  v ? "bg-muted/30 border-border/30" : "bg-muted/10 border-border/10 animate-pulse"
                }`}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <span className="text-[10px] font-medium text-muted-foreground">{a.label}</span>
                  {v ? (
                    <>
                      <StatusBadge status={v.action} size="sm" />
                      <span className="text-[10px] text-muted-foreground ml-auto">{v.confidence.toFixed(0)}%</span>
                    </>
                  ) : (
                    <span className="text-[10px] text-muted-foreground/30 ml-auto">--</span>
                  )}
                </div>
                {v ? (
                  <>
                    <p className="text-[10px] text-muted-foreground/80 leading-tight">{v.reasoning}</p>
                    <DataPills data={v.data_points} />
                  </>
                ) : (
                  <div className="h-6 bg-muted/20 rounded" />
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 최종 합의 결과 */}
      {consensus && (
        <div className="bg-muted/20 rounded-lg p-3 border border-border/40">
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium">합의:</span>
            <StatusBadge status={consensus.final_action} size="md" />
            <span className="text-xs">{consensus.final_confidence.toFixed(1)}%</span>
            <span className="text-[10px] text-muted-foreground">
              ({(consensus.agreement_rate * 100).toFixed(0)}% 동의)
            </span>
          </div>
          <p className="text-[10px] text-muted-foreground/80 mt-1 leading-tight">{consensus.reasoning}</p>
        </div>
      )}
    </div>
  );
}
