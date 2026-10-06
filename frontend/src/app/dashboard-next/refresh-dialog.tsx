"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { z } from "zod";
import { DASHBOARD_NEXT as COPY } from "@/lib/strings";
import { DetailDialog } from "./detail-dialog";
import styles from "./dashboard.module.css";

const T = COPY.REFRESH_DIALOG;

const runSchema = z.object({ id: z.string(), status: z.string(), jobs: z.array(z.object({ id: z.string(), status: z.string() })) });

const catalogSchema = z.object({ jobs: z.array(z.object({ id: z.string(), label: z.string(), description: z.string(), keys: z.array(z.string()) })), run: runSchema.nullable() });

const freshnessCounts = z.object({ pass: z.number(), warn: z.number(), fail: z.number() });

export function RefreshDialog({ delayedKeys = [], label = COPY.PIPELINE_PANEL.REFRESH }: { delayedKeys?: string[]; label?: string }) {
  return (
    <DetailDialog label={label} icon={<ArrowUpRight size={12} />} title={T.TITLE} lazy>
      <RefreshJobs delayedKeys={delayedKeys} />
    </DetailDialog>
  );
}

function RefreshJobs({ delayedKeys }: { delayedKeys: string[] }) {
  const router = useRouter();
  const [catalog, setCatalog] = useState<z.infer<typeof catalogSchema> | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState("");
  // 지연 소스는 첫 카탈로그 로드 때 한 번만 사전 선택한다 — 이후 폴링이 사용자의 선택을 덮지 않도록.
  const preselect = useRef<string[] | null>(delayedKeys);
  const handled = useRef<string | null>(null);
  const activeRun = catalog?.run && ["queued", "running"].includes(catalog.run.status);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();

    async function update() {
      try {
        const response = await fetch("/api/pipeline/refresh", { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]) });

        if (!response.ok) throw new Error();
        const next = catalogSchema.parse(await response.json());

        if (!active) return;
        setCatalog(next);
        setError("");

        if (preselect.current) {
          const keys = preselect.current;

          preselect.current = null;
          setSelected(next.jobs.filter((job) => job.keys.some((key) => keys.includes(key))).map((job) => job.id));
        }

        if (next.run && ["completed", "failed"].includes(next.run.status) && handled.current !== next.run.id) {
          const fresh = await fetch("/api/freshness", { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]) });

          if (!fresh.ok) throw new Error();
          const counts = freshnessCounts.parse(await fresh.json());

          if (!active) return;
          // 재확인이 성공한 뒤에만 처리 완료로 표시한다 — 일시적 실패면 다음 폴링이 다시 시도한다 (Codex #1658 P2)
          handled.current = next.run.id;
          setResult(T.RESULT(counts.pass, counts.warn, counts.fail));
          router.refresh();
          window.dispatchEvent(new Event("nuri-data-refreshed"));
        }
      } catch {
        if (active) setError(T.ERROR_POLL);
      } finally {
        if (active) timer = setTimeout(update, 5000);
      }
    }

    void update();

    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [router]);

  async function start() {
    setSending(true);
    setError("");
    setResult("");

    try {
      const response = await fetch("/api/pipeline/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jobs: selected }), signal: AbortSignal.timeout(10000) });

      if (!response.ok) {
        setError(response.status === 401 || response.status === 403 ? T.ERROR_AUTH : response.status === 409 ? T.ERROR_BUSY : T.ERROR_REQUEST);

        return;
      }

      const run = runSchema.parse(await response.json());

      setCatalog((value) => value ? { ...value, run } : value);
    } catch {
      setError(T.ERROR_RESPONSE);
    } finally {
      setSending(false);
    }
  }

  const unsupported = delayedKeys.filter((key) => catalog && !catalog.jobs.some((job) => job.keys.includes(key)));

  return <>
    <p>{T.INTRO}</p>
    <p className={styles.basis}>{T.SCOPE}</p>
    {!catalog && <p role="status">{T.LOADING}</p>}
    {catalog?.jobs.map((job) => (
      <label key={job.id} className={styles.refreshJob}>
        <input type="checkbox" checked={selected.includes(job.id)} disabled={!!activeRun || sending} onChange={(e) => setSelected((value) => e.target.checked ? [...value, job.id] : value.filter((id) => id !== job.id))} />
        <span><b>{job.label}</b><small>{job.description}</small></span>
        <span>{T.JOB_STATUS[catalog.run?.jobs.find((item) => item.id === job.id)?.status ?? ""]}</span>
      </label>
    ))}
    {!!unsupported.length && <p className={styles.caution}>{T.UNSUPPORTED}</p>}
    <div className={styles.refreshActions}>
      <button type="button" className={styles.button} disabled={!catalog || !selected.length || !!activeRun || sending} onClick={() => void start()}>
        {sending ? T.SENDING : activeRun ? T.IN_PROGRESS : T.START}
      </button>
      <Link href="/pipeline" className={styles.textLink}>{T.PIPELINE_LINK} <ArrowUpRight size={14} /></Link>
    </div>
    {catalog?.run && <p role="status">{T.LAST_REQUEST}{T.JOB_STATUS[catalog.run.status] ?? catalog.run.status}</p>}
    {result && <p role="status">{result}</p>}
    {error && <p role="alert" className={styles.caution}>{error}</p>}
    <p className={styles.basis}>{T.NOTE}</p>
  </>;
}
