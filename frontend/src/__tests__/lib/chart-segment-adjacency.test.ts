/**
 * 인접한 차트 세그먼트가 서로 구분되는지 — WCAG 1.4.11 (#1435).
 *
 * `#1431` 의 게이트는 각 차트 색을 **배경 대비**로만 잰다 (전부 4.80~8.88:1 통과). 배경 위에서
 * 잘 보이는 것과 **옆 조각과 구분되는 것**은 다른 요구사항이고, 규격은 인접 그래픽 객체의 예로
 * 차트 세그먼트를 명시한다.
 *
 * ## 색만으로는 불가능하다 (실측)
 *
 * `CHART_COLORS` 5 색의 모든 조합이 3:1 미만이다 — 최악 1.05, 최선 1.85. 다크 배경에서 5 색을
 * 전부 3:1 로 벌리는 배치는 존재하지 않으므로 팔레트 재배열은 해법이 아니다. 규격이 허용하는
 * 대로 **구분선**으로 충족한다.
 *
 * ## 단일 구분선 색이 성립하는 조건
 *
 * 구분선은 자기 양옆과 각각 3:1 이어야 한다. 밝은 색(#F0B726, 휘도 0.52)은 **어두운** 구분선을,
 * 어두운 색은 **밝은** 구분선을 요구하므로, 세그먼트 팔레트가 너무 넓으면 해가 없다. 실제로
 * 이전 `OTHER_COLOR`(#404854, 휘도 0.064)까지 포함하면 필요 조건이 `L ≥ 0.295` 이면서
 * `L ≤ 0.14` 라 **모순**이었다. 그래서 이 수정은 구분선만 넣지 않고 `OTHER_COLOR` 도 함께
 * 올렸다 — 둘 중 하나만으로는 안 닫힌다.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { CHART_COLORS, OTHER_COLOR } from "@/components/dashboard/composition-bar";

const SRC = join(process.cwd(), "src");
const CSS = readFileSync(join(SRC, "app/globals.css"), "utf8");

function darkToken(name: string): string {
  const dark = CSS.slice(CSS.search(/\.dark(?![\w-])/));
  const m = dark.match(new RegExp(`--${name}:\\s*(#[0-9A-Fa-f]{6})`));
  if (!m) throw new Error(`.dark 에서 --${name} 을 찾지 못했다`);
  return m[1];
}

const srgb = (v: number) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);
}
function ratio(a: string, b: string): number {
  const [la, lb] = [luminance(a), luminance(b)];
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const SEGMENT_COLORS = [...CHART_COLORS, OTHER_COLOR];
const NON_TEXT_MIN = 3.0;

describe("차트 세그먼트 인접 대비 (#1435)", () => {
  it("구분선이 모든 세그먼트 색과 3:1 이상이다", () => {
    // 이것이 성립해야 구분선이 제 역할을 한다 — 한 조각 옆에서만 안 보여도 그 경계는
    // 구분되지 않는다. 이전 OTHER_COLOR 가 정확히 그 상태였다 (구분선과 2.00:1).
    const sep = darkToken("background");
    const weak = SEGMENT_COLORS.map((c) => [c, ratio(sep, c)] as const).filter(([, r]) => r < NON_TEXT_MIN);
    expect(weak.map(([c, r]) => `${c} ${r.toFixed(2)}:1`),
      "구분선과 3:1 미만인 세그먼트 색이 있다 — 그 경계는 구분되지 않는다").toEqual([]);
  });

  it("구분선이 실제로 렌더된다", () => {
    // 색 대비만 재고 마크업을 안 보면, 구분선을 지워도 통과하는 게이트가 된다.
    const src = readFileSync(join(SRC, "components/dashboard/composition-bar.tsx"), "utf8");
    expect(src).toMatch(/border-l\s+border-background/);
    // 첫 조각에는 붙이지 않는다 (컨테이너 가장자리라 색만 깎인다)
    expect(src).toMatch(/i\s*>\s*0/);
  });

  it("카나리아 — 팔레트만으로는 3:1 을 못 만든다 (구분선이 필요한 이유)", () => {
    // 이 전제가 깨지면(예: 팔레트 교체로 인접 대비가 확보되면) 구분선 근거를 다시 쓸 것.
    const pairs: number[] = [];
    for (let i = 0; i < CHART_COLORS.length; i++) {
      for (let j = i + 1; j < CHART_COLORS.length; j++) pairs.push(ratio(CHART_COLORS[i], CHART_COLORS[j]));
    }
    expect(Math.max(...pairs)).toBeLessThan(NON_TEXT_MIN);
    expect(pairs).toHaveLength(10); // 5C2 — 스캔이 조합을 빠뜨리지 않았는지
  });

  it("OTHER_COLOR 는 페이지 배경 위에서도 보인다", () => {
    // 구분선 대비와 별개 축이다: 조각 자체가 배경과 2.00:1 이면 조각이 안 보인다.
    expect(ratio(darkToken("background"), OTHER_COLOR)).toBeGreaterThanOrEqual(NON_TEXT_MIN);
    expect(ratio(darkToken("card"), OTHER_COLOR)).toBeGreaterThanOrEqual(NON_TEXT_MIN);
  });
});
