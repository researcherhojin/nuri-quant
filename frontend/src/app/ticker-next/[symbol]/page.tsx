import Link from "next/link";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import { formatMoney } from "@/lib/format";
import { loadTicker } from "./data";
import { DecisionView, History, Research } from "./sections";
import { ResearchTabs } from "./research-tabs";
import { CollectResearch } from "./collect-research";
import { displayTime } from "@/app/(overview)/format";
import { Briefing } from "./briefing";
import { SourceDates } from "./source-dates";
import styles from "./ticker.module.css";

export const dynamic = "force-dynamic";

export default async function TickerPreview({ params, searchParams }: {
  params: Promise<{ symbol: string }>;
  searchParams?: Promise<{ bucket?: string; tab?: string }>;
}) {
  const { symbol: raw } = await params;
  const query = await searchParams;
  const symbol = raw.toUpperCase();
  const data = await loadTicker(symbol);
  const collectedPrice = data.research?.dossier?.price_history?.at(-1);
  const price = collectedPrice || data.ticker?.price;
  const bucket = ["urgent", "check", "portfolio", "hold"].find(key => key === query?.bucket);
  const back = bucket ? `/?bucket=${bucket}&ticker=${encodeURIComponent(symbol)}` : "/";

  return <div className={styles.page} data-testid="ticker-preview">
    <nav className={styles.navigation} aria-label={T.EYEBROW}>
      <Link href={back}><ArrowLeft size={15} />{T.BACK}</Link>
      <div><span className={styles.preview}>{T.PREVIEW}</span><Link href="/ticker-next">{T.SELECT}</Link><Link href={`/ticker/${encodeURIComponent(symbol)}`}>{T.ORIGINAL}<ArrowUpRight size={14} /></Link></div>
    </nav>
    <header className={styles.hero}>
      <div><p className={styles.kicker}>{T.EYEBROW}</p><h1>{data.research?.dossier?.profile.display_name || data.research?.dossier?.profile.name || data.ticker?.name || symbol}</h1><p className={styles.symbol}>{symbol}</p></div>
      <div className={styles.price}><span>{T.PRICE}</span><strong>{formatMoney(price?.close, { ticker: symbol })}</strong><small>{T.PRICE_DATE} · {price?.date || T.UNKNOWN_DATE}</small></div>
    </header>
    {!data.ticker && <p role="status" className={styles.notice}>{T.UNAVAILABLE} <Link className={styles.link} href={`/ticker-next/${encodeURIComponent(symbol)}`}>{T.RETRY}</Link></p>}
    <div className={styles.freshness}>
      <div className={styles.row}><span className={styles.kicker}>{data.research?.collected_today ? data.research.dossier?.unavailable?.length ? T.DAILY_PARTIAL : T.DAILY_CURRENT : T.DAILY_STALE}</span><span className={styles.muted}>{T.COLLECTED} · {displayTime(data.research?.dossier?.collected_at)}</span></div>
      <SourceDates data={data} />
      <CollectResearch symbol={symbol} />
      {!!data.research?.dossier?.unavailable?.length && <p className={styles.muted}>{T.PARTIAL}</p>}
    </div>
    <ResearchTabs brief={<Briefing data={data} symbol={symbol} />} evidence={<DecisionView data={data} />} research={<Research data={data} symbol={symbol} />} history={<History data={data} />} />
  </div>;
}
