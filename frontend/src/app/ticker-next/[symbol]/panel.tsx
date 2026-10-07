import type { ReactNode } from "react";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import { lookup } from "@/lib/utils";
import styles from "./ticker.module.css";

export function Panel({ title, icon, children, note, collapsibleNote = false, headingLevel = 2 }: { title: string; icon?: ReactNode; children: ReactNode; note?: string; collapsibleNote?: boolean; headingLevel?: 2 | 3 }) {
  return <section className={styles.panel}><header className={styles.panelHeading}>{headingLevel === 3 ? <h3>{icon}{title}</h3> : <h2>{icon}{title}</h2>}</header><div className={styles.panelBody}>{children}</div>{note && (collapsibleNote ? <details className={styles.footnote}><summary>{T.READING_NOTES}</summary><p>{note}</p></details> : <p className={styles.footnote}>{note}</p>)}</section>;
}

export function ActionLabel({ action }: { action?: string | null }) {
  const tone = action === "BUY" || action === "LONG" ? "positive" : action === "SELL" || action === "FLAT" ? "danger" : action === "REBALANCE" || action === "TRIM" || action === "HEDGE" ? "warning" : "neutral";

  const label = action ? lookup(T.ACTION_LABELS, action) : null;

  return <span className={styles.badge} data-tone={tone}>{label && <span>{label} · </span>}<span>{action || T.NOT_PROVIDED}</span></span>;
}

