import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import type { ReactNode } from "react";
import { MarketContext, type MacroEvent, type SystemHealth } from "@/components/ui/market-context";

// next/link → 단순 anchor 로 렌더 (네트워크/라우터 불필요)
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

afterEach(cleanup);

// 24h 이내 ISO timestamp 생성 헬퍼 (pinning/sparkline 결정론용)
function recentIso(minutesAgo: number): string {
  return new Date(Date.now() - minutesAgo * 60 * 1000).toISOString();
}

describe("MarketContext — statement coverage", () => {
  // L39: healthColor 의 high 분기 (value >= thresholds[1]) → text-emerald-400
  // macro.score=80 이면 [40,60] 임계 중 상단(60) 초과 → emerald 색
  it("macro 카드: 높은 score 는 emerald 색 (healthColor high branch)", () => {
    const health: Partial<SystemHealth> = {
      macro: { score: 80, interpretation: "risk-on" },
    };
    render(<MarketContext events={[]} health={health} />);

    const value = screen.getByText("80");
    expect(value.className).toContain("text-emerald-400");
    expect(screen.getByText("risk-on")).toBeInTheDocument();
  });

  // L40: healthColor 의 mid 분기 (thresholds[0] <= value < thresholds[1]) → text-amber-400
  it("macro 카드: 중간 score 는 amber 색 (healthColor mid branch)", () => {
    const health: Partial<SystemHealth> = {
      macro: { score: 50, interpretation: "neutral" },
    };
    render(<MarketContext events={[]} health={health} />);

    const value = screen.getByText("50");
    expect(value.className).toContain("text-amber-400");
  });

  // L41: healthColor 의 low 분기 (value < thresholds[0]) → text-red-400
  it("macro 카드: 낮은 score 는 red 색 (healthColor low branch)", () => {
    const health: Partial<SystemHealth> = {
      macro: { score: 10, interpretation: "risk-off" },
    };
    render(<MarketContext events={[]} health={health} />);

    const value = screen.getByText("10");
    expect(value.className).toContain("text-red-400");
  });

  // L49: regimeStripe 의 default 분기 — trend 가 알려진 값(bull/bear/sideways)이
  // 아니거나 undefined 일 때 border-l-zinc-700/60. events 가 있어야 stripe div 렌더됨.
  it("이벤트 카드 stripe: 알 수 없는 regime trend 는 zinc 기본 stripe (regimeStripe default branch)", () => {
    const events: MacroEvent[] = [
      {
        category: "sector_rally",
        headline: "Broad market advance across sectors",
        sentiment: 0.4,
        confidence: 0.5,
        published_at: recentIso(60),
        source: "wire",
      },
    ];
    // regime.trend 미지정 → regimeStripe(undefined) → default zinc
    const { container } = render(<MarketContext events={events} health={{}} />);

    const stripe = container.querySelector(".border-l-zinc-700\\/60");
    expect(stripe).not.toBeNull();
  });

  // L46-48: regimeStripe 의 알려진 trend 분기들 (bull → emerald stripe)
  it("이벤트 카드 stripe: bull regime 은 emerald stripe (regimeStripe bull branch)", () => {
    const events: MacroEvent[] = [
      {
        category: "sector_rally",
        headline: "Tech leadership broadens",
        sentiment: 0.6,
        confidence: 0.5,
        published_at: recentIso(120),
        source: "wire",
      },
    ];
    const health: Partial<SystemHealth> = {
      regime: { regime: "expansion", trend: "bull", confidence: 75 },
    };
    const { container } = render(<MarketContext events={events} health={health} />);

    expect(container.querySelector(".border-l-emerald-500\\/60")).not.toBeNull();
  });

  // L82: sparklinePath 의 early return — events.length === 0 → null.
  // events 가 비면 이벤트 카드 자체가 렌더 안 됨 (events.length > 0 가드).
  // 따라서 sparklinePath 의 L82 는 함수가 호출되는 events>0 경로에서는 도달 불가.
  // 직접 도달시키려면 events 가 1개 이상이어야 카드가 뜨고 sparklinePath 가 불리는데,
  // 그 경우 length===0 분기는 절대 진입하지 않는다.
  // → component 경로만으로는 L82 미도달. 아래 L86 테스트가 sparklinePath 본문을 실행하고,
  //   L82 는 component 에서 unreachable 하므로 source 에 v8-ignore 처리한다. (note 참조)

  // L86: sparklinePath 내부 `if (!day) continue;` — published_at 이 빈 문자열인 이벤트.
  // 빈 published_at → slice(0,10) === "" → falsy → continue. 유효 이벤트 2일치 + 빈 이벤트 혼합.
  it("sparkline: published_at 누락 이벤트는 건너뛴다 (sparklinePath !day continue branch)", () => {
    const events: MacroEvent[] = [
      {
        category: "fed_dovish",
        headline: "Day one dovish remarks from policymakers",
        sentiment: 0.5,
        confidence: 0.9,
        published_at: recentIso(60),
        source: "wire",
      },
      {
        category: "fed_dovish",
        headline: "Day two follow-through commentary",
        sentiment: 0.7,
        confidence: 0.9,
        published_at: recentIso(60 + 24 * 60),
        source: "wire",
      },
      {
        // published_at 빈 문자열 → L86 continue 트리거
        category: "earnings_beat",
        headline: "Undated headline that should be skipped in sparkline bucketing",
        sentiment: -0.9,
        confidence: 0.4,
        published_at: "",
        source: "wire",
      },
    ];
    render(<MarketContext events={events} health={{}} />);

    // 2개의 유효 일자 버킷 → days.length >= 2 → sparkline svg 렌더됨
    expect(screen.getByLabelText("7d sentiment trend")).toBeInTheDocument();
  });

  // 보강: pinning ON 경로 (24h 내 high-conf critical category) — ATTENTION 배지/📌
  it("pinned attention: 24h 내 고신뢰 critical 이벤트면 ATTENTION 표기", () => {
    const events: MacroEvent[] = [
      {
        category: "geopolitical_escalation",
        headline: "High-confidence escalation within last day",
        sentiment: -0.8,
        confidence: 0.92,
        published_at: recentIso(30),
        source: "wire",
      },
    ];
    render(<MarketContext events={events} health={{}} />);

    expect(screen.getByText("ATTENTION")).toBeInTheDocument();
    expect(screen.getByLabelText("pinned attention")).toBeInTheDocument();
  });

  // 보강: regime-shift 배너 (confidence < 60 && > 0)
  it("regime-shift 배너: 낮은 confidence 면 전환 신호 노출", () => {
    const health: Partial<SystemHealth> = {
      regime: { regime: "transition", trend: "sideways", confidence: 45 },
    };
    render(<MarketContext events={[]} health={health} />);

    expect(screen.getByText("Regime 전환 신호")).toBeInTheDocument();
  });
});
