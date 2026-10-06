/**
 * SystemHealthRail + MacroEventsCard + RegimeShiftBanner (#1208 U2b-2).
 *
 * MarketContext(4-card 가로 그리드 + 이벤트 카드)를 분해 — 대시보드가 좌 2/3 액션
 * 테이블 · 우 1/3 시스템 레일로 재구성되면서 (목업·plan §4), 건강 지표는 세로 컴팩트
 * 행으로, 이벤트 카드는 레일 하단으로 이동한다. 데이터 계약·색·링크는 기존 그대로.
 */
import Link from "next/link";
import { Pin, TriangleAlert } from "lucide-react";
import { CONTEXT, MARKET, MACRO_INTERPRETATION } from "@/lib/strings";
import {
  type MacroEvent, type SystemHealth,
  shouldPinCard, sparklinePath, categoryStyles, healthColor, regimeStripe, isRegimeShifting,
} from "@/components/ui/market-context";
import { trendKo, vixZone, fgLabel, fgColor } from "./helpers";

export interface Allocation { long: number; short: number; cash: number }

/** `/api/freshness` 항목 — 레일은 WARN/FAIL 만 나열한다 (#1652; 칩 컴포넌트 FreshnessBar 는 소비자가 없어 제거). */
export interface FreshnessItem {
  key: string;
  label: string;
  status: "PASS" | "WARN" | "FAIL";
  age_hours: number;
  message: string;
}

/**
 * #1652: 시장 사실(추세·VIX·심리·배분)은 이전에 레일 아래 한 줄 스트립(MarketStrip)에
 * 흩어져 있었다. 같은 레일 행 형식으로 모아 "레짐 → 심리 → 배분 → 데이터" 를 한 번에
 * 읽게 한다. 값이 없는 지표는 행을 만들지 않는다 — "VIX — —" 류 placeholder 금지(원칙 유지).
 */
/**
 * `/api/dashboard` 의 macro 블록. interpretation 은 백엔드(`macro_score.py`)가 정한다 —
 * 4단계 라벨 외에 coverage < MACRO_MIN_COVERAGE 이면 "Insufficient", 산출 실패면
 * "Unavailable"(coverage 0, 점수 50 placeholder). 프론트가 점수만 보고 라벨을 다시 지어내면
 * 그 한정이 사라진다 (Codex #1652 P1 두 라운드).
 */
export interface MacroReading { score: number; interpretation: string; coverage?: number }

/**
 * 백엔드 4단계 → 한국어 라벨·색. 점수로 다시 분류하지 않는다(`macroLevel()` 금지): 백엔드는 반올림 전
 * 값으로 분류하고 API 는 반올림해 보내므로 49.6 → {50, "Cautious"} 를 점수로 다시 나누면 "보통" 이 된다 (Codex #1652 r3).
 */
const MACRO_LEVELS: Record<string, { label: string; color: string }> = {
  Favorable: { label: MACRO_INTERPRETATION.Favorable, color: "text-emerald-400" },
  Neutral: { label: MACRO_INTERPRETATION.Neutral, color: "text-zinc-300" },
  Cautious: { label: MACRO_INTERPRETATION.Cautious, color: "text-orange-400" },
  Adverse: { label: MACRO_INTERPRETATION.Adverse, color: "text-red-400" },
};

export interface MarketFacts {
  trend: string;
  vix: number | null;
  fg: number | null;
  macro?: MacroReading;
  // #1284: 환율 미수집이면 백엔드가 null 을 낸다 — 분모를 모르면 배분도 모른다.
  actualAllocation?: Allocation | null;
  targetAllocation?: Allocation | null;
  fallbackAllocation?: Allocation | null;
}

/* ── 레짐 전환 배너 (full-width, 조건부) ─────────────────────── */
export function RegimeShiftBanner({ regime }: { regime: Partial<SystemHealth["regime"]> }) {
  if (!isRegimeShifting(regime)) return null;

  return (
    <div className="rounded-lg bg-amber-950/40 border border-amber-700/50 px-3 py-2 flex items-center gap-2 text-xs">
      <TriangleAlert className="shrink-0 size-3.5 text-amber-400" aria-hidden />
      <span className="text-amber-300 font-semibold">{CONTEXT.REGIME_SHIFT}</span>
      <span className="text-zinc-400">
        {CONTEXT.REGIME_SHIFT_NOW} {regime.regime ?? "—"} · {CONTEXT.REGIME_SHIFT_CONF}{" "}
        {/* v8 ignore start -- banner renders only when isRegimeShifting (conf 0~60) → confidence always defined, `?? 0` arm unreachable */}
        {regime.confidence ?? 0}
        {/* v8 ignore stop */}{CONTEXT.REGIME_SHIFT_ADVICE}
      </span>
    </div>
  );
}

/* ── 시스템 상태 레일 (세로 컴팩트 행 — #1619 에서 Certification 행 제거, #1652 에서 시장 사실 흡수) ── */
function RailRow({ label, value, sub, href, color, valueNode, title }: {
  label: string; value?: string; sub: string; href: string; color?: string; valueNode?: React.ReactNode; title?: string;
}) {
  return (
    <Link href={href} className="flex items-center gap-2.5 px-3 py-2 hover:bg-zinc-800/40 transition-colors">
      <span className="w-16 shrink-0 text-[11px] text-zinc-400">{label}</span>
      {valueNode ?? <span className={`font-mono text-sm font-semibold tabular-nums ${color ?? ""}`}>{value}</span>}
      <span className="ml-auto text-[11px] text-zinc-500 truncate max-w-[50%]" title={title ?? sub}>{sub}</span>
    </Link>
  );
}

/** 옛 FreshnessBar 와 같은 규칙 — 1h 미만·시간·일·N/A. */
export function formatAge(hours: number): string {
  if (hours >= 9000) return "N/A";

  if (hours < 1) return "<1h";

  if (hours < 24) return `${Math.round(hours)}h`;

  return `${Math.floor(hours / 24)}d`;
}

/**
 * 대시보드 macro 블록 → 레일 행. 백엔드가 4단계로 분류했을 때만 한국어 단계 라벨(양호/보통/부진/취약)을
 * 붙인다. "Insufficient" 같은 한정 라벨은 그대로 보이게 두고 색을 죽인다 — 얇은 표본의 58 이 "보통" 으로
 * 읽히면 안 된다. coverage 0(산출 실패, 점수 50 placeholder) 이면 점수 대신 "—" (Codex #1652 P1 r1+r2).
 */
export function macroRowFromDashboard(m: MacroReading): { value: string; sub: string; color: string } {
  if ((m.coverage ?? 1) <= 0) return { value: "—", sub: m.interpretation || "—", color: "text-zinc-500" };
  const level = MACRO_LEVELS[m.interpretation];

  if (!level) return { value: `${m.score}`, sub: m.interpretation || "—", color: "text-zinc-500" };

  return { value: `${m.score}`, sub: level.label, color: level.color };
}

/** 권장 배분이 의미 있을 때만 (0/100 기본값이나 실제와 같은 값은 "권장" 이 아니다 — MarketStrip 규칙 승계). */
export function meaningfulTarget(actual: Allocation | null, target: Allocation | null): Allocation | null {
  if (actual == null || target == null) return null;

  if (!(target.long > 0 || target.short > 0)) return null;

  if (target.long === actual.long && target.cash === actual.cash) return null;

  return target;
}

export function SystemHealthRail({ health, market, freshnessItems = [] }: {
  health: Partial<SystemHealth>;
  market?: MarketFacts;
  /** WARN/FAIL 만 레일에 나열한다 — PASS 칩 벽은 정보가 아니라 장식이었다 (#1652). */
  freshnessItems?: FreshnessItem[];
}) {
  const regime: Partial<SystemHealth["regime"]> = health.regime || {};
  const macro: Partial<SystemHealth["macro"]> = health.macro || {};
  const freshness: Partial<SystemHealth["freshness"]> = health.freshness || {};
  const vixInfo = vixZone(market?.vix ?? null);

  // 대시보드 macro 블록(coverage 포함)이 있으면 그것, 없으면(MarketContext 경로) health 그대로 — 같은 산식이다.
  const macroRow = market?.macro
    ? macroRowFromDashboard(market.macro)
    : { value: `${macro.score ?? 0}`, sub: macro.interpretation ?? "—", color: healthColor(macro.score ?? 0, [40, 60]) };

  // #1284: null 은 "현금 100%" 가 아니라 **미상**이다. 센티널로 접으면 환율이 없을 때
  // 화면이 "전액 현금" 이라고 주장하게 된다 — 없는 것과 모르는 것은 다르다.
  const allocationUnknown = market?.actualAllocation === null;
  const actual = market?.actualAllocation ?? { long: 0, short: 0, cash: 100 };
  const target = meaningfulTarget(allocationUnknown ? null : actual, market?.targetAllocation ?? market?.fallbackAllocation ?? null);
  const attention = freshnessItems.filter((i) => i.status !== "PASS");

  return (
    <div className="rounded-lg bg-zinc-900/60 border border-zinc-800/50 divide-y divide-zinc-800/50" data-testid="system-rail">
      <p className="px-3 py-2 text-[11px] font-semibold text-zinc-300">{CONTEXT.RAIL_TITLE}</p>
      <RailRow
        label={CONTEXT.REGIME}
        value={regime.regime?.toUpperCase()?.slice(0, 6) ?? "—"}
        sub={market ? `${trendKo(market.trend)} · ${regime.trend ?? "—"} ${regime.confidence ?? 0}%` : `${regime.trend ?? "—"} ${regime.confidence ?? 0}%`}
        href="/strategy"
        color={regime.trend === "bull" ? "text-emerald-400" : regime.trend === "bear" ? "text-red-400" : "text-amber-400"}
      />
      {market && market.vix != null && (
        <RailRow
          label="VIX"
          value={`${Math.round(market.vix * 10) / 10}`}
          sub={vixInfo.label}
          href="/strategy"
          color={vixInfo.color}
        />
      )}
      {market && market.fg != null && (
        <RailRow
          label={MARKET.SENTIMENT}
          valueNode={
            <span className={`inline-flex items-center justify-center h-5 min-w-5 px-1.5 rounded-full font-mono text-xs font-bold tabular-nums ${fgColor(market.fg)}`}>
              {market.fg}
            </span>
          }
          sub={fgLabel(market.fg)}
          href="/strategy"
        />
      )}
      <RailRow
        label={CONTEXT.MACRO}
        value={macroRow.value}
        sub={macroRow.sub}
        title={(market?.macro ?? macro).interpretation || undefined}
        href="/strategy"
        color={macroRow.color}
      />
      {market && (
        <RailRow
          label={MARKET.ALLOCATION}
          valueNode={
            allocationUnknown ? (
              <span className="font-mono text-sm font-semibold text-amber-400" data-testid="allocation-unknown">—</span>
            ) : (
              <span className="font-mono text-sm font-semibold tabular-nums">
                <span className="text-emerald-400">{actual.long}%</span>
                <span className="text-zinc-600"> / </span>
                <span className="text-zinc-300">{actual.cash}%</span>
              </span>
            )
          }
          sub={
            allocationUnknown
              ? MARKET.ACTUAL
              : target
                ? `${MARKET.ACTUAL} ${MARKET.INVEST}/${MARKET.CASH} → ${MARKET.TARGET} ${target.long}% / ${target.cash}%`
                : `${MARKET.ACTUAL} ${MARKET.INVEST}/${MARKET.CASH}`
          }
          href="/rebalance"
        />
      )}
      <RailRow
        label={CONTEXT.FRESHNESS}
        value={freshness.status ?? "—"}
        sub={freshness.fail_count ? `${freshness.fail_count}${CONTEXT.FAIL_SUFFIX} · ${CONTEXT.CHECK_PIPELINE}` : "OK"}
        href="/pipeline"
        color={freshness.status === "PASS" ? "text-emerald-400" : freshness.status === "WARN" ? "text-amber-400" : "text-red-400"}
      />
      {attention.length > 0 && (
        // 칩 벽이 아니라 레일 행과 같은 결의 조용한 목록 — 색은 글리프·라벨에만 (90/10 색 예산)
        <ul className="px-3 py-1.5 space-y-0.5" data-testid="rail-freshness">
          {attention.map((item) => {
            const fail = item.status === "FAIL";

            return (
              <li key={item.key} className="flex items-center gap-2 text-[11px]" title={item.message}>
                <span className={`w-3 text-center ${fail ? "text-red-400" : "text-amber-400"}`} aria-hidden>{fail ? "\u2715" : "\u25B3"}</span>
                <span className={`truncate ${fail ? "text-red-300/90" : "text-amber-300/90"}`}>{item.label}</span>
                <span className="ml-auto font-mono tabular-nums text-zinc-500">{formatAge(item.age_hours)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/* ── 매크로 이벤트 카드 (Phase A stripe/bold/sparkline · Phase B pinned) ── */
export function MacroEventsCard({ events, regimeTrend }: { events: MacroEvent[]; regimeTrend: string | undefined }) {
  if (events.length === 0) return null;
  const pinned = shouldPinCard(events);

  return (
    <div className={`rounded-lg bg-zinc-900/40 border ${pinned ? "border-amber-500/70 ring-1 ring-amber-500/30 shadow-amber-500/10 shadow-md" : "border-zinc-800/60"} border-l-4 ${regimeStripe(regimeTrend)} p-2.5`}>
      <div className="flex items-center justify-between mb-1.5">
        <h4 className="text-[10px] text-zinc-500 font-semibold flex items-center gap-1">
          {pinned && <Pin className="size-3 text-amber-400" aria-label="pinned attention" />}
          {CONTEXT.TITLE}
          {pinned && <span className="text-[9px] text-amber-300/80 font-bold">{CONTEXT.ATTENTION}</span>}
        </h4>
        {(() => {
          const sl = sparklinePath(events, 60, 14);

          if (!sl) return null;
          const trendColor = sl.latest > 0.1 ? "stroke-emerald-400" : sl.latest < -0.1 ? "stroke-red-400" : "stroke-zinc-500";

          return (
            <svg width="60" height="14" className={trendColor} aria-label="7d sentiment trend">
              <path d={sl.path} fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          );
        })()}
      </div>
      <div className="space-y-1">
        {events.map((ev, i) => {
          const style = categoryStyles[ev.category] || { emoji: "📌", color: "text-zinc-400" };
          const date = ev.published_at?.slice(5, 10) ?? "";
          const isHighConf = (ev.confidence ?? 0) >= 0.8;
          const headlineCls = isHighConf ? "text-zinc-300 font-medium" : "text-zinc-500";

          return (
            <div key={i} className="flex items-start gap-1.5 text-[11px]">
              <span className="shrink-0">{style.emoji}</span>
              <span className={`shrink-0 ${style.color} ${isHighConf ? "font-bold" : "font-medium"}`}>{date}</span>
              <span className={`shrink-0 ${style.color} ${isHighConf ? "font-bold" : "font-semibold"}`}>{ev.category_ko ?? ev.category}</span>
              <span className={`${headlineCls} truncate flex-1`} title={ev.headline}>
                {ev.headline.length > 60 ? ev.headline.slice(0, 57) + "..." : ev.headline}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
