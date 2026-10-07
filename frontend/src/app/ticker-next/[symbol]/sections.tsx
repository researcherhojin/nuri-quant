import Link from "next/link";
import { BookOpen, ChartNoAxesCombined, FileText, Users } from "lucide-react";
import { PriceChartLazy } from "@/components/ui/price-chart-lazy";
import { CONSENSUS, OVERVIEW, TICKER_PREVIEW as T } from "@/lib/strings";
import { formatMoney, formatNum, formatPct } from "@/lib/format";
import { displayTime } from "@/app/(overview)/format";
import type { TickerReview } from "./data";
import { isFund, priceRows } from "./research-format";
import { StockDetails } from "./briefing";
import { FundBriefing } from "./fund-briefing";
import { CurrentJudgment, PriceSummary } from "./decision-briefing";
import { lookup } from "@/lib/utils";
import { ActionLabel, Panel } from "./panel";
import styles from "./ticker.module.css";

export function HoldingReview({ data }: { data: TickerReview }) {
  return <Panel title={T.HOLDING} icon={<FileText size={17} />}>
    {!data.actions ? <p className={styles.empty}>{T.UNAVAILABLE}</p> : data.reviews.length === 0 ? <p className={styles.empty}>{T.NO_REVIEW}</p> : data.reviews.map((review, index) => <article className={styles.review} key={`${review.account}-${review.bucket}-${index}`}>
      <div className={styles.row}><span className={styles.kicker}>{OVERVIEW.INBOX_PANEL.BUCKETS[review.bucket]}</span><ActionLabel action={review.action} /></div>
      <p className={styles.muted}>{T.REVIEW_DATE} · {review.as_of || T.UNKNOWN_DATE}</p>
      <ul className={styles.reasons}>{review.reasons.length ? review.reasons.map((reason, i) => <li key={i}>{reason}</li>) : <li>{T.NO_REASON}</li>}</ul>
      <dl className={styles.axes}><div><dt>{T.ALPHA}</dt><dd><ActionLabel action={review.alpha_action} /></dd></div><div><dt>{T.PORTFOLIO_AXIS}</dt><dd><ActionLabel action={review.portfolio_action} /></dd></div></dl>
      <dl className={styles.holdingMetrics}><div><dt>{T.POSITION}</dt><dd>{review.position_pct == null ? "—" : `${formatNum(review.position_pct)}%`}</dd></div><div><dt>{T.PNL}</dt><dd>{formatPct(review.pnl_pct)}</dd></div></dl>
      <p className={styles.muted}>{T.ACCOUNT} · {review.account || T.NOT_PROVIDED}</p>
      <p className={styles.muted}>{T.ACCOUNT_NOTE}</p>
      {review.decision_id != null ? <Link className={styles.link} href={`/decisions/${review.decision_id}`}>{T.LEDGER} <BookOpen size={14} /></Link> : <p className={styles.muted}>{T.NO_LEDGER}</p>}
    </article>)}
    <div className={styles.reviewFooter}><Link className={styles.link} href="/portfolio">{T.PORTFOLIO}</Link>{data.actions && <span className={styles.muted}>{T.GENERATED} · {displayTime(data.actions.generated_at)}</span>}</div>
  </Panel>;
}

export function Evidence({ data }: { data: TickerReview }) {
  const consensus = data.ticker?.consensus;
  const verdicts = consensus?.error ? [] : consensus?.verdicts ?? [];

  return <div className={styles.evidenceFlow}>
    <Panel title={T.DISSENT} icon={<FileText size={17} />}>
      {!consensus || consensus.error ? <p className={styles.empty}>{T.NO_CONSENSUS}</p> : consensus.dissent?.length ? <ul className={styles.reasons}>{consensus.dissent.map((reason, index) => <li key={index}>{reason}</li>)}</ul> : <p className={styles.empty}>{T.NO_DISSENT}</p>}
    </Panel>
    <Panel title={T.AGENTS} icon={<Users size={17} />} note={T.AGENT_NOTE}>
      {!consensus || consensus.error ? <p className={styles.empty}>{T.NO_CONSENSUS}</p> : verdicts.length === 0 ? <p className={styles.empty}>{T.NO_DATA}</p> : verdicts.map((v, index) => <details className={styles.agent} key={`${v.agent_name}-${index}`}>
        <summary><span>{v.agent_name}</span><span className={styles.agentResult}>{v.degraded || v.abstained ? <span className={styles.muted}>{v.degraded ? CONSENSUS.PLACEHOLDER_DEGRADED : CONSENSUS.PLACEHOLDER_ABSTAINED}</span> : <><ActionLabel action={v.action} /><span className={styles.number}>{formatNum(v.confidence, 0)}</span></>}</span></summary>
        <p>{v.reasoning || T.NO_REASON}</p>
      </details>)}
    </Panel>
  </div>;
}

export function DecisionView({ data }: { data: TickerReview }) {
  return <div className={`${styles.detailDocument} ${styles.decisionLayout}`}>
    <div className={styles.decisionConclusion}><CurrentJudgment data={data} /></div>
    <aside className={styles.holdingAside}><HoldingReview data={data} /></aside>
    <div className={styles.decisionEvidence}><Evidence data={data} /></div>
  </div>;
}

export function Research({ data, symbol }: { data: TickerReview; symbol: string }) {
  const ticker = data.ticker;
  const fund = ticker?.fundamentals;
  const etf = isFund(data);
  const prices = priceRows(data);
  const fundKeys = ["pe_ratio", "roe", "revenue_growth", "debt_to_equity", "profit_margin", "beta"] as const;

  return <div className={`${styles.detailDocument} ${styles.researchDocument}`}>
    <div className={styles.marketGrid}><Panel title={T.PRICE_HISTORY} icon={<ChartNoAxesCombined size={17} />} note={T.PRICE_NOTE}>
      {!data.prices && !data.research?.dossier?.price_history ? <p className={styles.empty}>{T.UNAVAILABLE}</p> : prices.length ? <div className={styles.chart}><PriceChartLazy data={prices} ticker={symbol} /></div> : <p className={styles.empty}>{T.NO_DATA}</p>}
    </Panel>
    <PriceSummary data={data} symbol={symbol} /></div>
    {etf && <FundBriefing data={data} details />}
    {!etf && <>
    <StockDetails data={data} symbol={symbol} />
    <Panel title={T.FUNDAMENTALS} note={`${T.DATE} · ${fund?.date || T.UNKNOWN_DATE}`}>
      {!ticker ? <p className={styles.empty}>{T.UNAVAILABLE}</p> : !fund ? <p className={styles.empty}>{T.NO_DATA}</p> : <dl className={styles.fundamentals}>{fundKeys.map(key => <div key={key}><dt>{T.FUND_LABELS[key]}</dt><dd>{key === "debt_to_equity" ? formatPct(fund[key]) : ["roe", "revenue_growth", "profit_margin"].includes(key) ? formatPct(fund[key] == null ? null : fund[key] * 100) : formatNum(fund[key])}</dd></div>)}</dl>}
    </Panel>
    <div className={styles.researchTables}>
      <Panel title={T.RATINGS} note={T.SOURCE_NOTE}>
        {ticker?.analyst_ratings?.length ? <div className={styles.tableScroll}><table><thead><tr><th>{T.FIRM}</th><th>{T.DATE}</th><th>{T.GRADE}</th><th>{T.TARGET}</th></tr></thead><tbody>{ticker.analyst_ratings.map((r, i) => <tr key={i}><td>{r.firm}</td><td>{r.date || "—"}</td><td>{r.to_grade || r.action || "—"}</td><td>{formatMoney(r.target_price, { ticker: symbol })}</td></tr>)}</tbody></table></div> : <p className={styles.empty}>{ticker ? T.NO_DATA : T.UNAVAILABLE}</p>}
      </Panel>
      <Panel title={T.EARNINGS}>
        {ticker?.earnings?.length ? <div className={styles.tableScroll}><table><thead><tr><th>{T.PERIOD}</th><th>{T.ACTUAL}</th><th>{T.ESTIMATE}</th></tr></thead><tbody>{ticker.earnings.map((e, i) => <tr key={i}><td>{e.quarter || "—"}</td><td>{formatNum(e.eps_actual, 2)}</td><td>{formatNum(e.eps_estimate, 2)}</td></tr>)}</tbody></table></div> : <p className={styles.empty}>{ticker ? T.NO_DATA : T.UNAVAILABLE}</p>}
      </Panel>
      <Panel title={T.INSIDERS}>
        {ticker?.insider_trades?.length ? <div className={styles.tableScroll}><table><thead><tr><th>{T.PERSON}</th><th>{T.DATE}</th><th>{T.TRANSACTION}</th><th>{T.SHARES}</th></tr></thead><tbody>{ticker.insider_trades.map((r, i) => <tr key={i}><td>{r.insider_name || "—"}</td><td>{r.date || "—"}</td><td>{r.transaction_type || "—"}</td><td>{formatNum(r.shares, 0)}</td></tr>)}</tbody></table></div> : <p className={styles.empty}>{ticker ? T.NO_DATA : T.UNAVAILABLE}</p>}
      </Panel>
      <Panel title={T.INVESTORS}>
        {ticker?.superinvestors?.length ? <div className={styles.tableScroll}><table><thead><tr><th>{T.PERSON}</th><th>{T.DATE}</th><th>{T.WEIGHT}</th></tr></thead><tbody>{ticker.superinvestors.map((r, i) => <tr key={i}><td>{r.investor}</td><td>{r.filing_date || "—"}</td><td>{r.portfolio_pct == null ? "—" : `${formatNum(r.portfolio_pct)}%`}</td></tr>)}</tbody></table></div> : <p className={styles.empty}>{ticker ? T.NO_DATA : T.UNAVAILABLE}</p>}
      </Panel>
    </div>
    </>}
  </div>;
}

export function History({ data }: { data: TickerReview }) {
  const records = data.history?.decisions ?? [];
  const latest = records[0];
  const previous = records[1];

  return <div className={`${styles.detailDocument} ${styles.historyDocument}`}><Panel title={T.HISTORY} icon={<BookOpen size={17} />} note={T.HISTORY_NOTE}>
    <p className={styles.lead}>{T.HISTORY_EXPLAIN}</p>
    {latest && previous && <p className={styles.muted}>{T.HISTORY_CHANGE(previous.action, latest.action)}</p>}
    {!data.history ? <p className={styles.empty}>{T.UNAVAILABLE}</p> : !records.length ? <p className={styles.empty}>{T.NO_DATA}</p> : <ol className={styles.historyList}>{records.map((d, index) => <li key={d.id}>
      <div className={styles.historyDate}><time dateTime={d.date}>{d.date}</time><ActionLabel action={d.action} /></div>
      <article className={styles.historyEntry} aria-label={`${d.date} ${T.HISTORY}`}>
        <dl className={styles.historyMetrics}><div><dt>{T.OUTCOME}</dt><dd>{d.outcome ? lookup(T.OUTCOMES, d.outcome) || d.outcome : "—"}</dd></div><div><dt>{T.RETURN_7D}</dt><dd>{formatPct(d.pnl_7d)}</dd></div><div><dt>{T.RETURN_30D}</dt><dd>{formatPct(d.pnl_30d)}</dd></div></dl>
        {d.reasoning ? <details className={styles.historyReason} open={index === 0}><summary>{T.PRO_REASONS}</summary><p>{d.reasoning}</p></details> : <p className={styles.muted}>{T.NO_REASON}</p>}
        <Link className={styles.link} href={`/decisions/${d.id}`}>{T.OPEN}<BookOpen size={14} /></Link>
      </article>
    </li>)}</ol>}
  </Panel></div>;
}
