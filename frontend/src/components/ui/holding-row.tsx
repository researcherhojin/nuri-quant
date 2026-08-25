/**
 * HoldingRow — 보유 종목 통합 행 (Phase 2-C #199 + Phase 2-D #214)
 *
 * 한 줄에 종목 정보 + 매매 상태 + 가격 타겟 + 일변 + sparkline + 워치 트리거를 담는다.
 * morning_brief 영감의 "1 row = 1 ticker, complete picture" 패턴.
 */
import Link from "next/link";

import { Sparkline } from "@/components/ui/sparkline";
import { HOLDING_STATUS, HOLDING_LABEL } from "@/lib/strings";
import { formatMoney, isKrwTicker } from "@/lib/format";

// ── Raw input shapes (API response surfaces) ─────────────────
export interface RawHolding {
  ticker: string;
  account?: string;        // raw broker account id — used for advisor reason matching
  accountLabel?: string;   // anonymized display label (e.g. "Main") — used for action matching + display
  quantity?: number;
  avg_price?: number | null;
  latest_price?: number | null;
  previous_close?: number | null;   // #214: yesterday's close for daily delta
  sparkline_30d?: number[];          // #214: 30 daily closes, oldest → newest
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
  dailyDeltaPct: number | null;  // #214: 오늘 종가 vs 어제 종가 % (price history 없으면 null)
  sparkline: number[];            // #214: 30 closes oldest→newest (빈 배열이면 렌더 skip)
  latestPrice: number | null;     // #214 polish: 현재가 (표에 직접 표시)
  avgPrice: number | null;        // #214 polish: 평단가 (표시 + sparkline baseline)
  status: HoldingStatus;
  stopLoss: number | null;
  target1: number | null;
  target2: number | null;
  target1Reached: boolean;
  target2Reached: boolean;
  watch: WatchTrigger;
  sector: string | null;         // #218: GICS-ish 섹터 (2xl+ 초광폭 화면에서만 표시)
  positionPct: number | null;    // #218: 전체 포트폴리오(holdings+cash USD) 대비 비중 %
}

/**
 * #218 초광폭(2xl+) 컬럼 옵션 — 27" 모니터에서 비어있던 오른쪽 공간을 활용.
 * `totalPortfolioUsd` (holdings + cash USD)와 `usdKrwRate`를 받아 per-holding
 * 비중(%)을 계산한다. 값 누락 시 positionPct 는 null (HoldingRow가 em dash 렌더).
 */
export interface BuildOptions {
  totalPortfolioUsd?: number;
  usdKrwRate?: number;
}

// ── Builder ──────────────────────────────────────────────────
export function buildEnrichedHoldings(
  holdings: RawHolding[],
  actions: RawAction[] = [],
  targets: RawTarget[] = [],
  advisorActions: RawAdvisorAction[] = [],
  upcomingEvents: RawEvent[] = [],
  options: BuildOptions = {},
): EnrichedHolding[] {
  const totalUsd = options.totalPortfolioUsd ?? 0;
  const usdKrwRate = options.usdKrwRate ?? 0;
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
    // h.avg_price != null 가드 뒤이므로 (h.avg_price ?? 0) 의 redundant nullish 제거 — TS 가 number 로 narrow
    .filter((h) => h.latest_price != null && h.avg_price != null && h.avg_price > 0)
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

      // 통화 추론은 lib/format 한 곳 (#1197) — 이전 로컬 판정은 .KQ(코스닥)를 놓쳤다
      const currency: "USD" | "KRW" =
        h.currency === "KRW" || isKrwTicker(h.ticker) ? "KRW" : "USD";

      // #214: 일변 (오늘 vs 어제) + sparkline (30일 closes)
      const prevClose = h.previous_close;
      const dailyDeltaPct =
        prevClose != null && prevClose > 0
          ? ((latest - prevClose) / prevClose) * 100
          : null;
      const sparkline = Array.isArray(h.sparkline_30d) ? h.sparkline_30d : [];

      // #218: per-holding 비중 계산 (USD 기준).
      // KR 종목은 usdKrwRate 로 환산. totalUsd<=0 이거나 필수 값 누락 시 null.
      const qty = h.quantity ?? 0;
      const holdingValueLocal = latest * qty;
      const holdingValueUsd =
        currency === "KRW"
          ? usdKrwRate > 0
            ? holdingValueLocal / usdKrwRate
            : null
          : holdingValueLocal;
      const positionPct =
        holdingValueUsd != null && totalUsd > 0
          ? (holdingValueUsd / totalUsd) * 100
          : null;

      return {
        account: accountLabel,
        ticker: h.ticker,
        name: h.name ?? null,
        currency,
        pnlPct,
        dailyDeltaPct,
        sparkline,
        // filter 가 non-null 보장 → 위에서 narrow 한 latest/avg 직접 사용 (dead `?? null` 제거)
        latestPrice: latest,
        avgPrice: avg,
        status,
        stopLoss: stopLossPrice,
        target1: target?.target_1 ?? null,
        target2: target?.target_2 ?? null,
        target1Reached: tpTriggered === "target_1" || tpTriggered === "target_2",
        target2Reached: tpTriggered === "target_2",
        watch,
        sector: h.sector ?? null,
        positionPct,
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
// 표기는 formatMoney 로 위임 (#1197 codex P2) — 같은 대시보드에서 액션 카드는 $195.50,
// 보유 행은 $196 으로 갈리던 표기 이원화 제거. USD 는 항상 소수 2자리.
export function formatPrice(price: number | null, currency: "USD" | "KRW"): string {
  return formatMoney(price, { currency });
}

function statusVisual(s: HoldingStatus): { text: string; className: string } {
  switch (s.kind) {
    case "stop_loss":
      return { text: HOLDING_STATUS.STOP_LOSS, className: "bg-red-500/15 text-red-400 border-red-500/30" };
    case "violation":
      return { text: HOLDING_STATUS.VIOLATION, className: "bg-red-500/15 text-red-400 border-red-500/30" };
    case "sell":
      return { text: `${HOLDING_STATUS.SELL} ${s.confidence}`, className: "bg-red-500/15 text-red-400 border-red-500/30" };
    case "tp2":
      return { text: HOLDING_STATUS.TP2, className: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" };
    case "tp1":
      return { text: HOLDING_STATUS.TP1, className: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" };
    case "buy":
      return { text: `${HOLDING_STATUS.BUY} ${s.confidence}`, className: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" };
    case "hold":
      return { text: HOLDING_STATUS.HOLD, className: "bg-zinc-800/60 text-zinc-400 border-zinc-700" };
  }
}

// watchVisual() removed with #221 iter 4 — watch column was deleted from the
// row because its information was already shown in the top 이벤트 strip
// (single-source-of-truth UI). The `watch` field on EnrichedHolding is still
// computed by buildEnrichedHoldings so future features (tooltip, badge, etc)
// can consume it without touching the data layer.

// ── Component ────────────────────────────────────────────────
// #503 Phase C — macro-aware sectors prop. 이 set 에 포함되는 sector keyword 를
// substring 으로 가진 holding 은 sector cell 옆에 📡 뱃지를 띄운다.
interface HoldingRowProps_macroAware {
  macroAwareSectors?: Set<string>;
}

interface HoldingRowProps extends HoldingRowProps_macroAware {
  holding: EnrichedHolding;
  href?: string;
}

export function HoldingRow({ holding: h, href, macroAwareSectors }: HoldingRowProps) {
  const status = statusVisual(h.status);
  const pnlClass = h.pnlPct >= 0 ? "text-emerald-400" : "text-red-400";
  const linkHref = href ?? `/ticker/${h.ticker}`;
  const displayName = h.name || h.ticker.replace(".KS", "");

  // #503 Phase C — sector 가 활성 macro event 영향권에 있는지 lazy 검사.
  // import 하면 macro-impact 모듈에 의존 — single import 만, prop 처럼 행 단위
  // 검사가 필요하다.
  const macroAware = macroAwareSectors && h.sector
    ? Array.from(macroAwareSectors).some(k => h.sector!.toLowerCase().includes(k))
    : false;

  // #214: 일변 (daily delta)
  const hasDelta = h.dailyDeltaPct != null;
  const deltaClass = !hasDelta
    ? "text-zinc-700"
    : h.dailyDeltaPct! >= 0
    ? "text-emerald-400"
    : "text-red-400";
  const deltaText = !hasDelta
    ? "—"
    : `${h.dailyDeltaPct! >= 0 ? "+" : ""}${h.dailyDeltaPct!.toFixed(1)}%`;

  // target_1 cell
  const t1Cell = h.target1Reached ? (
    <span className="text-emerald-400 text-[10px]">{HOLDING_STATUS.REACHED}</span>
  ) : (
    <span className="text-zinc-400">{formatPrice(h.target1, h.currency)}</span>
  );

  // target_2 cell — highlight when target_1 reached but target_2 not (next goal)
  const t2NextGoal = h.target1Reached && !h.target2Reached;
  const t2Cell = h.target2Reached ? (
    <span className="text-emerald-400 text-[10px]">{HOLDING_STATUS.REACHED}</span>
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
      className="flex w-fit items-center gap-2 px-2 py-1.5 rounded hover:bg-zinc-800/50 text-xs group"
    >
      {/* account — wider at 2xl+ so labels like "LONG_TERM" don't truncate. Stays w-10 below
          2xl to keep the lg (1024) row width under the content budget (752 content). */}
      <span className="text-[9px] text-zinc-600 uppercase w-10 2xl:w-16 shrink-0 truncate" title={h.account}>
        {h.account}
      </span>
      {/* name */}
      <span className="font-medium text-zinc-100 truncate min-w-0 flex-1 sm:flex-none sm:w-20">
        {displayName}
      </span>
      {/* 현재가 / 평단가 — md+ (768px+). leading-[1.3] 으로 두 줄 사이 여유 살림. */}
      <span
        className="hidden md:flex flex-col items-end text-right tabular-nums shrink-0 w-18 leading-[1.3]"
        aria-label={HOLDING_LABEL.CURRENT_AVG}
      >
        <span className="text-[10px] text-zinc-200">{formatPrice(h.latestPrice, h.currency)}</span>
        <span className="text-[9px] text-zinc-500">{formatPrice(h.avgPrice, h.currency)}</span>
      </span>
      {/* pnl (누적) — 항상 */}
      <span className={`font-semibold tabular-nums text-right w-14 shrink-0 ${pnlClass}`}>
        {h.pnlPct >= 0 ? "+" : ""}
        {h.pnlPct.toFixed(1)}%
      </span>
      {/* 일변 (daily delta) — sm+ */}
      <span
        className={`hidden sm:inline-block tabular-nums text-right w-12 shrink-0 text-[10px] ${deltaClass}`}
        aria-label={HOLDING_LABEL.DAILY_DELTA}
        data-testid="daily-delta"
      >
        {deltaText}
      </span>
      {/* status badge — 항상 */}
      <span
        className={`inline-flex items-center justify-center text-[10px] font-medium rounded border px-1.5 py-0.5 w-17 shrink-0 ${status.className}`}
      >
        {status.text}
      </span>
      {/* stop loss — md+ */}
      <span
        className="hidden md:inline-block w-17 text-right tabular-nums text-zinc-500 shrink-0"
        aria-label={HOLDING_LABEL.STOP_LOSS}
      >
        {formatPrice(h.stopLoss, h.currency)}
      </span>
      {/* target_1 — lg+ */}
      <span
        className="hidden lg:inline-block w-17 text-right tabular-nums shrink-0"
        aria-label={HOLDING_LABEL.TARGET_1}
      >
        {t1Cell}
      </span>
      {/* target_2 — lg+ */}
      <span
        className="hidden lg:inline-block w-17 text-right tabular-nums shrink-0"
        aria-label={HOLDING_LABEL.TARGET_2}
      >
        {t2Cell}
      </span>
      {/*
        sparkline — 두 variant를 CSS breakpoint로 swap.
        xl (1280–1535): 고정 80px
        2xl+ (1536+):   고정 240px — 80px 대비 3x, 읽기 좋은 밀도. flex 확장 안 함.
      */}
      <span className="hidden xl:inline-flex 2xl:hidden items-center shrink-0" data-testid="sparkline-narrow">
        <Sparkline
          series={h.sparkline}
          width={80}
          height={18}
          baseline={h.avgPrice}
        />
      </span>
      <span
        className="hidden 2xl:inline-flex items-center shrink-0"
        data-testid="sparkline-wide"
      >
        <Sparkline
          series={h.sparkline}
          width={240}
          height={18}
          baseline={h.avgPrice}
        />
      </span>
      {/* #218: 섹터 — 2xl+ (1536px+) 27" 모니터용. Label 데이터라 text-left.
          #503 Phase C: macro 영향권 sector 는 📡 뱃지 + amber 색강조. */}
      <span
        className={`hidden 2xl:inline-block w-24 text-left text-[10px] truncate shrink-0 ${macroAware ? "text-amber-400 font-semibold" : "text-zinc-500"}`}
        aria-label={HOLDING_LABEL.SECTOR}
        data-testid="sector-cell"
        title={macroAware ? `${h.sector} — macro 영향권` : h.sector ?? undefined}
      >
        {macroAware && <span aria-label="macro-aware" className="mr-0.5">📡</span>}
        {h.sector ?? "—"}
      </span>
      {/* #218: 비중 (% of portfolio) — 2xl+ (1536px+) 27" 모니터용 */}
      <span
        className="hidden 2xl:inline-block w-14 text-right tabular-nums text-[10px] text-zinc-400 shrink-0"
        aria-label={HOLDING_LABEL.POSITION_PCT}
        data-testid="position-pct-cell"
      >
        {h.positionPct != null ? `${h.positionPct.toFixed(1)}%` : "—"}
      </span>
    </Link>
  );
}
