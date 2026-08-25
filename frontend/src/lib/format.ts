// 통화·숫자 포맷 일원화 (#1197 U1b-1) — KRW 판정과 화폐 표기는 여기 한 곳에서만.
// 배경: 통화 결정이 6곳에 흩어져 .KS 종목이 $ 로 표기되는 버그가 반복됨
// (ticker 헤더 $1,128,000 · client-table 의 `v > 10000` 휴리스틱 등).

const KRW_TICKER = /\.(KS|KQ)$/;

/** .KS(코스피)/.KQ(코스닥) 티커 여부 — 통화 추론의 유일한 티커 규칙 */
export function isKrwTicker(ticker: string | null | undefined): boolean {
  return !!ticker && KRW_TICKER.test(ticker.trim().toUpperCase());
}

/**
 * 화폐 표기: KRW 는 ₩ + 정수 천단위, USD 는 $ + 소수 2자리 천단위.
 * currency("KRW"/"USD")가 있으면 우선, 없으면 ticker 접미사로 판정.
 */
export function formatMoney(
  value: number | null | undefined,
  opts: { ticker?: string | null; currency?: string | null } = {},
): string {
  if (value == null || Number.isNaN(value)) return "—";
  const krw = opts.currency ? opts.currency.toUpperCase() === "KRW" : isKrwTicker(opts.ticker);
  return krw
    ? `₩${Math.round(value).toLocaleString("en-US")}`
    : `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** 퍼센트: 부호(+/−) 항상 병기 (색맹 대비 — 색만으로 방향 전달 금지, 스펙 §1) */
export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

/** 일반 수치: raw float 노출 금지 (52.9428571... → 52.9) */
export function formatNum(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}
