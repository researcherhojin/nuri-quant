/**
 * 호출부 불투명도 수식어가 텍스트를 AA 아래로 끌어내리지 않는지 (#1433).
 *
 * `#1431` 의 게이트는 `globals.css` 를 파싱한다 — **토큰 수준**이다. 이 결함은 CSS 가 아니라
 * `.tsx` 호출부에 있었다: 토큰은 전부 AA 를 넘는데 `text-muted-foreground/70` 같은 수식어가
 * 실효 대비를 4.47 로 떨어뜨린다. 파싱 대상이 다르므로 저쪽 게이트로는 원리상 안 잡힌다.
 *
 * ## 왜 알파로는 3계층을 못 만드나 (실측)
 *
 * `--muted-foreground` 는 카드 위 7.66:1 이라 여유가 크지 않다:
 *
 * ```
 *   /70 → 4.47   /60 → 3.68   /50 → 2.97   /40 → 2.37   /30 → 1.90
 * ```
 *
 * AA(4.5)를 넘는 첫 단계는 `/85`(5.93)인데 그건 이미 원색과 구분이 안 된다. 즉 **"더 옅게"와
 * "AA" 를 알파로 동시에 만족시킬 수 없다.** 그래서 계층을 토큰(`--faint`, Blueprint GRAY3)으로
 * 옮겼고 — 그러면 #1431 게이트가 자동으로 덮는다 — 이 파일은 알파가 다시 새는 것을 막는다.
 *
 * ## 표면 추론의 한계 (숨기지 않는다)
 *
 * 같은 유틸리티도 `bg-card` 안이냐 페이지 배경 위냐에 따라 실효 대비가 다르다. 정적 스캔으로
 * 요소의 실제 배경을 알 수는 없으므로 **가장 흔한 표면(`--card`)으로 잰다**. 이 근사가 놓치는
 * 축이 하나 있다: `--popover`(#2F343C)는 카드보다 밝아 같은 색이 더 낮게 나온다. 그래서
 * `--faint` 는 popover 위에서 4.35 로 미달이고, 아래 별도 테스트가 툴팁·팝오버 컴포넌트에서
 * `text-faint` 사용을 막는다.
 */
import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC = join(process.cwd(), "src");
const CSS = readFileSync(join(SRC, "app/globals.css"), "utf8");

/** `.dark` 블록의 토큰 값 — #1431 과 같은 정본(주석 복사본이 아니라 CSS 자체)을 읽는다. */
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
/** fg 를 alpha 로 bg 위에 합성 — 알파를 무시하면 실제보다 후하게 나온다 (#1431 codex R2). */
function over(fg: string, alpha: number, bg: string): string {
  const px = (h: string, i: number) => parseInt(h.slice(i, i + 2), 16);
  const ch = (i: number) => Math.round(px(fg, i) * alpha + px(bg, i) * (1 - alpha));
  return "#" + [1, 3, 5].map((i) => ch(i).toString(16).padStart(2, "0")).join("");
}

function walk(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(dir)) {
    const p = join(dir, e);
    if (statSync(p).isDirectory()) {
      if (e !== "__tests__") walk(p, out);
    } else if (/\.tsx?$/.test(e) && !/\.test\./.test(e)) {
      out.push(p);
    }
  }
  return out;
}

const FILES = walk(SRC);
const TEXT_ALPHA = /\btext-(foreground|muted-foreground|card-foreground|popover-foreground|faint)\/(\d{1,3})\b/g;

describe("호출부 불투명도 수식어 (#1433)", () => {
  it("텍스트 토큰에 붙은 알파가 AA 아래로 내려가지 않는다", () => {
    const card = darkToken("card");
    const offenders: string[] = [];
    let scanned = 0;
    for (const file of FILES) {
      const text = readFileSync(file, "utf8");
      for (const m of text.matchAll(TEXT_ALPHA)) {
        scanned++;
        const eff = ratio(over(darkToken(m[1]), Number(m[2]) / 100, card), card);
        if (eff < 4.5) {
          offenders.push(`${file.slice(SRC.length + 1)}  ${m[0]}  ${eff.toFixed(2)}:1`);
        }
      }
    }
    expect(offenders, "카드 위 실효 대비가 AA 미만이다 — 알파 대신 토큰으로 계층을 표현할 것 (--faint)").toEqual([]);
    // 카나리아: 스캔이 파일을 못 찾으면 위 단언이 공허하다 (#910)
    expect(FILES.length).toBeGreaterThan(50);
  });

  it("카나리아 — 미달 조합을 실제로 집어낸다", () => {
    // 스캐너가 정규식·합성 어느 쪽에서든 눈이 멀면 위 테스트가 0 개를 통과시킨다.
    const card = darkToken("card");
    expect(ratio(over(darkToken("muted-foreground"), 0.7, card), card)).toBeLessThan(4.5);
    expect(ratio(over(darkToken("muted-foreground"), 0.9, card), card)).toBeGreaterThanOrEqual(4.5);
    expect([...'<p className="text-muted-foreground/70">'.matchAll(TEXT_ALPHA)]).toHaveLength(1);
  });

  it("--faint 는 popover 표면에서 미달이므로 툴팁·팝오버에서 쓰지 않는다", () => {
    // 표면 추론의 한계를 보완하는 표적 검사. `--faint` 는 popover 위 4.35:1 이다.
    const popover = darkToken("popover");
    expect(ratio(darkToken("faint"), popover)).toBeLessThan(4.5); // 전제가 유지되는지

    // Recharts 툴팁은 `contentStyle` + `CHART_TOOLTIP_*` 상수로 그려진다 — Tailwind 클래스가
    // 닿지 않으므로 `<Tooltip>` 을 쓰는 파일을 통째로 잡으면 차트 헤더·범례(카드 표면)까지
    // 오탐한다. 실제로 첫 판이 그렇게 두 파일을 잘못 집었다. className 이 실제로 적용되는
    // popover 표면은 shadcn `PopoverContent` 와 `bg-popover` 를 직접 쓰는 요소뿐이다.
    const POPOVER_SURFACE = /<PopoverContent\b|\bbg-popover\b/;
    const offenders = FILES.filter((f) => {
      const t = readFileSync(f, "utf8");
      return /\btext-faint\b/.test(t) && POPOVER_SURFACE.test(t);
    });
    expect(offenders.map((f) => f.slice(SRC.length + 1)),
      "popover 표면 컴포넌트가 --faint 를 쓴다 — 거기선 4.35:1 로 AA 미달이다").toEqual([]);
  });
});
