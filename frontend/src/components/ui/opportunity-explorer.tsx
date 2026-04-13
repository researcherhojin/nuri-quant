"use client";

import Link from "next/link";
import { OPPORTUNITY } from "@/lib/strings";

interface Opportunity {
  ticker: string;
  price: number | null;
  change_1d: number | null;
  change_5d: number | null;
  volume_ratio: number | null;
  rsi: number | null;
  signal: string | null;
  score: number | null;
  pros: string[];
  cons: string[];
  verdict: string;
  verdict_level: string;
}

interface OpportunityExplorerProps {
  opportunities: Opportunity[];
}

const verdictStyles: Record<string, { bg: string; text: string; label: string }> = {
  positive: { bg: "bg-emerald-500/20", text: "text-emerald-400", label: OPPORTUNITY.POSITIVE },
  neutral: { bg: "bg-amber-500/20", text: "text-amber-400", label: OPPORTUNITY.NEUTRAL },
  danger: { bg: "bg-red-500/20", text: "text-red-400", label: OPPORTUNITY.DANGER },
  muted: { bg: "bg-zinc-700/50", text: "text-zinc-500", label: OPPORTUNITY.MUTED },
};

function OpportunityCard({ opp }: { opp: Opportunity }) {
  const style = verdictStyles[opp.verdict_level] || verdictStyles.muted;
  const change5dColor = (opp.change_5d ?? 0) >= 0 ? "text-emerald-400" : "text-red-400";

  return (
    <div className="rounded-lg p-3 bg-zinc-900/40 border border-zinc-800/60">
      {/* 헤더 */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <Link href={`/ticker/${opp.ticker}`} className="text-sm font-semibold text-zinc-100 hover:text-white transition-colors">
            {opp.ticker}
          </Link>
          <span className="text-xs text-zinc-400 tabular-nums">
            ${opp.price?.toFixed(2) ?? "—"}
          </span>
          {opp.signal && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400">
              {opp.signal}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-[10px] tabular-nums">
          <span className={change5dColor}>5D {(opp.change_5d ?? 0) >= 0 ? "+" : ""}{opp.change_5d?.toFixed(1) ?? 0}%</span>
          {opp.volume_ratio != null && opp.volume_ratio >= 1.5 && (
            <span className="text-amber-400">Vol {opp.volume_ratio.toFixed(1)}x</span>
          )}
          {opp.rsi != null && (
            <span className={opp.rsi < 30 ? "text-emerald-400" : opp.rsi > 70 ? "text-red-400" : "text-zinc-500"}>
              RSI {Math.round(opp.rsi)}
            </span>
          )}
        </div>
      </div>

      {/* 찬성 / 반대 */}
      <div className="grid grid-cols-2 gap-2 text-[10px] mb-2">
        <div>
          {opp.pros.length > 0 && (
            <>
              <span className="text-emerald-500 font-semibold">{OPPORTUNITY.PROS}</span>
              {opp.pros.map((p, i) => (
                <p key={i} className="text-zinc-400 leading-tight mt-0.5">{p}</p>
              ))}
            </>
          )}
        </div>
        <div>
          {opp.cons.length > 0 && (
            <>
              <span className="text-red-500 font-semibold">{OPPORTUNITY.CONS}</span>
              {opp.cons.map((c, i) => (
                <p key={i} className="text-zinc-400 leading-tight mt-0.5">{c}</p>
              ))}
            </>
          )}
        </div>
      </div>

      {/* 판정 + 링크 */}
      <div className="flex items-center justify-between pt-2 border-t border-zinc-800/40">
        <div className="flex items-center gap-1.5">
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${style.bg} ${style.text}`}>
            {style.label}
          </span>
          <span className="text-[10px] text-zinc-500 truncate max-w-[200px]">{opp.verdict}</span>
        </div>
        <Link
          href={`/ticker/${opp.ticker}`}
          className="text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          {OPPORTUNITY.CHART} →
        </Link>
      </div>
    </div>
  );
}

export function OpportunityExplorer({ opportunities }: OpportunityExplorerProps) {
  if (opportunities.length === 0) {
    return (
      <div className="rounded-lg bg-zinc-900/40 border border-zinc-800/60 p-4 text-center text-sm text-zinc-500">
        {OPPORTUNITY.EMPTY}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {opportunities.map((opp) => (
        <OpportunityCard key={opp.ticker} opp={opp} />
      ))}
    </div>
  );
}
