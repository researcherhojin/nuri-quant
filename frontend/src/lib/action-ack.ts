/**
 * action-ack (#1212 U2b-4) — 액션 행 seen-state (per-viewer localStorage).
 *
 * 운영자가 이미 확인(ack)한 액션과 새 액션을 구분한다. identity 는
 * `ticker|account|action|priority` — priority(버킷)까지 넣어야 같은 튜플이
 * 두 버킷에 동시에 뜰 때 한쪽 ack 이 다른쪽 NEW 를 지우지 않고, check→urgent
 * 승격도 새 항목으로 re-alert 된다 (codex R1 P1). 값은 ack 시점의
 * 판정일(as_of) — 같은 항목이라도 판정일이 갱신되면 다시 NEW (re-alert). 서버·타 기기와 공유되지
 * 않는 뷰어 편의 상태라 localStorage 가 맞는 자리이고, 접근은 전부
 * try/catch (프라이빗 창·차단 환경에서 accessor 자체가 throw 할 수 있다).
 */

export type AckMap = Record<string, string>;

const STORAGE_KEY = "nuri.actions.ack.v1";

interface AckableItem {
  ticker: string;
  account?: string;
  action: string;
  priority: string;
  as_of?: string | null;
}

export function actionKey(item: AckableItem): string {
  return `${item.ticker}|${item.account ?? ""}|${item.action}|${item.priority}`;
}

/** map null = 아직 미로드(SSR/마운트 전) — NEW 를 그리지 않아 hydration 안전 */
export function isNewItem(item: AckableItem, map: AckMap | null): boolean {
  if (map === null) return false;
  const acked = map[actionKey(item)];
  if (acked === undefined) return true;
  // ISO(YYYY-MM-DD) 문자열 비교 = 시간 순 비교. as_of 없는 항목은 ack 1회면 종결.
  return item.as_of != null && item.as_of > acked;
}

export function loadAckMap(): AckMap {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return {};
    const map: AckMap = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (typeof v === "string") map[k] = v;
    }
    return map;
  } catch {
    return {};
  }
}

/** ack 후의 새 맵을 반환하고 저장은 best-effort (실패해도 in-memory 는 동작) */
export function ackItem(map: AckMap, item: AckableItem): AckMap {
  const next = { ...map, [actionKey(item)]: item.as_of ?? "" };
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // 저장 불가 환경 — 세션 내 in-memory ack 만 유지
  }
  return next;
}
