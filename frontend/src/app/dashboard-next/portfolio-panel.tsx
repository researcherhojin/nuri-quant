"use client";

import { useState } from "react";
import type { Portfolio } from "./data";
import { summarizePortfolio, type Composition } from "./portfolio-summary";
import { DetailDialog } from "./detail-dialog";
import styles from "./dashboard.module.css";

const segmentColor = (index: number) => `hsl(${(215 + index * 137.508) % 360} 38% 68%)`;
export function PortfolioPanel({ portfolio, exchangeRate }: { portfolio: Portfolio | null; exchangeRate?: number | null }) {
  const [group, setGroup] = useState<Composition>("ticker");
  if (!portfolio) return <p className={styles.empty}>포트폴리오를 불러오지 못했습니다.</p>;
  const { total, rows, oldestPrice, newestPrice } = summarizePortfolio(portfolio, exchangeRate, group);

  return <>
    <div className={styles.tabs} aria-label="포트폴리오 구성 기준">{([["ticker", "종목별"], ["sector", "업종별"], ["account", "계좌별"]] as const).map(([key, label]) => <button type="button" key={key} aria-pressed={group === key} onClick={() => setGroup(key)}>{label}</button>)}</div>
    <div className={`${styles.panelBody} ${styles.portfolioBody}`}>
      <div className={styles.compositionChart}>
        <div className={styles.donut}>
          <svg viewBox="0 0 140 140" role="img" aria-label={total == null ? "포트폴리오 비중 산출 불가" : total === 0 ? "평가 자산 없음" : "포트폴리오 구성 비중 도넛 차트"}>
            <circle cx="70" cy="70" r="56" fill="none" stroke="var(--line)" strokeWidth="13" />
            {total != null && total > 0 && rows.map((row, i) => {
              const offset = rows.slice(0, i).reduce((sum, item) => sum + (item.weight ?? 0), 0);
              return row.weight != null && row.weight > 0 ? <circle key={row.key} cx="70" cy="70" r="56" fill="none" stroke={segmentColor(i)} strokeWidth="13" pathLength="100" strokeDasharray={`${row.weight} ${100 - row.weight}`} strokeDashoffset={-offset} transform="rotate(-90 70 70)"><title>{`${row.label} · ${row.weight.toFixed(1)}%`}</title></circle> : null;
            })}
          </svg>
          <div className={styles.donutTotal}><small>총 평가액</small><strong>{total == null ? "산출 불가" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(total)}</strong><small>USD · 현금 포함</small></div>
        </div>
        <div className={styles.compositionLegend} tabIndex={0} role="region" aria-label="전체 포트폴리오 비중 목록">{rows.map((row, i) => <div className={styles.compositionRow} key={row.key}><span title={row.label === row.key ? row.label : `${row.label} (${row.key})`}><i style={{ background: segmentColor(i) }} />{row.label}</span><b>{row.weight == null ? "—" : `${row.weight.toFixed(1)}%`}</b></div>)}</div>
      </div>
      <p className={styles.compositionCount}>전체 {rows.length}개 구성 · 목록을 스크롤해 확인</p>
      {total == null && <p className={styles.caution}>가격·환율·현금 데이터 확인 필요 · 비중 산출 보류</p>}
      <DetailDialog label="평가 기준 · 전체 구성 ↗" title="포트폴리오 구성과 평가 기준"><p>저장된 최근 종가로 보유 수량을 평가하고 현금을 합산합니다. KRW 자산은 저장된 USD/KRW 환율로 환산합니다. 목표 비중이 아닌 현재 보유 구성입니다.</p><p>가격 기준일 · {oldestPrice ?? "미제공"}{newestPrice !== oldestPrice ? ` ~ ${newestPrice}` : ""}. 실시간 시세가 아니며 종목별 기준일이 다를 수 있습니다.</p>{rows.map(row => <div className={styles.sourceRow} key={row.key}><span>{row.label}{row.label !== row.key && <small className={styles.tickerCode}>{row.key}</small>}</span><b>{row.weight == null ? "비중 미상" : `${row.weight.toFixed(1)}%`}</b></div>)}</DetailDialog>
    </div>
  </>;
}
