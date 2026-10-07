import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { portfolioSchema, readPanel } from "@/app/(overview)/data";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import { TickerSearch } from "./ticker-search";
import styles from "./[symbol]/ticker.module.css";

export const dynamic = "force-dynamic";

export const metadata = { title: `${T.LANDING_TITLE} · Nuri-Quant` };

export default async function TickerIndex() {
  const portfolio = await readPanel("/api/portfolio", portfolioSchema);
  const holdings = [...new Map((portfolio?.holdings ?? []).map(item => [item.ticker, { ticker: item.ticker, name: item.name }])).values()];

  return <div className={`${styles.page} ${styles.landing}`}>
    <nav className={styles.navigation}><Link href="/"><ArrowLeft size={15} />{T.BACK}</Link></nav>
    <header className={styles.hero}><div><h1>{T.LANDING_TITLE}</h1><p className={styles.lead}>{T.LANDING_DESCRIPTION}</p></div></header>
    <TickerSearch />
    <section className={styles.savedTickers} aria-labelledby="saved-tickers"><h2 id="saved-tickers">{T.LANDING_HOLDINGS}</h2>
      {holdings.length ? <ul>{holdings.map(item => <li key={item.ticker}><Link href={`/ticker-next/${encodeURIComponent(item.ticker)}`}><strong>{item.ticker}</strong><span>{item.name || item.ticker}</span></Link></li>)}</ul> : <p className={styles.empty}>{T.LANDING_NO_HOLDINGS}</p>}
    </section>
  </div>;
}
