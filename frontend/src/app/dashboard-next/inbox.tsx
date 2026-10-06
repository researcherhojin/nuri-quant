"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, ChevronRight } from "lucide-react";
import type { Actions } from "./data";
import { displayChange, displayNumber, displayTime } from "./format";
import { DASHBOARD_NEXT as COPY } from "@/lib/strings";
import styles from "./dashboard.module.css";

const buckets = ["urgent", "check", "portfolio", "hold"] as const;
export type Bucket = typeof buckets[number];
const labels = { urgent: "우선 확인", check: "검토", portfolio: "포트폴리오 규칙", hold: "유지" };

export function Inbox({ actions, initialBucket }: { actions: Actions | null; initialBucket: Bucket }) {
  const [bucket, setBucket] = useState(initialBucket);
  const [index, setIndex] = useState(0);
  const items = actions?.[bucket] ?? [];
  const selected = items[index];

  return (
    <>
      <div className={styles.tabs} role="group" aria-label="판단 목록 필터">
        {buckets.map((key) => (
          <button key={key} type="button" aria-pressed={bucket === key} onClick={() => { setBucket(key); setIndex(0); }}>
            {labels[key]} <span>{actions ? actions[key].length : "—"}</span>
          </button>
        ))}
      </div>
      {!actions ? <p className={styles.empty}>{COPY.UNAVAILABLE}</p> : !selected ? (
        <p className={styles.empty}>{labels[bucket]} 목록에 현재 표시할 항목이 없습니다.</p>
      ) : (
        <div className={styles.inbox}>
          <div className={styles.queue} role="group" aria-label={`${labels[bucket]} 종목 선택`}>
            {items.map((item, itemIndex) => (
              <button key={`${item.ticker}-${item.account}-${itemIndex}`} type="button" aria-pressed={index === itemIndex} onClick={() => setIndex(itemIndex)}>
                <span className={styles.queueNumber}>{String(itemIndex + 1).padStart(2, "0")}</span>
                <span><strong>{item.name || item.ticker}</strong><small>{item.ticker}{item.account ? ` · ${item.account}` : ""}</small></span>
                <span className={styles.badge} data-tone={bucket === "urgent" ? "danger" : bucket === "portfolio" ? "warning" : "neutral"}>{item.action}</span>
                <ChevronRight size={14} aria-hidden="true" />
              </button>
            ))}
          </div>
          <article className={styles.evidence} aria-label="선택한 판단 근거" aria-live="polite">
            <div className={styles.sectionHeading}>
              <div><h3>{selected.name || selected.ticker}</h3></div>
              <Link href={`/ticker/${encodeURIComponent(selected.ticker)}`} className={styles.textLink}>종목 상세 <ArrowUpRight size={14} /></Link>
            </div>
            <p className={styles.basis}>판정 기준일 · {displayTime(selected.as_of)}</p>
            <ul className={styles.reasons}>{selected.reasons.length ? selected.reasons.map((reason, i) => <li key={i}>{reason}</li>) : <li>판단 근거 미제공</li>}</ul>
            <dl className={styles.evidenceMetrics}>
              <div><dt>보유 비중</dt><dd>{displayNumber(selected.position_pct, "%")}</dd></div>
              <div><dt>평가 손익률</dt><dd className={styles.change} data-direction={selected.pnl_pct == null ? "unknown" : selected.pnl_pct > 0 ? "up" : selected.pnl_pct < 0 ? "down" : "flat"}>{displayChange(selected.pnl_pct)}</dd></div>
              <div><dt>시스템 신뢰도</dt><dd>{displayNumber(selected.confidence, "%")}</dd></div>
            </dl>
            <div className={styles.axes}>
              <span>기대수익 신호 <b>{selected.alpha_action || "미제공"}</b></span>
              <span>포트폴리오 신호 <b>{selected.portfolio_action || "미제공"}</b></span>
            </div>
            {selected.decision_id != null ? <Link href={`/decisions/${selected.decision_id}`} className={styles.evidenceLink}>판정 원장에서 전체 근거 확인 <ArrowUpRight size={14} /></Link> : <p className={styles.basis}>연결된 판정 원장 기록이 없습니다.</p>}
          </article>
        </div>
      )}
      <p className={styles.panelFooter}>목록 생성 · {displayTime(actions?.generated_at)}</p>
    </>
  );
}
