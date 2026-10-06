import { DASHBOARD_NEXT } from "@/lib/strings";
import styles from "./dashboard.module.css";

export default function Loading() {
  return (
    <div className={`${styles.dashboard} ${styles.loading}`} role="status" aria-busy="true">
      <span className={styles.srOnly}>{DASHBOARD_NEXT.LOADING}</span>
      <div className={styles.skeletonHeading} aria-hidden="true" />
      <div className={styles.skeletonStrip} aria-hidden="true" />
      <div className={styles.metrics} aria-hidden="true">{[0, 1, 2, 3].map((key) => <div className={styles.skeletonPanel} key={key} />)}</div>
      <div className={styles.primaryGrid} aria-hidden="true"><div className={styles.skeletonPanel} /><div className={styles.skeletonPanel} /></div>
      <div className={styles.secondaryGrid} aria-hidden="true">{[0, 1, 2].map((key) => <div className={styles.skeletonPanel} key={key} />)}</div>
      <div className={styles.basis}>{DASHBOARD_NEXT.LOADING}</div>
    </div>
  );
}
