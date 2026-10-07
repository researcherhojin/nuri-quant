import type { ReactNode } from "react";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import styles from "./ticker.module.css";

export type ReportSectionId = keyof typeof T.DOCUMENT_SECTIONS;

export function ReportSection({ id, children }: { id: ReportSectionId; children: ReactNode }) {
  return <section id={`research-${id}`}><h2>{T.DOCUMENT_SECTIONS[id]}</h2>{children}</section>;
}

export function ReportFrame({ header, children }: { header: ReactNode; children: ReactNode }) {
  return <div className={`${styles.reportLayout} ${styles.sourceReportLayout}`}>
    <article className={`${styles.report} ${styles.sourceReport}`} data-testid="ticker-briefing" aria-label={T.BRIEF}>
      <header className={styles.sourceReportHeader}><h2>{T.DOCUMENT_TITLE}</h2>{header}</header>
      {children}
    </article>
    <nav className={styles.reportIndex} aria-label={T.DOCUMENT_INDEX}><p>{T.DOCUMENT_INDEX}</p>{Object.entries(T.DOCUMENT_SECTIONS).map(([id, label]) => <a key={id} href={`#research-${id}`}>{label}</a>)}</nav>
  </div>;
}
