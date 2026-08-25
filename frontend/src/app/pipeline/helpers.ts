/**
 * Pipeline 타임라인 순수 헬퍼 (#1219 U4b).
 *
 * payload 는 이벤트별 임의 객체 — 이전에는 stderr/command/error 특례 뒤에
 * JSON.stringify raw 폴백이 화면에 그대로 노출됐다 (U3 evidence kv 와 같은
 * 계열의 raw JSON 결함). 사람이 읽는 요약 한 줄로 바꾼다.
 */

const PRIORITY_KEYS = ["stderr", "command", "error"] as const;
const MAX_KV = 3;

function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  if (typeof v === "string") return v;
  if (typeof v === "boolean") return v ? "true" : "false";
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

export function summarizePayload(payload: Record<string, unknown> | null | undefined): string {
  if (!payload || Object.keys(payload).length === 0) return "";
  // 우선순위 키는 단독 표기 (기존 동작 유지 — 실패 원인이 가장 중요)
  for (const k of PRIORITY_KEYS) {
    const v = payload[k];
    if (v) return String(v).slice(0, 80);
  }
  const entries = Object.entries(payload);
  const shown = entries.slice(0, MAX_KV).map(([k, v]) => `${k} ${fmtValue(v)}`);
  const rest = entries.length - MAX_KV;
  return shown.join(" · ") + (rest > 0 ? ` +${rest}` : "");
}
