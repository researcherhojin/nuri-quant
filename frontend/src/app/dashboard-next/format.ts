import { DASHBOARD_NEXT as COPY } from "@/lib/strings";

// `fixed` 를 주면 소수 자릿수를 고정한다 (지수 레벨·변화율은 소수 둘째 자리가 관례, #1676).
export function displayNumber(value: number | null | undefined, suffix = "", fixed?: number): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const digits = fixed == null ? { maximumFractionDigits: 1 } : { minimumFractionDigits: fixed, maximumFractionDigits: fixed };

  return `${value.toLocaleString("ko-KR", digits)}${suffix}`;
}

export function displayTime(value: string | null | undefined): string {
  if (!value) return COPY.TIME_UNKNOWN;

  // 시간대 없는 백엔드 시각을 브라우저 로컬 시간으로 임의 해석하지 않는다.
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(value)) return value.replace("T", " ");
  const date = new Date(value);

  if (!Number.isFinite(date.getTime())) return COPY.TIME_UNKNOWN;

  return `${new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date)} KST`;
}

/** 행 안의 짧은 시각 `MM-DD HH:mm` (KST). 오프셋 없는 값은 시간대를 지어내지 않고 그대로 자른다. */
export function displayShortTime(value: string | null | undefined): string | null {
  if (!value) return null;

  if (!/(Z|[+-]\d{2}:\d{2})$/.test(value)) return value.slice(5, 16).replace("T", " ");
  const date = new Date(value);

  if (!Number.isFinite(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? "";

  return `${part("month")}-${part("day")} ${part("hour")}:${part("minute")}`;
}

export function displayChange(value: number | null | undefined, fixed?: number): string {
  return value == null || !Number.isFinite(value) ? "—" : `${value > 0 ? "+" : ""}${displayNumber(value, "%", fixed)}`;
}
