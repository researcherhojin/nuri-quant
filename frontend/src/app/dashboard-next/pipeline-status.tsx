"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, RefreshCw, Workflow } from "lucide-react";
import { DASHBOARD_NEXT as COPY } from "@/lib/strings";
import { pipelineSchema, schedulerSchema, type Pipeline } from "./pipeline-contract";
import { RefreshDialog } from "./refresh-dialog";
import { DetailDialog } from "./detail-dialog";
import { displayShortTime, displayTime } from "./format";
import styles from "./dashboard.module.css";
import { lookup } from "@/lib/utils";

const T = COPY.PIPELINE_PANEL;

/** 조회 시각 표시 — ISO 문자열을 KST hh:mm 으로. */
function checkedLabel(checkedAt: string | null) {
  if (!checkedAt) return T.CHECK_PENDING;

  return T.CHECKED_AT(new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(checkedAt)));
}

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
        request("/api/pipeline/status").then((value) => pipelineSchema.parse(value)),
        request("/api/scheduler/health").then((value) => schedulerSchema.parse(value)),
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

  const footerStatus = failed ? T.STALE : health ? lookup(T.SCHEDULER, health) || T.SCHEDULER_OTHER(health) : T.SCHEDULER_PENDING;

  return (
    <section className={styles.panel} aria-label={T.ARIA}>
      <div className={styles.panelHeading}>
        <h2><Workflow size={14} />{COPY.PIPELINE}</h2>
        <div className={styles.pipelineControls}>
          <Link href="/pipeline" className={styles.textLink}>{T.DETAIL} <ArrowUpRight size={14} /></Link>
          <button type="button" aria-label={T.RELOAD_ARIA} title={T.RELOAD_TITLE} disabled={loading} onClick={() => setRefreshKey((key) => key + 1)}>
            <RefreshCw size={12} className={loading ? styles.refreshing : undefined} />
          </button>
        </div>
      </div>
      <div className={styles.panelBody}>
        {pipeline?.steps.length ? pipeline.steps.map((step) => (
          <div className={styles.pipelineRow} key={step.step}>
            <span className={styles.statusDot} data-tone={step.status === "error" ? "danger" : step.status === "running" ? "positive" : "neutral"} />
            <span title={step.label}>{lookup(T.STAGES, step.step) || step.label}</span>
            {/* 모든 스테이지가 같은 형식(MM-DD HH:mm KST) — decide 는 판정일이 아니라 그 판정일 행이 처음 기록된 시각 (#1675) */}
            <small title={displayTime(step.step === "decide" ? step.artifact?.recorded_at : step.last_updated)}>
              {displayShortTime(step.step === "decide" ? step.artifact?.recorded_at : step.last_updated) || (step.step === "decide" ? step.artifact?.date?.slice(5) || T.NO_LEDGER_DATE : T.NO_EVENT)}
            </small>
            <span className={styles.pipelineStatus}>
              {step.step === "decide" ? (
                <DetailDialog
                  label={step.status === "error" ? T.DECIDE_ERROR : step.artifact?.status === "available" ? T.DECIDE_COUNT(step.artifact.count ?? 0) : T.DECIDE_CHECK}
                  title={T.DECIDE_TITLE}
                >
                  <p>{T.DECIDE_GUIDE}</p>
                  <p>{T.DECIDE_LEDGER(step.artifact?.date || T.NOT_PROVIDED, step.artifact?.count == null ? "—" : String(step.artifact.count))}</p>
                  <p>{T.DECIDE_EVENT(lookup(T.EVENTS, step.status) || step.status, displayTime(step.last_updated))}</p>
                  <p>{T.DECIDE_CAVEAT}</p>
                  <Link href="/decisions" className={styles.textLink}>{T.LEDGER_LINK} <ArrowUpRight size={14} /></Link>
                </DetailDialog>
              ) : lookup(T.EVENTS, step.status) || step.status}
            </span>
          </div>
        )) : <p className={styles.empty}>{pipeline ? T.EMPTY : T.UNAVAILABLE}</p>}
      </div>
      <div className={styles.panelFooter}>
        <p role="status" className={failed || health !== "ok" ? styles.pipelineWarning : undefined}>{footerStatus}</p>
        <div className={styles.pipelineChecked} title={T.CHECKED_TITLE(displayTime(checkedAt))}>
          {checkedLabel(checkedAt)}
          <RefreshDialog delayedKeys={delayedKeys} />
        </div>
      </div>
    </section>
  );
}
