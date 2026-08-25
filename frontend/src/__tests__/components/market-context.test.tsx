import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { type MacroEvent, type SystemHealth } from "@/components/ui/market-context";
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

vi.mock("next/link", () => ({
  default: ({ children, href, className }: { children: React.ReactNode; href: string; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}));

const sampleEvents = [
  {
    category: "geopolitical_escalation",
    headline: "Trump threatens Strait of Hormuz blockade",
    sentiment: -0.7,
    confidence: 0.78,
    published_at: "2026-04-12T17:18:00+00:00",
    source: "reuters",
  },
  {
    category: "earnings_beat",
    headline: "TSMC Q1 Revenue Surges 35% on AI Demand",
    sentiment: 0.75,
    confidence: 0.78,
    published_at: "2026-04-11T06:10:00+00:00",
    source: "bloomberg",
  },
  {
    category: "oil_supply_shock",
    headline: "Oil jumps 7% after naval blockade",
    sentiment: -0.35,
    confidence: 0.78,
    published_at: "2026-04-12T14:18:00+00:00",
    source: "cnbc",
  },
];

const sampleHealth = {
  siege: { score: 54, certified: false, passed: 6, failed: 1, warnings: 4, total: 11 },
  regime: { regime: "recovery", trend: "sideways", confidence: 75 },
  macro: { score: 56, interpretation: "Neutral" },
  freshness: { status: "WARN", fail_count: 0, warn_count: 2 },
};

describe("MarketContext", () => {
  it("renders 4 health cards", () => {
    render(<MarketContext events={[]} health={sampleHealth} />);
    expect(screen.getByText("Certification")).toBeTruthy();
    expect(screen.getByText("레짐")).toBeTruthy();
    expect(screen.getByText("매크로")).toBeTruthy();
    expect(screen.getByText("데이터")).toBeTruthy();
  });

  it("shows SIEGE score with rejected status", () => {
    render(<MarketContext events={[]} health={sampleHealth} />);
    expect(screen.getByText("54%")).toBeTruthy();
    expect(screen.getByText("미인증")).toBeTruthy();
  });

  it("shows certified SIEGE status in green", () => {
    const certifiedHealth = { ...sampleHealth, siege: { ...sampleHealth.siege, score: 100, certified: true } };
    render(<MarketContext events={[]} health={certifiedHealth} />);
    expect(screen.getByText("100%")).toBeTruthy();
    expect(screen.getByText("인증")).toBeTruthy();
  });

  it("shows regime info", () => {
    render(<MarketContext events={[]} health={sampleHealth} />);
    expect(screen.getByText("RECOVE")).toBeTruthy(); // sliced to 6 chars
    expect(screen.getByText("sideways 75%")).toBeTruthy();
  });

  it("shows macro score", () => {
    render(<MarketContext events={[]} health={sampleHealth} />);
    expect(screen.getByText("56")).toBeTruthy();
    expect(screen.getByText("Neutral")).toBeTruthy();
  });

  it("shows freshness status", () => {
    render(<MarketContext events={[]} health={sampleHealth} />);
    expect(screen.getByText("WARN")).toBeTruthy();
  });

  it("renders macro events when present", () => {
    render(<MarketContext events={sampleEvents} health={sampleHealth} />);
    expect(screen.getByText("시장 컨텍스트")).toBeTruthy();
    expect(screen.getByText(/Hormuz blockade/)).toBeTruthy();
    expect(screen.getByText(/TSMC Q1/)).toBeTruthy();
  });

  it("shows event category emojis", () => {
    render(<MarketContext events={sampleEvents} health={sampleHealth} />);
    // geopolitical_escalation uses 🔴, earnings_beat uses 📈
    const body = document.body.textContent;
    expect(body).toContain("04-12"); // date from published_at
  });

  it("does not render events section when empty", () => {
    render(<MarketContext events={[]} health={sampleHealth} />);
    expect(screen.queryByText("시장 컨텍스트")).toBeNull();
  });

  it("health cards link to correct pages", () => {
    render(<MarketContext events={[]} health={sampleHealth} />);
    const siegeLink = screen.getByText("Certification").closest("a");
    expect(siegeLink?.getAttribute("href")).toBe("/engine");
    const regimeLink = screen.getByText("레짐").closest("a");
    expect(regimeLink?.getAttribute("href")).toBe("/strategy");
  });

  it("handles empty health gracefully", () => {
    render(<MarketContext events={[]} health={{}} />);
    expect(screen.getByText("Certification")).toBeTruthy();
    expect(screen.getByText("0%")).toBeTruthy();
  });

  it("shows FAIL freshness in red", () => {
    const failHealth = { ...sampleHealth, freshness: { status: "FAIL", fail_count: 3, warn_count: 0 } };
    render(<MarketContext events={[]} health={failHealth} />);
    expect(screen.getByText("FAIL")).toBeTruthy();
    expect(screen.getByText("3 fail")).toBeTruthy();
  });

  it("shows PASS freshness with OK", () => {
    const passHealth = { ...sampleHealth, freshness: { status: "PASS", fail_count: 0, warn_count: 0 } };
    render(<MarketContext events={[]} health={passHealth} />);
    expect(screen.getByText("PASS")).toBeTruthy();
    expect(screen.getByText("OK")).toBeTruthy();
  });

  it("renders bull regime in green", () => {
    const bullHealth = { ...sampleHealth, regime: { regime: "bull_low_vol", trend: "bull", confidence: 90 } };
    render(<MarketContext events={[]} health={bullHealth} />);
    expect(screen.getByText("BULL_L")).toBeTruthy(); // sliced
  });

  // #503 Phase A — visual saliency
  it("applies regime stripe class to events card", () => {
    const bullHealth = { ...sampleHealth, regime: { regime: "bull", trend: "bull", confidence: 90 } };
    const { container } = render(<MarketContext events={sampleEvents} health={bullHealth} />);
    const stripe = container.querySelector(".border-l-emerald-500\\/60");
    expect(stripe).toBeTruthy();
  });

  it("renders 7d sparkline svg when ≥2 days of events", () => {
    const { container } = render(<MarketContext events={sampleEvents} health={sampleHealth} />);
    const svg = container.querySelector("svg[aria-label='7d sentiment trend']");
    expect(svg).toBeTruthy();
    const path = svg?.querySelector("path");
    expect(path?.getAttribute("d")).toContain("M ");
  });

  it("hides sparkline when only 1 distinct day in events", () => {
    const oneDayEvents = sampleEvents.map(ev => ({ ...ev, published_at: "2026-04-12T10:00:00+00:00" }));
    const { container } = render(<MarketContext events={oneDayEvents} health={sampleHealth} />);
    expect(container.querySelector("svg[aria-label='7d sentiment trend']")).toBeNull();
  });

  // #503 Phase B — conditional pinning + regime banner
  it("pins card with ATTENTION badge when high-conf critical event in 24h", () => {
    const recent = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
    const pinEvents = [{
      category: "geopolitical_escalation",
      headline: "Critical event",
      sentiment: -0.8, confidence: 0.85, published_at: recent, source: "reuters",
    }];
    const { container } = render(<MarketContext events={pinEvents} health={sampleHealth} />);
    expect(screen.getByText("ATTENTION")).toBeTruthy();
    expect(container.querySelector(".ring-amber-500\\/30")).toBeTruthy();
  });

  it("does NOT pin when critical event is > 24h old", () => {
    const stale = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();
    const oldEvents = [{
      category: "geopolitical_escalation",
      headline: "Old event",
      sentiment: -0.8, confidence: 0.9, published_at: stale, source: "reuters",
    }];
    render(<MarketContext events={oldEvents} health={sampleHealth} />);
    expect(screen.queryByText("ATTENTION")).toBeNull();
  });

  it("renders regime-shift banner when regime confidence < 60", () => {
    const lowConf = { ...sampleHealth, regime: { regime: "recovery", trend: "sideways", confidence: 50 } };
    render(<MarketContext events={[]} health={lowConf} />);
    expect(screen.getByText("Regime 전환 신호")).toBeTruthy();
  });

  it("does NOT render regime-shift banner when confidence >= 60", () => {
    render(<MarketContext events={[]} health={sampleHealth} />);
    expect(screen.queryByText("Regime 전환 신호")).toBeNull();
  });

  it("bolds high-confidence events (>= 0.8)", () => {
    const highConfEvents = [
      { ...sampleEvents[0], confidence: 0.85, published_at: "2026-04-12T17:18:00+00:00" },
      { ...sampleEvents[1], confidence: 0.6, published_at: "2026-04-11T06:10:00+00:00" },
    ];
    const { container } = render(<MarketContext events={highConfEvents} health={sampleHealth} />);
    const boldDates = container.querySelectorAll(".font-bold");
    expect(boldDates.length).toBeGreaterThan(0);
  });
});
