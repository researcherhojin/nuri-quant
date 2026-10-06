import { SYSTEM_STANCE } from "@/lib/strings";
import { lookup } from "@/lib/utils";

/**
 * `/api/opportunities` 의 `system` — BUY 후보 emitter 가 그 종목을 어떻게 분류했는가 (#1683).
 * 서버 컴포넌트(dashboard-next)와 클라이언트 컴포넌트(OpportunityExplorer)가 같이 쓰므로
 * `"use client"` 모듈에 두지 않는다 (frontend/CLAUDE.md "RSC boundary").
 */
export interface SystemStance {
  status: string;
  score: number | null;
  threshold: number | null;
  reason: string | null;
}

export type StanceTone = "positive" | "neutral" | "danger" | "muted";

const TONE = {
  qualified: "positive",
  below_threshold: "muted",
  excluded: "neutral",
  blocked: "danger",
  not_scored: "muted",
} satisfies Record<string, StanceTone>;

export function stanceTone(system: SystemStance): StanceTone {
  return lookup(TONE, system.status) ?? "muted";
}

function scored(label: string, system: SystemStance): string {
  if (system.score == null || system.threshold == null) return label;

  // 내림 — 반올림하면 69.6 미달이 "기준 미달 70 / 70" 으로 자기모순이 된다
  return `${label} ${Math.floor(system.score)} / ${Math.floor(system.threshold)}`;
}

function withReason(label: string, reason: string | null): string {
  const text = lookup(SYSTEM_STANCE.REASON, reason) ?? reason;

  return text ? `${label} · ${text}` : label;
}

/** 분류 전체 문장 — 차단이면 emitter 가 남긴 사유까지. */
export function stanceText(system: SystemStance): string {
  switch (system.status) {
    case "qualified":
      return scored(SYSTEM_STANCE.QUALIFIED, system);
    case "below_threshold":
      return scored(SYSTEM_STANCE.BELOW_THRESHOLD, system);
    case "excluded":
      return withReason(SYSTEM_STANCE.EXCLUDED, system.reason);
    case "blocked":
      return withReason(SYSTEM_STANCE.BLOCKED, system.reason);
    default:
      return withReason(SYSTEM_STANCE.NOT_SCORED, system.reason);
  }
}

/** 좁은 칸(배지·버튼)용 — 차단 사유 문장은 길어서 상세에서만 보인다. */
export function stanceLabel(system: SystemStance): string {
  return system.status === "blocked" ? SYSTEM_STANCE.BLOCKED : stanceText(system);
}
