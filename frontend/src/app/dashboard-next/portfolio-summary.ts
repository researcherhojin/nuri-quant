import { DASHBOARD_NEXT as COPY } from "@/lib/strings";
import type { Portfolio } from "./data";

export type Composition = "ticker" | "sector" | "account";

export function summarizePortfolio(portfolio: Portfolio, exchangeRate: number | null | undefined, group: Composition) {
  const values = new Map<string, number>();
  const names = new Map<string, string>();
  let incomplete = false;

  const add = (key: string, value: number | null) => {
    if (value == null || !Number.isFinite(value) || value < 0) {
      incomplete = true;

      return;
    }

    values.set(key, (values.get(key) ?? 0) + value);
  };

  for (const holding of portfolio.holdings) {
    const rate = holding.currency === "USD" ? 1 : holding.currency === "KRW" && exchangeRate != null && exchangeRate > 0 ? exchangeRate : null;
    const value = rate != null && holding.latest_price != null && holding.latest_price > 0 ? holding.quantity * holding.latest_price / rate : null;
    const label = group === "sector" ? holding.sector || COPY.PORTFOLIO.UNCLASSIFIED : group === "account" ? holding.account : holding.ticker;

    // 합산 키는 티커로 유지한다. 이름이 같은 다른 종목을 합치지 않는다.
    if (group === "ticker" && /\.(KS|KQ)$/.test(holding.ticker) && holding.name?.trim()) names.set(holding.ticker, holding.name.trim());
    add(label, value);
  }

  if (group === "account") portfolio.cash.accounts.forEach(item => add(item.account, item.total_usd));
  else add(COPY.PORTFOLIO.CASH, portfolio.cash.total_cash_usd);

  if (portfolio.cash.total_cash_usd == null) incomplete = true;
  const sum = [...values.values()].reduce((a, b) => a + b, 0);
  const total = incomplete ? null : sum;
  const rows = [...values].sort((a, b) => b[1] - a[1]).map(([key, value]) => ({ key, label: names.get(key) ?? key, value, weight: total != null && total > 0 ? value / total * 100 : null }));
  const dates = portfolio.holdings.map(h => h.price_date).filter((d): d is string => !!d).sort();

  return { total, rows, oldestPrice: dates[0] ?? null, newestPrice: dates.at(-1) ?? null };
}
