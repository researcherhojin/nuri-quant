import type { TickerReview } from "./data";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import { lookup } from "@/lib/utils";
import { displayTime } from "@/app/(overview)/format";
import { isFund, priceRows } from "./research-format";
import styles from "./ticker.module.css";

export function SourceDates({ data }: { data: TickerReview }) {
  const dossier = data.research?.dossier;
  const fund = dossier?.fund;

  const rows = [
    [T.PRICE_BASIS, priceRows(data).at(-1)?.date || data.ticker?.price?.date],
    [T.PROFILE_BASIS, dossier ? displayTime(dossier.collected_at) : null],
    ...(isFund(data) ? [[T.FUND_DETAILS_DATE, fund?.details_as_of], [T.HOLDINGS_DATE, fund?.holdings_as_of], [T.FUND_VALUATION_BASIS, fund?.valuation_as_of], [T.FAQ_DATE, fund?.faq_as_of]] : [[T.FINANCIAL_BASIS, dossier?.statements.income[0]?.period], [T.CASHFLOW_BASIS, dossier?.statements.cashflow[0]?.period], [T.BALANCE_BASIS, dossier?.statements.balance[0]?.period]]),
    [T.AS_OF, data.ticker?.consensus?.as_of],
    [T.REVIEW_DATE, [...new Set(data.reviews.map(item => item.as_of).filter(Boolean))].join(" · ")],
    [T.NEWS_BASIS, dossier?.news_check ? displayTime(dossier.news_check.checked_at) : null],
  ];

  return <details className={styles.freshnessDetails}>
    <summary>{T.DATA_DATES}</summary>
    <p className={styles.muted}>{T.BASIS_NOTE}</p>
    <dl className={styles.sourceDates}>{rows.map(([label, date]) => <div key={label}><dt>{label}</dt><dd>{date || T.UNKNOWN_DATE}</dd></div>)}</dl>
    {!!dossier?.unavailable?.length && <p className={styles.notice}>{T.MISSING_SOURCES} · {dossier.unavailable.map(key => lookup(T.SOURCE_FIELDS, key) || T.NOT_PROVIDED).join(" · ")}</p>}
  </details>;
}
