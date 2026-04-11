/**
 * HoldingRow — 보유 종목 통합 행 (Phase 2-C #199)
 *
 * 한 줄에 종목 정보 + 매매 상태 + 가격 타겟 + 워치 트리거를 담는다.
 * morning_brief 영감의 "1 row = 1 ticker, complete picture" 패턴.
 */
import Link from "next/link";

// ── Raw input shapes (API response surfaces) ─────────────────
export interface RawHolding {
  ticker: string;
  account?: string;        // raw broker name (e.g. "kakaopay") — used for advisor reason matching
  accountLabel?: string;   // anonymized display label (e.g. "Main") — used for action matching + display
  quantity?: number;
  avg_price?: number | null;
  latest_price?: number | null;
  currency?: string;
  sector?: string | null;
  name?: string | null;
}

export interface RawAction {
  action: string;
  ticker: string;
  account?: string;
  confidence: number;
  agreement?: number;
  reason?: string;
}

export interface RawTarget {
  ticker: string;
  stop_loss?: number | null;
  target_1?: number | null;
  target_2?: number | null;
  take_profit_triggered?: "target_1" | "target_2" | null;
  trailing_stop_triggered?: boolean;
  current_price?: number | null;
}

export interface RawAdvisorAction {
  ticker: string;
  violation_type: string;
  severity: "low" | "medium" | "high" | "critical";
  current_value?: number;
  reason?: string;
}

export interface RawEvent {
  date: string;
  event_type: string;
  ticker: string | null;
  description?: string;
}

// ── Enriched output ──────────────────────────────────────────
export type HoldingStatus =
  | { kind: "stop_loss" }
  | { kind: "violation"; weight: number }
  | { kind: "sell"; confidence: number }
  | { kind: "tp2" }
  | { kind: "tp1" }
  | { kind: "buy"; confidence: number }
  | { kind: "hold" };

export type WatchTrigger =
  | { kind: "earnings"; daysUntil: number }
  | { kind: "none" };

export interface EnrichedHolding {
  account: string;
  ticker: string;
  name: string | null;
  currency: "USD" | "KRW";
  pnlPct: number;
  status: HoldingStatus;
  stopLoss: number | null;
  target1: number | null;
  target2: number | null;
  target1Reached: boolean;
  target2Reached: boolean;
  watch: WatchTrigger;
}

// ── Builder ──────────────────────────────────────────────────
export function buildEnrichedHoldings(
  holdings: RawHolding[],
  actions: RawAction[] = [],
  targets: RawTarget[] = [],
  advisorActions: RawAdvisorAction[] = [],
  upcomingEvents: RawEvent[] = [],
): EnrichedHolding[] {
  const targetByTicker = new Map(targets.map((t) => [t.ticker, t]));
  const earningsByTicker = new Map<string, RawEvent[]>();
  for (const ev of upcomingEvents) {
    if (!ev.ticker) continue;
    if (ev.event_type !== "earnings") continue;
    const list = earningsByTicker.get(ev.ticker) ?? [];
    list.push(ev);
    earningsByTicker.set(ev.ticker, list);
  }

  // Local-date midnight to avoid timezone-induced off-by-one when event dates
  // are stored as plain YYYY-MM-DD (no time component).
  const _now = new Date();
  const todayMs = new Date(_now.getFullYear(), _now.getMonth(), _now.getDate()).getTime();

  const enriched = holdings
    .filter((h) => h.latest_price != null && h.avg_price != null && (h.avg_price ?? 0) > 0)
    .map((h): EnrichedHolding => {
      const latest = h.latest_price as number;
      const avg = h.avg_price as number;
      const pnlPct = (latest / avg - 1) * 100;
      const accountRaw = h.account ?? "";
      const accountLabel = h.accountLabel ?? accountRaw;
      const target = targetByTicker.get(h.ticker);

      // Action: ticker + (optional) labeled account match
      // Actions from /api/dashboard use anonymized labels — match against accountLabel.
      const action = actions.find(
        (a) => a.ticker === h.ticker && (!a.account || !accountLabel || a.account === accountLabel),
      );

      // Advisor violation: severity high/critical, prefer reason mentioning the raw account.
      // Reason strings from rebalance_advisor (PR #211) embed the raw broker account name.
      const advisor = advisorActions.find(
        (a) =>
          a.ticker === h.ticker &&
          (a.severity === "high" || a.severity === "critical") &&
          (accountRaw === "" || !a.reason || a.reason.includes(accountRaw)),
      );

      // Status (priority order)
      const stopLossPrice = target?.stop_loss ?? null;
      const tpTriggered = target?.take_profit_triggered ?? null;
      let status: HoldingStatus;
      if (stopLossPrice != null && latest < stopLossPrice) {
        status = { kind: "stop_loss" };
      } else if (advisor) {
        status = { kind: "violation", weight: advisor.current_value ?? 0 };
      } else if (action?.action === "SELL") {
        status = { kind: "sell", confidence: action.confidence };
      } else if (tpTriggered === "target_2") {
        status = { kind: "tp2" };
      } else if (tpTriggered === "target_1") {
        status = { kind: "tp1" };
      } else if (action?.action === "BUY") {
        status = { kind: "buy", confidence: action.confidence };
      } else {
        status = { kind: "hold" };
      }

      // Watch: nearest upcoming earnings within 30 days
      const events = earningsByTicker.get(h.ticker) ?? [];
      const upcoming = events
        .map((ev) => {
          // Parse YYYY-MM-DD as local date (avoid UTC interpretation)
          const [y, m, d] = ev.date.split("-").map(Number);
          if (!y || !m || !d) return { ev, days: Number.NaN };
          const eventMs = new Date(y, m - 1, d).getTime();
          return { ev, days: Math.round((eventMs - todayMs) / 86_400_000) };
        })
        .filter(({ days }) => Number.isFinite(days) && days >= 0 && days <= 30)
        .sort((a, b) => a.days - b.days)[0];
      const watch: WatchTrigger = upcoming ? { kind: "earnings", daysUntil: upcoming.days } : { kind: "none" };

      const currency: "USD" | "KRW" =
        h.currency === "KRW" || h.ticker.endsWith(".KS") ? "KRW" : "USD";

      return {
        account: accountLabel,
        ticker: h.ticker,
        name: h.name ?? null,
        currency,
        pnlPct,
        status,
        stopLoss: stopLossPrice,
        target1: target?.target_1 ?? null,
        target2: target?.target_2 ?? null,
        target1Reached: tpTriggered === "target_1" || tpTriggered === "target_2",
        target2Reached: tpTriggered === "target_2",
        watch,
      };
    });

  // Sort: account asc → status priority → |pnl| desc
  const statusPriority: Record<HoldingStatus["kind"], number> = {
    stop_loss: 1,
    violation: 2,
    sell: 3,
    tp2: 4,
    tp1: 5,
    buy: 6,
    hold: 7,
  };
  enriched.sort((a, b) => {
    if (a.account !== b.account) return a.account.localeCompare(b.account);
    const pa = statusPriority[a.status.kind];
    const pb = statusPriority[b.status.kind];
    if (pa !== pb) return pa - pb;
    return Math.abs(b.pnlPct) - Math.abs(a.pnlPct);
  });

  return enriched;
}

// ── Format helpers ───────────────────────────────────────────
export function formatPrice(price: number | null, currency: "USD" | "KRW"): string {
  if (price == null) return "—";
  if (currency === "KRW") return `₩${Math.round(price).toLocaleString()}`;
  return price < 100 ? `$${price.toFixed(2)}` : `$${Math.round(price).toLocaleString()}`;
}

function statusVisual(s: HoldingStatus): { text: string; className: string } {
  switch (s.kind) {
    case "stop_loss":
      return { text: "손절", className: "bg-red-500/15 text-red-400 border-red-500/30" };
    case "violation":
      return { text: "⚠ 위반", className: "bg-red-500/15 text-red-400 border-red-500/30" };
    case "sell":
      return { text: `매도 ${s.confidence}`, className: "bg-red-500/15 text-red-400 border-red-500/30" };
    case "tp2":
      return { text: "✓ 익절₂", className: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" };
    case "tp1":
      return { text: "✓ 익절₁", className: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" };
    case "buy":
      return { text: `매수 ${s.confidence}`, className: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" };
    case "hold":
      return { text: "보유", className: "bg-zinc-800/60 text-zinc-400 border-zinc-700" };
  }
}

function watchVisual(w: WatchTrigger): { text: string; className: string } | null {
  if (w.kind === "none") return null;
  if (w.kind === "earnings") {
    if (w.daysUntil === 0) return { text: "실적 D-DAY", className: "text-amber-400" };
    if (w.daysUntil <= 7) return { text: `실적 D-${w.daysUntil}`, className: "text-amber-400" };
    return { text: `실적 D-${w.daysUntil}`, className: "text-zinc-500" };
  }
  return null;
}

// ── Component ────────────────────────────────────────────────
interface HoldingRowProps {
  holding: EnrichedHolding;
  href?: string;
}

export function HoldingRow({ holding: h, href }: HoldingRowProps) {
  const status = statusVisual(h.status);
  const watch = watchVisual(h.watch);
  const pnlClass = h.pnlPct >= 0 ? "text-emerald-400" : "text-red-400";
  const linkHref = href ?? `/ticker/${h.ticker}`;
  const displayName = h.name || h.ticker.replace(".KS", "");

  // target_1 cell
  const t1Cell = h.target1Reached ? (
    <span className="text-emerald-400 text-[10px]">✓ 도달</span>
  ) : (
    <span className="text-zinc-400">{formatPrice(h.target1, h.currency)}</span>
  );

  // target_2 cell — highlight when target_1 reached but target_2 not (next goal)
  const t2NextGoal = h.target1Reached && !h.target2Reached;
  const t2Cell = h.target2Reached ? (
    <span className="text-emerald-400 text-[10px]">✓ 도달</span>
  ) : (
    <span className={t2NextGoal ? "text-zinc-100 font-semibold" : "text-zinc-500"}>
      {formatPrice(h.target2, h.currency)}
    </span>
  );

  return (
    <Link
      href={linkHref}
      data-testid="holding-row"
      data-status={h.status.kind}
      className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-zinc-800/50 text-xs group"
    >
      {/* account */}
      <span className="text-[9px] text-zinc-600 uppercase w-10 shrink-0 truncate" title={h.account}>
        {h.account}
      </span>
      {/* name */}
      <span className="font-medium text-zinc-100 truncate min-w-0 flex-1 sm:flex-none sm:w-20">
        {displayName}
      </span>
      {/* pnl */}
      <span className={`font-semibold tabular-nums text-right w-14 shrink-0 ${pnlClass}`}>
        {h.pnlPct >= 0 ? "+" : ""}
        {h.pnlPct.toFixed(1)}%
      </span>
      {/* status badge */}
      <span
        className={`inline-flex items-center justify-center text-[10px] font-medium rounded border px-1.5 py-0.5 w-[68px] shrink-0 ${status.className}`}
      >
        {status.text}
      </span>
      {/* stop loss — sm+ */}
      <span
        className="hidden sm:inline-block w-[72px] text-right tabular-nums text-zinc-500 shrink-0"
        aria-label="손절가"
      >
        {formatPrice(h.stopLoss, h.currency)}
      </span>
      {/* target_1 — sm+ */}
      <span
        className="hidden sm:inline-block w-[72px] text-right tabular-nums shrink-0"
        aria-label="1차 익절가"
      >
        {t1Cell}
      </span>
      {/* target_2 — sm+ */}
      <span
        className="hidden sm:inline-block w-[72px] text-right tabular-nums shrink-0"
        aria-label="2차 익절가"
      >
        {t2Cell}
      </span>
      {/* watch trigger */}
      <span
        className={`flex-1 text-[10px] text-right truncate ${watch ? watch.className : "text-zinc-700"}`}
      >
        {watch ? watch.text : "—"}
      </span>
    </Link>
  );
}
