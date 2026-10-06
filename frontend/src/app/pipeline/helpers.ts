/**
 * Pipeline 타임라인 순수 헬퍼 (#1219 U4b).
 *
 * payload 는 이벤트별 임의 객체 — 이전에는 stderr/command/error 특례 뒤에
 * JSON.stringify raw 폴백이 화면에 그대로 노출됐다 (U3 evidence kv 와 같은
 * 계열의 raw JSON 결함). 사람이 읽는 요약 한 줄로 바꾼다.
 */

import { isBoolean, isNumber, isPlainObject, isString, type JsonValue } from "@/lib/types";

const MAX_KV = 3;

function fmtValue(v: JsonValue): string {
  if (v === null || v === undefined) return "—";

  if (isNumber(v)) return Number.isInteger(v) ? String(v) : v.toFixed(2);

  if (isString(v)) return v;

  if (isBoolean(v)) return v ? "true" : "false";

  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

/**
 * payload 는 객체가 보통이지만 백엔드(`get_timeline`)는 JSON 디코드에 실패하면 **원문 문자열**을,
 * 비었으면 null 을 그대로 내보내고 `json.loads` 는 배열·스칼라도 낸다 (#1661). 객체가 아니면
 * 키로 풀지 않고 값 하나로 80자까지 보인다 — 문자열을 `Object.entries` 로 돌리면 글자 인덱스가 찍힌다.
 */
export function summarizePayload(payload: JsonValue | undefined): string {
  if (payload == null || payload === "") return "";

  if (!isPlainObject(payload)) return fmtValue(payload).slice(0, 80);

  if (Object.keys(payload).length === 0) return "";

  // 우선순위 키 단독 표기 — 원 동작 정확 패리티 (codex R1 P2): stderr 만 80자
  // 절단하고 command/error 는 전문 통과 (시각 절단은 line-clamp-1 몫)
  if (payload.stderr) return String(payload.stderr).slice(0, 80);

  if (payload.command) return String(payload.command);

  if (payload.error) return String(payload.error);
  const entries = Object.entries(payload);
  const shown = entries.slice(0, MAX_KV).map(([k, v]) => `${k} ${fmtValue(v)}`);
  const rest = entries.length - MAX_KV;

  return shown.join(" · ") + (rest > 0 ? ` +${rest}` : "");
}
