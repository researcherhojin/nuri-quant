"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { z } from "zod";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import styles from "./[symbol]/ticker.module.css";

const resultSchema = z.object({ results: z.array(z.object({ ticker: z.string().regex(/^[A-Za-z0-9^][A-Za-z0-9.^=-]*$/), name: z.string().nullish() })) });

type Result = z.infer<typeof resultSchema>["results"][number];

export function TickerSearch() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Result[]>([]);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!query.trim()) return;

    const controller = new AbortController();

    const timer = setTimeout(async () => {
      setMessage(T.SEARCH_LOADING);

      try {
        const response = await fetch(`/api/tickers/search?q=${encodeURIComponent(query.trim())}`, { signal: controller.signal });

        if (!response.ok) throw new Error("Search unavailable");

        const parsed = resultSchema.parse(await response.json());

        if (controller.signal.aborted) return;

        setResults(parsed.results);
        setMessage(parsed.results.length ? "" : T.SEARCH_EMPTY);
      } catch {
        if (controller.signal.aborted) return;

        setResults([]);
        setMessage(T.SEARCH_FAILED);
      }
    }, 250);

    return () => { clearTimeout(timer); controller.abort(); };
  }, [query]);

  function open(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const matched = results.find(item => item.name?.toLocaleLowerCase() === query.trim().toLocaleLowerCase());
    const symbol = matched?.ticker.toUpperCase() || query.trim().toUpperCase();

    if (!/^[A-Z0-9^][A-Z0-9.^=-]{0,19}$/.test(symbol)) {
      setMessage(T.SEARCH_INVALID);

      return;
    }

    router.push(`/ticker-next/${encodeURIComponent(symbol)}`);
  }

  return <div className={styles.tickerSearch}>
    <form onSubmit={open}><label htmlFor="ticker-query">{T.SEARCH_LABEL}</label><div className={styles.searchField}><input id="ticker-query" value={query} maxLength={20} placeholder={T.SEARCH_PLACEHOLDER} autoComplete="off" aria-describedby="ticker-search-help ticker-search-status" onChange={event => { setQuery(event.target.value); setResults([]); setMessage(""); }} /><button type="submit" disabled={!query.trim()}>{T.SEARCH_OPEN}</button></div></form>
    <p id="ticker-search-help" className={styles.muted}>{T.SEARCH_HELP}</p>
    <p id="ticker-search-status" role="status" className={styles.muted}>{message}</p>
    {!!results.length && <ul className={styles.searchResults}>{results.map(item => <li key={item.ticker}><Link href={`/ticker-next/${encodeURIComponent(item.ticker)}`}><strong>{item.ticker}</strong><span>{item.name || item.ticker}</span></Link></li>)}</ul>}
  </div>;
}
