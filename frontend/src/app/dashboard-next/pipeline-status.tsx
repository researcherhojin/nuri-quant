"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw, Workflow } from "lucide-react";
import { pipelineSchema, schedulerSchema, type Pipeline } from "./pipeline-contract";
import { RefreshDialog } from "./refresh-dialog";
import { DetailDialog } from "./detail-dialog";
import { displayTime } from "./format";
import styles from "./dashboard.module.css";

const stageLabels: Record<string, string> = { collect: "데이터 수집", analyze: "지표 분석", consensus: "의견 종합", decide: "판정 기록", track: "결과 추적" };
const labels: Record<string, string> = { done: "성공 기록", success: "성공 기록", running: "실행 중", error: "오류", idle: "대기" };
const healthLabels: Record<string, string> = { ok: "스케줄러 정상", stale: "스케줄러 응답 지연", unknown: "스케줄러 확인 불가", error: "스케줄러 조회 오류", unavailable: "스케줄러 연결 실패" };

export function PipelineStatus({ initial, delayedKeys = [] }: { initial: Pipeline | null; delayedKeys?: string[] }) {
  const [pipeline, setPipeline] = useState(initial);
  const [health, setHealth] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    let pending = false;
    let controller: AbortController | null = null;
    const refresh = async () => {
      if (pending || document.visibilityState === "hidden") return;
      pending = true;
      setLoading(true);
      controller = new AbortController();
      const signal = controller.signal;
      const timeout = setTimeout(() => controller?.abort(), 10000);
      const request = async (path: string) => {
        const response = await fetch(path, { cache: "no-store", signal });
        if (!response.ok) throw new Error("Status unavailable");
        return response.json();
      };
      const [steps, scheduler] = await Promise.allSettled([
        request("/api/pipeline/status").then(value => pipelineSchema.parse(value)),
        request("/api/scheduler/health").then(value => schedulerSchema.parse(value)),
      ]);
      clearTimeout(timeout);
      pending = false;
      if (!active) return;
      if (steps.status === "fulfilled") {
        setPipeline(steps.value);
        setCheckedAt(new Date().toISOString());
        setFailed(false);
      } else {
        setFailed(true);
      }
      setHealth(scheduler.status === "fulfilled" ? scheduler.value.status : "unavailable");
      setLoading(false);
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 60000);
    const visible = () => { if (document.visibilityState === "visible") void refresh(); };
    document.addEventListener("visibilitychange", visible);
    window.addEventListener("nuri-data-refreshed", visible);
    return () => {
      active = false;
      clearInterval(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", visible);
      window.removeEventListener("nuri-data-refreshed", visible);
    };
  }, [refreshKey]);

  return (
    <section className={styles.panel} aria-label="파이프라인 실행 상태">
      <div className={styles.panelHeading}>
        <h2><Workflow size={14} />파이프라인 상태</h2>
        <div className={styles.pipelineControls}>
          <Link href="/pipeline" className={styles.textLink}>상세 ↗</Link>
          <button type="button" aria-label="파이프라인 상태 새로고침" title="상태만 조회 · 작업 재실행 아님" disabled={loading} onClick={() => setRefreshKey(key => key + 1)}><RefreshCw size={12} className={loading ? styles.refreshing : undefined} /></button>
        </div>
      </div>
      <div className={styles.panelBody}>
        {pipeline?.steps.length ? pipeline.steps.map(step => (
          <div className={styles.pipelineRow} key={step.step}>
            <span className={styles.statusDot} data-tone={step.status === "error" ? "danger" : step.status === "running" ? "positive" : "neutral"} />
            <span title={step.label}>{stageLabels[step.step] || step.label}</span>
            <small title={displayTime(step.last_updated)}>{step.step === "decide" ? step.artifact?.date || "원장 미확인" : step.last_updated?.slice(5, 16).replace("T", " ") || "기록 없음"}</small>
            <span className={styles.pipelineStatus}>{step.step === "decide" ? <DetailDialog label={step.status === "error" ? "실행 오류" : step.artifact?.status === "available" ? `${step.artifact.count}건 기록` : "확인 필요"} title="판정 기록 상태"><p>판정 기록(Decide)은 별도 예약 작업이 없습니다. 의견 종합(Consensus) 작업 안에서 결과를 원장에 저장합니다.</p><p>최근 원장 기준일: {step.artifact?.date || "미확인"} · 기록 {step.artifact?.count ?? "—"}건</p><p>실행 이벤트: {labels[step.status] || step.status} · {displayTime(step.last_updated)}</p><p>기록이 있다는 사실이 최신 판단이나 품질을 보장하지 않습니다. 표시한 날짜는 현재 연결된 DB의 판정 기준일입니다. 개발 DB는 운영 원장의 읽기 복제본이므로 갱신·동기화 상태를 함께 확인하세요.</p><Link href="/decisions" className={styles.textLink}>판정 원장 확인 ↗</Link></DetailDialog> : labels[step.status] || step.status}</span>
          </div>
        )) : <p className={styles.empty}>{pipeline ? "실행 기록 없음" : "실행 상태 확인 불가"}</p>}
      </div>
      <div className={styles.panelFooter}>
        <p role="status" className={failed || health !== "ok" ? styles.pipelineWarning : undefined}>{failed ? "갱신 실패 · 이전 기록 표시" : health ? healthLabels[health] || `스케줄러 ${health}` : "스케줄러 확인 중"}</p>
        <div className={styles.pipelineChecked} title={`마지막 상태 조회 ${displayTime(checkedAt)} · 마지막 실행 결과는 데이터 신선도와 별개입니다.`}>{checkedAt ? `조회 ${new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(checkedAt))} KST` : "조회 대기"}<RefreshDialog delayedKeys={delayedKeys} /></div>
      </div>
    </section>
  );
}
