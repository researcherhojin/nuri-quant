"use client";

/**
 * ClientTable — Server Component에서 안전하게 사용할 수 있는 DataTable 래퍼.
 *
 * Next.js 16에서 Server Component → Client Component로 함수(render)를 넘길 수 없으므로,
 * 이 컴포넌트가 render 로직을 내장하고 Server Component에서는 데이터만 넘긴다.
 *
 * 사용법:
 *   <ClientTable variant="scorecard" data={data} />
 */
import { ReactNode } from "react";
import { DataTable } from "./data-table";
import { StatusBadge } from "./status-badge";

interface Props {
  variant: string;
  data: any[];
  compact?: boolean;
  title?: string;
}

// 공통 렌더러
const ticker = (v: string) => <span className="font-medium">{v}</span>;
const pct = (v: number) => (
  <span className={v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-muted-foreground"}>
    {v > 0 ? "+" : ""}{typeof v === "number" ? v.toFixed(1) : v}%
  </span>
);
const num = (v: number) => typeof v === "number" ? v.toFixed(1) : String(v);
const badge = (v: string) => <StatusBadge status={v} size="sm" />;
const badgeMd = (v: string) => <StatusBadge status={v} size="md" />;
const dim = (v: any) => <span className="text-muted-foreground text-xs">{String(v ?? "—")}</span>;
const money = (v: number) => <span className="text-emerald-400">${v?.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>;
const price = (v: number) => {
  if (!v) return <span className="text-muted-foreground/70">—</span>;
  const isKr = v > 10000;
  return <span>{isKr ? `₩${v.toLocaleString()}` : `$${v.toFixed(2)}`}</span>;
};

// === 변형별 컬럼 정의 ===
const VARIANTS: Record<string, any[]> = {
  scorecard: [
    { key: "signal_id", label: "Signal", render: (v: string) => <StatusBadge status={v} size="sm" /> },
    { key: "total_trades", label: "Trades", align: "right" },
    { key: "win_rate", label: "Win Rate", align: "right", render: (v: number) => pct(v * 100) },
    { key: "profit_factor", label: "PF", align: "right", render: num },
    { key: "avg_return", label: "Avg Return", align: "right", render: pct },
  ],
  scan: [
    { key: "ticker", label: "Ticker", render: ticker },
    { key: "price", label: "Price", align: "right", render: (v: number) => `$${v?.toFixed(2)}` },
    { key: "change_1d", label: "1D", align: "right", render: pct },
    { key: "change_5d", label: "5D", align: "right", render: pct },
    { key: "rsi", label: "RSI", align: "right", render: num },
    { key: "signal", label: "Signal", render: badge },
    { key: "score", label: "Score", align: "right" },
  ],
  gate: [
    { key: "description", label: "Condition" },
    { key: "phase", label: "Phase", align: "center", render: badge },
    { key: "passed", label: "Status", align: "center", render: (v: boolean) => v ? "✅" : "❌" },
    { key: "detail", label: "Detail", render: dim },
  ],
  conflicts: [
    { key: "ticker", label: "Ticker", render: ticker },
    { key: "conflict_type", label: "Type", render: badge },
    { key: "severity", label: "Severity", align: "center", render: badgeMd },
    { key: "buy_signals", label: "BUY Signals", render: (v: string[]) => dim(v?.join(", ")) },
    { key: "sell_signals", label: "SELL Signals", render: (v: string[]) => dim(v?.join(", ")) },
  ],
  drift: [
    { key: "signal_id", label: "Signal", render: badge },
    { key: "status", label: "Status", align: "center", render: badgeMd },
    { key: "all_time_wr", label: "All-time WR", align: "right", render: pct },
    { key: "recent_wr", label: "Recent WR", align: "right", render: pct },
    { key: "drift_pct", label: "Drift", align: "right", render: pct },
  ],
  rebalance: [
    { key: "ticker", label: "Ticker", render: ticker },
    { key: "sector", label: "Sector", render: dim },
    { key: "action", label: "Action", align: "center", render: badgeMd },
    { key: "current_weight", label: "Current %", align: "right", render: (v: number) => `${v?.toFixed(1)}%` },
    { key: "target_weight", label: "Target %", align: "right", render: (v: number) => `${v?.toFixed(1)}%` },
    { key: "signals", label: "Signals", render: (v: string[]) => dim(v?.join(", ")) },
  ],
  targets: [
    { key: "ticker", label: "Ticker", render: ticker },
    { key: "stock_type", label: "Type", align: "center", render: (v: string) => badge(v === "growth" ? "momentum" : "HOLD") },
    { key: "current_price", label: "현재가", align: "right", render: price },
    { key: "stop_loss", label: "손절가", align: "right", render: (v: number) => <span className="text-red-400">{price(v)}</span> },
    { key: "target_1", label: "1차 익절", align: "right", render: (v: number) => <span className="text-emerald-400">{price(v)}</span> },
    { key: "target_2", label: "2차 익절", align: "right", render: (v: number) => <span className="text-emerald-400">{price(v)}</span> },
    { key: "analyst_target", label: "목표가", align: "right", render: (v: number) => v ? <span className="text-blue-400">{price(v)}</span> : dim("—") },
    { key: "take_profit_triggered", label: "시그널", align: "center", render: (_v: string | null, row: any) => {
      if (row.trailing_stop_triggered) return <span className="text-red-400 text-[10px] font-medium">TRAIL STOP</span>;
      if (_v === "target_2") return <span className="text-amber-400 text-[10px] font-medium">TP2 ({row.take_profit_sell_pct}%)</span>;
      if (_v === "target_1") return <span className="text-emerald-400 text-[10px] font-medium">TP1 ({row.take_profit_sell_pct}%)</span>;
      return dim("—");
    }},
  ],
  swing: [
    { key: "ticker", label: "Ticker", render: ticker },
    { key: "price", label: "Price", align: "right", render: (v: number) => `$${v?.toLocaleString()}` },
    { key: "scan_signal", label: "Signal", align: "center", render: badge },
    { key: "scan_score", label: "Score", align: "right" },
    { key: "agent_action", label: "Agent", align: "center", render: badgeMd },
    { key: "agent_confidence", label: "Conf", align: "right" },
  ],
  advisor: [
    { key: "priority", label: "#", align: "center", render: dim },
    { key: "ticker", label: "Ticker", render: ticker },
    { key: "severity", label: "심각도", align: "center", render: (v: string) => badge(v === "critical" ? "SELL" : v === "high" ? "REDUCE" : "WATCH") },
    { key: "action", label: "조치", align: "center", render: (v: string) => <span className={v === "SELL_ALL" ? "text-red-400 font-medium" : "text-amber-400"}>{v === "SELL_ALL" ? "전량 매도" : "일부 매도"}</span> },
    { key: "sell_shares", label: "수량", align: "right", render: (v: number) => `${v}주` },
    { key: "sell_value_usd", label: "회수", align: "right", render: money },
    { key: "reason", label: "사유", render: dim },
  ],
};

export function ClientTable({ variant, data, compact, title }: Props) {
  const columns = VARIANTS[variant];
  if (!columns) return <p className="text-red-400 text-sm">Unknown variant: {variant}</p>;
  return (
    <>
      {title && <p className="text-xs text-muted-foreground mb-3">{title}</p>}
      <DataTable columns={columns} data={data} compact={compact} />
    </>
  );
}
