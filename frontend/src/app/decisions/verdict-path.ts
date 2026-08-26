// #1257: 판정 경로 파생 — "왜 이 판정·이 확신도인가" 를 재구성하는 순수 헬퍼.
// 정본은 백엔드 scoring_detail(final_action_source, #1256 부터 persist)이고,
// 그 이전 387행은 reasoning 프리픽스 파싱으로 fallback 한다.

export interface ScoringDetail {
  final_action_source?: "risk_veto" | "divergence_penalty" | "weighted_sum" | string;
  degraded_agents?: string[];
  panel_coverage?: number;
  risk_veto_fired?: boolean;
  penalty_applied?: boolean;
  pre_penalty_action?: string;
  [key: string]: unknown;
}

// 백엔드 scoring.py 가 veto 발동 시 reasoning 앞에 붙이는 고정 프리픽스 —
// scoring_detail 이 없는 과거 행의 유일한 판정 소스 신호.
export const VETO_REASONING_PREFIX = "리스크 에이전트 거부권 발동";

export type ActionSource = "risk_veto" | "divergence_penalty" | "weighted_sum";

// scoring_detail 은 SELECT * 경유라 JSON 문자열로 도착한다 — 안전 파싱.
export function parseScoringDetail(raw: unknown): ScoringDetail | null {
  let obj: unknown = raw;
  if (typeof raw === "string") {
    try {
      obj = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (obj == null || typeof obj !== "object" || Array.isArray(obj)) return null;
  return obj as ScoringDetail;
}

// 판정 소스 파생. scoring_detail 우선, 과거 행은 reasoning 프리픽스 fallback,
// 그 외에는 기본 경로(weighted_sum) — 셋 중 하나로 반드시 수렴한다.
export function deriveActionSource(sd: ScoringDetail | null, reasoning: string | null): ActionSource {
  const src = sd?.final_action_source;
  if (src === "risk_veto" || src === "divergence_penalty" || src === "weighted_sum") return src;
  if (reasoning?.startsWith(VETO_REASONING_PREFIX)) return "risk_veto";
  return "weighted_sum";
}

// 합의 분포 (BUY/SELL/중립·무의견) — 히어로의 분포 바 입력.
export function verdictSplit(verdicts: { action: string }[]): { buy: number; sell: number; rest: number } {
  let buy = 0;
  let sell = 0;
  for (const v of verdicts) {
    if (v.action === "BUY") buy += 1;
    else if (v.action === "SELL") sell += 1;
  }
  return { buy, sell, rest: verdicts.length - buy - sell };
}
