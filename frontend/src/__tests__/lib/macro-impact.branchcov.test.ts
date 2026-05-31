import { describe, expect, it } from "vitest";
import type { MacroEvent } from "@/components/ui/market-context";
import { getMacroImpactedSectors, isMacroAware } from "@/lib/macro-impact";

// #503 Phase C — branch coverage for macro-impact lookup helpers.
// nullish-coalescing 양 arm (confidence ?? 0, CATEGORY_SECTORS[...] ?? [])
// + 모든 short-circuit 분기를 양쪽 다 hit 한다.

// fresh = cutoff (24h) 이내, stale = 그보다 과거.
const freshIso = () => new Date(Date.now() - 60 * 60 * 1000).toISOString();
const staleIso = () => new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();

const ev = (overrides: Partial<MacroEvent>): MacroEvent =>
  ({
    category: "oil_supply_shock",
    confidence: 0.9,
    published_at: freshIso(),
    ...overrides,
  }) as MacroEvent;

describe("getMacroImpactedSectors", () => {
  it("includes sectors for a fresh, confident, known-category event", () => {
    // confidence present (?? left arm), finite ts, ts >= cutoff, known category (?? left arm)
    const out = getMacroImpactedSectors([ev({ category: "oil_supply_shock" })]);
    expect(out).toEqual(new Set(["energy", "oil"]));
  });

  it("skips events below the confidence threshold (< 0.6 true arm)", () => {
    const out = getMacroImpactedSectors([ev({ confidence: 0.59 })]);
    expect(out.size).toBe(0);
  });

  it("treats missing confidence as 0 (?? 0 right arm) and skips it", () => {
    // confidence undefined → ?? 0 → 0 < 0.6 → continue
    const out = getMacroImpactedSectors([ev({ confidence: undefined })]);
    expect(out.size).toBe(0);
  });

  it("skips events with unparseable published_at (!Number.isFinite true arm)", () => {
    const out = getMacroImpactedSectors([ev({ published_at: "not-a-date" })]);
    expect(out.size).toBe(0);
  });

  it("skips stale events older than the 24h cutoff (ts < cutoff true arm)", () => {
    // finite ts (!isFinite false arm) but older than cutoff
    const out = getMacroImpactedSectors([ev({ published_at: staleIso() })]);
    expect(out.size).toBe(0);
  });

  it("returns empty set for a known but sector-agnostic category (empty array)", () => {
    // known key with [] value → ?? left arm taken, no sectors added
    const out = getMacroImpactedSectors([ev({ category: "earnings_beat" })]);
    expect(out.size).toBe(0);
  });

  it("falls back to empty array for an unknown category (?? [] right arm)", () => {
    // CATEGORY_SECTORS[unknown] === undefined → ?? [] → loop body never runs
    const out = getMacroImpactedSectors([
      ev({ category: "totally_unknown_category" as MacroEvent["category"] }),
    ]);
    expect(out.size).toBe(0);
  });
});

describe("isMacroAware", () => {
  const impacted = new Set(["energy", "oil"]);

  it("returns false for a null sector (!sector true arm)", () => {
    expect(isMacroAware(null, impacted)).toBe(false);
  });

  it("returns false for an undefined sector (!sector true arm)", () => {
    expect(isMacroAware(undefined, impacted)).toBe(false);
  });

  it("returns false when the impacted set is empty (size === 0 true arm)", () => {
    // sector truthy (!sector false arm) but impacted empty
    expect(isMacroAware("Energy", new Set())).toBe(false);
  });

  it("returns true when the sector substring matches an impacted keyword (includes true arm)", () => {
    // sector truthy, impacted non-empty → loop, includes → true
    expect(isMacroAware("ETF/EnergySelect", impacted)).toBe(true);
  });

  it("returns false when no impacted keyword is a substring (includes false arm)", () => {
    expect(isMacroAware("Healthcare", impacted)).toBe(false);
  });
});
