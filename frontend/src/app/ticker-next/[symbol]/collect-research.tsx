"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import styles from "./ticker.module.css";

// 수집은 버튼으로만 시작한다 — 페이지를 여는 것만으로 DB 쓰기와 외부 호출이 일어나면 안 된다.
// 예전에는 당일 자료가 없으면 마운트 시 자동 수집했고, 검색으로 연 아무 종목·CI e2e 방문이 외부 소스를 호출했다.
export function CollectResearch({ symbol }: { symbol: string }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");

  const collect = useCallback(async () => {
    setPending(true);
    setMessage("");

    try {
      const response = await fetch(`/api/ticker/${encodeURIComponent(symbol)}/research/refresh?force=true`, { method: "POST" });

      if (!response.ok) {
        setMessage(response.status === 404 ? T.COLLECT_UNKNOWN : response.status === 401 || response.status === 403 ? T.COLLECT_AUTH : T.COLLECT_FAILED);

        return;
      }

      router.refresh();
    } catch {
      setMessage(T.COLLECT_FAILED);
    } finally {
      setPending(false);
    }
  }, [symbol, router]);

  return <div className={styles.collect}><button type="button" className={styles.collectButton} disabled={pending} onClick={() => void collect()}><RefreshCw size={14} />{pending ? T.COLLECTING : T.COLLECT}</button>{message && <p role="status" className={styles.muted}>{message}</p>}</div>;
}
