import { describe, it, expect } from "vitest";
import { getMacroImpactedSectors, isMacroAware } from "@/lib/macro-impact";
import type { MacroEvent } from "@/components/ui/market-context";

function evt(category: string, conf = 0.8, hoursAgo = 2): MacroEvent {
  const ts = new Date(Date.now() - hoursAgo * 60 * 60 * 1000).toISOString();
  return {
    category, headline: "", sentiment: 0, confidence: conf,
    published_at: ts, source: "test",
  };
}

describe("getMacroImpactedSectors", () => {
  it("returns empty set for empty events", () => {
    expect(getMacroImpactedSectors([]).size).toBe(0);
  });

  it("maps oil_supply_shock to Energy/Oil", () => {
    const sectors = getMacroImpactedSectors([evt("oil_supply_shock")]);
    expect(sectors.has("energy")).toBe(true);
    expect(sectors.has("oil")).toBe(true);
  });

  it("maps fed_dovish to Tech/Growth/Semi", () => {
    const sectors = getMacroImpactedSectors([evt("fed_dovish")]);
    expect(sectors.has("tech")).toBe(true);
    expect(sectors.has("growth")).toBe(true);
    expect(sectors.has("semi")).toBe(true);
  });

  it("filters low-confidence events (< 0.6)", () => {
    expect(getMacroImpactedSectors([evt("oil_supply_shock", 0.5)]).size).toBe(0);
  });

  it("filters events older than 24h", () => {
    expect(getMacroImpactedSectors([evt("oil_supply_shock", 0.9, 48)]).size).toBe(0);
  });

  it("ignores ticker-specific categories (sector_rally, earnings)", () => {
    expect(getMacroImpactedSectors([evt("sector_rally")]).size).toBe(0);
    expect(getMacroImpactedSectors([evt("earnings_beat")]).size).toBe(0);
  });

  it("merges keywords from multiple events", () => {
    const sectors = getMacroImpactedSectors([
      evt("oil_supply_shock"),
      evt("fed_hawkish"),
    ]);
    expect(sectors.has("energy")).toBe(true);
    expect(sectors.has("bank")).toBe(true);
    expect(sectors.has("financial")).toBe(true);
  });
});

describe("isMacroAware", () => {
  const impacted = new Set(["energy", "tech"]);

  it("matches direct sector keyword", () => {
    expect(isMacroAware("Energy", impacted)).toBe(true);
    expect(isMacroAware("Technology", impacted)).toBe(true);
  });

  it("matches via substring (ETF/USTech)", () => {
    expect(isMacroAware("ETF/USTech", impacted)).toBe(true);
  });

  it("returns false for null / undefined sector", () => {
    expect(isMacroAware(null, impacted)).toBe(false);
    expect(isMacroAware(undefined, impacted)).toBe(false);
  });

  it("returns false for empty impacted set", () => {
    expect(isMacroAware("Energy", new Set())).toBe(false);
  });

  it("is case-insensitive", () => {
    expect(isMacroAware("ENERGY", impacted)).toBe(true);
    expect(isMacroAware("energy", impacted)).toBe(true);
  });

  it("returns false when no keyword matches", () => {
    expect(isMacroAware("Healthcare", impacted)).toBe(false);
  });
});
