import { Building2, Layers3, ShieldAlert } from "lucide-react";
import type { TickerReview } from "./data";
import { ReportFrame, ReportSection } from "./report-frame";
import { CurrentJudgment, PriceSummary } from "./decision-briefing";
import { displayTime } from "@/app/(overview)/format";
import type { ReactNode } from "react";
import { Panel } from "./panel";
import { amount, sourceUrl } from "./research-format";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import { formatNum } from "@/lib/format";
import { lookup } from "@/lib/utils";
import styles from "./ticker.module.css";

export function FundBriefing({ data, symbol = data.research?.ticker || "", news, details = false }: { data: TickerReview; symbol?: string; news?: ReactNode; details?: boolean }) {
  const dossier = data.research?.dossier;
  const fund = dossier?.fund;
  const profile = dossier?.profile;
  const holdings = fund?.holdings ?? [];
  const top = holdings.slice(0, 3);
  const totalHoldings = holdings.reduce((sum, item) => sum + item.weight_pct, 0);
  const total = top.reduce((sum, item) => sum + item.weight_pct, 0);
  const source = sourceUrl(fund?.source_url);
  const prospectus = sourceUrl(fund?.prospectus_url);

  const risks = fund?.risks.flatMap(risk => {
    const explanation = lookup(T.RISK_GLOSSARY, risk.title);

    return explanation ? [{ ...explanation, original: risk.text }] : [];
  }) ?? [];

  const intro = <Panel title={T.FUND_INTRO} icon={<Building2 size={17} />} headingLevel={3} note={T.FUND_NOTE} collapsibleNote>
      <p className={styles.muted}>{profile?.name} · {profile?.symbol} · ETF · {profile?.exchange || T.NOT_PROVIDED}</p>
      {!fund && <p className={styles.empty}>{T.FUND_DATA_MISSING}</p>}
      {fund?.benchmark ? <dl className={styles.companyMetrics}><div><dt>{T.ISSUER}</dt><dd>{fund.issuer || "—"}</dd></div><div><dt>{T.EXPENSE}</dt><dd>{fund.expense_pct == null ? "—" : `${formatNum(fund.expense_pct, 2)}%`}</dd></div><div><dt>{T.BENCHMARK}</dt><dd>{fund.benchmark}</dd></div><div><dt>{T.NAV}</dt><dd>{amount(fund.nav, fund.currency)}</dd></div></dl> : <dl className={styles.companyMetrics}>
        <div><dt>{T.AUM}</dt><dd title={amount(fund?.aum, fund?.currency)}>{fund?.aum == null ? "—" : `${new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 2 }).format(fund.aum)}${fund.currency ? ` ${fund.currency}` : ""}`}</dd></div>
        <div><dt>{T.EXPENSE}</dt><dd>{fund?.expense_pct == null ? "—" : `${formatNum(fund.expense_pct, 2)}%`}</dd></div>
        <div><dt>{T.INCEPTION}</dt><dd>{fund?.inception || "—"}</dd></div>
        <div><dt>{T.HOLDING_COUNT}</dt><dd>{formatNum(fund?.holding_count, 0)}</dd></div>
      </dl>}
      <p className={styles.muted}>{T.FUND_DETAILS_DATE} · {fund?.details_as_of || T.UNKNOWN_DATE}</p>
      <div className={styles.introSources}>{profile?.description && <details className={styles.business}><summary>{T.BUSINESS_ORIGINAL}</summary><p>{profile.description}</p></details>}
      {source && <a className={styles.link} href={source} target="_blank" rel="noreferrer">{T.SOURCE} · {fund?.source_name}</a>}</div>
    </Panel>;

  const points = <Panel title={T.POINTS} icon={<Layers3 size={17} />} headingLevel={3} note={T.CONCENTRATION_NOTE} collapsibleNote>
      {top.length ? <>
        <p className={styles.highlight}>{T.FUND_CONCENTRATION(top.length, formatNum(total, 2))}</p>
        <p className={styles.readingText}>{T.FUND_CONCENTRATION_EXPLAIN}</p>
        <ul className={styles.weightList}>{top.map(item => <li key={item.name}><div><span>{item.name}</span><strong>{formatNum(item.weight_pct, 2)}%</strong></div><div className={styles.weightTrack} aria-hidden="true"><span style={{ width: `${item.weight_pct}%` }} /></div></li>)}</ul>
        <p className={styles.muted}>{T.HOLDINGS_DATE} · {fund?.holdings_as_of || T.UNKNOWN_DATE}</p>
      </> : fund?.benchmark ? <><p className={styles.lead}>{T.FUND_BENCHMARK(fund.benchmark)}</p><p className={styles.muted}>{T.FUND_HOLDINGS_UNAVAILABLE}</p></> : <p className={styles.empty}>{T.FUND_DATA_MISSING}</p>}
      {fund?.expense_pct != null && <div className={styles.costNote}><span>{T.EXPENSE}</span><strong>{formatNum(fund.expense_pct, 2)}%</strong><p>{T.FUND_COST_EXPLAIN}</p></div>}
      {!!fund?.highlights?.length && <div className={styles.businessProfiles}>
        <h3 className={styles.subheading}>{T.HIGHLIGHT_BUSINESSES}</h3>
        <p className={styles.muted}>{T.HIGHLIGHT_NOTE}</p>
        {fund.highlights.map(item => <article key={item.symbol}><h4>{item.name} <span className={styles.muted}>{item.symbol}</span></h4>{item.explanation && <p>{item.explanation}</p>}<details className={styles.business}><summary>{T.BUSINESS_EXCERPT}</summary><p>{item.description}</p></details></article>)}
      </div>}
      {fund?.exposure_text && <div className={styles.exposure}><h3 className={styles.subheading}>{T.EXPOSURE}</h3><p>{fund.exposure_text}</p><p className={styles.muted}>{T.FAQ_DATE} · {fund.faq_as_of || T.UNKNOWN_DATE}</p></div>}
      {fund?.source_consistency_issue && <p className={styles.notice}>{T.SOURCE_CONSISTENCY}</p>}
      {!!fund?.faq?.length && <details className={styles.business}><summary>{T.FAQ_ORIGINAL}</summary>{fund.faq.map(item => <article key={item.question}><h4>{item.question}</h4><p>{item.answer}</p></article>)}</details>}
    </Panel>;

  const riskPanel = <Panel title={T.RISK_FACTS} icon={<ShieldAlert size={17} />} headingLevel={3} note={T.EXPENSE_NOTE} collapsibleNote>
      {!!fund?.structure_notes?.length && <div className={styles.factProse}><h3 className={styles.subheading}>{T.FUND_STRUCTURE}</h3>{fund.structure_notes.map(note => <p key={note}>{note}</p>)}</div>}
      {risks.length ? <div className={styles.riskGrid}>{risks.map(risk => <article key={risk.title}><h3 className={styles.subheading}>{risk.title}</h3><p>{risk.text}</p></article>)}</div> : !fund?.structure_notes?.length && <p className={styles.empty}>{T.NO_RISK_FACT}</p>}
      {!!risks.length && <details className={styles.business}><summary>{T.RISK_ORIGINAL}</summary>{risks.map(risk => <p key={risk.title}>{risk.original}</p>)}</details>}
      <div className={styles.sourceLinks}>{source && <a className={styles.link} href={source} target="_blank" rel="noreferrer">{fund?.benchmark ? T.FUND_SOURCE : T.OFFICIAL}</a>}{prospectus && <a className={styles.link} href={prospectus} target="_blank" rel="noreferrer">{T.PROSPECTUS}</a>}</div>
    </Panel>;

  const valuation = <Panel headingLevel={details ? 2 : 3} title={T.VALUATION} note={`${T.DATE} · ${fund?.valuation_as_of || T.UNKNOWN_DATE}`}>
      {fund?.benchmark ? <><dl className={styles.fundamentals}><div><dt>{T.NAV}</dt><dd>{amount(fund.nav, fund.currency)}</dd></div><div><dt>{T.DEVIATION}</dt><dd>{fund.deviation_pct == null ? "—" : `${formatNum(fund.deviation_pct, 2)}%`}</dd></div></dl><p className={styles.muted}>{T.FUND_SNAPSHOT_NOTE}</p></> : <><dl className={styles.fundamentals}><div><dt>PER</dt><dd>{formatNum(fund?.pe)}</dd></div><div><dt>{T.PBR}</dt><dd>{formatNum(fund?.pb)}</dd></div><div><dt>{T.PSR}</dt><dd>{formatNum(fund?.ps)}</dd></div></dl><p className={styles.lead}>{T.FUND_VALUATION_NOTE}</p></>}
      {source && <a className={styles.link} href={source} target="_blank" rel="noreferrer">{T.SOURCE} · {fund?.source_name}</a>}
    </Panel>;

  return details ? <div className={styles.dataGrid}>{valuation}<Panel title={T.HOLDINGS} note={`${T.HOLDINGS_DATE} · ${fund?.holdings_as_of || T.UNKNOWN_DATE}`}>
      {!holdings.length ? <p className={styles.empty}>{T.NO_DATA}</p> : <div className={styles.tableScroll}><table><thead><tr><th>{T.ASSET_NAME}</th><th>{T.WEIGHT}</th></tr></thead><tbody>{holdings.map((item, index) => <tr key={index}><td>{item.name}</td><td>{formatNum(item.weight_pct, 2)}%</td></tr>)}</tbody></table></div>}
      {!!holdings.length && <p className={styles.lead}>{T.FUND_TOTAL(holdings.length, formatNum(totalHoldings, 2))}</p>}
      {!fund?.holdings_as_of && <p className={styles.muted}>{T.FUND_UNKNOWN_DATE}</p>}
      {source && <a className={styles.link} href={`${source}#holdings`} target="_blank" rel="noreferrer">{T.SOURCE} · {fund?.source_name}</a>}
    </Panel></div> : <ReportFrame header={<><p className={styles.muted}>{T.COLLECTED} · {displayTime(dossier?.collected_at)}</p><p className={styles.muted}>{T.SOURCE} · {fund?.source_name || T.NOT_PROVIDED}</p><details className={styles.evidenceDetails}><summary>{T.DOCUMENT_BASIS}</summary><p>{T.FUND_NOTE}</p></details></>}>
      <ReportSection id="summary"><p>{fund?.strategy_text || T.FUND_DATA_MISSING}</p></ReportSection>
      <ReportSection id="business">{intro}</ReportSection>
      <ReportSection id="changes">{news || <p className={styles.empty}>{T.NEWS_NOT_CHECKED}</p>}</ReportSection>
      <ReportSection id="financials">{valuation}</ReportSection>
      <ReportSection id="outlook">{points}{riskPanel}</ReportSection>
      <ReportSection id="schedule">{data.research?.events.length ? data.research.events.map((event, index) => <p key={index}>{event.date} · {event.description || T.NOT_PROVIDED}</p>) : <p className={styles.muted}>{T.DOCUMENT_NO_SCHEDULE}</p>}</ReportSection>
      <ReportSection id="judgment"><CurrentJudgment data={data} compact /><PriceSummary data={data} symbol={symbol} compact /></ReportSection>
    </ReportFrame>;
}
