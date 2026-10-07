import type { TickerReview } from "./data";

export function sourceUrl(raw: string | null | undefined): string | null {
  if (!raw) return null;

  try {
    const url = new URL(raw);

    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

export function amount(value: number | null | undefined, currency?: string | null): string {
  if (value == null) return "—";

  return `${value.toLocaleString("ko-KR", { maximumFractionDigits: 0 })}${currency ? ` ${currency}` : ""}`;
}

export function compactAmount(value: number | null | undefined, currency?: string | null): string {
  if (value == null || Math.abs(value) < 100_000) return amount(value, currency);

  return `${new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 2 }).format(value)}${currency ? ` ${currency}` : ""}`;
}

export function isFund(data: TickerReview): boolean {
  // cspell:ignore MUTUALFUND
  return Boolean(data.research?.dossier?.fund) || ["ETF", "MUTUALFUND"].includes(data.research?.dossier?.profile.quote_type || "");
}

export function priceRows(data: TickerReview) {
  return data.research?.dossier?.price_history?.length ? data.research.dossier.price_history : data.prices?.prices ?? [];
}
