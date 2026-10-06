"use client";

import { useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { OVERVIEW as COPY } from "@/lib/strings";
import type { Portfolio } from "./data";
import { summarizePortfolio, type Composition } from "./portfolio-summary";
import { DetailDialog } from "./detail-dialog";
import styles from "./dashboard.module.css";

const T = COPY.PORTFOLIO;

const GROUPS = ["ticker", "sector", "account"] as const;

const segmentColor = (index: number) => `hsl(${(215 + index * 137.508) % 360} 38% 68%)`;

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export function PortfolioPanel({ portfolio, exchangeRate }: { portfolio: Portfolio | null; exchangeRate?: number | null }) {
  const [group, setGroup] = useState<Composition>("ticker");

  if (!portfolio) return <p className={styles.empty}>{T.UNAVAILABLE}</p>;
  const { total, rows, oldestPrice, newestPrice } = summarizePortfolio(portfolio, exchangeRate, group);
  const chartAria = total == null ? T.CHART_ARIA_UNKNOWN : total === 0 ? T.CHART_ARIA_EMPTY : T.CHART_ARIA;
  const weight = (value: number | null) => (value == null ? "—" : `${value.toFixed(1)}%`);

  return <>
    <div className={styles.tabs} aria-label={T.GROUP_ARIA}>
      {GROUPS.map((key) => <button type="button" key={key} aria-pressed={group === key} onClick={() => setGroup(key)}>{T.GROUPS[key]}</button>)}
    </div>
    <div className={`${styles.panelBody} ${styles.portfolioBody}`}>
      <div className={styles.compositionChart}>
        <div className={styles.donut}>
          <svg viewBox="0 0 140 140" role="img" aria-label={chartAria}>
            <circle cx="70" cy="70" r="56" fill="none" stroke="var(--line)" strokeWidth="13" />
            {total != null && total > 0 && rows.map((row, i) => {
              const offset = rows.slice(0, i).reduce((sum, item) => sum + (item.weight ?? 0), 0);

              return row.weight != null && row.weight > 0 ? (
                <circle key={row.key} cx="70" cy="70" r="56" fill="none" stroke={segmentColor(i)} strokeWidth="13" pathLength="100" strokeDasharray={`${row.weight} ${100 - row.weight}`} strokeDashoffset={-offset} transform="rotate(-90 70 70)">
                  <title>{`${row.label} · ${row.weight.toFixed(1)}%`}</title>
                </circle>
              ) : null;
            })}
          </svg>
          <div className={styles.donutTotal}>
            <small>{T.TOTAL}</small>
            <strong>{total == null ? T.TOTAL_UNKNOWN : usd.format(total)}</strong>
            <small>{T.TOTAL_UNIT}</small>
          </div>
        </div>
        <div className={styles.compositionLegend} tabIndex={0} role="region" aria-label={T.LEGEND_ARIA}>
          {rows.map((row, i) => (
            <div className={styles.compositionRow} key={row.key}>
              <span title={row.label === row.key ? row.label : `${row.label} (${row.key})`}><i style={{ background: segmentColor(i) }} />{row.label}</span>
              <b>{weight(row.weight)}</b>
            </div>
          ))}
        </div>
      </div>
      <p className={styles.compositionCount}>{T.COUNT(rows.length)}</p>
      {total == null && <p className={styles.caution}>{T.INCOMPLETE}</p>}
      <DetailDialog label={T.BASIS} icon={<ArrowUpRight size={12} />} title={T.BASIS_TITLE}>
        <p>{T.BASIS_GUIDE}</p>
        <p>{T.PRICE_DATE}{oldestPrice ?? T.NOT_PROVIDED}{newestPrice !== oldestPrice ? ` ~ ${newestPrice}` : ""}{T.PRICE_DATE_NOTE}</p>
        {rows.map((row) => (
          <div className={styles.sourceRow} key={row.key}>
            <span>{row.label}{row.label !== row.key && <small className={styles.tickerCode}>{row.key}</small>}</span>
            <b>{row.weight == null ? T.WEIGHT_UNKNOWN : `${row.weight.toFixed(1)}%`}</b>
          </div>
        ))}
      </DetailDialog>
    </div>
  </>;
}
