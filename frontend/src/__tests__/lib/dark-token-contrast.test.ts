/**
 * #1431 — 다크 토큰의 대비 하한을 **주석이 아니라 테스트로** 잠근다.
 *
 * 발단: `globals.css` 가드레일 주석이 "링크 8.2:1 — 전부 AAA. 이 대비를 낮추는 변경 금지"
 * 라고 말하면서, 그 8.2:1 이 `#4C90F0` 으로는 **도달 불가능한 값**이었다 (순흑 위 6.55:1 이
 * 최대). 같은 주석의 다른 두 숫자는 소수점까지 정확했다 — 측정 관행이 없었던 게 아니라
 * 검사하는 게이트가 없어서 한 줄만 조용히 틀렸다.
 *
 * 이 파일이 세 번 고쳐진 이유를 남긴다. 매번 **게이트 자신이 같은 병에 걸려 있었다**:
 *
 * 1. claim 을 테스트에 하드코딩 → 거짓 8.2:1 을 주석에 되돌려도 전부 초록 (codex R1).
 *    이제 `@contrast fg/bg ratio` 를 CSS 에서 **파싱**한다.
 * 2. 짝짓기를 Tailwind 클래스 grep 으로만 뽑음 → `--accent-foreground` 는 소비자 0인데 재고,
 *    링크 텍스트로 쓰이는 `--primary` 는 3:1 로만 쟀다 (codex R1).
 * 3. **토큰이 CSS 변수로 소비되는 경로를 못 봄** → `text-popover-foreground` 클래스는 0건이나
 *    `chart-theme.ts` 가 `var(--popover-foreground)` 로 툴팁 본문에 쓴다. 그리고 실제 배경이
 *    **알파 합성**인 경우(`bg-destructive/20`, `bg-primary/10`)를 원색 배경으로 쟀다 —
 *    합성하면 AA 아래로 떨어지는 조합이 둘 있다 (codex R2).
 *
 * 교훈: 소비자 조사는 `text-*` 클래스 grep 으로 끝나지 않는다. `var(--token)` 참조와
 * `bg-token/NN` 알파를 같이 봐야 렌더링되는 실제 대비가 나온다.
 *
 * ## 이 게이트가 검사하지 **않는** 것 (codex R3 — 범위를 명시하지 않으면 이 파일이 실제보다
 * 넓은 보증을 하는 것처럼 읽힌다)
 *
 * **호출부의 전경 알파 수식어.** `text-muted-foreground/70` (48곳) · `/50` (13곳) · `/60`
 * (7곳) · `text-foreground/80` (18곳) 같은 per-site 불투명도는 여기서 안 본다. 실측하면
 * `/70` ≈ 4.47:1, `/60` ≈ 3.68:1, `/50` ≈ 2.97:1 로 상당수가 AA 아래다. 이건 `globals.css`
 * 파서가 아니라 **소스 스캐너**가 할 일이라 별도 이슈다 (#1433). 이 파일은 **토큰 수준**
 * 짝만 보증한다 — 토큰이 회귀하지 않는다는 보증이지, 화면 전체가 AA 라는 보증이 아니다.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const CSS = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf-8");

/* ── 색 계산 ──────────────────────────────────────────────── */

function rgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}

/** sRGB 상대 휘도 (WCAG 2.x). */
function luminance(hex: string): number {
  const lin = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const [r, g, b] = rgb(hex).map((c) => lin(c / 255));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG 대비비. 순서 무관. */
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/**
 * `bg-token/NN` 의 실제 배경색. 브라우저는 감마 인코딩된 sRGB 값 위에서 합성하므로
 * 0-255 값의 선형 보간이 맞다 (휘도 공간 보간이 아니다).
 */
function over(fg: string, alpha: number, bg: string): string {
  const [f, b] = [rgb(fg), rgb(bg)];
  const mix = f.map((c, i) => Math.round(c * alpha + b[i] * (1 - alpha)));
  return `#${mix.map((c) => c.toString(16).padStart(2, "0")).join("")}`.toUpperCase();
}

/* ── CSS 파싱 ─────────────────────────────────────────────── */

/**
 * 중괄호 깊이를 세어 모든 룰 블록을 뽑는다. `@layer` 안이나 들여쓴 셀렉터도 잡기 위해서다 —
 * codex R2: 정규식판은 **들여쓰기 없는 정확히 `.dark`** 만 인식해서, `html.dark` 나 `@layer`
 * 안의 두 번째 블록이 캐스케이드를 이기면서도 카운트를 빠져나갔다.
 */
function ruleBlocks(css: string): Array<{ selector: string; body: string }> {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, " "); // 주석 안 중괄호가 스캐너를 속이지 않도록
  const out: Array<{ selector: string; body: string }> = [];
  const stack: Array<{ selector: string; start: number }> = [];
  let cut = 0;
  for (let i = 0; i < clean.length; i++) {
    if (clean[i] === "{") {
      // 셀렉터는 직전 `;` 이후부터다. `@custom-variant dark (&:is(.dark *));` 처럼 세미콜론으로
      // 끝나는 at-rule 문이 앞에 있으면, 그걸 포함한 채 자르면 뒤따르는 `@theme inline` 블록이
      // `.dark` 셀렉터로 오인된다 (실제로 이 레포 globals.css 1행이 그렇다).
      const raw = clean.slice(cut, i);
      stack.push({ selector: raw.slice(raw.lastIndexOf(";") + 1).trim(), start: i + 1 });
      cut = i + 1;
    } else if (clean[i] === "}") {
      const frame = stack.pop();
      if (frame) out.push({ selector: frame.selector, body: clean.slice(frame.start, i) });
      cut = i + 1;
    }
  }
  return out;
}

/**
 * `.dark` 클래스를 쓰는 셀렉터 중 실제로 토큰을 선언하는 블록. 정확히 하나여야 한다.
 *
 * `\b` 를 쓰면 안 된다 (codex R3): `\b` 는 `k` 와 `-` 사이에서도 성립해 **`.dark-mode` 가
 * 매치된다** — 진짜 블록을 `.dark-mode` 로 개명하면 앱의 `.dark` 테마는 토큰을 잃는데
 * 게이트는 초록이었다. 반대로 접두사를 `[a-z]*` 로 묶으면 `:is(.dark)` 와 `.foo.dark` 를
 * 놓친다. 클래스 이름 경계로 직접 잘라야 둘 다 맞는다.
 */
const DARK_SELECTOR = /\.dark(?![\w-])/;

function darkTokens(): Record<string, string> {
  const declaring = ruleBlocks(CSS).filter(
    (b) => DARK_SELECTOR.test(b.selector) && /--[a-z0-9-]+\s*:/.test(b.body),
  );
  if (declaring.length === 0) {
    throw new Error("globals.css 에서 토큰을 선언하는 `.dark` 블록을 못 찾았다 — 검사 대상이 사라졌다");
  }
  if (declaring.length > 1) {
    throw new Error(
      `토큰을 선언하는 \`.dark\` 블록이 ${declaring.length}개다 (${declaring
        .map((b) => b.selector)
        .join(" / ")}) — 캐스케이드상 마지막이 이기므로 하나만 재는 이 게이트는 거짓이 된다`,
    );
  }
  const found = [...declaring[0].body.matchAll(/--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})\b/g)];
  if (found.length === 0) throw new Error(".dark 블록에서 hex 토큰을 0개 파싱했다 — 정규식이 눈이 멀었다");
  return Object.fromEntries(found.map((m) => [m[1], m[2].toUpperCase()]));
}

const T = darkTokens();

function token(name: string): string {
  const v = T[name];
  if (!v) throw new Error(`--${name} 가 .dark 블록에 없다 (또는 hex 가 아니다)`);
  return v;
}

/* ── 실제 렌더링되는 짝 ───────────────────────────────────── */

interface Pair {
  /** 사람이 읽는 이름. allowlist 키이기도 하다. */
  name: string;
  fg: string;
  /** 배경. 알파 합성이면 `{ token, alpha, on }`. */
  bg: string | { token: string; alpha: number; on: string };
  /** 근거 — 이 조합이 실제로 화면에 존재한다는 증거. 없으면 넣지 않는다. */
  why: string;
}

const TEXT_PAIRS: Pair[] = [
  { name: "foreground/background", fg: "foreground", bg: "background", why: "text-foreground, 페이지 표면" },
  { name: "foreground/card", fg: "foreground", bg: "card", why: "text-foreground × bg-card" },
  { name: "foreground/muted", fg: "foreground", bg: "muted", why: "regime-chart.tsx 칩: bg-muted text-foreground" },
  { name: "foreground/sidebar", fg: "foreground", bg: "sidebar", why: "bg-sidebar, 텍스트는 --foreground 상속" },
  { name: "card-foreground/card", fg: "card-foreground", bg: "card", why: "text-card-foreground" },
  { name: "muted-foreground/card", fg: "muted-foreground", bg: "card", why: "text-muted-foreground × bg-card" },
  { name: "muted-foreground/muted", fg: "muted-foreground", bg: "muted", why: "strategy/page.tsx: bg-muted text-muted-foreground" },
  { name: "muted-foreground/popover", fg: "muted-foreground", bg: "popover", why: "차트 툴팁 축·범례 — CHART_MUTED on CHART_TOOLTIP_BG" },
  { name: "popover-foreground/popover", fg: "popover-foreground", bg: "popover", why: "차트 툴팁 본문 — chart-theme.ts CHART_TOOLTIP_ITEM = var(--popover-foreground)" },
  { name: "primary/card", fg: "primary", bg: "card", why: "text-primary 링크 (engine/page.tsx, decisions/page.tsx)" },
  { name: "primary/background", fg: "primary", bg: "background", why: "동일 링크가 카드 밖 표면에도 놓인다" },
  { name: "primary-foreground/primary", fg: "primary-foreground", bg: "primary", why: "button.tsx default: bg-primary text-primary-foreground" },
  { name: "secondary-foreground/secondary", fg: "secondary-foreground", bg: "secondary", why: "button.tsx secondary" },
  // ── 알파 합성. 원색 배경으로 재면 실제보다 후하게 나온다 (codex R2). ──
  { name: "primary/primary10-on-sidebar", fg: "primary", bg: { token: "primary", alpha: 0.1, on: "sidebar" }, why: "sidebar.tsx 활성 항목: text-primary bg-primary/10" },
  { name: "destructive/destructive20-on-card", fg: "destructive", bg: { token: "destructive", alpha: 0.2, on: "card" }, why: "button.tsx destructive (dark:bg-destructive/20)" },
  { name: "destructive/destructive30-on-card", fg: "destructive", bg: { token: "destructive", alpha: 0.3, on: "card" }, why: "button.tsx destructive hover (dark:hover:bg-destructive/30)" },
];

function resolve(bg: Pair["bg"]): string {
  return typeof bg === "string" ? token(bg) : over(token(bg.token), bg.alpha, token(bg.on));
}

/**
 * **AA 미달로 기록된 조합** — 숨기지 않고 값과 후속 이슈(#1432)를 함께 적는다.
 *
 * 양방향 검사다 (`invariants.md` 의 `ALLOWED` 관례와 동일): 대비가 나빠져도 FAIL 이고
 * **고쳐져도 FAIL** 한다. 고친 사람이 이 줄을 지우게 만들어서 낡은 면제가 안 남는다.
 * 허용 오차 0.02 는 8비트 반올림 잡음용이라, 그보다 작은 열화는 통과한다.
 *
 * 셋의 성격이 다르다 — 뭉뚱그리면 과장이 된다 (codex R3):
 * - sidebar 항목은 **실제로 렌더된다** (`pathname === item.href` 활성 상태).
 * - destructive 둘은 `button.tsx` 의 variant **정의**이고 `variant="destructive"` 소비자는
 *   현재 **0** 이다. 지금 화면에 있는 결함이 아니라, 처음 쓰는 순간 AA 미달로 들어오는
 *   장전된 결함이다. 그래서 지우지 않고 남긴다.
 */
const KNOWN_BELOW_AA: Record<string, number> = {
  "primary/primary10-on-sidebar": 4.4,
  "destructive/destructive20-on-card": 3.87,
  "destructive/destructive30-on-card": 3.28,
};

/**
 * **가드레일 기준선.** `globals.css` 주석의 "이 대비를 낮추는 무드 맞춤 변경 금지" 를
 * 기계로 옮긴 것이다.
 *
 * 왜 필요한가 (codex R4): AA 바닥만 검사하면 `--foreground` 를 15.11:1 → 6:1 로 낮추고
 * `@contrast` 줄을 **정직하게** 갱신해도 전부 통과한다. 숫자는 참이 되고 가드레일은 깨진다.
 * 바닥(4.5 / 3.0)은 접근성 최소치지 이 레포가 약속한 값이 아니다.
 *
 * `KNOWN_BELOW_AA` 와 달리 **단방향**이다. 저쪽은 "고쳐지면 항목을 지워라" 라서 양방향이
 * 맞지만, 이쪽 약속은 "낮추지 마라" 이므로 개선은 그냥 통과해야 한다. 낮추려면 이 줄을
 * 고치는 명시적 행위가 필요하고, 그게 리뷰에서 보이는 것이 이 맵의 목적이다.
 */
const GUARDRAIL_MIN: Record<string, number> = {
  "foreground/background": 17.23,
  "foreground/card": 15.11,
  "foreground/muted": 13.47,
  "foreground/sidebar": 15.11,
  "card-foreground/card": 15.11,
  "muted-foreground/card": 7.66,
  "muted-foreground/muted": 6.83,
  "muted-foreground/popover": 5.92,
  "popover-foreground/popover": 11.68,
  "primary/card": 5.06,
  "primary/background": 5.76,
  "primary-foreground/primary": 5.76,
  "secondary-foreground/secondary": 13.47,
  "primary/primary10-on-sidebar": 4.4,
  "destructive/destructive20-on-card": 3.87,
  "destructive/destructive30-on-card": 3.28,
  ring: 5.06,
  "chart-1": 5.06,
  "chart-2": 5.92,
  "chart-3": 6.79,
  "chart-4": 8.88,
  "chart-5": 4.8,
};

/**
 * 그래픽·UI 요소. WCAG 1.4.11 non-text = 3:1. 배경·카드 양쪽에 놓이므로 빡빡한 쪽으로 본다.
 * `--primary`/`--destructive` 는 텍스트로도 쓰여 위에서 더 센 기준으로 재므로 여기 없다.
 * `--sidebar-primary`/`--sidebar-ring`/`--accent-foreground` 도 없다 — 소비자 0.
 */
const GRAPHIC = ["ring", "chart-1", "chart-2", "chart-3", "chart-4", "chart-5"];

/** CSS 주석의 `@contrast fg/bg ratio` 줄 — 이게 이 테스트가 검증하는 **주장**이다. */
function parseClaims(): Array<[fg: string, bg: string, claimed: number]> {
  const claims = [...CSS.matchAll(/@contrast\s+([a-z0-9-]+)\/([a-z0-9-]+)\s+([\d.]+)/g)].map(
    (m) => [m[1], m[2], Number(m[3])] as [string, string, number],
  );
  if (claims.length === 0) {
    throw new Error("globals.css 주석에서 `@contrast` 주장을 0건 파싱했다 — 주장이 지워졌거나 형식이 바뀌었다");
  }
  return claims;
}

/* ── 검사 ─────────────────────────────────────────────────── */

describe("다크 토큰 대비 (#1431)", () => {
  it("파싱이 실제로 토큰을 잡았다", () => {
    expect(Object.keys(T).length).toBeGreaterThan(15);
    expect(T.background).toMatch(/^#[0-9A-F]{6}$/);
    expect(T.card).toMatch(/^#[0-9A-F]{6}$/);
  });

  it.each(TEXT_PAIRS.filter((p) => !(p.name in KNOWN_BELOW_AA)).map((p) => [p.name, p] as const))(
    "%s 는 AA 4.5:1 이상",
    (_name, p) => {
      const bg = resolve(p.bg);
      const ratio = contrast(token(p.fg), bg);
      expect(ratio, `${p.name} (${token(p.fg)} on ${bg}) = ${ratio.toFixed(2)}:1 — AA 미달 · 근거: ${p.why}`).toBeGreaterThanOrEqual(4.5);
    },
  );

  it.each(GRAPHIC)("--%s 는 background·card 양쪽에서 non-text 3:1 이상", (t) => {
    const worst = Math.min(contrast(token(t), T.background), contrast(token(t), T.card));
    expect(worst, `--${t} 최악 대비 ${worst.toFixed(2)}:1 — non-text 3:1 미달`).toBeGreaterThanOrEqual(3);
  });

  it("어떤 짝도 기준선 아래로 내려가지 않았다 — 가드레일", () => {
    // AA 바닥과 별개다. 바닥은 접근성 최소치, 이쪽은 이 레포가 약속한 값.
    const all: Array<[string, number]> = [
      ...TEXT_PAIRS.map((p) => [p.name, contrast(token(p.fg), resolve(p.bg))] as [string, number]),
      ...GRAPHIC.map(
        (t) => [t, Math.min(contrast(token(t), T.background), contrast(token(t), T.card))] as [string, number],
      ),
    ];
    for (const [name, actual] of all) {
      const floor = GUARDRAIL_MIN[name];
      expect(floor, `${name} 이 GUARDRAIL_MIN 에 없다 — 짝을 추가했으면 기준선도 기록할 것`).toBeDefined();
      expect(
        actual,
        `${name}: 기준선 ${floor}:1 → 실측 ${actual.toFixed(2)}:1 로 **낮아졌다**. 의도한 변경이면 GUARDRAIL_MIN 을 같이 고칠 것 (globals.css 가드레일 주석 참조)`,
      ).toBeGreaterThanOrEqual(floor - 0.02);
    }
  });

  it("GUARDRAIL_MIN 에 낡은 항목이 없다", () => {
    // 짝을 지우면 기준선도 지워야 한다. 안 그러면 사라진 조합을 지키는 척하는 줄이 남는다.
    const live = new Set([...TEXT_PAIRS.map((p) => p.name), ...GRAPHIC]);
    const stale = Object.keys(GUARDRAIL_MIN).filter((k) => !live.has(k));
    expect(stale, `GUARDRAIL_MIN 에 대응 짝이 없는 항목: ${stale.join(", ")}`).toEqual([]);
  });

  it("알려진 AA 미달 조합이 기록된 값 그대로다 — 나빠져도, 고쳐져도 FAIL", () => {
    // 양방향. 고친 뒤 이 줄을 안 지우면 낡은 면제가 남으므로 그것도 실패로 친다.
    for (const [name, recorded] of Object.entries(KNOWN_BELOW_AA)) {
      const pair = TEXT_PAIRS.find((p) => p.name === name);
      expect(pair, `KNOWN_BELOW_AA 의 ${name} 이 TEXT_PAIRS 에 없다 — 낡은 항목`).toBeDefined();
      const actual = contrast(token(pair!.fg), resolve(pair!.bg));
      expect(
        Math.abs(actual - recorded),
        `${name}: 기록 ${recorded}:1 vs 실측 ${actual.toFixed(2)}:1 — 고쳤다면 KNOWN_BELOW_AA 에서 지울 것 (#1432)`,
      ).toBeLessThan(0.02);
      expect(actual, `${name} 이 AA 를 넘었다 — KNOWN_BELOW_AA 에서 지울 것 (#1432)`).toBeLessThan(4.5);
    }
  });

  it("주석의 @contrast 주장이 토큰 실측과 일치한다", () => {
    for (const [fg, bg, claimed] of parseClaims()) {
      const actual = contrast(token(fg), token(bg));
      expect(
        Math.abs(actual - claimed),
        `@contrast ${fg}/${bg}: 주석 ${claimed}:1 vs 실측 ${actual.toFixed(2)}:1`,
      ).toBeLessThan(0.01);
    }
  });

  it("주석이 주장해야 할 짝을 빠짐없이 주장하고 있다", () => {
    // 위 테스트는 "주장이 맞나" 만 본다 — 주장을 지우면 통과한다. 6개 중 4개를 지워도
    // 통과하던 게 codex R3 지적이라, 목록 전체를 요구한다.
    const REQUIRED = [
      "foreground/card",
      "muted-foreground/card",
      "muted-foreground/popover",
      "primary/background",
      "primary/card",
      "primary-foreground/primary",
    ];
    const pairs = parseClaims().map(([f, b]) => `${f}/${b}`);
    expect(pairs.sort()).toEqual([...REQUIRED].sort());
  });

  it("Blueprint 라이트 인텐트를 이 배경에 얹으면 AA 미달이다 (기록된 실측)", () => {
    // ⚠️ 이건 **게이트가 아니라 기록**이다 (codex R3): blueprint 는 이 레포의 의존성이 아니라
    // 값이 하드코딩돼 있고, 따라서 설치본이나 앱 동작과 연결돼 있지 않다. 남기는 이유는
    // #1431 의 동기를 잊지 않기 위해서다 — @blueprintjs/core 6.18.0 의 tokens-dark.css 는
    // `--bp-intent-*` 를 **0개** 정의한다(라이트 파일은 25개). 다크에서 인텐트를 쓰면 라이트
    // 값을 물려받고, 이 배경(#111418)에서 20개 중 14개가 AA 미달이다. 아래 4개는 그 확인용
    // 표본이다. 실제 채택 시에는 그때 설치본으로 다시 재야 한다.
    const BP_LIGHT_INTENT_REST = { primary: "#2d72d2", success: "#238551", warning: "#c87619", danger: "#cd4246" };
    const failing = Object.entries(BP_LIGHT_INTENT_REST)
      .filter(([, hex]) => contrast(hex, T.background) < 4.5)
      .map(([name]) => name);
    expect(failing).toEqual(["primary", "success", "danger"]);
  });
});

describe("차트 색 리터럴 드리프트 (#1431)", () => {
  // codex R1: `composition-bar.tsx` 가 --chart-* 를 hex 리터럴로 복사해 두어, 토큰을 바꿔도
  // 그 차트는 안 바뀌고 리터럴을 바꾸면 위 게이트를 우회한다. 두 벌을 묶는다.
  it("CHART_COLORS 가 --chart-1..5 토큰과 같다", async () => {
    const { CHART_COLORS } = await import("@/components/dashboard/composition-bar");
    expect(CHART_COLORS.map((c) => c.toUpperCase())).toEqual([1, 2, 3, 4, 5].map((i) => token(`chart-${i}`)));
  });
});
