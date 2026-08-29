"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * ClientTable — Server Component에서 안전하게 사용할 수 있는 DataTable 래퍼.
 *
 * Next.js 16에서 Server Component → Client Component로 함수(render)를 넘길 수 없으므로,
 * 이 컴포넌트가 render 로직을 내장하고 Server Component에서는 데이터만 넘긴다.
 *
 * 사용법:
 *   <ClientTable variant="scorecard" data={data} />
 */
import { DataTable } from "./data-table";
import { StatusBadge } from "./status-badge";
import { formatMoney } from "@/lib/format";

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
// 통화는 티커로 판정 (#1197) — 이전의 `v > 10000` 휴리스틱은 ₩8,145 종목을 $ 로,
// $10,000 초과 미국 종목을 ₩ 로 표기했다. row 가 없는 호출은 USD 로 남는다.
const price = (v: number, row?: { ticker?: string }) => {
  if (!v) return <span className="text-muted-foreground/70">—</span>;
  return <span>{formatMoney(v, { ticker: row?.ticker })}</span>;
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
  // #1219: scan/swing 두 변형이 같은 스캔의 중복 뷰였다 — union 병합 단일 변형.
  // 병합 특성상 어느 쪽에도 없는 필드가 있어 렌더러는 전부 null 허용 (—).
  scanner: [
    { key: "ticker", label: "Ticker", render: ticker },
    { key: "price", label: "Price", align: "right", render: price },
    { key: "change_1d", label: "1D", align: "right", render: (v: number | null) => (v == null ? dim("—") : pct(v)) },
    { key: "change_5d", label: "5D", align: "right", render: (v: number | null) => (v == null ? dim("—") : pct(v)) },
    { key: "rsi", label: "RSI", align: "right", render: (v: number | null) => (v == null ? dim("—") : num(v)) },
    { key: "signal", label: "Signal", render: (v: string | null) => (v ? badge(v) : dim("—")) },
    { key: "score", label: "Score", align: "right", render: (v: number | null) => (v == null ? dim("—") : String(v)) },
    { key: "agent_action", label: "Agent", align: "center", render: (v: string | null) => (v ? badgeMd(v) : dim("—")) },
    { key: "agent_confidence", label: "Conf", align: "right", render: (v: number | null) => (v == null ? dim("—") : String(v)) },
    { key: "approved", label: "승인", align: "center", render: (v: boolean | null, row: { reason?: string | null }) =>
      v === null ? dim("—") : v
        ? <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-sm bg-emerald-500/15 text-emerald-400">승인</span>
        : <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-sm bg-zinc-700/40 text-zinc-400" title={row.reason ?? undefined}>미승인</span> },
  ],
  gate: [
    { key: "description", label: "Condition" },
    { key: "phase", label: "Phase", align: "center", render: badge },
    { key: "passed", label: "Status", align: "center", render: (v: boolean) => v
      ? <span className="text-emerald-400">✓</span>
      : <span className="text-red-400">✕</span> },
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
    { key: "stop_loss", label: "손절가", align: "right", render: (v: number, row: any) => <span className="text-red-400">{price(v, row)}</span> },
    { key: "target_1", label: "1차 익절", align: "right", render: (v: number, row: any) => <span className="text-emerald-400">{price(v, row)}</span> },
    { key: "target_2", label: "2차 익절", align: "right", render: (v: number, row: any) => <span className="text-emerald-400">{price(v, row)}</span> },
    { key: "analyst_target", label: "목표가", align: "right", render: (v: number, row: any) => v ? <span className="text-blue-400">{price(v, row)}</span> : dim("—") },
    { key: "take_profit_triggered", label: "시그널", align: "center", render: (_v: string | null, row: any) => {
      if (row.trailing_stop_triggered) return <span className="text-red-400 text-[10px] font-medium">TRAIL STOP</span>;
      if (_v === "target_2") return <span className="text-amber-400 text-[10px] font-medium">TP2 ({row.take_profit_sell_pct}%)</span>;
      if (_v === "target_1") return <span className="text-emerald-400 text-[10px] font-medium">TP1 ({row.take_profit_sell_pct}%)</span>;
      return dim("—");
    }},
  ],
  advisor: [
    { key: "priority", label: "#", align: "center", render: (v: number) => {
      const color = v === 1 ? "bg-red-500/20 text-red-400 border-red-500/30"
                   : v === 2 ? "bg-amber-500/20 text-amber-400 border-amber-500/30"
                   : "bg-zinc-500/20 text-muted-foreground border-zinc-500/30";
      // design-review F-004: 무설명 숫자 칩 — 의미를 tooltip 으로
      return <span title={`매도 우선순위 ${v} (낮을수록 먼저)`} className={`inline-flex items-center justify-center size-5 rounded-full border text-[10px] font-medium ${color}`}>{v}</span>;
    }},
    { key: "ticker", label: "Ticker", render: ticker },
    // design-review F-004: "심각도" 헤더 아래 액션 배지(SELL/REDUCE)를 그리던 헤더-값
    // 불일치 수정 — 심각도는 심각도 값으로 그린다 (조치는 옆의 조치 컬럼 소관)
    { key: "severity", label: "심각도", align: "center", render: (v: string) => {
      const cls = v === "critical" ? "bg-red-500/20 text-red-400 border-red-500/30"
                : v === "high" ? "bg-amber-500/20 text-amber-400 border-amber-500/30"
                : "bg-zinc-500/20 text-muted-foreground border-zinc-500/30";
      return <span className={`inline-block px-1.5 py-0.5 rounded-sm border text-[10px] font-bold uppercase ${cls}`}>{v}</span>;
    }},
    { key: "action", label: "조치", align: "center", render: (v: string) => <span className={v === "SELL_ALL" ? "text-red-400 font-medium" : "text-amber-400"}>{v === "SELL_ALL" ? "전량 매도" : "일부 매도"}</span> },
    { key: "sell_shares", label: "수량", align: "right", render: (v: number) => `${v}주` },
    { key: "sell_value_usd", label: "회수", align: "right", render: money },
    { key: "reason", label: "사유", render: dim },
  ],
};

// === 변형별 행 스타일 ===
const ROW_CLASSNAMES: Record<string, (row: any) => string> = {
  targets: (row) => {
    if (row.trailing_stop_triggered) return "bg-red-500/8";
    if (row.take_profit_triggered === "target_2") return "bg-amber-500/8";
    if (row.take_profit_triggered === "target_1") return "bg-emerald-500/8";
    return "";
  },
};

export function ClientTable({ variant, data, compact, title }: Props) {
  const columns = VARIANTS[variant];
  if (!columns) return <p className="text-red-400 text-sm">Unknown variant: {variant}</p>;
  return (
    <>
      {title && <p className="text-xs text-muted-foreground mb-3">{title}</p>}
      <DataTable columns={columns} data={data} compact={compact} rowClassName={ROW_CLASSNAMES[variant]} />
    </>
  );
}
