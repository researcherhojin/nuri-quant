import Link from "next/link";
import { CONTEXT } from "@/lib/strings";

interface MacroEvent {
  category: string;
  category_ko?: string;
  headline: string;
  sentiment: number;
  confidence: number;
  published_at: string;
  source: string;
}

interface SystemHealth {
  siege: { score: number; certified: boolean; passed?: number; failed?: number; warnings?: number; total?: number };
  regime: { regime: string; trend: string; confidence: number };
  macro: { score: number; interpretation: string };
  freshness: { status: string; fail_count?: number; warn_count?: number };
}

interface MarketContextProps {
  events: MacroEvent[];
  health: SystemHealth;
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

function HealthCard({ label, value, sub, href, color }: { label: string; value: string; sub: string; href: string; color: string }) {
  return (
    <Link href={href} className="flex-1 min-w-[80px] rounded-lg bg-zinc-900/60 border border-zinc-800/50 p-2.5 hover:bg-zinc-800/60 transition-colors">
      <p className="text-[10px] text-zinc-600 mb-0.5">{label}</p>
      <p className={`text-lg font-bold tabular-nums leading-tight ${color}`}>{value}</p>
      <p className="text-[10px] text-zinc-500 mt-0.5 truncate">{sub}</p>
    </Link>
  );
}

export function MarketContext({ events, health }: MarketContextProps) {
  const siege = health.siege || {};
  const regime = health.regime || {};
  const macro = health.macro || {};
  const freshness = health.freshness || {};

  return (
    <div className="space-y-3">
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

      {/* 매크로 이벤트 */}
      {events.length > 0 && (
        <div className="rounded-lg bg-zinc-900/40 border border-zinc-800/60 p-2.5">
          <h4 className="text-[10px] text-zinc-500 font-semibold mb-1.5">{CONTEXT.TITLE}</h4>
          <div className="space-y-1">
            {events.map((ev, i) => {
              const style = categoryStyles[ev.category] || { emoji: "📌", color: "text-zinc-400" };
              const date = ev.published_at?.slice(5, 10) ?? "";
              return (
                <div key={i} className="flex items-start gap-1.5 text-[10px]">
                  <span className="shrink-0">{style.emoji}</span>
                  <span className={`shrink-0 ${style.color} font-medium`}>{date}</span>
                  <span className={`shrink-0 ${style.color} font-semibold`}>{ev.category_ko ?? ev.category}</span>
                  <span className="text-zinc-500 truncate flex-1" title={ev.headline}>
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
