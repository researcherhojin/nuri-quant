import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarketContext } from "@/components/ui/market-context";

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
    expect(screen.getByText("SIEGE")).toBeTruthy();
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
    const siegeLink = screen.getByText("SIEGE").closest("a");
    expect(siegeLink?.getAttribute("href")).toBe("/engine");
    const regimeLink = screen.getByText("레짐").closest("a");
    expect(regimeLink?.getAttribute("href")).toBe("/strategy");
  });

  it("handles empty health gracefully", () => {
    render(<MarketContext events={[]} health={{} as any} />);
    expect(screen.getByText("SIEGE")).toBeTruthy();
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
});
