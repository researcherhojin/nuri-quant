import { TICKER_PREVIEW as T } from "@/lib/strings";
import styles from "./ticker.module.css";

export default function Loading() {
  return <div className={styles.page} role="status" aria-label={T.LOADING}><p className={styles.muted}>{T.LOADING}</p><div className={styles.skeleton} /><div className={styles.skeleton} /><div className={styles.skeleton} /></div>;
}
