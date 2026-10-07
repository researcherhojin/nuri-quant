import { Building2, FileText, Newspaper, ChartNoAxesCombined } from "lucide-react";
import type { TickerReview } from "./data";
import { Panel } from "./panel";
import { FundBriefing } from "./fund-briefing";
import { BriefingLayout } from "./briefing-layout";
import { NewsItem } from "./news-item";
import { PublicBriefing, BriefingGeneration } from "./public-briefing";
import { FinancialReading } from "./financial-reading";
import { amount, compactAmount, isFund, sourceUrl } from "./research-format";

export { sourceUrl } from "./research-format";

import { TICKER_PREVIEW as T } from "@/lib/strings";
import { formatNum, formatPct } from "@/lib/format";
import { displayTime } from "@/app/(overview)/format";
import styles from "./ticker.module.css";

export function Briefing({ data, symbol }: { data: TickerReview; symbol: string }) {
  const research = data.research;
  const dossier = research?.dossier;
  const profile = dossier?.profile;
  const business = dossier?.business;
  const fund = isFund(data);
  const newsCheck = dossier?.news_check;
  const news = newsCheck ? dossier?.news ?? research?.news ?? [] : [];
  const statement = dossier?.statements;
  const income = statement?.income[0];
  const previous = statement?.income[1];
  const cashflow = statement?.cashflow[0];
  const currency = profile?.financial_currency;
  const growth = income?.revenue != null && previous?.revenue != null && previous.revenue > 0 ? (income.revenue / previous.revenue - 1) * 100 : null;
  const website = sourceUrl(profile?.website);
  const description = profile?.description;
  const excerpt = description && description.length > 420 ? `${description.slice(0, 420).replace(/\s+\S*$/, "")}…` : description;
  const yahoo = `https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}/`;
  const facts = [];

  if (income?.revenue != null) facts.push(T.SUMMARY_REVENUE(income.period, amount(income.revenue, currency), growth == null ? null : formatPct(growth)));

  if (income?.net_income != null) facts.push(T.SUMMARY_PROFIT(income.period, amount(income.net_income, currency)));

  if (cashflow && (cashflow.operating_cashflow != null || cashflow.free_cashflow != null)) facts.push(T.SUMMARY_CASHFLOW(cashflow.period, amount(cashflow.operating_cashflow, currency), amount(cashflow.free_cashflow, currency)));

  if (income?.revenue != null && income.revenue > 0 && income.net_income != null) facts.push(T.MARGIN_EXPLAIN(income.period, formatPct(income.net_income / income.revenue * 100)));

  if (income?.net_income != null && income.net_income > 0 && cashflow?.period === income.period && cashflow.operating_cashflow != null) facts.push(T.CASH_CONVERSION(income.period, formatNum(cashflow.operating_cashflow / income.net_income, 2)));

  const balance = statement?.balance[0];

  if (balance?.cash != null && balance.debt != null) facts.push(T.CASH_COMPARE(balance.period, amount(balance.cash, currency), amount(balance.debt, currency)));

  const riskFacts = [];

  if (income?.net_income != null && income.net_income < 0) riskFacts.push(T.LOSS_FACT);

  if (cashflow?.operating_cashflow != null && cashflow.operating_cashflow < 0) riskFacts.push(T.CASHFLOW_FACT);

  const newsPanel = <Panel headingLevel={3} title={T.RECENT} icon={<Newspaper size={17} />} note={T.NEWS_NOTE}>
      {newsCheck && <div className={styles.newsFreshness}><span>{T.NEWS_CHECKED} · {displayTime(newsCheck.checked_at)}</span><span>{newsCheck.window_start} — {newsCheck.window_end}</span></div>}
      {!!newsCheck?.failed_sources.length && <p className={styles.notice}>{T.NEWS_SOURCE_FAILED(newsCheck.failed_sources.join(" · "))}</p>}
      {!research ? <p className={styles.empty}>{T.UNAVAILABLE}</p> : <>
        {news.length ? <ul className={styles.news}>{news.slice(0, 3).map((item, index) => <NewsItem key={index} item={item} />)}</ul> : <p className={styles.empty}>{newsCheck ? newsCheck.failed_sources.length === newsCheck.sources.length ? T.NEWS_SEARCH_FAILED : T.NEWS_NONE_RECENT : T.NEWS_NOT_CHECKED}</p>}
        {news.length > 3 && <details className={styles.business}><summary>{T.MORE_NEWS(news.length - 3)}</summary><ul className={styles.news}>{news.slice(3).map((item, index) => <NewsItem key={index} item={item} />)}</ul></details>}
        {research.events.length ? <ul className={styles.news}>{research.events.map((event, index) => <li key={index}><span className={styles.muted}>{event.date} · {event.event_type || T.NOT_PROVIDED}</span><p>{event.description || T.NOT_PROVIDED}</p></li>)}</ul> : null}
      </>}
    </Panel>;

  if (fund) return <FundBriefing data={data} symbol={symbol} news={newsPanel} />;

  if (research?.public_briefing?.status === "ready" && research.public_briefing.report) return <PublicBriefing data={data} symbol={symbol} briefing={research.public_briefing} />;

  return <><BriefingGeneration data={data} symbol={symbol} /><BriefingLayout data={data} symbol={symbol} intro={<Panel headingLevel={3} title={T.COMPANY} icon={<Building2 size={17} />} note={profile ? `${T.YAHOO} · ${T.COLLECTED} ${displayTime(dossier?.collected_at)}` : undefined}>
      {!research ? <p className={styles.empty}>{T.UNAVAILABLE}</p> : !profile ? <p className={styles.empty}>{T.NO_PROFILE}</p> : <>
        <div className={styles.companyTitle}><h3>{profile.display_name || profile.name}</h3><span>{profile.name} · {profile.symbol} · {profile.exchange || T.NOT_PROVIDED}</span></div>
        <p className={styles.muted}>{T.IDENTITY_NOTE}</p>
        {business?.summary && <p className={styles.lead}>{business.summary}</p>}
        <dl className={styles.companyMetrics}><div><dt>{T.SECTOR}</dt><dd>{business?.sector_label || profile.sector || "—"}</dd></div><div><dt>{T.INDUSTRY}</dt><dd>{business?.industry_label || profile.industry || "—"}</dd></div><div><dt>{T.COUNTRY}</dt><dd>{profile.country === "South Korea" ? T.COUNTRY_KR : profile.country || "—"}</dd></div><div><dt>{T.MARKET_CAP}</dt><dd>{compactAmount(profile.market_cap, profile.currency)}</dd></div></dl>
        {!!business?.activities.length && <div className={styles.businessProfiles}><h3 className={styles.subheading}>{T.BUSINESS_CORE}</h3>{business.activities.map(activity => <article key={activity.title}><h4>{activity.title}</h4><p>{activity.explanation}</p><span className={styles.muted}>{T.SOURCE} · {activity.source_phrase}</span></article>)}</div>}
        {!business?.summary && excerpt && <div className={styles.factProse}><h3 className={styles.subheading}>{T.BUSINESS_EXCERPT}</h3><p>{excerpt}</p><p className={styles.muted}>{T.BUSINESS_PARTIAL}</p></div>}
        {profile.description ? <details className={styles.business}><summary>{T.BUSINESS_ORIGINAL}</summary><p>{profile.description}</p></details> : <p className={styles.empty}>{T.NO_DATA}</p>}
        <div className={styles.sourceLinks}><a className={styles.link} href={`${yahoo}profile/`} target="_blank" rel="noreferrer">{T.SOURCE} · {T.YAHOO}</a>{website && <a className={styles.link} href={website} target="_blank" rel="noreferrer">{T.WEBSITE}</a>}</div>
      </>}

    </Panel>} points={<Panel headingLevel={3} title={T.BRIEF_FACTS} icon={<FileText size={17} />} note={T.FINANCIAL_NOTE}>
        {business ? <FinancialReading data={data} /> : facts.length ? <div className={styles.factProse}>{facts.map(fact => <p key={fact}>{fact}</p>)}</div> : <p className={styles.empty}>{T.NO_FINANCIALS}</p>}
        {!currency && <p className={styles.muted}>{T.CURRENCY_UNKNOWN}</p>}
      </Panel>} risks={<Panel headingLevel={3} title={T.RISK_FACTS} icon={<FileText size={17} />}>
        <ul className={styles.reasons}>{riskFacts.length ? riskFacts.map(fact => <li key={fact}>{fact}</li>) : <li>{T.NO_RISK_FACT}</li>}</ul>
        <h3 className={styles.subheading}>{T.CHECKPOINTS}</h3><ul className={styles.reasons}>{business?.activities.length ? business.activities.map(activity => <li key={activity.title}><strong>{activity.title}</strong> · {activity.checkpoint}</li>) : T.QUESTIONS.map(question => <li key={question}>{question}</li>)}</ul>
      </Panel>} news={newsPanel} /></>;
}

export function StockDetails({ data, symbol }: { data: TickerReview; symbol: string }) {
  const research = data.research;
  const dossier = research?.dossier;
  const statement = dossier?.statements;
  const currency = dossier?.profile.financial_currency;
  const yahoo = `https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}/`;
  const periods = [...new Set([...(statement?.income ?? []), ...(statement?.cashflow ?? []), ...(statement?.balance ?? [])].map(row => row.period))].sort().reverse();
  const metrics = [["revenue", T.REVENUE], ["operating_income", T.OPERATING_INCOME], ["net_income", T.NET_INCOME], ["operating_cashflow", T.OCF], ["free_cashflow", T.FCF], ["cash", T.CASH], ["debt", T.DEBT]] as const;

  return <div className={styles.stack}>
    <Panel title={T.FINANCIAL_TREND} icon={<ChartNoAxesCombined size={17} />} note={`${T.FINANCIAL_CURRENCY} · ${currency || T.CURRENCY_UNKNOWN} · ${T.FINANCIAL_NOTE}`}>
      {!periods.length ? <p className={styles.empty}>{T.NO_FINANCIALS}</p> : <div className={styles.tableScroll}><table><thead><tr><th>{T.PERIOD}</th>{metrics.map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead><tbody>{periods.map(period => {
        const values = { ...statement?.income.find(row => row.period === period), ...statement?.cashflow.find(row => row.period === period), ...statement?.balance.find(row => row.period === period) };

        // 각 표는 해당 보고 기간만 합친다. 서로 다른 결산 시점의 값을 섞지 않는다.
        return <tr key={period}><th>{period}</th>{metrics.map(([key]) => <td key={key}>{amount(values[key])}</td>)}</tr>;
      })}</tbody></table></div>}
      {dossier && <a className={styles.link} href={`${yahoo}financials/`} target="_blank" rel="noreferrer">{T.SOURCE} · {T.YAHOO}</a>}
    </Panel>
    <Panel title={T.VALUATION} note={T.VALUATION_NOTE}>
      <p className={styles.muted}>{T.DATE_SNAPSHOTS} · {T.NO_PEERS}</p>
      {!research?.fundamentals_history.length ? <p className={styles.empty}>{T.NO_DATA}</p> : <div className={styles.tableScroll}><table><thead><tr><th>{T.DATE}</th><th>PER</th><th>{T.FORWARD_PE}</th><th>{T.PBR}</th></tr></thead><tbody>{research.fundamentals_history.map(row => <tr key={row.date}><td>{row.date}</td><td>{formatNum(row.pe_ratio)}</td><td>{formatNum(row.forward_pe)}</td><td>{formatNum(row.price_to_book)}</td></tr>)}</tbody></table></div>}
    </Panel>
  </div>;
}
