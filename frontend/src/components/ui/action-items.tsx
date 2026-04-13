"use client";

import Link from "next/link";
import { useState } from "react";
import { ACTION } from "@/lib/strings";

interface ActionItem {
  ticker: string;
  name?: string | null;
  action: string;
  confidence: number;
  agreement?: number | null;
  pnl_pct: number;
  position_pct: number;
  current_price?: number | null;
  avg_price?: number | null;
  account?: string;
  stop_loss?: number | null;
  target_1?: number | null;
  target_2?: number | null;
  reasons: string[];
  priority: string;
}

interface ActionItemsProps {
  urgent: ActionItem[];
  check: ActionItem[];
  hold: ActionItem[];
}

const priorityStyles = {
  urgent: { bg: "bg-red-950/30", border: "border-red-900/50", dot: "bg-red-500", text: "text-red-400" },
  check: { bg: "bg-amber-950/20", border: "border-amber-900/40", dot: "bg-amber-500", text: "text-amber-400" },
  hold: { bg: "bg-zinc-900/40", border: "border-zinc-800/60", dot: "bg-zinc-500", text: "text-zinc-400" },
};

function ActionCard({ item }: { item: ActionItem }) {
  const [expanded, setExpanded] = useState(false);
  const style = priorityStyles[item.priority as keyof typeof priorityStyles] || priorityStyles.hold;
  const isKr = item.ticker.endsWith(".KS");
  const fmt = (v: number | null | undefined) => {
    if (v == null) return "—";
    return isKr ? `₩${v.toLocaleString()}` : `$${v.toFixed(2)}`;
  };

  return (
    <div className={`rounded-lg p-3 ${style.bg} border ${style.border}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <Link href={`/ticker/${item.ticker}`} className="text-sm font-semibold text-zinc-100 hover:text-white transition-colors">
              {item.name || item.ticker}
            </Link>
            {item.name && <span className="text-[10px] text-zinc-600">{item.ticker}</span>}
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
              item.action === "SELL" ? "bg-red-500/20 text-red-400" :
              item.action === "BUY" ? "bg-emerald-500/20 text-emerald-400" :
              "bg-zinc-700 text-zinc-400"
            }`}>
              {item.action}
            </span>
            {item.account && <span className="text-[10px] text-zinc-600">{item.account}</span>}
          </div>
          <div className="mt-1 space-y-0.5">
            {item.reasons.map((r, i) => (
              <p key={i} className="text-xs text-zinc-400 leading-tight">{r}</p>
            ))}
          </div>
        </div>
        <div className="text-right shrink-0 space-y-0.5">
          <p className={`text-sm font-semibold tabular-nums ${item.pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {item.pnl_pct >= 0 ? "+" : ""}{item.pnl_pct.toFixed(1)}%
          </p>
          <p className="text-[10px] text-zinc-500 tabular-nums">{ACTION.WEIGHT} {item.position_pct.toFixed(1)}%</p>
          <p className="text-[10px] text-zinc-600 tabular-nums">{ACTION.CONF} {item.confidence}</p>
        </div>
      </div>

      {/* 확장 상세 */}
      {expanded && (
        <div className="mt-2 pt-2 border-t border-zinc-800/50 grid grid-cols-3 gap-2 text-[10px]">
          <div><span className="text-zinc-600">현재가</span> <span className="text-zinc-300 tabular-nums">{fmt(item.current_price)}</span></div>
          <div><span className="text-zinc-600">손절</span> <span className="text-red-400 tabular-nums">{fmt(item.stop_loss)}</span></div>
          <div><span className="text-zinc-600">1차익절</span> <span className="text-emerald-400 tabular-nums">{fmt(item.target_1)}</span></div>
        </div>
      )}

      <div className="mt-2 flex gap-2">
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          {expanded ? "접기" : ACTION.DETAIL} {expanded ? "▲" : "▼"}
        </button>
      </div>
    </div>
  );
}

export function ActionItems({ urgent, check, hold }: ActionItemsProps) {
  const total = urgent.length + check.length + hold.length;

  if (total === 0) {
    return (
      <div className="rounded-lg bg-zinc-900/40 border border-zinc-800/60 p-4 text-center text-sm text-zinc-500">
        {ACTION.EMPTY}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* 🔴 즉시 실행 */}
      {urgent.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-red-400 mb-1.5 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-red-500" />
            {ACTION.URGENT} ({urgent.length})
          </h3>
          <div className="space-y-2">
            {urgent.map((item) => <ActionCard key={`${item.ticker}-${item.account}`} item={item} />)}
          </div>
        </div>
      )}

      {/* 🟡 오늘 확인 */}
      {check.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-amber-400 mb-1.5 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-amber-500" />
            {ACTION.CHECK} ({check.length})
          </h3>
          <div className="space-y-2">
            {check.map((item) => <ActionCard key={`${item.ticker}-${item.account}`} item={item} />)}
          </div>
        </div>
      )}

      {/* ✅ 유지 */}
      {hold.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-zinc-500 mb-1.5 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-zinc-500" />
            {ACTION.HOLD_SUMMARY} ({hold.length})
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {hold.map((item) => (
              <Link
                key={`${item.ticker}-${item.account}`}
                href={`/ticker/${item.ticker}`}
                className="inline-flex items-center gap-1 px-2 py-1 rounded bg-zinc-900/60 border border-zinc-800/40 text-[10px] hover:bg-zinc-800/60 transition-colors"
              >
                <span className="text-zinc-300">{item.name || item.ticker}</span>
                <span className={`tabular-nums font-medium ${item.action === "BUY" ? "text-emerald-500" : "text-zinc-500"}`}>
                  {item.action} {item.confidence}
                </span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
