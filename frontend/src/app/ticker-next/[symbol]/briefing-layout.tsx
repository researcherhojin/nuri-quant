import type { ReactNode } from "react";
import type { TickerReview } from "./data";
import { CurrentJudgment, PriceSummary } from "./decision-briefing";
import { ReportFrame, ReportSection } from "./report-frame";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import { displayTime } from "@/app/(overview)/format";
import styles from "./ticker.module.css";

export function BriefingLayout({ data, symbol, intro, points, risks, news }: { data: TickerReview; symbol: string; intro: ReactNode; points: ReactNode; risks: ReactNode; news: ReactNode }) {
  const dossier = data.research?.dossier;

  return <ReportFrame header={<p className={styles.muted}>{T.COLLECTED} · {displayTime(dossier?.collected_at)}</p>}>
    <ReportSection id="summary"><p>{dossier?.business?.summary || dossier?.profile.name || T.NO_PROFILE}</p></ReportSection>
    <ReportSection id="business">{intro}</ReportSection>
    <ReportSection id="changes">{news}</ReportSection>
    <ReportSection id="financials">{points}</ReportSection>
    <ReportSection id="outlook">{risks}</ReportSection>
    <ReportSection id="schedule">{data.research?.events.length ? data.research.events.map((event, index) => <p key={index}>{event.date} · {event.description || T.NOT_PROVIDED}</p>) : <p className={styles.muted}>{T.DOCUMENT_NO_SCHEDULE}</p>}</ReportSection>
    <ReportSection id="judgment"><CurrentJudgment data={data} compact /><PriceSummary data={data} symbol={symbol} compact /></ReportSection>
  </ReportFrame>;
}
