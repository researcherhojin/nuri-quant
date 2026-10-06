"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, ChevronRight } from "lucide-react";
import type { Actions } from "./data";
import { displayChange, displayNumber, displayTime } from "./format";
import { OVERVIEW as COPY } from "@/lib/strings";
import styles from "./dashboard.module.css";

const buckets = ["urgent", "check", "portfolio", "hold"] as const;

export type Bucket = typeof buckets[number];

const T = COPY.INBOX_PANEL;

export function Inbox({ actions, initialBucket }: { actions: Actions | null; initialBucket: Bucket }) {
  const [bucket, setBucket] = useState(initialBucket);
  const [index, setIndex] = useState(0);
  const items = actions?.[bucket] ?? [];
  // 갱신으로 목록이 줄면 선택을 마지막 항목으로 되돌린다 — 안 그러면 남은 항목이 있어도 "없음" 으로 보인다 (Codex #1658 P2)
  const safeIndex = Math.min(index, Math.max(items.length - 1, 0));
  const selected = items[safeIndex];

  return (
    <>
      <div className={styles.tabs} role="group" aria-label={T.FILTER_ARIA}>
        {buckets.map((key) => (
          <button key={key} type="button" aria-pressed={bucket === key} onClick={() => { setBucket(key); setIndex(0); }}>
            {T.BUCKETS[key]} <span>{actions ? actions[key].length : "—"}</span>
          </button>
        ))}
      </div>
      {!actions ? <p className={styles.empty}>{COPY.UNAVAILABLE}</p> : !selected ? (
        <p className={styles.empty}>{T.BUCKET_EMPTY(T.BUCKETS[bucket])}</p>
      ) : (
        <div className={styles.inbox}>
          <div className={styles.queue} role="group" aria-label={T.QUEUE_ARIA(T.BUCKETS[bucket])}>
            {items.map((item, itemIndex) => (
              <button key={`${item.ticker}-${item.account}-${itemIndex}`} type="button" aria-pressed={safeIndex === itemIndex} onClick={() => setIndex(itemIndex)}>
                <span className={styles.queueNumber}>{String(itemIndex + 1).padStart(2, "0")}</span>
                <span><strong>{item.name || item.ticker}</strong><small>{item.ticker}{item.account ? ` · ${item.account}` : ""}</small></span>
                <span className={styles.badge} data-tone={bucket === "urgent" ? "danger" : bucket === "portfolio" ? "warning" : "neutral"}>{item.action}</span>
                <ChevronRight size={14} aria-hidden="true" />
              </button>
            ))}
          </div>
          <article className={styles.evidence} aria-label={T.EVIDENCE_ARIA} aria-live="polite">
            <div className={styles.sectionHeading}>
              <div><h3>{selected.name || selected.ticker}</h3></div>
              <Link href={`/ticker/${encodeURIComponent(selected.ticker)}`} className={styles.textLink}>{T.TICKER_DETAIL} <ArrowUpRight size={14} /></Link>
            </div>
            <p className={styles.basis}>{T.AS_OF}{displayTime(selected.as_of)}</p>
            <ul className={styles.reasons}>{selected.reasons.length ? selected.reasons.map((reason, i) => <li key={i}>{reason}</li>) : <li>{T.NO_REASONS}</li>}</ul>
            <dl className={styles.evidenceMetrics}>
              <div><dt>{T.POSITION}</dt><dd>{displayNumber(selected.position_pct, "%")}</dd></div>
              <div><dt>{T.PNL}</dt><dd className={styles.change} data-direction={selected.pnl_pct == null ? "unknown" : selected.pnl_pct > 0 ? "up" : selected.pnl_pct < 0 ? "down" : "flat"}>{displayChange(selected.pnl_pct)}</dd></div>
              <div><dt>{T.CONFIDENCE}</dt><dd>{displayNumber(selected.confidence, "%")}</dd></div>
            </dl>
            <div className={styles.axes}>
              <span>{T.ALPHA_AXIS} <b>{selected.alpha_action || T.NOT_PROVIDED}</b></span>
              <span>{T.PORTFOLIO_AXIS} <b>{selected.portfolio_action || T.NOT_PROVIDED}</b></span>
            </div>
            {selected.decision_id != null
              ? <Link href={`/decisions/${selected.decision_id}`} className={styles.evidenceLink}>{T.LEDGER_LINK} <ArrowUpRight size={14} /></Link>
              : <p className={styles.basis}>{T.NO_LEDGER}</p>}
          </article>
        </div>
      )}
      <p className={styles.panelFooter}>{T.GENERATED}{displayTime(actions?.generated_at)}</p>
    </>
  );
}
