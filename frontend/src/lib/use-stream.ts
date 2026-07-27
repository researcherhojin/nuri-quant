"use client";

import { useEffect, useState } from "react";

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
 *
 * URL 은 반드시 상대 경로. API_BASE 를 앞에 붙이면 브라우저가 그 주소를 직접
 * 때리는데, API_BASE 는 NEXT_PUBLIC_API_URL 이 빌드 시점에 인라인된 서버 기준
 * 주소(localhost / 사설 IP)라 브라우저에서는 자기 자신을 가리켜 연결이 죽는다.
 * 상대 경로여야 next.config rewrites 프록시를 탄다.
 * Test: src/__tests__/lib/client-absolute-url-guard.test.ts
 */
export function useStream(): StreamData | null {
  const [data, setData] = useState<StreamData | null>(null);

  useEffect(() => {
    const es = new EventSource("/api/stream");

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
