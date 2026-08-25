/**
 * Decisions 페이지 순수 헬퍼 (#1216 U3).
 *
 * 판정일 계산은 백엔드 규칙의 미러다: outcome 은 결정일로부터 90일 경과 시
 * pnl_90d 로 판정된다 (nuri/trading/engine/decisions.py — BUY: pnl>0 성공,
 * SELL: pnl<0 성공, 그외 neutral). 규칙이 바뀌면 여기 상수도 함께 바뀌어야 한다.
 */
import { DECISIONS } from "@/lib/strings";

export const ADJUDICATION_DAYS = 90;

/** KST 기준 오늘 (YYYY-MM-DD) — 서버가 UTC 여도 결정일과 같은 달력을 쓴다 */
export function todayKst(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul" }).format(new Date());
}

/** ISO 날짜 + n일 (UTC 고정 산술 — DST/타임존 무관) */
export function addDays(iso: string, days: number): string {
  const t = new Date(`${iso}T00:00:00Z`);
  t.setUTCDate(t.getUTCDate() + days);
  return t.toISOString().slice(0, 10);
}

export interface AdjudicationInfo {
  kind: "adjudicated" | "waiting" | "due";
  /** 판정 기준일 (결정일 + 90d) — 백엔드는 이날부터 판정 가능 (elapsed >= 90) */
  adjudicationDate: string;
  /** waiting 일 때만: 판정까지 남은 일수 (≥1 — D-0 은 존재하지 않는다) */
  daysLeft?: number;
}

export function adjudicationInfo(decisionDate: string, outcome: string, today: string): AdjudicationInfo {
  const adjDate = addDays(decisionDate, ADJUDICATION_DAYS);
  if (outcome !== "pending") return { kind: "adjudicated", adjudicationDate: adjDate };
  const msLeft = Date.parse(`${adjDate}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`);
  const daysLeft = Math.ceil(msLeft / 86_400_000);
  // 경계 미러 (codex R1 P1): 백엔드는 elapsed >= 90, 즉 판정일 **당일부터** 판정 가능.
  // 그날 이후에도 pending 이면 "대기(D-0)"가 아니라 "도래·미판정"이다.
  if (daysLeft <= 0) return { kind: "due", adjudicationDate: adjDate };
  return { kind: "waiting", adjudicationDate: adjDate, daysLeft };
}

/** outcome → intent 태그 (성공→BUY 배지 오매핑(#1216) 대체) */
export const OUTCOME_TAG: Record<string, { label: string; cls: string }> = {
  success: { label: DECISIONS.OUTCOME_SUCCESS, cls: "bg-emerald-500/15 text-emerald-400" },
  failure: { label: DECISIONS.OUTCOME_FAILURE, cls: "bg-red-500/15 text-red-400" },
  neutral: { label: DECISIONS.OUTCOME_NEUTRAL, cls: "bg-zinc-500/15 text-zinc-400" },
  pending: { label: DECISIONS.OUTCOME_PENDING, cls: "bg-zinc-700/40 text-zinc-500" },
};

/** date DESC 정렬을 유지한 채 일자별 그룹으로 묶는다 */
export function groupByDate<T extends { date: string }>(rows: T[]): Array<[string, T[]]> {
  const groups: Array<[string, T[]]> = [];
  for (const row of rows) {
    const last = groups[groups.length - 1];
    if (last && last[0] === row.date) last[1].push(row);
    else groups.push([row.date, [row]]);
  }
  return groups;
}

export const OUTCOME_FILTERS = ["pending", "success", "failure", "neutral"] as const;
export type OutcomeFilter = (typeof OUTCOME_FILTERS)[number];
export const ACTION_FILTERS = ["BUY", "SELL", "HOLD"] as const;
export type ActionFilter = (typeof ACTION_FILTERS)[number];

export function parseOutcomeFilter(raw: string | undefined): OutcomeFilter | undefined {
  return (OUTCOME_FILTERS as readonly string[]).includes(raw ?? "") ? (raw as OutcomeFilter) : undefined;
}

export function parseActionFilter(raw: string | undefined): ActionFilter | undefined {
  return (ACTION_FILTERS as readonly string[]).includes(raw ?? "") ? (raw as ActionFilter) : undefined;
}

/** 필터 조합 → URL (기본값은 파라미터 생략 — 공유 가능한 최소 URL) */
export function filterHref(outcome: OutcomeFilter | undefined, action: ActionFilter | undefined): string {
  const q = new URLSearchParams();
  if (outcome) q.set("outcome", outcome);
  if (action) q.set("action", action);
  const qs = q.toString();
  return qs ? `/decisions?${qs}` : "/decisions";
}

/* ── 상세 페이지: evidence detail JSON → key-value (#1216 raw JSON 폐지) ── */

/** 표시용 숫자: 정수는 그대로, 소수는 최대 2자리로 절사 (fx_rate 1480.780029… 방지) */
export function fmtKvNumber(v: number): string {
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(2).replace(/\.?0+$/, "");
}

export function fmtKvValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isFinite(v) ? fmtKvNumber(v) : "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "string") return v;
  // 중첩 객체/배열 — 드문 케이스, 압축 JSON fallback
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

/** detail 이 JSON 객체면 [key, 표시값] 목록, 아니면 null (호출자가 raw fallback) */
export function parseDetailKV(detail: string | null): Array<[string, string]> | null {
  if (!detail) return null;
  try {
    const parsed: unknown = JSON.parse(detail);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
    return Object.entries(parsed).map(([k, v]) => [k, fmtKvValue(v)]);
  } catch {
    return null;
  }
}

/** 소수 고정 표기 (vix 21.040000915… → 21.0). null 은 — */
export function fmtFixed(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? "—" : v.toFixed(digits);
}
