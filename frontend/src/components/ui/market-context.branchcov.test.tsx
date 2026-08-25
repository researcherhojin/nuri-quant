import { render } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import type { ReactNode } from "react";
import { shouldPinCard, sparklinePath, type MacroEvent, type SystemHealth } from "@/components/ui/market-context";
import { SystemHealthRail, MacroEventsCard, RegimeShiftBanner } from "@/components/dashboard/system-rail";

// U2b-2 (#1208): MarketContext 컴포넌트는 SystemHealthRail·MacroEventsCard·
// RegimeShiftBanner 로 분해됨 — 테스트는 프로덕션 조립(page.tsx)과 동일한 구성을
// 이 래퍼로 미러링해 기존 assert 를 유지한다.
function MarketContext({ events, health }: { events: MacroEvent[]; health: Partial<SystemHealth> }) {
  return (
    <>
      <RegimeShiftBanner regime={health.regime ?? {}} />
      <SystemHealthRail health={health} />
      <MacroEventsCard events={events} regimeTrend={health.regime?.trend} />
    </>
  );
}

// next/link → 단순 anchor (네트워크/라우터 불필요), 기존 coverage 테스트와 동일 패턴
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function makeEvent(overrides: Partial<MacroEvent> = {}): MacroEvent {
  return {
    category: "fed_dovish",
    category_ko: "연준 비둘기",
    headline: "Fed signals rate cut",
    sentiment: 0.5,
    confidence: 0.9,
    published_at: "2026-01-15T10:00:00Z",
    source: "reuters",
    ...overrides,
  };
}

describe("market-context branch coverage (residual arms)", () => {
  // ── shouldPinCard: undefined confidence → `(ev.confidence ?? 0)` right arm ──
  // critical category event with confidence undefined → nullish → 0 < 0.8 → false
  it("shouldPinCard treats undefined confidence as 0 (no pin)", () => {
    const ev = makeEvent({ category: "fed_hawkish", confidence: undefined });
    expect(shouldPinCard([ev])).toBe(false);
  });

  // ── sparklinePath: negative latest (drives the events-card sparkline red arm) ──
  it("sparklinePath yields a negative latest for a falling 2-day series", () => {
    const sl = sparklinePath(
      [
        makeEvent({ published_at: "2026-01-10T10:00:00Z", sentiment: 0.5 }),
        makeEvent({ published_at: "2026-01-11T10:00:00Z", sentiment: -0.5 }),
      ],
      60,
      14,
    );
    expect(sl).not.toBeNull();
    expect(sl!.latest).toBeLessThan(0);
  });

  // ── regimeStripe BEAR arm (source `if (trend === "bear")`) ──
  // events card left border = border-l-red-500/60 when regime.trend === "bear"
  it("renders bear regime stripe (red) on the events card", () => {
    const { container } = render(
      <MarketContext
        events={[makeEvent({ published_at: "2026-01-15T10:00:00Z" })]}
        health={{ regime: { regime: "risk_off", trend: "bear", confidence: 80 } }}
      />,
    );
    expect(container.querySelector(".border-l-red-500\\/60")).not.toBeNull();
  });

  // ── regime-shift banner WITHOUT a regime name (`regime.regime ?? "—"` right arm) ──
  // shifting=true (confidence 45 → conf<60 && conf>0) AND regime.regime undefined
  it("renders regime-shift banner with '—' when regime name is missing", () => {
    const { getByText } = render(
      <MarketContext
        events={[]}
        // regime.regime 의도적 누락 → `?? "—"` 우측 arm 테스트 (컴포넌트는 Partial 방어 처리)
        health={{ regime: { trend: "sideways", confidence: 45 } as SystemHealth["regime"] }}
      />,
    );
    // banner placeholder "—" is the right arm of `regime.regime ?? "—"`
    expect(getByText(/현재 —/)).toBeDefined();
  });

  // ── regime card BULL cond-expr true arm (color = text-emerald-400) ──
  it("colors the Regime card emerald when trend is bull", () => {
    const { getByText } = render(
      <MarketContext
        events={[]}
        health={{ regime: { regime: "risk_on", trend: "bull", confidence: 80 } }}
      />,
    );
    // value sliced to 6 chars uppercase → "RISK_O", carries bull emerald color
    expect(getByText("RISK_O").className).toContain("text-emerald-400");
  });

  // ── sparkline ZINC arm: latest in [-0.1, 0.1] → neither emerald nor red ──
  // day 2 has two events averaging to 0.0 → latest ≈ 0 → "stroke-zinc-500"
  it("renders a flat sparkline as zinc stroke when latest is near zero", () => {
    const events = [
      makeEvent({ published_at: "2026-01-10T10:00:00Z", sentiment: 0.5 }),
      makeEvent({ published_at: "2026-01-11T08:00:00Z", sentiment: 0.5 }),
      makeEvent({ published_at: "2026-01-11T12:00:00Z", sentiment: -0.5 }),
    ];
    const sl = sparklinePath(events, 60, 14);
    expect(sl).not.toBeNull();
    expect(Math.abs(sl!.latest)).toBeLessThanOrEqual(0.1);
    const { container } = render(<MarketContext events={events} health={{}} />);
    expect(container.querySelector(".stroke-zinc-500")).not.toBeNull();
  });

  // ── event row: unknown category `||` glyph + undefined published_at date `?? ""` ──
  // First event: unknown category → 📌 fallback; undefined published_at → date `?? ""`
  //   right arm (ev.published_at?.slice(...) is undefined → falls back to "").
  // Need ≥2 distinct days from OTHER events so the events card + rows render.
  it("renders event rows with unknown category and undefined published_at", () => {
    const events = [
      makeEvent({
        category: "totally_unknown_category",
        category_ko: undefined,
        confidence: undefined,
        published_at: undefined, // → date `?? ""` right arm (no slice result)
        sentiment: 0.5,
        headline: "first event",
      }),
      makeEvent({
        category: "earnings_miss",
        confidence: 0.95,
        published_at: "2026-01-10T10:00:00Z",
        sentiment: 0.4,
        headline: "second event",
      }),
      makeEvent({
        category: "fed_dovish",
        confidence: 0.95,
        published_at: "2026-01-11T10:00:00Z",
        sentiment: 0.4,
        headline: "third event",
      }),
    ];
    const { container, getByText } = render(
      <MarketContext events={events} health={{ regime: { trend: "sideways", confidence: 80 } as SystemHealth["regime"] }} />,
    );
    // unknown category fallback glyph
    expect(getByText("📌")).toBeDefined();
    // undefined confidence → not high-conf → non-bold "font-medium" arm present
    expect(container.querySelector(".font-medium")).not.toBeNull();
    // the undefined-published_at row still renders its headline
    expect(getByText("first event")).toBeDefined();
  });

  // ── long-headline truncation arm (`headline.length > 60` true) ──
  it("truncates a headline longer than 60 chars", () => {
    const longHeadline =
      "This is an extremely long macro headline that definitely exceeds the sixty character truncation threshold for sure";
    const events = [
      makeEvent({ published_at: "2026-01-10T10:00:00Z", headline: longHeadline }),
      makeEvent({ published_at: "2026-01-11T10:00:00Z" }),
    ];
    const { getByText } = render(<MarketContext events={events} health={{}} />);
    expect(getByText(/\.\.\.$/)).toBeDefined();
  });
});
