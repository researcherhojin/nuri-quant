export function displayNumber(value: number | null | undefined, suffix = ""): string {
  return value == null || !Number.isFinite(value) ? "—" : `${value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}${suffix}`;
}

export function displayTime(value: string | null | undefined): string {
  if (!value) return "기준 시각 미제공";
  // 시간대 없는 백엔드 시각을 브라우저 로컬 시간으로 임의 해석하지 않는다.
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(value)) return value.replace("T", " ");
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "기준 시각 미제공";
  return `${new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date)} KST`;
}

export function displayChange(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? "—" : `${value > 0 ? "+" : ""}${displayNumber(value, "%")}`;
}
