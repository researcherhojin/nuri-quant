"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "./api";

interface StreamData {
  timestamp?: number;
  regime?: string;
  confidence?: number;
  vix?: number;
  fear_greed?: number;
  macro_score?: number;
  open_positions?: number;
}

/**
 * SSE 스트림 훅 — /api/stream에서 30초마다 상태 수신.
 */
export function useStream(): StreamData | null {
  const [data, setData] = useState<StreamData | null>(null);

  useEffect(() => {
    const es = new EventSource(`${API_BASE}/api/stream`);

    es.onmessage = (event) => {
      try {
        setData(JSON.parse(event.data));
      } catch {
        // 파싱 실패 무시
      }
    };

    es.onerror = () => {
      // 자동 재연결 (EventSource 기본 동작)
    };

    return () => es.close();
  }, []);

  return data;
}
