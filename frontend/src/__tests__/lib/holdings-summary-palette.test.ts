/**
 * #1301 — composition 팔레트의 "기타" 색이 **형제 뒤로 물러나는지**.
 *
 * #1275 가 차트 크롬을 토큰으로 옮길 때 `holdings-summary.ts` 는 범위 밖이었고, 그래서
 * 이 파일의 색값은 **어떤 게이트도 보지 않았다** — 그게 #1301 이 지적한 결함이다.
 *
 * 다만 고치는 방향이 이슈의 가정과 달랐다. 이슈는 `var(--muted-foreground)` 를 유력 후보로
 * 봤지만 측정이 그걸 기각한다 (다크 `--card` `#1C2127` 기준):
 *
 *   `#71717a` (현행)          L 0.167  ← 형제(cyan-400 L 0.531)들 뒤로 물러남
 *   `var(--muted-foreground)` L 0.447  ← 형제와 **대등**해져 "기타" 가 앞으로 나온다
 *   `var(--muted)`            L 0.023  ← 사실상 안 보인다
 *
 * 그래서 값은 계열색으로 남기고 **요구사항 자체를 잠근다.** 색을 고르는 사람이 바뀌어도
 * "기타는 명명된 종목보다 어둡다" 는 계약은 여기서 깨진다.
 */
import { describe, expect, it } from "vitest";
import { OTHER_COLOR, SECTOR_COLORS, TICKER_COLORS } from "@/lib/holdings-summary";

/** WCAG 상대 밝기. 대비비가 아니라 **밝기**를 보는 이유는 위계가 밝기 순서이기 때문이다. */
function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

const SIBLINGS = [...SECTOR_COLORS, ...TICKER_COLORS];

describe("composition 팔레트 (#1301)", () => {
  it("'기타' 는 명명된 조각 전부보다 어둡다", () => {
    // 이게 이 색의 **요구사항**이다 — 토큰이냐 hex 냐보다 이쪽이 계약이다.
    const other = luminance(OTHER_COLOR);
    const brightest = Math.min(...SIBLINGS.map(luminance));
    expect(other, `기타(${OTHER_COLOR}, L=${other.toFixed(3)}) 가 형제만큼 밝다`).toBeLessThan(brightest);
  });

  it("그렇다고 보이지 않을 만큼 어둡지도 않다", () => {
    // 반대 방향 — `var(--muted)`(L 0.023) 류로 내려가면 조각이 배경에 묻힌다.
    expect(luminance(OTHER_COLOR)).toBeGreaterThan(0.05);
  });

  it("팔레트에 중복 색이 없다", () => {
    // 같은 색 두 조각은 범례를 무의미하게 만든다. 팔레트를 손볼 때 흔한 실수다.
    for (const [name, palette] of [
      ["SECTOR_COLORS", SECTOR_COLORS],
      ["TICKER_COLORS", TICKER_COLORS],
    ] as [string, readonly string[]][]) {
      expect(new Set(palette).size, `${name} 에 중복 색`).toBe(palette.length);
    }
    expect(SIBLINGS).not.toContain(OTHER_COLOR);
  });

  it("밝기 계산이 실제로 구분한다 (canary)", () => {
    // 함수가 상수를 돌려주면 위 검사들이 전부 공허하게 통과한다.
    expect(luminance("#ffffff")).toBeGreaterThan(luminance("#000000"));
    expect(luminance("#ABB3BF")).toBeGreaterThan(luminance("#71717a"));
  });
});
