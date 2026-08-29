"use client";

import { useStream } from "@/lib/use-stream";

/**
 * LiveIndicator — SSE 스트림 상태를 네비게이션 바 옆에 표시.
 */
export function LiveIndicator() {
  const data = useStream();

  if (!data) return null;

  return (
    <div className="flex items-center gap-2 text-[10px] text-muted-foreground ml-auto shrink-0">
      <span className="relative flex size-2">
        <span className="animate-ping absolute inline-flex size-full rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex rounded-full size-2 bg-emerald-500" />
      </span>
      {data.regime && <span>{data.regime}</span>}
      {data.macro_score != null && <span>M{data.macro_score}</span>}
      {data.vix != null && <span>VIX {data.vix}</span>}
    </div>
  );
}
