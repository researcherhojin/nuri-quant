import type { TickerReview } from "./data";
import { sourceUrl } from "./research-format";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import { lookup } from "@/lib/utils";
import styles from "./ticker.module.css";

type Article = NonNullable<TickerReview["research"]>["news"][number];

export function NewsItem({ item }: { item: Article }) {
  const verified = item.content_status === "verified" && !!item.excerpt && !!sourceUrl(item.article_url);
  const url = sourceUrl(verified ? item.article_url : item.url);

  const questions = verified ? (item.topics ?? []).flatMap(topic => {
    const question = lookup(T.NEWS_TOPICS, topic);

    return question ? [question] : [];
  }) : [];

  return <li>
    <span className={styles.muted}>{item.date} · {item.source || T.NOT_PROVIDED}</span>
    <div className={styles.newsBody}>
      {url ? <a href={url} target="_blank" rel="noreferrer">{item.title || T.NOT_PROVIDED}</a> : <p>{item.title || T.NOT_PROVIDED}</p>}
      {verified ? <>
        <p className={styles.muted}>{T.NEWS_EXCERPT}</p><blockquote>{item.excerpt}</blockquote>
        {!!questions.length && <details className={styles.newsReading}><summary>{T.NEWS_READING}</summary><ul>{questions.map(question => <li key={question}>{question}</li>)}</ul><p className={styles.muted}>{T.NEWS_INTERPRETATION_NOTE}</p></details>}
      </> : <p className={styles.muted}>{item.content_status === "unavailable" ? T.NEWS_CONTENT_UNAVAILABLE : T.NEWS_CONTENT_NOT_CHECKED}</p>}
    </div>
  </li>;
}
