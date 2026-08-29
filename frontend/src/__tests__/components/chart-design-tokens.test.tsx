/**
 * #1275 — 차트 레이어가 다크 토큰 시스템 안에 있는지.
 *
 * recharts 는 grid stroke · tooltip border · tick fill 을 SVG 속성/인라인 스타일로 받아서
 * Tailwind 클래스가 안 먹는다. 그래서 zinc hex 를 직접 박아 뒀는데(실측 63곳 / 9파일),
 * 그러면 차트만 토큰 시스템 밖에 남는다. 게다가 이 앱의 다크 팔레트는 **zinc 가 아니다** —
 * `--background: #111418` · `--popover: #2F343C` · `--muted-foreground: #ABB3BF` 라서
 * 차트는 테마를 못 따라올 뿐 아니라 지금도 앱 팔레트와 어긋나 있었다.
 *
 * #1253 이 `pipeline/page.tsx` 에서 쓴 2겹 잠금을 그대로 따른다:
 *   - **동작** — 실제로 recharts 에 넘어가는 값이 `var(--...)` 인가 (recharts 를 가로채
 *     받은 props 를 그대로 본다)
 *   - **구조** — 소스에 중립 hex 리터럴이 남지 않았는가 (동작 잠금은 한 차트만 보므로
 *     나머지 8개에 새 하드코딩이 생기면 놓친다)
 *
 * ⚠️ #1253 과 달리 **"hex 전면 금지" 가 아니다.** 차트에는 의미를 담은 계열색이
 * 정당하게 있다(`#10b981` pass, violation 색 등). 스윕이 그것까지 잡으면 멀쩡한 색을
 * 지우게 되므로 **zinc 계열 중립색만** 겨눈다 — 카나리아가 그 경계를 양쪽으로 확인한다.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CertificationPoint, GateCondition } from "@/components/ui/siege-timeline-chart";

// recharts 를 가로채 실제로 넘어온 props 를 노출시킨다.
const captured: Record<string, Record<string, unknown>> = {};
type StubProps = Record<string, unknown> & { children?: React.ReactNode };

vi.mock("recharts", () => {
  const cap = (name: string, { children, ...props }: StubProps) => {
    captured[name] = props;
    return <div data-testid={`rc-${name}`}>{children as React.ReactNode}</div>;
  };
  // 명명 함수 선언이다 — 팩토리로 만들면 displayName 을 붙여야 하는데 그 대입이
  // `react-hooks/immutability` 에 걸린다.
  function ResponsiveContainer({ children }: StubProps) {
    return <div>{children as React.ReactNode}</div>;
  }
  function BarChart({ children }: StubProps) {
    return <div>{children as React.ReactNode}</div>;
  }
  function CartesianGrid(p: StubProps) {
    return cap("CartesianGrid", p);
  }
  function XAxis(p: StubProps) {
    return cap("XAxis", p);
  }
  function YAxis(p: StubProps) {
    return cap("YAxis", p);
  }
  function Tooltip(p: StubProps) {
    return cap("Tooltip", p);
  }
  function Legend(p: StubProps) {
    return cap("Legend", p);
  }
  function Bar(p: StubProps) {
    return cap("Bar", p);
  }
  return { ResponsiveContainer, BarChart, CartesianGrid, XAxis, YAxis, Tooltip, Legend, Bar };
});

/** 차트 크롬에 쓰이던 zinc 계열 중립색. 의미를 담은 계열색은 **일부러** 제외한다. */
const NEUTRAL_HEX = /#(?:fafafa|f4f4f5|e4e4e7|d4d4d8|a1a1aa|71717a|52525b|3f3f46|27272a|18181b|09090b)\b/gi;

/** 같은 이탈의 Tailwind 클래스 문법. hex 스윕만으로는 절반만 잡힌다. */
const ZINC_CLASS = /\b(?:bg|text|border|fill|stroke|from|to|via)-zinc-\d{2,3}\b/g;

/**
 * 선언된 계열 팔레트를 걷어낸다 (#1301). 예외를 allowlist 가 아니라 **구조**로 두기 위해서다 —
 * 팔레트 밖에 색이 생기면 그 순간 스윕에 걸린다.
 */
function stripSeriesPalette(src: string): string {
  return (
    src
      // 주석은 선언이 아니다 — 이 파일의 JSDoc 이 측정값으로 hex 를 **인용**한다.
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "")
      .replace(/export const [A-Z_]+ = \[[\s\S]*?\] as const;/g, "")
      .replace(/export const OTHER_COLOR = "[^"]*";/g, "")
  );
}

const CHART_FILES = [
  "src/components/ui/gate-failure-chart.tsx",
  "src/components/ui/equity-curve-chart.tsx",
  "src/components/ui/price-chart.tsx",
  "src/components/ui/siege-timeline-chart.tsx",
  "src/components/evidence/fear-greed-chart.tsx",
  "src/components/evidence/signal-performance-chart.tsx",
  "src/components/evidence/regime-chart.tsx",
  "src/components/evidence/sell-evidence-chart.tsx",
  "src/components/evidence/portfolio-treemap.tsx",
];

function makePoint(): CertificationPoint {
  const condition: GateCondition = {
    id: "sector_limit",
    description: "",
    passed: false,
    detail: "",
    severity: "error",
  };
  return {
    id: 1,
    timestamp: "2026-04-20T10:00:00+09:00",
    certified: false,
    score: 55,
    total_conditions: 10,
    passed: 7,
    failed: 1,
    warnings: 0,
    regime: null,
    portfolio_hash: "h",
    caller: "cli",
    conditions: [condition],
  };
}

describe("차트 레이어는 다크 토큰을 쓴다 (#1275)", () => {
  it("grid · 축 · 툴팁 · 범례가 CSS 변수로 넘어간다", async () => {
    const { GateFailureChart } = await import("@/components/ui/gate-failure-chart");
    render(<GateFailureChart items={[makePoint()]} />);

    const isVar = (v: unknown) => expect(String(v)).toMatch(/var\(--/);

    isVar(captured.CartesianGrid?.stroke);
    isVar((captured.XAxis?.tick as { fill?: string })?.fill);
    isVar((captured.YAxis?.tick as { fill?: string })?.fill);

    const content = captured.Tooltip?.contentStyle as { backgroundColor?: string; border?: string };
    isVar(content?.backgroundColor);
    isVar(content?.border);
    isVar((captured.Tooltip?.labelStyle as { color?: string })?.color);
    isVar((captured.Tooltip?.itemStyle as { color?: string })?.color);
    isVar((captured.Legend?.wrapperStyle as { color?: string })?.color);
  });

  it("차트 소스에 중립 hex 리터럴이 남아 있지 않다", () => {
    const offenders: string[] = [];
    for (const rel of CHART_FILES) {
      const found = readFileSync(join(process.cwd(), rel), "utf8").match(NEUTRAL_HEX) ?? [];
      if (found.length) offenders.push(`${rel}: ${found.join(", ")}`);
    }
    expect(offenders, `중립 hex 잔존:\n${offenders.join("\n")}`).toHaveLength(0);
  });

  it("차트 소스에 zinc 유틸리티 클래스도 남아 있지 않다", () => {
    // hex 만 잡으면 절반짜리다 — 같은 이탈이 Tailwind 클래스 문법으로도 있었다(실측 8곳).
    // 특히 범례 스와치(`bg-zinc-400`)는 이제 `var(--muted-foreground)` 로 그려지는 계열선
    // 바로 옆에 있어서, 안 고치면 **범례가 자기 계열선과 어긋난다.**
    const offenders: string[] = [];
    for (const rel of CHART_FILES) {
      const found = readFileSync(join(process.cwd(), rel), "utf8").match(ZINC_CLASS) ?? [];
      if (found.length) offenders.push(`${rel}: ${found.join(", ")}`);
    }
    expect(offenders, `zinc 클래스 잔존:\n${offenders.join("\n")}`).toHaveLength(0);
  });

  it("holdings-summary 도 스윕이 본다 — 선언된 계열 팔레트만 예외 (#1301)", () => {
    // #1275 는 이 파일을 범위 밖에 뒀고, 그래서 여기 색값은 **어떤 게이트도 안 봤다**.
    // 팔레트는 의미를 담은 계열색이라 정당하지만(측정 근거는 `holdings-summary-palette.test.ts`),
    // 그 **밖에** 새로 박히는 중립 hex 는 잡아야 한다.
    //
    // 예외를 allowlist 로 두지 않고 **선언을 걷어낸 나머지**를 스윕한다 — allowlist 는
    // 항목이 낡아도 조용하지만, 이 방식은 팔레트 밖에 색이 생기는 순간 걸린다.
    const src = readFileSync(join(process.cwd(), "src/lib/holdings-summary.ts"), "utf8");
    const outsidePalette = stripSeriesPalette(src);
    const found = outsidePalette.match(NEUTRAL_HEX) ?? [];
    expect(found, `팔레트 밖 중립 hex: ${found.join(", ")}`).toHaveLength(0);
  });

  it("팔레트 제거가 파일 전체를 지우지 않는다 (canary)", () => {
    // 제거가 과하면 위 검사는 빈 문자열을 스윕하며 영원히 초록이다.
    const src = readFileSync(join(process.cwd(), "src/lib/holdings-summary.ts"), "utf8");
    const stripped = stripSeriesPalette(src);
    expect(stripped).toContain("summarizeHoldings");
    expect(stripped).not.toContain("#71717a");
    // 팔레트 밖에 놓인 중립 hex 는 실제로 잡힌다.
    expect(stripSeriesPalette('const x = "#27272a";').match(NEUTRAL_HEX)).toEqual(["#27272a"]);
  });

  it("스윕이 실제로 눈이 있고, 계열색까지 잡지는 않는다 (canary)", () => {
    // 눈이 있는가 — 정규식이 조용히 아무것도 안 잡으면 위 테스트는 영원히 초록이다.
    expect('stroke="#27272a"'.match(NEUTRAL_HEX)).toEqual(["#27272a"]);
    expect('border: "1px solid #3f3f46"'.match(NEUTRAL_HEX)).toEqual(["#3f3f46"]);
    // 과하지는 않은가 — 의미를 담은 계열색은 정당하므로 잡으면 안 된다.
    expect('fill="#10b981"'.match(NEUTRAL_HEX)).toBeNull();
    expect('fill="#ef4444"'.match(NEUTRAL_HEX)).toBeNull();
    // 클래스 스윕도 같은 두 방향으로 확인한다.
    expect('className="bg-zinc-400"'.match(ZINC_CLASS)).toEqual(["bg-zinc-400"]);
    expect('className="bg-emerald-500"'.match(ZINC_CLASS)).toBeNull();
  });

  it("역할이 다른 상수는 값도 분리돼 있다", async () => {
    // 같은 `#27272a` 였지만 격자 선과 treemap 의 '위반 없음' 채움은 의미가 다르다.
    // 한 상수로 뭉개면 한쪽을 조정할 때 다른 쪽이 따라 움직인다 (#1275 이 명시한 주의).
    const theme = await import("@/lib/chart-theme");
    expect(theme.CHART_GRID_STROKE).not.toBe(theme.CHART_EMPTY_FILL);
    for (const [name, value] of Object.entries(theme)) {
      expect(String(value), `${name} 이 토큰이 아니다`).toMatch(/var\(--/);
    }
  });
});
