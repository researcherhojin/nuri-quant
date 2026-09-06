/**
 * #1431 — 다크 토큰의 대비 하한을 **주석이 아니라 테스트로** 잠근다.
 *
 * 이 파일이 생긴 이유: `globals.css` 의 가드레일 주석이 "대비 실측(WCAG) … 링크 8.2:1 —
 * 전부 AAA. 이 대비를 낮추는 변경 금지" 라고 말하면서, 그 8.2:1 이 `#4C90F0` 으로는
 * **도달 불가능한 값**이었다 (순흑 위에서도 6.55:1, 8.2:1 이 되려면 배경 휘도가 음수).
 * 같은 주석의 다른 두 숫자(15.11 / 7.66)는 정확했다 — 즉 측정 관행이 없었던 게 아니라
 * 검사하는 게이트가 없어서 한 줄이 조용히 틀린 채로 남았다.
 *
 * ⚠️ **값을 여기 복사하지 않는다.** `globals.css` 를 파싱해서 검사한다. 토큰을 테스트에
 * 복사하면 두 벌이 갈라지고, 그게 정확히 이 이슈가 잡은 실패 유형(문서와 실제의 드리프트)을
 * 재생산한다. 파싱이 실패하면 그것도 FAIL 이다 — 블록 이름이 바뀌면 조용히 0건을 검사하는
 * 게 아니라 터져야 한다 (#910 죽은 게이트 교훈).
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const CSS = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf-8");

/** sRGB 상대 휘도 (WCAG 2.x). */
function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

/** WCAG 대비비. 순서 무관. */
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** `.dark { … }` 블록의 hex 토큰만 뽑는다. rgb()/var() 토큰은 대상이 아니다. */
function darkTokens(): Record<string, string> {
  const block = /\.dark\s*\{([\s\S]*?)\n\}/.exec(CSS);
  if (!block) throw new Error("globals.css 에서 `.dark { … }` 블록을 못 찾았다 — 게이트가 검사할 대상이 사라졌다");
  const found = [...block[1].matchAll(/--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})\b/g)];
  if (found.length === 0) throw new Error(".dark 블록에서 hex 토큰을 0개 파싱했다 — 정규식이 눈이 멀었다");
  return Object.fromEntries(found.map((m) => [m[1], m[2]]));
}

const T = darkTokens();

/** 텍스트로 렌더되는 토큰 → 그 토큰이 얹히는 표면. WCAG AA 일반 텍스트 = 4.5:1. */
const TEXT_ON: Array<[token: string, surface: string]> = [
  ["foreground", "background"],
  ["card-foreground", "card"],
  ["popover-foreground", "popover"],
  ["muted-foreground", "card"],
  ["secondary-foreground", "secondary"],
  ["accent-foreground", "accent"],
  ["sidebar-foreground", "sidebar"],
  ["sidebar-accent-foreground", "sidebar-accent"],
];

/**
 * 그래픽·UI 요소로 렌더되는 토큰. WCAG 1.4.11 non-text contrast = 3:1.
 * 배경과 카드 **둘 다** 위에 놓이므로 더 빡빡한 쪽으로 검사한다.
 */
const GRAPHIC = [
  "primary", "destructive", "ring",
  "chart-1", "chart-2", "chart-3", "chart-4", "chart-5",
  "sidebar-primary", "sidebar-ring",
];

describe("다크 토큰 대비 (#1431)", () => {
  it("파싱이 실제로 토큰을 잡았다", () => {
    // 게이트가 0건을 검사하며 초록인 상태를 막는 카나리아.
    expect(Object.keys(T).length).toBeGreaterThan(15);
    expect(T.background).toMatch(/^#[0-9A-Fa-f]{6}$/);
    expect(T.card).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });

  it.each(TEXT_ON)("--%s 는 --%s 위에서 AA 4.5:1 이상", (token, surface) => {
    const fg = T[token];
    const bg = T[surface];
    expect(fg, `--${token} 가 .dark 블록에 없다`).toBeDefined();
    expect(bg, `--${surface} 가 .dark 블록에 없다`).toBeDefined();
    const ratio = contrast(fg, bg);
    expect(
      ratio,
      `--${token} (${fg}) on --${surface} (${bg}) = ${ratio.toFixed(2)}:1 — AA 4.5:1 미달`,
    ).toBeGreaterThanOrEqual(4.5);
  });

  it.each(GRAPHIC)("--%s 는 background·card 양쪽에서 non-text 3:1 이상", (token) => {
    const c = T[token];
    expect(c, `--${token} 가 .dark 블록에 없다`).toBeDefined();
    const worst = Math.min(contrast(c, T.background), contrast(c, T.card));
    expect(
      worst,
      `--${token} (${c}) 최악 대비 ${worst.toFixed(2)}:1 — non-text 3:1 미달`,
    ).toBeGreaterThanOrEqual(3);
  });

  it("주석이 적어둔 대비 수치가 실제와 일치한다", () => {
    // 이 이슈의 본체. 주석에 숫자를 쓰는 관행 자체는 유지하되, 그 숫자를 검사한다.
    // 8.2:1 은 이 검사가 있었다면 애초에 커밋되지 못했다.
    const claims: Array<[label: string, fg: string, bg: string, claimed: number]> = [
      ["text/card", T.foreground, T.card, 15.11],
      ["muted/card", T["muted-foreground"], T.card, 7.66],
      ["link/background", T.primary, T.background, 5.76],
      ["link/card", T.primary, T.card, 5.06],
    ];
    for (const [label, fg, bg, claimed] of claims) {
      const actual = contrast(fg, bg);
      expect(
        Math.abs(actual - claimed),
        `${label}: 주석 ${claimed}:1 vs 실측 ${actual.toFixed(2)}:1`,
      ).toBeLessThan(0.01);
    }
  });

  it("Blueprint 라이트 인텐트를 그대로 들여오면 이 게이트가 막는다", () => {
    // #1431 의 동기. @blueprintjs/core 6.18.0 tokens-dark.css 는 --bp-intent-* 를 0개
    // 정의하므로, 다크에서 인텐트를 쓰려면 라이트 값을 물려받게 된다. 그 값들은 이 배경에서
    // 20개 중 14개가 AA 미달이다 — 이 테스트가 존재하는 이유를 값으로 박아둔다.
    const BP_LIGHT_INTENT_REST = {
      primary: "#2d72d2",
      success: "#238551",
      warning: "#c87619",
      danger: "#cd4246",
    };
    const failing = Object.entries(BP_LIGHT_INTENT_REST)
      .filter(([, hex]) => contrast(hex, T.background) < 4.5)
      .map(([name]) => name);
    expect(failing).toEqual(["primary", "success", "danger"]);
  });
});
