/**
 * /api/evidence/data/{chart_id} payload 타입 + 차트 공용 색상 (#1225 U5a-2).
 *
 * "use client" 아님 — 서버 페이지(page.tsx)가 타입을, 클라이언트 차트가
 * 타입+색상을 함께 import 한다 (RSC boundary 규칙: frontend/CLAUDE.md).
 * 색상 램프는 기존 Plotly 생성기(evidence_charts.py)와 동일 계열 유지.
 */

export interface SpyPoint {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  sma50: number | null;
  sma200: number | null;
}

export interface DatedValue {
  date: string;
  value: number;
}

export interface RegimeInfo {
  regime: string;
  trend: string;
  volatility: string;
  confidence: number;
}

export interface RegimeData {
  spy: SpyPoint[];
  vix: DatedValue[];
  regime: RegimeInfo | null;
  count: number;
}

export interface HeatmapItem {
  ticker: string;
  current_value_usd: number;
  pnl_pct: number;
  weight_pct: number;
  sector: string | null;
  violation: "stop_loss" | "overweight" | null;
}

export interface HeatmapData {
  items: HeatmapItem[];
  count: number;
}

export interface SignalRow {
  signal_id: string;
  win_rate: number;
  profit_factor: number | null;
  total_trades: number | null;
  drift_status: string;
}

export interface SignalPerformanceData {
  signals: SignalRow[];
  count: number;
}

export interface FearGreedData {
  history: DatedValue[];
  count: number;
}

export interface SellViolation {
  ticker: string;
  type: "stop_loss" | "overweight";
  severity: number;
  action: string;
  recovery: string;
}

export interface SellEvidenceData {
  violations: SellViolation[];
  count: number;
}

/* ── 색상 (Plotly 생성기와 동일 계열 — 초록=이익, 빨강=손실/손절, 노랑=비중) ── */

export const VIOLATION_COLORS: Record<"stop_loss" | "overweight", string> = {
  stop_loss: "#ef5350",
  overweight: "#ffd54f",
};

export const DRIFT_COLORS: Record<string, string> = {
  critical: "#ef5350",
  degrading: "#ff9800",
};

/** 손익% → 히트맵 셀 색 (Plotly colorscale 의 5-구간 근사) */
export function pnlColor(pnl: number): string {
  if (pnl <= -10) return "#d32f2f";
  if (pnl < -2) return "#ef5350";
  if (pnl <= 2) return "#616161";
  if (pnl <= 10) return "#66bb6a";
  return "#2e7d32";
}
