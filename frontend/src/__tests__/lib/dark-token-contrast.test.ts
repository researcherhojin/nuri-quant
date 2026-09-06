/**
 * #1431 — 다크 토큰의 대비 하한을 **주석이 아니라 테스트로** 잠근다.
 *
 * 이 파일이 생긴 이유: `globals.css` 의 가드레일 주석이 "대비 실측(WCAG) … 링크 8.2:1 —
 * 전부 AAA. 이 대비를 낮추는 변경 금지" 라고 말하면서, 그 8.2:1 이 `#4C90F0` 으로는
 * **도달 불가능한 값**이었다 (순흑 위에서도 6.55:1). 같은 주석의 다른 두 숫자는 정확했다 —
 * 측정 관행이 없었던 게 아니라 검사하는 게이트가 없어서 한 줄이 조용히 틀렸다.
 *
 * ⚠️ **값을 여기 복사하지 않는다 — 토큰도, 주석의 숫자도.** 첫 구현이 정확히 그 실수를 했다:
 * 주석 검증이랍시고 claim 을 테스트에 하드코딩해서, 거짓 8.2:1 을 주석에 되돌려도 21개가
 * 전부 초록이었다 (codex R1 P1). 지금은 `@contrast fg/bg ratio` 줄을 **CSS 에서 파싱**해
 * 실측과 대조한다.
 *
 * ⚠️ **짝짓기는 실사용에서 뽑는다.** 첫 구현은 `--accent-foreground`/`--accent` 를 검사했는데
 * `text-accent-foreground` 소비자가 **0** 이었다 — 존재하지 않는 조합을 재고 있었다. 반대로
 * `--primary` 는 링크 **텍스트**로 6곳에서 쓰이는데 3:1 그래픽으로만 분류돼 있었고,
 * `--muted-foreground` 는 차트 툴팁에서 `--popover` 위에 얹히는데(`lib/chart-theme.ts`)
 * `--card` 만 보고 있었다 (7.66 vs 5.92). 아래 목록의 각 줄에는 근거 개수를 적어둔다.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const CSS_PATH = join(process.cwd(), "src/app/globals.css");
const CSS = readFileSync(CSS_PATH, "utf-8");

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

/**
 * `.dark { … }` 블록의 hex 토큰. rgb()/var() 토큰은 대상이 아니다.
 *
 * 블록이 **정확히 하나**임을 요구한다 (codex R1 P1): 두 번째 `.dark` 블록이 나중에 오면
 * 캐스케이드는 그쪽이 이기는데 첫 블록만 파싱하는 게이트는 옛 값을 계속 재게 된다.
 */
function darkTokens(): Record<string, string> {
  const blocks = [...CSS.matchAll(/^\.dark\s*\{([\s\S]*?)^\}/gm)];
  if (blocks.length === 0) {
    throw new Error("globals.css 에서 `.dark { … }` 블록을 못 찾았다 — 게이트가 검사할 대상이 사라졌다");
  }
  if (blocks.length > 1) {
    throw new Error(
      `\`.dark\` 블록이 ${blocks.length}개다 — 캐스케이드상 마지막이 이기므로 첫 블록만 재는 이 게이트는 거짓이 된다. 블록을 합치거나 게이트를 캐스케이드 인식으로 고칠 것`,
    );
  }
  const found = [...blocks[0][1].matchAll(/--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})\b/g)];
  if (found.length === 0) throw new Error(".dark 블록에서 hex 토큰을 0개 파싱했다 — 정규식이 눈이 멀었다");
  return Object.fromEntries(found.map((m) => [m[1], m[2]]));
}

const T = darkTokens();

function token(name: string): string {
  const v = T[name];
  if (!v) throw new Error(`--${name} 가 .dark 블록에 없다 (또는 hex 가 아니다)`);
  return v;
}

/**
 * 텍스트로 렌더되는 토큰 → 실제로 얹히는 표면. WCAG AA 일반 텍스트 = 4.5:1.
 * 괄호 안은 근거(소비자 수). 근거 없는 조합은 넣지 않는다.
 */
const TEXT_ON: Array<[fg: string, bg: string, why: string]> = [
  ["foreground", "background", "text-foreground ×59, 페이지 표면"],
  ["foreground", "card", "text-foreground ×59 안에서 bg-card ×84"],
  ["foreground", "sidebar", "bg-sidebar ×1, 텍스트는 --foreground 상속"],
  ["card-foreground", "card", "text-card-foreground ×1"],
  ["muted-foreground", "card", "text-muted-foreground ×253 × bg-card ×84"],
  ["muted-foreground", "popover", "차트 툴팁 — CHART_MUTED on CHART_TOOLTIP_BG (chart-theme.ts)"],
  ["primary", "card", "text-primary 링크 ×6 (engine/page.tsx, decisions/page.tsx)"],
  ["primary", "background", "동일 링크가 카드 밖 표면에도 놓인다"],
  ["primary-foreground", "primary", "button.tsx default: bg-primary text-primary-foreground"],
  ["destructive", "card", "text-destructive ×1"],
  ["secondary-foreground", "secondary", "button.tsx secondary"],
];

/**
 * 그래픽·UI 요소. WCAG 1.4.11 non-text = 3:1. 배경·카드 양쪽에 놓이므로 빡빡한 쪽으로 본다.
 *
 * `--primary`/`--destructive` 는 여기 없다 — 텍스트로도 쓰이므로 위에서 4.5:1 로 재고,
 * 그게 3:1 을 포함한다. `--sidebar-primary`/`--sidebar-ring`/`--accent-foreground` 도 없다:
 * 소비자 0. 쓰이기 시작하면 그때 근거와 함께 추가한다.
 */
const GRAPHIC = ["ring", "chart-1", "chart-2", "chart-3", "chart-4", "chart-5"];

/** CSS 주석의 `@contrast fg/bg ratio` 줄. 이게 이 테스트가 검증하는 **주장**이다. */
function parseClaims(): Array<[fg: string, bg: string, claimed: number]> {
  const claims = [...CSS.matchAll(/@contrast\s+([a-z0-9-]+)\/([a-z0-9-]+)\s+([\d.]+)/g)].map(
    (m) => [m[1], m[2], Number(m[3])] as [string, string, number],
  );
  if (claims.length === 0) {
    throw new Error("globals.css 주석에서 `@contrast` 주장을 0건 파싱했다 — 주장이 지워졌거나 형식이 바뀌었다");
  }
  return claims;
}

describe("다크 토큰 대비 (#1431)", () => {
  it("파싱이 실제로 토큰을 잡았다", () => {
    // 게이트가 0건을 검사하며 초록인 상태를 막는 카나리아.
    expect(Object.keys(T).length).toBeGreaterThan(15);
    expect(T.background).toMatch(/^#[0-9A-Fa-f]{6}$/);
    expect(T.card).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });

  it.each(TEXT_ON)("--%s 는 --%s 위에서 AA 4.5:1 이상 (%s)", (fg, bg) => {
    const ratio = contrast(token(fg), token(bg));
    expect(
      ratio,
      `--${fg} (${token(fg)}) on --${bg} (${token(bg)}) = ${ratio.toFixed(2)}:1 — AA 4.5:1 미달`,
    ).toBeGreaterThanOrEqual(4.5);
  });

  it.each(GRAPHIC)("--%s 는 background·card 양쪽에서 non-text 3:1 이상", (t) => {
    const c = token(t);
    const worst = Math.min(contrast(c, T.background), contrast(c, T.card));
    expect(worst, `--${t} (${c}) 최악 대비 ${worst.toFixed(2)}:1 — non-text 3:1 미달`).toBeGreaterThanOrEqual(3);
  });

  it("주석의 @contrast 주장이 토큰 실측과 일치한다", () => {
    // 이 이슈의 본체. 주장을 **CSS 에서 읽어** 대조하므로, 8.2:1 같은 값을 주석에 되돌리면
    // 여기서 떨어진다. 값을 테스트로 복사하던 첫 구현은 그 회귀를 통과시켰다.
    for (const [fg, bg, claimed] of parseClaims()) {
      const actual = contrast(token(fg), token(bg));
      expect(
        Math.abs(actual - claimed),
        `@contrast ${fg}/${bg}: 주석 ${claimed}:1 vs 실측 ${actual.toFixed(2)}:1`,
      ).toBeLessThan(0.01);
    }
  });

  it("주석이 링크 대비를 실제로 주장하고 있다", () => {
    // 위 테스트는 "주장이 맞나" 만 본다 — 주장을 통째로 지우면 통과한다. 이슈가 걸린
    // 바로 그 페어(링크)는 존재 자체를 요구한다.
    const pairs = parseClaims().map(([f, b]) => `${f}/${b}`);
    expect(pairs).toContain("primary/background");
    expect(pairs).toContain("primary/card");
  });

  it("Blueprint 라이트 인텐트를 그대로 들여오면 이 게이트가 막는다", () => {
    // #1431 의 동기. @blueprintjs/core 6.18.0 tokens-dark.css 는 --bp-intent-* 를 0개
    // 정의하므로(라이트는 25개), 다크에서 인텐트를 쓰면 라이트 값을 물려받는다. 그 값들은
    // 이 배경에서 20개 중 14개가 AA 미달이다 — 이유를 값으로 박아둔다.
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

describe("차트 색 리터럴 드리프트 (#1431)", () => {
  // codex R1 P1: `composition-bar.tsx` 가 --chart-* 를 hex 리터럴로 복사해 두어, 토큰을
  // 바꿔도 그 차트는 안 바뀌고 리터럴을 바꾸면 위 게이트를 우회한다. 두 벌을 묶는다.
  it("CHART_COLORS 가 --chart-1..5 토큰과 같다", async () => {
    const { CHART_COLORS } = await import("@/components/dashboard/composition-bar");
    const fromTokens = [1, 2, 3, 4, 5].map((i) => token(`chart-${i}`).toUpperCase());
    expect(CHART_COLORS.map((c) => c.toUpperCase())).toEqual(fromTokens);
  });
});
