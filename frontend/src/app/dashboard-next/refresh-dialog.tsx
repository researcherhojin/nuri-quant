"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { z } from "zod";
import { DetailDialog } from "./detail-dialog";
import styles from "./dashboard.module.css";

const runSchema = z.object({ id: z.string(), status: z.string(), jobs: z.array(z.object({ id: z.string(), status: z.string() })) });
const catalogSchema = z.object({ jobs: z.array(z.object({ id: z.string(), label: z.string(), description: z.string(), keys: z.array(z.string()) })), run: runSchema.nullable() });
const labels: Record<string, string> = { queued: "대기", running: "진행 중", completed: "작업 완료", failed: "실패", skipped: "실행하지 않음" };

export function RefreshDialog({ delayedKeys = [], label = "데이터 갱신 ↗" }: { delayedKeys?: string[]; label?: string }) {
  return <DetailDialog label={label} title="데이터 갱신 작업" lazy><RefreshJobs delayedKeys={delayedKeys} /></DetailDialog>;
}

function RefreshJobs({ delayedKeys }: { delayedKeys: string[] }) {
  const router = useRouter();
  const delayedKey = JSON.stringify(delayedKeys);
  const [catalog, setCatalog] = useState<z.infer<typeof catalogSchema> | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState("");
  const initialized = useRef(false);
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
        if (!initialized.current) {
          initialized.current = true;
          setSelected(next.jobs.filter(job => job.keys.some(key => (JSON.parse(delayedKey) as string[]).includes(key))).map(job => job.id));
        }
        if (next.run && ["completed", "failed"].includes(next.run.status) && handled.current !== next.run.id) {
          handled.current = next.run.id;
          const fresh = await fetch("/api/freshness", { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]) });
          if (!fresh.ok) throw new Error();
          const counts = z.object({ pass: z.number(), warn: z.number(), fail: z.number() }).parse(await fresh.json());
          if (!active) return;
          setResult(`재확인: 정상 ${counts.pass} · 주의 ${counts.warn} · 지연 ${counts.fail}. 작업 완료 후에도 원본 데이터가 오래되면 지연이 남습니다.`);
          router.refresh();
          window.dispatchEvent(new Event("nuri-data-refreshed"));
        }
      } catch {
        if (active) setError("갱신 상태를 확인하지 못했습니다. 자동으로 다시 조회합니다. 요청한 작업은 서버에서 계속될 수 있습니다.");
      } finally {
        if (active) timer = setTimeout(update, 5000);
      }
    }
    void update();
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [delayedKey, router]);

  async function start() {
    setSending(true); setError(""); setResult("");
    try {
      const response = await fetch("/api/pipeline/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jobs: selected }), signal: AbortSignal.timeout(10000) });
      if (!response.ok) {
        setError(response.status === 401 || response.status === 403 ? "실행 권한이 필요합니다. API 인증 상태를 확인해 주세요." : response.status === 409 ? "이미 갱신 작업이 실행 중입니다. 진행 상태를 확인하세요." : "갱신 요청을 처리하지 못했습니다. 진행 상태를 확인한 후 다시 시도하세요.");
        return;
      }
      const run = runSchema.parse(await response.json());
      setCatalog(value => value ? { ...value, run } : value);
    } catch { setError("서버 응답을 확인하지 못했습니다. 중복 요청 전에 진행 상태를 확인하세요."); }
    finally { setSending(false); }
  }
  const unsupported = delayedKeys.filter(key => catalog && !catalog.jobs.some(job => job.keys.includes(key)));
  return <>
    <p>수집 또는 재계산할 작업을 선택하세요. 주가 → 지표 → 종합 분석 순서로 실행합니다. 기술 지표가 오래되었다면 주가도 함께 수집하세요.</p>
    <p className={styles.basis}>합의·판정·성과 기록은 예약 작업과 운영 원장에서 관리합니다. 이 갱신으로 새 투자 판단이 생성되지는 않습니다.</p>
    {!catalog && <p role="status">갱신 가능한 작업을 불러오는 중입니다.</p>}
    {catalog?.jobs.map(job => <label key={job.id} className={styles.refreshJob}><input type="checkbox" checked={selected.includes(job.id)} disabled={!!activeRun || sending} onChange={e => setSelected(value => e.target.checked ? [...value, job.id] : value.filter(id => id !== job.id))} /><span><b>{job.label}</b><small>{job.description}</small></span><span>{labels[catalog.run?.jobs.find(item => item.id === job.id)?.status ?? ""]}</span></label>)}
    {!!unsupported.length && <p className={styles.caution}>일부 지연 소스는 이 화면에서 직접 갱신하지 않습니다. 파이프라인 상세에서 예약 작업과 원본 소스를 확인하세요.</p>}
    <div className={styles.refreshActions}><button type="button" className={styles.button} disabled={!catalog || !selected.length || !!activeRun || sending} onClick={() => void start()}>{sending ? "요청 중…" : activeRun ? "갱신 진행 중…" : "선택한 데이터 갱신"}</button><Link href="/pipeline" className={styles.textLink}>파이프라인 상세 ↗</Link></div>
    {catalog?.run && <p role="status">최근 요청 · {labels[catalog.run.status] ?? catalog.run.status}</p>}
    {result && <p role="status">{result}</p>}
    {error && <p role="alert" className={styles.caution}>{error}</p>}
    <p className={styles.basis}>여러 분이 걸릴 수 있습니다. 진행 내역은 현재 API 프로세스 기준이며 재시작 시 초기화됩니다. 요약 수치는 서버 캐시 만료 후 반영될 수 있습니다.</p>
  </>;
}
