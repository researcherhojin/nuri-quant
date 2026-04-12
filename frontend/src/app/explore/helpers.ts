/**
 * Explore page helper functions — extracted for testability.
 * Pure functions, no React/Server Component dependency.
 */
import { TREND, VIX_ZONE, FEAR_GREED, MACRO_LEVEL, SIGNAL, EXPLORE } from "@/lib/strings";

export function trendKo(t: string) {
  return t === "bull" ? TREND.BULL : t === "bear" ? TREND.BEAR : TREND.SIDEWAYS;
}

export function vixZone(v: number | null): { label: string; color: string } {
  if (v == null) return { label: "—", color: "text-zinc-500" };
  if (v < 12) return { label: VIX_ZONE.CALM, color: "text-blue-400" };
  if (v < 17) return { label: VIX_ZONE.LOW, color: "text-emerald-400" };
  if (v < 23) return { label: VIX_ZONE.NORMAL, color: "text-zinc-300" };
  if (v < 33) return { label: VIX_ZONE.CAUTION, color: "text-orange-400" };
  return { label: VIX_ZONE.DANGER, color: "text-red-400" };
}

export function fgLabel(fg: number | null): string {
  if (fg == null) return "—";
  if (fg < 25) return FEAR_GREED.EXTREME_FEAR;
  if (fg < 45) return FEAR_GREED.FEAR;
  if (fg <= 55) return FEAR_GREED.NEUTRAL;
  if (fg <= 75) return FEAR_GREED.GREED;
  return FEAR_GREED.EXTREME_GREED;
}

export function macroLevel(s: number): { label: string; color: string } {
  if (s >= 70) return { label: MACRO_LEVEL.GOOD, color: "text-emerald-400" };
  if (s >= 50) return { label: MACRO_LEVEL.NORMAL, color: "text-zinc-300" };
  if (s >= 30) return { label: MACRO_LEVEL.WEAK, color: "text-orange-400" };
  return { label: MACRO_LEVEL.FRAGILE, color: "text-red-400" };
}

const SIGNAL_KO: Record<string, string> = {
  bb_bounce: SIGNAL.BB_BOUNCE, macd_bullish_turn: SIGNAL.MACD_BULLISH_TURN,
  macd_bearish_turn: SIGNAL.MACD_BEARISH_TURN, macd_golden: SIGNAL.MACD_GOLDEN,
  macd_dead: SIGNAL.MACD_DEAD, rsi_oversold: SIGNAL.RSI_OVERSOLD,
  rsi_overbought: SIGNAL.RSI_OVERBOUGHT, sma_golden: SIGNAL.SMA_GOLDEN,
  sma_dead: SIGNAL.SMA_DEAD, volume_spike: SIGNAL.VOLUME_SPIKE,
  gap_up: SIGNAL.GAP_UP, gap_down: SIGNAL.GAP_DOWN,
  bb_squeeze_breakout: SIGNAL.BB_SQUEEZE_BREAKOUT,
  near_52w_low_bounce: SIGNAL.NEAR_52W_LOW_BOUNCE,
  volume_profile_resistance: SIGNAL.VOLUME_PROFILE_RESISTANCE,
};

export function signalKo(id: string): string {
  return SIGNAL_KO[id] ?? id.replace(/_/g, " ");
}

export function formatPrice(price: number | null, isKr: boolean): string {
  if (price == null) return EXPLORE.NO_PRICE;
  return isKr
    ? `₩${Math.round(price).toLocaleString()}`
    : price < 100 ? `$${price.toFixed(2)}` : `$${Math.round(price).toLocaleString()}`;
}

export function formatDelta(price: number | null, prev: number | null): { str: string; color: string } | null {
  if (price == null || prev == null || prev <= 0) return null;
  const delta = ((price - prev) / prev) * 100;
  return {
    str: `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`,
    color: delta >= 0 ? "text-emerald-400" : "text-red-400",
  };
}

// Popular tickers (from universe.yaml top by market cap)
export const POPULAR_US = [
  { ticker: "NVDA", name: "NVIDIA" },
  { ticker: "TSLA", name: "Tesla" },
  { ticker: "AAPL", name: "Apple" },
  { ticker: "MSFT", name: "Microsoft" },
  { ticker: "GOOGL", name: "Alphabet" },
  { ticker: "AMZN", name: "Amazon" },
];

export const POPULAR_KR = [
  { ticker: "005930.KS", name: "삼성전자" },
  { ticker: "000660.KS", name: "SK하이닉스" },
  { ticker: "035420.KS", name: "NAVER" },
  { ticker: "005380.KS", name: "현대차" },
  { ticker: "373220.KS", name: "LG에너지솔루션" },
  { ticker: "035720.KS", name: "카카오" },
];

export const KR_NAMES: Record<string, string> = Object.fromEntries(POPULAR_KR.map((t) => [t.ticker, t.name]));

export function tickerDisplay(ticker: string): string {
  return KR_NAMES[ticker] ?? ticker;
}
