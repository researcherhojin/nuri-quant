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
  /** summary 자체 Other 버킷 — 크기·위치와 무관하게 기타로 병합 (#1210 P1) */
  isOther?: boolean;
}

export const CHART_COLORS = ["#4C90F0", "#3FA6DA", "#43BF4D", "#F0B726", "#9179F2"] as const;
/** Blueprint GRAY2 (#1435). 이전 `#404854` 는 구분선(`--background`)과 **2.00:1** 이라
 *  구분선이 이 조각 옆에서는 보이지 않았고, 카드 표면과도 1.75:1 이라 조각 자체가 잘 안
 *  보였다. GRAY1(#5F6B7C)로 올려봤지만 **카드 위 2.99** 로 0.01 차이 미달이라 기각했다 —
 *  구성 바는 카드 안에 놓이므로 그 표면이 기준이다. GRAY2 는 배경 4.60 / 카드 4.03. */
export const OTHER_COLOR = "#738091";

/** 상위 5 + 기타 병합. "상위 5"는 **개별** 슬라이스 기준이다 — holdings-summary 가
 *  이미 병합해 둔 자체 Other 버킷(top-12/top-4 잔여)은 집계 행이라 크기가 개별 상위
 *  5위 안에 들어도 카테고리 세그먼트로 승격하지 않고 항상 기타에 합산한다 (#1210 P1,
 *  codex R1). 색은 재할당하지 않는다 — 재매핑은 호출자(composition-section) 한 곳. */
export function toBarSegments(slices: BarSegment[], otherLabel: string): BarSegment[] {
  const individual = slices.filter((s) => !s.isOther);
  const top = individual.slice(0, CHART_COLORS.length);
  const restSum =
    individual.slice(CHART_COLORS.length).reduce((sum, s) => sum + s.value, 0) +
    slices.filter((s) => s.isOther).reduce((sum, s) => sum + s.value, 0);
  if (restSum > 0) return [...top, { label: otherLabel, value: restSum, color: OTHER_COLOR }];
  return top;
}

export function CompositionBar({ segments }: { segments: BarSegment[] }) {
  if (segments.length === 0) return null;
  // 접근성 (#1210 P2, codex R1): 세그먼트별 title 은 포인터 전용이라 스크린리더가
  // 못 읽는다 — img 의 accessible name 에 구성 전체를 열거하고 세그먼트는 장식 처리.
  const description = segments.map((s) => `${s.label} ${s.value.toFixed(1)}%`).join(", ");
  return (
    <div
      className="flex h-3.5 w-full rounded-sm overflow-hidden"
      data-testid="composition-bar"
      role="img"
      aria-label={`포트폴리오 구성: ${description}`}
    >
      {segments.map((s, i) => (
        <span
          key={s.label}
          data-testid="composition-bar-segment"
          aria-hidden="true"
          // WCAG 1.4.11 (#1435): 인접 세그먼트는 서로 3:1 로 구분돼야 하는데 팔레트 조합의
          // 최대가 1.85:1 이라 색만으로는 불가능하다 — 다크 배경에서 5 색을 전부 3:1 로
          // 벌리는 배치가 존재하지 않는다. 규격이 허용하는 대로 **구분선**으로 충족한다.
          // 색은 `--background`: 6 개 세그먼트 색 전부와 3.41~10.12:1 이다.
          // `border-box` 라 1px 테두리가 폭을 늘리지 않아 합이 100% 를 넘지 않는다.
          className={`h-full min-w-[3px] ${i > 0 ? "border-l border-background" : ""}`}
          style={{ width: `${s.value}%`, background: s.color }}
          title={`${s.label} ${s.value.toFixed(1)}%`}
        />
      ))}
    </div>
  );
}
