/**
 * recharts 차트의 **중립 크롬 색** — 전부 `globals.css` 토큰을 가리킨다 (#1275).
 *
 * 차트들이 zinc 계열 hex 를 직접 박고 있었다(실측 63곳 / 9파일). 이건 위생 문제만이
 * 아니다 — 이 앱의 다크 팔레트는 **zinc 가 아니다**:
 *
 * | 토큰 | 다크 값 | 차트가 쓰던 zinc |
 * |---|---|---|
 * | `--background` | `#111418` | `#18181b` |
 * | `--popover` | `#2F343C` | `#18181b` |
 * | `--muted-foreground` | `#ABB3BF` | `#a1a1aa` / `#71717a` |
 * | `--border` | `rgb(255 255 255 / 10%)` | `#27272a` |
 *
 * 즉 차트는 테마 토큰을 바꿔도 안 따라올 뿐 아니라 **지금도 앱 팔레트와 어긋나** 있다.
 * 토큰으로 옮기면 외형이 앱 쪽으로 이동한다 — 의도된 변화다.
 *
 * 인라인 스타일도 SVG 속성도 CSS 변수를 해석하므로 hex 를 쓸 이유가 없다 (#1253 이
 * `pipeline/page.tsx` 에서 확인한 것과 같은 근거).
 *
 * ⚠️ **역할이 다르면 상수도 다르다.** 같은 `#27272a` 라도 격자 선과 treemap 의
 * "위반 없음" 채움은 의미가 다르다 — 한 상수로 뭉개면 한쪽을 조정할 때 다른 쪽이 따라
 * 움직인다 (#1275 이 명시한 주의).
 */

/** 격자 선 (`CartesianGrid stroke`). */
export const CHART_GRID_STROKE = "var(--border)";

/** 축 눈금 · 범례 · 주석 등 **약하게 읽혀야 하는** 모든 중립 텍스트/선. */
export const CHART_MUTED = "var(--muted-foreground)";

/** 툴팁 배경 — 떠 있는 패널이므로 `--popover`. */
export const CHART_TOOLTIP_BG = "var(--popover)";

/** 툴팁 테두리. `border` 단축 속성에 그대로 넣는 완성형 문자열이다. */
export const CHART_TOOLTIP_BORDER = "1px solid var(--input)";

/** 툴팁 **안쪽** 본문 텍스트 (배경이 `--popover` 이므로 그 짝을 쓴다). */
export const CHART_TOOLTIP_ITEM = "var(--popover-foreground)";

/** 셀 구분선 — 배경색으로 그어 타일을 갈라 보이게 한다 (siege 타임라인 dot). */
export const CHART_CELL_STROKE = "var(--background)";

/** treemap 의 **위반 없음** 채움. 격자 선과 값이 같아도 의미가 달라 분리한다. */
export const CHART_EMPTY_FILL = "var(--muted)";

/** 도형 위에 얹는 강조 라벨 (treemap 티커명). */
export const CHART_LABEL_STRONG = "var(--foreground)";
