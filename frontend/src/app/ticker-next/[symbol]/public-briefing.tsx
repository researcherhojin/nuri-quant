import type { TickerReview } from "./data";
import type { BriefingPassage, PublicBriefingData } from "./public-briefing-schema";
import { CurrentJudgment, PriceSummary } from "./decision-briefing";
import { GenerateBriefing } from "./generate-briefing";
import { FinancialReading } from "./financial-reading";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import { displayTime } from "@/app/(overview)/format";
import { sourceUrl } from "./research-format";
import { ReportFrame, ReportSection } from "./report-frame";
import styles from "./ticker.module.css";

function References({ passage, briefing }: { passage: BriefingPassage; briefing: PublicBriefingData }) {
  const claims = briefing.claims?.filter(claim => passage.claim_ids.includes(claim.claim_id)) ?? [];

  return <details className={styles.evidenceDetails}><summary>{T.BRIEFING_EVIDENCE}</summary><div className={styles.evidenceList}>{claims.map(claim => {
    const source = briefing.sources?.find(item => item.source_id === claim.source_id);
    const url = sourceUrl(source?.url);

    return <div key={claim.claim_id} className={styles.claimEvidence}><p><strong>{T.BRIEFING_KINDS[claim.kind]}</strong> · {claim.entity}{claim.period && ` · ${claim.period}`}</p><p>{claim.statement}</p>{source && url && <a className={styles.link} href={url} target="_blank" rel="noreferrer">{source.title} · {source.published_at || T.BRIEFING_UNDATED(displayTime(source.collected_at))}</a>}</div>;
  })}</div></details>;
}

function Paragraph({ passage, briefing }: { passage: BriefingPassage; briefing: PublicBriefingData }) {
  return <><p>{passage.text}</p><References passage={passage} briefing={briefing} /></>;
}

export function BriefingGeneration({ data, symbol }: { data: TickerReview; symbol: string }) {
  const briefing = data.research?.public_briefing;

  return <div className={styles.briefingGeneration}><div><strong>{T.BRIEFING_TITLE}</strong><p className={styles.muted}>{briefing?.message || T.BRIEFING_INTRO}</p></div><GenerateBriefing symbol={symbol} status={briefing?.status} /></div>;
}

export function PublicBriefing({ data, symbol, briefing }: { data: TickerReview; symbol: string; briefing: PublicBriefingData }) {
  const report = briefing.report;

  if (briefing.status !== "ready" || !report) return null;

  return <ReportFrame header={<><p className={styles.muted}>{T.BRIEFING_TIMES(displayTime(briefing.collected_at), displayTime(briefing.generated_at))}</p><p className={styles.muted}>{briefing.coverage && T.BRIEFING_COVERAGE(briefing.coverage.official, briefing.coverage.news, briefing.coverage.snapshot)}{briefing.coverage?.official === 0 && T.BRIEFING_NO_IR}</p><details className={styles.evidenceDetails}><summary>{T.DOCUMENT_BASIS}</summary><p>{briefing.rejected_claim_count ? T.BRIEFING_REJECTED(briefing.rejected_claim_count) : ""}{T.BRIEFING_CHECKED}</p></details></>}>
      <ReportSection id="summary"><Paragraph passage={report.summary} briefing={briefing} /></ReportSection>
      <ReportSection id="business"><p className={styles.muted}>{data.research?.dossier?.profile.name} · {symbol}</p><Paragraph passage={report.business} briefing={briefing} />{data.research?.dossier?.profile.description && <details className={styles.business}><summary>{T.BUSINESS_ORIGINAL}</summary><p>{data.research.dossier.profile.description}</p></details>}<a className={styles.link} href={`https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}/profile/`} target="_blank" rel="noreferrer">{T.SOURCE} · {T.YAHOO}</a></ReportSection>
      <ReportSection id="changes"><Paragraph passage={report.changes} briefing={briefing} /></ReportSection>
      <ReportSection id="financials"><Paragraph passage={report.financials} briefing={briefing} /><FinancialReading data={data} /></ReportSection>
      <ReportSection id="outlook">{report.arguments.map((argument, index) => <div key={`${index}-${argument.title}`} className={styles.researchArgument}><h3>{argument.title}</h3><p>{argument.fact.text}</p><dl><div><dt>{T.BRIEFING_IMPACT}</dt><dd><p>{argument.impact.text}</p></dd></div><div><dt>{T.BRIEFING_COUNTER}</dt><dd><p>{argument.counterpoint.text}</p></dd></div><div><dt>{T.BRIEFING_CHECKPOINT}</dt><dd><p>{argument.checkpoint.text}</p></dd></div><div><dt>{T.BRIEFING_TIMING}</dt><dd><p>{argument.timing.text}</p></dd></div></dl><References passage={{ text: argument.fact.text, claim_ids: [...new Set([argument.fact, argument.impact, argument.counterpoint, argument.checkpoint, argument.timing].flatMap(passage => passage.claim_ids))] }} briefing={briefing} /></div>)}</ReportSection>
      <ReportSection id="schedule"><Paragraph passage={report.schedule} briefing={briefing} /></ReportSection>
      <ReportSection id="judgment"><CurrentJudgment data={data} compact /><PriceSummary data={data} symbol={symbol} compact /></ReportSection>
      <footer className={styles.footnote}>{T.BRIEFING_FOOTER(briefing.model)}</footer>
  </ReportFrame>;
}
