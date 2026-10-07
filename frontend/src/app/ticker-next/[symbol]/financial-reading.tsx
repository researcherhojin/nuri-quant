import type { TickerReview } from "./data";
import { compactAmount } from "./research-format";
import { formatPct } from "@/lib/format";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import styles from "./ticker.module.css";

export function FinancialReading({ data }: { data: TickerReview }) {
  const dossier = data.research?.dossier;
  const income = dossier?.statements.income[0];
  const previous = dossier?.statements.income[1];
  const cash = dossier?.statements.cashflow[0];
  const balance = dossier?.statements.balance[0];
  const currency = dossier?.profile.financial_currency;
  const revenueChange = income?.revenue != null && previous?.revenue != null && previous.revenue > 0 ? (income.revenue / previous.revenue - 1) * 100 : null;
  const profitChange = income?.operating_income != null && previous?.operating_income != null && previous.operating_income > 0 ? (income.operating_income / previous.operating_income - 1) * 100 : null;
  const margin = income?.revenue != null && income.revenue > 0 && income.operating_income != null ? income.operating_income / income.revenue * 100 : null;
  const oldMargin = previous?.revenue != null && previous.revenue > 0 && previous.operating_income != null ? previous.operating_income / previous.revenue * 100 : null;

  return <div className={styles.financialReading}>
    {income && <section>
      <h3 className={styles.subheading}>{T.GROWTH_QUALITY}</h3><p className={styles.muted}>{T.PERIOD} · {income.period}</p>
      <dl className={styles.companyMetrics}><div><dt>{T.REVENUE}</dt><dd>{compactAmount(income.revenue, currency)}</dd></div><div><dt>{T.OPERATING_INCOME}</dt><dd>{compactAmount(income.operating_income, currency)}</dd></div><div><dt>{T.NET_INCOME}</dt><dd>{compactAmount(income.net_income, currency)}</dd></div></dl>
      {revenueChange != null && profitChange != null && <p>{T.PROFIT_CHANGE(income.period, formatPct(revenueChange), formatPct(profitChange))}</p>}
      {margin != null && oldMargin != null && <p>{T.PROFITABILITY_CHANGE(formatPct(oldMargin), formatPct(margin))}</p>}
      {revenueChange != null && profitChange != null && (revenueChange > 0 && profitChange < 0 ? <p>{T.GROWTH_DIVERGENCE}</p> : revenueChange > 0 && profitChange > 0 ? <p>{T.GROWTH_TOGETHER}</p> : null)}
    </section>}
    {cash && <section><h3 className={styles.subheading}>{T.CASH_QUALITY}</h3>
      <p>{T.SUMMARY_CASHFLOW(cash.period, compactAmount(cash.operating_cashflow, currency), compactAmount(cash.free_cashflow, currency))}</p>
      {income?.period === cash.period && income.net_income != null && income.net_income > 0 && cash.operating_cashflow != null && cash.operating_cashflow < 0 && <p>{T.PROFIT_CASH_DIVERGENCE}</p>}
      {dossier?.business?.has_financing && <p className={styles.muted}>{T.FINANCING_CONTEXT}</p>}
    </section>}
    {balance && <section><h3 className={styles.subheading}>{T.FUNDING_STRUCTURE}</h3><p>{T.CASH_COMPARE(balance.period, compactAmount(balance.cash, currency), compactAmount(balance.debt, currency))}</p></section>}
    {!income && !cash && !balance && <p className={styles.empty}>{T.NO_FINANCIALS}</p>}
  </div>;
}
