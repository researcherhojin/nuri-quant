
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

export const categoryStyles: Record<string, { emoji: string; color: string }> = {
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

export function healthColor(value: number, thresholds: [number, number]): string {
  if (value >= thresholds[1]) return "text-emerald-400";
  if (value >= thresholds[0]) return "text-amber-400";
  return "text-red-400";
}

// #503 Phase A — regime stripe color (events card 좌측 border)
export function regimeStripe(trend: string | undefined): string {
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

export function shouldPinCard(events: MacroEvent[]): boolean {
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
export function isRegimeShifting(regime: Partial<SystemHealth["regime"]>): boolean {
  const conf = regime.confidence ?? 100;
  return conf < 60 && conf > 0;
}

// #503 Phase A — 7d aggregate-by-day sparkline path (SVG points)
// export: 빈 events 방어 가드는 컴포넌트 경로(events.length>0)에서 도달 불가 → 직접 단위 테스트용 export (behavior 불변)
export function sparklinePath(events: MacroEvent[], width: number, height: number): { path: string; latest: number } | null {
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
  /* v8 ignore next */
  const range = max - min || 1; // min≤-1, max≥1 → range≥2, never falsy: `|| 1` unreachable
  const points = means.map((m, i) => {
    const x = (i / (means.length - 1)) * width;
    const y = height - ((m - min) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return { path: `M ${points.join(" L ")}`, latest: means[means.length - 1] };
}

// HealthCard/MarketContext 컴포넌트는 U2b-2 (#1208) 에서
// components/dashboard/system-rail.tsx 의 SystemHealthRail · MacroEventsCard ·
// RegimeShiftBanner 로 분해·이관됨. 이 모듈은 타입·판정 유틸·스타일 맵의 정본으로 남는다.
