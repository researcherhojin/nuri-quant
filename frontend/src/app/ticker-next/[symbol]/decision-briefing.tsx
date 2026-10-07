import { ChartNoAxesCombined, FileText } from "lucide-react";
import type { TickerReview } from "./data";
import { ActionLabel, Panel } from "./panel";
import { priceRows } from "./research-format";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import { formatMoney, formatNum, formatPct } from "@/lib/format";
import { lookup } from "@/lib/utils";
import styles from "./ticker.module.css";

export function CurrentJudgment({ data, compact = false }: { data: TickerReview; compact?: boolean }) {
  const consensus = data.ticker?.consensus;
  const valid = consensus && !consensus.error ? consensus : null;
  const action = valid?.final_action;
  const source = valid?.scoring_detail?.final_action_source;
  const mechanism = source ? lookup(T.DECISION_MECHANISMS, source) : null;

  const legacyCalculation = valid?.verdicts?.some(verdict =>
    (verdict.agent_name === "fundamental" && /부채비율\s+[\d.]+x/.test(verdict.reasoning || "")) ||
    (verdict.agent_name === "risk" && verdict.reasoning?.includes("비중 초과") && !verdict.data_points?.position_basis));

  const explanation = action ? lookup(T.ACTION_MEANING, action) : null;
  const reasons = valid?.verdicts?.filter(verdict => !verdict.degraded && !verdict.abstained && verdict.action === action && verdict.reasoning).sort((a, b) => source === "risk_veto" ? Number(b.agent_name === "risk") - Number(a.agent_name === "risk") : 0).slice(0, 3) ?? [];

  return <Panel title={T.CURRENT_JUDGMENT} icon={<FileText size={17} />} note={T.JUDGMENT_SOURCE} collapsibleNote={compact}>
    <div className={styles.judgmentHeadline}><ActionLabel action={action} /><span className={styles.muted}>{T.AS_OF} · {valid?.as_of || T.UNKNOWN_DATE}</span></div>
    <p className={styles.lead}>{explanation || T.NO_CONSENSUS}</p>
    {legacyCalculation && <p role="note" className={styles.notice}>{T.LEGACY_CALCULATION_NOTE}</p>}
    <p className={styles.muted}>{mechanism || T.DECISION_MECHANISM_UNKNOWN}</p>
    {source === "risk_veto" && <p className={styles.muted}>{T.VETO_CONFIDENCE_NOTE}</p>}
    <p className={styles.muted}>{T.CONFIDENCE} · {formatNum(valid?.final_confidence, 0)}{T.CONFIDENCE_DENOMINATOR}</p>
    {compact ? <p className={styles.judgmentExcerpt}>{reasons[0]?.reasoning || T.NO_VALID_REASON}</p> : <div>
      <div><h3 className={styles.subheading}>{T.PRO_REASONS}</h3><ul className={styles.reasons}>{reasons.length ? reasons.map((verdict, index) => <li key={index}>{verdict.reasoning}<span className={styles.muted}> · {verdict.agent_name}</span></li>) : <li>{T.NO_VALID_REASON}</li>}</ul></div>
    </div>}
    {compact ? <details className={styles.business}><summary>{T.JUDGMENT_GUIDE}</summary><p>{T.CONFIDENCE_NOTE}</p><p>{T.AXIS_NOTE}</p></details> : <><p className={styles.muted}>{T.CONFIDENCE_NOTE}</p><p className={styles.muted}>{T.AXIS_NOTE}</p></>}
  </Panel>;
}

export function PriceSummary({ data, symbol, compact = false }: { data: TickerReview; symbol: string; compact?: boolean }) {
  const rows = [...priceRows(data)].sort((a, b) => a.date.localeCompare(b.date));
  const first = rows[0];
  const latest = rows.at(-1);
  const highs = rows.map(row => row.high).filter(value => value > 0);
  const lows = rows.map(row => row.low).filter(value => value > 0);
  const high = highs.length ? Math.max(...highs) : null;
  const low = lows.length ? Math.min(...lows) : null;
  const change = latest && first && first.close > 0 ? (latest.close / first.close - 1) * 100 : null;
  const drawdown = latest && high != null && high > 0 ? (latest.close / high - 1) * 100 : null;

  const closes = rows.map(row => row.close);
  const min = closes.length ? Math.min(...closes) : 0;
  const max = closes.length ? Math.max(...closes) : 0;
  const points = closes.map((close, index) => `${20 + index / Math.max(1, closes.length - 1) * 560},${160 - (close - min) / (max - min || 1) * 130}`).join(" ");

  return <Panel title={T.PRICE_RANGE} icon={<ChartNoAxesCombined size={17} />} note={T.PRICE_RANGE_NOTE} collapsibleNote={compact}>
    {!latest || !first ? <p className={styles.empty}>{T.NO_DATA}</p> : <>
      {compact && <div className={styles.priceTrend}><svg viewBox="0 0 600 180" role="img" aria-label={T.PRICE_TREND(first.date, latest.date)}><path d="M20 160H580 M20 95H580 M20 30H580" stroke="#2d3949" fill="none" /><polyline points={points} stroke="#a9c7f5" strokeWidth="3" fill="none" vectorEffect="non-scaling-stroke" /></svg><div><span>{first.date}</span><strong>{formatPct(change)}</strong><span>{latest.date}</span></div></div>}
      {!compact && <p className={styles.lead}>{T.PRICE_EXPLAIN(first.date, latest.date, formatPct(change))}</p>}
      <dl className={styles.fundamentals}>
        {!compact && <><div><dt>{T.RANGE_START}</dt><dd>{first.date}</dd></div><div><dt>{T.RANGE_END}</dt><dd>{latest.date}</dd></div></>}
        <div><dt>{T.RANGE_HIGH}</dt><dd>{formatMoney(high, { ticker: symbol })}</dd></div><div><dt>{T.RANGE_LOW}</dt><dd>{formatMoney(low, { ticker: symbol })}</dd></div>
        <div><dt>{T.RANGE_DRAWDOWN}</dt><dd>{formatPct(drawdown)}</dd></div>{!compact && <div><dt>{T.VOLUME}</dt><dd>{formatNum(latest.volume, 0)}</dd></div>}
      </dl>
      <p className={styles.muted}>{T.PRICE_NOT_CHEAP}</p>
      {data.research?.dossier?.price_history?.length ? <a className={styles.link} href={`https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}/history/`} target="_blank" rel="noreferrer">{T.SOURCE} · {T.YAHOO}</a> : <p className={styles.muted}>{T.STORED_PRICE_SOURCE}</p>}
    </>}
  </Panel>;
}
