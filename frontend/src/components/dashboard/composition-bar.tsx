/**
 * CompositionBar (#1210 U2b-3) — 포트폴리오 구성 가로 스택 바.
 *
 * 도넛(recharts CompositionDonut, 320px) 대체 — 목업·plan §1 합의: 캔디 팔레트
 * 폐지, 카테고리 5색 + 기타 무채. 순수 server component (recharts 의존 제거).
 * 색은 globals.css --chart-1..5 와 동일 값 — CSS 변수는 SSR inline style 에서
 * 읽을 수 없어 상수로 미러링한다 (globals.css 변경 시 함께 갱신).
 */

export interface BarSegment {
  label: string;
  /** 전체 대비 % (0-100) */
  value: number;
  color: string;
}

export const CHART_COLORS = ["#4C90F0", "#3FA6DA", "#43BF4D", "#F0B726", "#9179F2"] as const;
export const OTHER_COLOR = "#404854";

/** 상위 5 + 기타 병합. 색은 재할당하지 않는다 — 재매핑은 호출자(composition-section)
 *  한 곳에서 하고 (summary 자체 Other 버킷 = 무채 예외 포함) 바는 그 색을 그대로 쓴다. */
export function toBarSegments(slices: BarSegment[], otherLabel: string): BarSegment[] {
  const top = slices.slice(0, CHART_COLORS.length);
  const restSum = slices.slice(CHART_COLORS.length).reduce((sum, s) => sum + s.value, 0);
  if (restSum > 0) return [...top, { label: otherLabel, value: restSum, color: OTHER_COLOR }];
  return top;
}

export function CompositionBar({ segments }: { segments: BarSegment[] }) {
  if (segments.length === 0) return null;
  return (
    <div className="flex h-3.5 w-full rounded-sm overflow-hidden" data-testid="composition-bar" role="img" aria-label="포트폴리오 구성 비중 바">
      {segments.map((s) => (
        <span
          key={s.label}
          data-testid="composition-bar-segment"
          className="h-full min-w-[2px]"
          style={{ width: `${s.value}%`, background: s.color }}
          title={`${s.label} ${s.value.toFixed(1)}%`}
        />
      ))}
    </div>
  );
}
