/**
 * SystemHealthRail + MacroEventsCard + RegimeShiftBanner (#1208 U2b-2).
 *
 * MarketContext(4-card 가로 그리드 + 이벤트 카드)를 분해 — 대시보드가 좌 2/3 액션
 * 테이블 · 우 1/3 시스템 레일로 재구성되면서 (목업·plan §4), 건강 지표는 세로 컴팩트
 * 행으로, 이벤트 카드는 레일 하단으로 이동한다. 데이터 계약·색·링크는 기존 그대로.
 */
import Link from "next/link";
import { CONTEXT } from "@/lib/strings";
import {
  type MacroEvent, type SystemHealth,
  shouldPinCard, sparklinePath, categoryStyles, healthColor, regimeStripe, isRegimeShifting,
} from "@/components/ui/market-context";

/* ── 레짐 전환 배너 (full-width, 조건부) ─────────────────────── */
export function RegimeShiftBanner({ regime }: { regime: Partial<SystemHealth["regime"]> }) {
  if (!isRegimeShifting(regime)) return null;
  return (
    <div className="rounded-lg bg-amber-950/40 border border-amber-700/50 px-3 py-2 flex items-center gap-2 text-xs">
      <span className="shrink-0">⚠</span>
      <span className="text-amber-300 font-semibold">Regime 전환 신호</span>
      <span className="text-zinc-400">
        현재 {regime.regime ?? "—"} · 신뢰도{" "}
        {/* v8 ignore start -- banner renders only when isRegimeShifting (conf 0~60) → confidence always defined, `?? 0` arm unreachable */}
        {regime.confidence ?? 0}
        {/* v8 ignore stop */}% — 다음 행동 보류 권고
      </span>
    </div>
  );
}

/* ── 시스템 상태 레일 (세로 4행 컴팩트) ──────────────────────── */
function RailRow({ label, value, sub, href, color }: { label: string; value: string; sub: string; href: string; color: string }) {
  return (
    <Link href={href} className="flex items-center gap-2.5 px-3 py-2 hover:bg-zinc-800/40 transition-colors">
      <span className="w-24 shrink-0 text-[11px] text-zinc-400">{label}</span>
      <span className={`font-mono text-sm font-semibold tabular-nums ${color}`}>{value}</span>
      <span className="ml-auto text-[11px] text-zinc-500 truncate max-w-[45%]" title={sub}>{sub}</span>
    </Link>
  );
}

export function SystemHealthRail({ health }: { health: Partial<SystemHealth> }) {
  const siege: Partial<SystemHealth["siege"]> = health.siege || {};
  const regime: Partial<SystemHealth["regime"]> = health.regime || {};
  const macro: Partial<SystemHealth["macro"]> = health.macro || {};
  const freshness: Partial<SystemHealth["freshness"]> = health.freshness || {};
  return (
    <div className="rounded-lg bg-zinc-900/60 border border-zinc-800/50 divide-y divide-zinc-800/50" data-testid="system-rail">
      <p className="px-3 py-2 text-[11px] font-semibold text-zinc-300">{CONTEXT.RAIL_TITLE}</p>
      <RailRow
        label={CONTEXT.SIEGE}
        value={`${siege.score ?? 0}%`}
        sub={siege.certified ? CONTEXT.CERTIFIED : CONTEXT.REJECTED}
        href="/engine"
        color={siege.certified ? "text-emerald-400" : "text-red-400"}
      />
      <RailRow
        label={CONTEXT.REGIME}
        value={regime.regime?.toUpperCase()?.slice(0, 6) ?? "—"}
        sub={`${regime.trend ?? "—"} ${regime.confidence ?? 0}%`}
        href="/strategy"
        color={regime.trend === "bull" ? "text-emerald-400" : regime.trend === "bear" ? "text-red-400" : "text-amber-400"}
      />
      <RailRow
        label={CONTEXT.MACRO}
        value={`${macro.score ?? 0}`}
        sub={macro.interpretation ?? "—"}
        href="/strategy"
        color={healthColor(macro.score ?? 0, [40, 60])}
      />
      <RailRow
        label={CONTEXT.FRESHNESS}
        value={freshness.status ?? "—"}
        sub={freshness.fail_count ? `${freshness.fail_count} fail` : "OK"}
        href="/pipeline"
        color={freshness.status === "PASS" ? "text-emerald-400" : freshness.status === "WARN" ? "text-amber-400" : "text-red-400"}
      />
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
          {pinned && <span className="text-amber-400" aria-label="pinned attention">📌</span>}
          {CONTEXT.TITLE}
          {pinned && <span className="text-[9px] text-amber-300/80 font-bold">ATTENTION</span>}
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
