export const dynamic = "force-dynamic";

import { Suspense } from "react";
import Link from "next/link";
import { fetchAPI } from "@/lib/api";
import { StatusBadge } from "@/components/ui/status-badge";
import { EXPLORE, REGIME_GUIDE, COMMON } from "@/lib/strings";
import { trendKo, vixZone, fgLabel, macroLevel, signalKo, formatPrice, formatDelta, tickerDisplay, POPULAR_US, POPULAR_KR } from "./helpers";

// ── Types ──
interface Candidate {
  ticker: string;
  direction: string;
  signal_id: string;
  confidence: number;
}

// ── Search component (Client) ──
import { ExploreSearch } from "./search";

// ── Price data types ──
interface BatchPriceData {
  prices: Record<string, { price: number | null; prev: number | null; date: string | null }>;
}

// ── Quick-link card (pure component — receives pre-fetched data) ──
function QuickLinkCard({ ticker, name, price, prev }: {
  ticker: string; name: string; price: number | null; prev: number | null;
}) {
  const isKr = ticker.endsWith(".KS") || ticker.endsWith(".KQ");
  const hasPrice = price != null;
  const priceStr = formatPrice(price, isKr);
  const delta = formatDelta(price, prev);
  const deltaStr = delta?.str ?? "";
  const deltaColor = delta?.color ?? "";

  return (
    <Link
      href={`/ticker/${ticker}`}
      className={`flex flex-col gap-0.5 rounded-lg border px-3 py-2 transition-colors min-w-0 ${
        hasPrice
          ? "border-zinc-800/60 bg-zinc-900/40 hover:bg-zinc-800/60 hover:border-zinc-700"
          : "border-zinc-800/30 bg-zinc-900/20 opacity-60 hover:opacity-80"
      }`}
      data-testid={`quicklink-${ticker}`}
    >
      <span className="text-xs font-semibold text-zinc-100 truncate">{name}</span>
      <div className="flex items-baseline gap-1.5">
        <span className={`text-[10px] tabular-nums ${hasPrice ? "text-zinc-400" : "text-zinc-600"}`}>{priceStr}</span>
        {deltaStr && <span className={`text-[10px] tabular-nums font-medium ${deltaColor}`}>{deltaStr}</span>}
      </div>
    </Link>
  );
}

// ── Market Context Strip ──
// Single dedicated endpoint that queries VIX/F&G/macro from DB independently.
// Works even when regime classification fails (SPY data stale).
interface MarketContextData {
  trend: string | null;
  vix: number | null;
  vix_date: string | null;
  fear_greed: number | null;
  fg_date: string | null;
  macro_score: number | null;
}

async function MarketContext() {
  const ctx = await fetchAPI<MarketContextData>("/api/tickers/market-context").catch(() => null);

  const trend = ctx?.trend ?? null;
  const vix = ctx?.vix ?? null;
  const fg = ctx?.fear_greed ?? null;
  const hasMacro = ctx?.macro_score != null && ctx.macro_score > 0;
  const hasAny = trend || vix != null || fg != null || hasMacro;

  if (!hasAny) {
    return (
      <div className="text-[10px] text-zinc-500 px-2 py-1.5 rounded bg-zinc-900/40 border border-zinc-800/60">
        ⚠ {EXPLORE.MARKET_NO_DATA}
      </div>
    );
  }

  const vInfo = vixZone(vix);
  const mInfo = hasMacro ? macroLevel(ctx!.macro_score!) : null;
  const tColor = trend === "bull" ? "text-emerald-400" : trend === "bear" ? "text-red-400" : "text-amber-400";

  return (
    <div className="flex items-center gap-3 flex-wrap text-[10px] text-zinc-500 px-2 py-1.5 rounded bg-zinc-900/40 border border-zinc-800/60">
      {trend && (
        <span className="flex items-center gap-1.5">
          <span className={`${tColor} font-semibold`}>{trendKo(trend)}</span>
          {REGIME_GUIDE[trend] && <span className="text-zinc-600">— {REGIME_GUIDE[trend]}</span>}
        </span>
      )}
      {vix != null && (
        <span>VIX <span className={`font-semibold tabular-nums ${vInfo.color}`}>{Math.round(vix * 10) / 10}</span> <span className={vInfo.color}>{vInfo.label}</span></span>
      )}
      {fg != null && (
        <span>심리 <span className="font-semibold tabular-nums">{fg}</span> <span className="text-zinc-600">{fgLabel(fg)}</span></span>
      )}
      {mInfo && ctx?.macro_score && (
        <span>경제 <span className={`font-semibold tabular-nums ${mInfo.color}`}>{ctx.macro_score}</span> <span className={mInfo.color}>{mInfo.label}</span></span>
      )}
    </div>
  );
}

// ── Recent Signals ──
async function RecentSignals() {
  const data = await fetchAPI<{ candidates: Candidate[] }>("/api/candidates?days=5").catch(() => null);
  const candidates = data?.candidates ?? [];

  if (candidates.length === 0) {
    return (
      <p className="text-[10px] text-zinc-500 px-2">
        {EXPLORE.SIGNALS_NO_DATA}
      </p>
    );
  }

  // Deduplicate by ticker — show only latest signal per ticker
  const seen = new Set<string>();
  const unique = candidates.filter((c) => {
    if (seen.has(c.ticker)) return false;
    seen.add(c.ticker);
    return true;
  });

  return (
    <div className="flex flex-wrap gap-2 px-2">
      {unique.slice(0, 8).map((c, i) => (
        <Link
          key={`${c.ticker}-${i}`}
          href={`/ticker/${c.ticker}`}
          className="flex items-center gap-1 text-[10px] hover:text-zinc-100 transition-colors"
        >
          <span className="text-zinc-200 font-medium">{tickerDisplay(c.ticker)}</span>
          <span className="text-zinc-500">{signalKo(c.signal_id ?? "")}</span>
          <StatusBadge status={c.direction} size="sm" />
        </Link>
      ))}
    </div>
  );
}

// ── Loading skeletons ──
function QuickLinkSkeleton() {
  return <div className="h-14 rounded-lg bg-zinc-900/40 border border-zinc-800/60 animate-pulse" />;
}

function StripSkeleton() {
  return <div className="h-8 rounded bg-zinc-900/40 border border-zinc-800/60 animate-pulse" />;
}

// ── Quicklinks section (single batch fetch for all 12 tickers) ──
async function QuickLinksGrid() {
  const allTickers = [...POPULAR_US, ...POPULAR_KR].map((t) => t.ticker);
  const batch = await fetchAPI<BatchPriceData>(
    `/api/tickers/latest-prices?tickers=${allTickers.join(",")}`
  ).catch((): BatchPriceData => ({ prices: {} }));

  const hasAnyMissing = allTickers.some((t) => !batch.prices[t]?.price);

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <p className="text-[9px] text-zinc-500 uppercase tracking-wide mb-2">{EXPLORE.US_POPULAR}</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {POPULAR_US.map((t) => {
              const p = batch.prices[t.ticker];
              return <QuickLinkCard key={t.ticker} ticker={t.ticker} name={t.name} price={p?.price ?? null} prev={p?.prev ?? null} />;
            })}
          </div>
        </div>
        <div>
          <p className="text-[9px] text-zinc-500 uppercase tracking-wide mb-2">{EXPLORE.KR_POPULAR}</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {POPULAR_KR.map((t) => {
              const p = batch.prices[t.ticker];
              return <QuickLinkCard key={t.ticker} ticker={t.ticker} name={t.name} price={p?.price ?? null} prev={p?.prev ?? null} />;
            })}
          </div>
        </div>
      </div>
      {hasAnyMissing && (
        <p className="text-[9px] text-zinc-600 px-1">
          💡 흐린 카드는 가격 미수집 — <code className="text-zinc-500 bg-zinc-800/50 px-1 rounded">{EXPLORE.COLLECT_HINT}</code>
        </p>
      )}
    </div>
  );
}

// ── Page ──
export default function ExplorePage() {
  return (
    <div className="flex flex-col gap-5 max-w-4xl">
      <div>
        <h1 className="text-lg font-semibold">Explore</h1>
        <p className="text-xs text-muted-foreground mt-1">
          {EXPLORE.SEARCH_HINT}
        </p>
      </div>

      {/* Search */}
      <ExploreSearch />

      {/* Quick-link grids — single batch API call for all 12 tickers */}
      <Suspense fallback={
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div><div className="grid grid-cols-2 sm:grid-cols-3 gap-2">{POPULAR_US.map((t) => <QuickLinkSkeleton key={t.ticker} />)}</div></div>
          <div><div className="grid grid-cols-2 sm:grid-cols-3 gap-2">{POPULAR_KR.map((t) => <QuickLinkSkeleton key={t.ticker} />)}</div></div>
        </div>
      }>
        <QuickLinksGrid />
      </Suspense>

      {/* Market context */}
      <div>
        <p className="text-[9px] text-zinc-500 uppercase tracking-wide mb-1.5">{EXPLORE.MARKET_CONTEXT}</p>
        <Suspense fallback={<StripSkeleton />}>
          <MarketContext />
        </Suspense>
      </div>

      {/* Recent signals */}
      <div>
        <p className="text-[9px] text-zinc-500 uppercase tracking-wide mb-1.5">{EXPLORE.RECENT_SIGNALS}</p>
        <Suspense fallback={<StripSkeleton />}>
          <RecentSignals />
        </Suspense>
      </div>

      {/* Quick start */}
      <div className="mt-2 rounded-lg border border-zinc-800/60 bg-zinc-900/30 px-4 py-3">
        <p className="text-xs text-zinc-400">
          💡 <span className="font-medium text-zinc-300">{EXPLORE.QUICK_START}</span>
          {" — "}
          <Link
            href="/portfolio?onboarding=true"
            className="text-emerald-400 hover:text-emerald-300 underline underline-offset-2"
          >
            {EXPLORE.LOAD_SAMPLE}
          </Link>
          {" → "}
          <span className="text-zinc-500">{EXPLORE.LOAD_SAMPLE_DESC}</span>
        </p>
      </div>
    </div>
  );
}
