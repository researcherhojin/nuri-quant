import Link from "next/link";
import { CONTEXT } from "@/lib/strings";

export interface MacroEvent {
  category: string;
  category_ko?: string;
  headline: string;
  sentiment: number;
  confidence: number;
  published_at: string;
  source: string;
}

export interface SystemHealth {
  siege: { score: number; certified: boolean; passed?: number; failed?: number; warnings?: number; total?: number };
  regime: { regime: string; trend: string; confidence: number };
  macro: { score: number; interpretation: string };
  freshness: { status: string; fail_count?: number; warn_count?: number };
}

interface MarketContextProps {
  events: MacroEvent[];
  health: Partial<SystemHealth>;
}

const categoryStyles: Record<string, { emoji: string; color: string }> = {
  geopolitical_escalation: { emoji: "🔴", color: "text-red-400" },
  geopolitical_de_escalation: { emoji: "🟢", color: "text-emerald-400" },
  oil_supply_shock: { emoji: "🛢", color: "text-amber-400" },
  trade_war: { emoji: "⚔", color: "text-orange-400" },
  fed_dovish: { emoji: "🕊", color: "text-emerald-400" },
  fed_hawkish: { emoji: "🦅", color: "text-red-400" },
  earnings_beat: { emoji: "📈", color: "text-emerald-400" },
  earnings_miss: { emoji: "📉", color: "text-red-400" },
  sector_rally: { emoji: "🚀", color: "text-blue-400" },
};

function healthColor(value: number, thresholds: [number, number]): string {
  if (value >= thresholds[1]) return "text-emerald-400";
  if (value >= thresholds[0]) return "text-amber-400";
  return "text-red-400";
}

// #503 Phase A — regime stripe color (events card 좌측 border)
function regimeStripe(trend: string | undefined): string {
  if (trend === "bull") return "border-l-emerald-500/60";
  if (trend === "bear") return "border-l-red-500/60";
  if (trend === "sideways") return "border-l-amber-500/60";
  return "border-l-zinc-700/60";
}

// #503 Phase B — pinning: 24h 내 high-conf (≥0.8) critical-category 이벤트 존재 시 attention.
// Critical = 의사결정에 직결되는 macro/geopolitical/policy shift.
const CRITICAL_CATEGORIES = new Set([
  "geopolitical_escalation",
  "geopolitical_de_escalation",
  "fed_dovish",
  "fed_hawkish",
  "oil_supply_shock",
  "trade_war",
]);

function shouldPinCard(events: MacroEvent[]): boolean {
  const now = Date.now();
  const cutoff = now - 24 * 60 * 60 * 1000;
  return events.some(ev => {
    if (!CRITICAL_CATEGORIES.has(ev.category)) return false;
    if ((ev.confidence ?? 0) < 0.8) return false;
    const ts = Date.parse(ev.published_at);
    return Number.isFinite(ts) && ts >= cutoff;
  });
}

// #503 Phase B — regime banner: regime confidence 가 60% 미만이면 전환 임박 신호.
function isRegimeShifting(regime: Partial<SystemHealth["regime"]>): boolean {
  const conf = regime.confidence ?? 100;
  return conf < 60 && conf > 0;
}

// #503 Phase A — 7d aggregate-by-day sparkline path (SVG points)
function sparklinePath(events: MacroEvent[], width: number, height: number): { path: string; latest: number } | null {
  if (events.length === 0) return null;
  const buckets: Record<string, number[]> = {};
  for (const ev of events) {
    const day = ev.published_at?.slice(0, 10);
    if (!day) continue;
    (buckets[day] ||= []).push(ev.sentiment);
  }
  const days = Object.keys(buckets).sort();
  if (days.length < 2) return null;
  const means = days.map(d => buckets[d].reduce((a, b) => a + b, 0) / buckets[d].length);
  const min = Math.min(...means, -1);
  const max = Math.max(...means, 1);
  const range = max - min || 1;
  const points = means.map((m, i) => {
    const x = (i / (means.length - 1)) * width;
    const y = height - ((m - min) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return { path: `M ${points.join(" L ")}`, latest: means[means.length - 1] };
}

function HealthCard({ label, value, sub, href, color }: { label: string; value: string; sub: string; href: string; color: string }) {
  return (
    <Link href={href} className="flex-1 min-w-20 rounded-lg bg-zinc-900/60 border border-zinc-800/50 p-2.5 hover:bg-zinc-800/60 transition-colors">
      <p className="text-[10px] text-zinc-600 mb-0.5">{label}</p>
      <p className={`text-lg font-bold tabular-nums leading-tight ${color}`}>{value}</p>
      <p className="text-[10px] text-zinc-500 mt-0.5 truncate">{sub}</p>
    </Link>
  );
}

export function MarketContext({ events, health }: MarketContextProps) {
  const siege: Partial<SystemHealth["siege"]> = health.siege || {};
  const regime: Partial<SystemHealth["regime"]> = health.regime || {};
  const macro: Partial<SystemHealth["macro"]> = health.macro || {};
  const freshness: Partial<SystemHealth["freshness"]> = health.freshness || {};

  const pinned = shouldPinCard(events);
  const shifting = isRegimeShifting(regime);

  return (
    <div className="space-y-3">
      {/* #503 Phase B — regime-shift banner (regime.confidence < 60%) */}
      {shifting && (
        <div className="rounded-lg bg-amber-950/40 border border-amber-700/50 px-3 py-2 flex items-center gap-2 text-xs">
          <span className="shrink-0">⚠</span>
          <span className="text-amber-300 font-semibold">Regime 전환 신호</span>
          <span className="text-zinc-400">
            현재 {regime.regime ?? "—"} · 신뢰도 {regime.confidence ?? 0}% — 다음 행동 보류 권고
          </span>
        </div>
      )}

      {/* 시스템 건강 4-card */}
      <div className="flex gap-2">
        <HealthCard
          label={CONTEXT.SIEGE}
          value={`${siege.score ?? 0}%`}
          sub={siege.certified ? CONTEXT.CERTIFIED : CONTEXT.REJECTED}
          href="/engine"
          color={siege.certified ? "text-emerald-400" : "text-red-400"}
        />
        <HealthCard
          label={CONTEXT.REGIME}
          value={regime.regime?.toUpperCase()?.slice(0, 6) ?? "—"}
          sub={`${regime.trend ?? "—"} ${regime.confidence ?? 0}%`}
          href="/strategy"
          color={regime.trend === "bull" ? "text-emerald-400" : regime.trend === "bear" ? "text-red-400" : "text-amber-400"}
        />
        <HealthCard
          label={CONTEXT.MACRO}
          value={`${macro.score ?? 0}`}
          sub={macro.interpretation ?? "—"}
          href="/strategy"
          color={healthColor(macro.score ?? 0, [40, 60])}
        />
        <HealthCard
          label={CONTEXT.FRESHNESS}
          value={freshness.status ?? "—"}
          sub={freshness.fail_count ? `${freshness.fail_count} fail` : "OK"}
          href="/pipeline"
          color={freshness.status === "PASS" ? "text-emerald-400" : freshness.status === "WARN" ? "text-amber-400" : "text-red-400"}
        />
      </div>

      {/* 매크로 이벤트 — Phase A: stripe/bold/sparkline · Phase B: pinned attention */}
      {events.length > 0 && (
        <div className={`rounded-lg bg-zinc-900/40 border ${pinned ? "border-amber-500/70 ring-1 ring-amber-500/30 shadow-amber-500/10 shadow-md" : "border-zinc-800/60"} border-l-4 ${regimeStripe(regime.trend)} p-2.5`}>
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
                <div key={i} className="flex items-start gap-1.5 text-[10px]">
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
      )}
    </div>
  );
}
