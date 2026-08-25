/**
 * 대시보드 표시 헬퍼 (#1204 U2a) — page.tsx 에서 추출, 동작 불변.
 * 색 매핑·라벨 변환·URL 파라미터 파싱만 담당한다 (데이터 fetch 없음).
 * 기존 소비자(테스트 포함)는 page.tsx 의 re-export 를 통해 그대로 import 한다.
 */
import { VERDICT, TREND, VIX_ZONE, FEAR_GREED, MACRO_LEVEL, SECTION } from "@/lib/strings";

export const verdictLabels: Record<string, string> = {
  aggressive: VERDICT.AGGRESSIVE, neutral: VERDICT.NEUTRAL, cautious: VERDICT.CAUTIOUS, defensive: VERDICT.DEFENSIVE,
  stale: VERDICT.STALE,
};
export const levelStyles: Record<string, { text: string }> = {
  aggressive: { text: "text-emerald-400" },
  neutral:    { text: "text-zinc-400" },
  cautious:   { text: "text-amber-400" },
  defensive:  { text: "text-red-400" },
  stale:      { text: "text-amber-400" }, // 판단 보류 — 경고색 (#1180)
};
export const pipelineStatusColors: Record<string, string> = {
  idle: "bg-zinc-500", running: "bg-blue-500 animate-pulse", done: "bg-emerald-500", error: "bg-red-500",
};

export function trendKo(t: string) { return t === "bull" ? TREND.BULL : t === "bear" ? TREND.BEAR : TREND.SIDEWAYS; }
export function vixZone(v: number | null): { label: string; color: string } {
  if (v == null) return { label: "—", color: "text-zinc-500" };
  if (v < 12) return { label: VIX_ZONE.CALM, color: "text-blue-400" };
  if (v < 17) return { label: VIX_ZONE.LOW, color: "text-emerald-400" };
  if (v < 23) return { label: VIX_ZONE.NORMAL, color: "text-zinc-300" };
  if (v < 33) return { label: VIX_ZONE.CAUTION, color: "text-orange-400" };
  return { label: VIX_ZONE.DANGER, color: "text-red-400" };
}
export function fgLabel(fg: number | null): string {
  if (fg == null) return "—";
  if (fg < 25) return FEAR_GREED.EXTREME_FEAR; if (fg < 45) return FEAR_GREED.FEAR;
  if (fg <= 55) return FEAR_GREED.NEUTRAL; if (fg <= 75) return FEAR_GREED.GREED;
  return FEAR_GREED.EXTREME_GREED;
}
export function fgColor(fg: number | null): string {
  if (fg == null) return "bg-zinc-700 text-zinc-400";
  if (fg < 25) return "bg-red-500/20 text-red-400";
  if (fg < 45) return "bg-orange-500/20 text-orange-400";
  if (fg <= 55) return "bg-yellow-500/20 text-yellow-400";
  if (fg <= 75) return "bg-lime-500/20 text-lime-400";
  return "bg-emerald-500/20 text-emerald-400";
}
export function macroLevel(s: number): { label: string; color: string } {
  if (s >= 70) return { label: MACRO_LEVEL.GOOD, color: "text-emerald-400" };
  if (s >= 50) return { label: MACRO_LEVEL.NORMAL, color: "text-zinc-300" };
  if (s >= 30) return { label: MACRO_LEVEL.WEAK, color: "text-orange-400" };
  return { label: MACRO_LEVEL.FRAGILE, color: "text-red-400" };
}
/** 계좌 라벨 한국어 표시 (Pension만 특수, 나머지는 원본 유지) */
export function accountKo(label: string | undefined): string {
  if (!label) return "";
  if (label === "Pension") return SECTION.PENSION;
  return label;
}

// #214 polish: sparkline period options shown as URL-driven toggle (?period=14|30|60|90)
export const SPARKLINE_PERIOD_OPTIONS = [14, 30, 60, 90] as const;
export type SparklinePeriod = (typeof SPARKLINE_PERIOD_OPTIONS)[number];

export function parseSparklinePeriod(raw: string | undefined): SparklinePeriod {
  const n = parseInt(raw ?? "30", 10);
  if (SPARKLINE_PERIOD_OPTIONS.includes(n as SparklinePeriod)) return n as SparklinePeriod;
  return 30;
}

// Helper — "MM-DD" format
export const fmtEventDate = (iso: string) => (iso && iso.length >= 10 ? iso.slice(5, 10) : iso ?? "");
// Helper — D-day from YYYY-MM-DD (local time, timezone-safe)
export const eventDday = (iso: string): string => {
  if (!iso || iso.length < 10) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return "";
  const eventMs = new Date(y, m - 1, d).getTime();
  const today = new Date();
  const todayMs = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  const days = Math.round((eventMs - todayMs) / 86_400_000);
  if (days === 0) return "D-DAY";
  return days > 0 ? `D-${days}` : `D+${-days}`;
};
