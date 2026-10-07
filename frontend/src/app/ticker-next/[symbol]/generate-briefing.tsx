"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { publicBriefingSchema } from "./public-briefing-schema";
import { z } from "zod";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import styles from "./ticker.module.css";

const responseSchema = z.object({ public_briefing: publicBriefingSchema.nullable() });

export function GenerateBriefing({ symbol, status }: { symbol: string; status?: string }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [polling, setPolling] = useState(false);

  useEffect(() => {
    if (!polling && status !== "pending") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const started = Date.now();

    const poll = async () => {
      if (cancelled) return;

      try {
        const response = await fetch(`/api/ticker/${encodeURIComponent(symbol)}/research`, { cache: "no-store" });
        const result = response.ok ? responseSchema.safeParse(await response.json()) : null;

        if (result?.success && result.data.public_briefing?.status !== "pending") {
          setPolling(false);
          setPending(false);
          router.refresh();

          return;
        }
      } catch { /* 일시적인 조회 실패는 다음 조회에서 확인한다. */ }

      if (Date.now() - started > 300000) {
        setPolling(false);
        setPending(false);
        setMessage(T.BRIEFING_SLOW);

        return;
      }

      timer = setTimeout(() => void poll(), 2500);
    };

    void poll();

    return () => { cancelled = true; clearTimeout(timer); };
  }, [polling, status, symbol, router]);

  const generate = async () => {
    setPending(true);
    setMessage("");

    try {
      const response = await fetch(`/api/ticker/${encodeURIComponent(symbol)}/research/briefing`, { method: "POST" });

      if (!response.ok) {
        setMessage(response.status === 409 ? T.BRIEFING_STALE_DATA : response.status === 503 ? T.BRIEFING_BUSY : T.BRIEFING_START_FAILED);
        setPending(false);

        return;
      }

      setPolling(true);
    } catch {
      setPending(false);
      setMessage(T.BRIEFING_START_FAILED);
    }
  };

  const busy = pending || status === "pending";

  return <div><button className={styles.collectButton} disabled={busy || status === "ready"} onClick={() => void generate()}>{busy ? T.BRIEFING_GENERATING : status === "ready" ? T.BRIEFING_DONE : T.BRIEFING_GENERATE}</button>{message && <p role="status" className={styles.muted}>{message}</p>}</div>;
}
