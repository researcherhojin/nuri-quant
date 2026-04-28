"use client";

/**
 * useTraceStream — 에이전트 reasoning trace SSE 스트림 훅.
 *
 * /api/consensus/{ticker}/stream에서 verdict를 완료 순서대로 수신.
 * 유한 스트림: 10 verdicts → 1 consensus → done → 자동 종료.
 */
import { useCallback, useRef, useState } from "react";
import { API_BASE } from "./api";

interface AgentVerdict {
  agent_name: string;
  ticker: string;
  action: string;
  confidence: number;
  reasoning: string;
  data_points: Record<string, unknown>;
}

interface ConsensusResult {
  ticker: string;
  final_action: string;
  final_confidence: number;
  agreement_rate: number;
  verdicts: AgentVerdict[];
  dissent: string[];
  reasoning: string;
}

export interface TraceState {
  verdicts: AgentVerdict[];
  consensus: ConsensusResult | null;
  isStreaming: boolean;
  error: string | null;
}

export function useTraceStream() {
  const [state, setState] = useState<TraceState>({
    verdicts: [],
    consensus: null,
    isStreaming: false,
    error: null,
  });
  const esRef = useRef<EventSource | null>(null);

  const start = useCallback((ticker: string) => {
    esRef.current?.close();
    setState({ verdicts: [], consensus: null, isStreaming: true, error: null });

    const es = new EventSource(
      `${API_BASE}/api/consensus/${encodeURIComponent(ticker)}/stream`
    );
    esRef.current = es;

    es.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);
        if (parsed.type === "verdict") {
          setState((prev) => ({ ...prev, verdicts: [...prev.verdicts, parsed.data] }));
        } else if (parsed.type === "consensus") {
          setState((prev) => ({ ...prev, consensus: parsed.data }));
        } else if (parsed.type === "done") {
          setState((prev) => ({ ...prev, isStreaming: false }));
          es.close();
        }
      } catch {
        // 파싱 실패 무시
      }
    };

    es.onerror = () => {
      setState((prev) => ({ ...prev, isStreaming: false, error: "스트림 연결 실패" }));
      es.close();
    };
  }, []);

  const stop = useCallback(() => {
    esRef.current?.close();
    setState((prev) => ({ ...prev, isStreaming: false }));
  }, []);

  return { ...state, start, stop };
}
