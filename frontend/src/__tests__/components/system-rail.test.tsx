import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SystemHealthRail, meaningfulTarget, formatAge } from "@/components/dashboard/system-rail";

vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

const health = {
  regime: { regime: "bull_low_vol", trend: "bull", confidence: 100 },
  macro: { score: 68, interpretation: "Neutral" },
  freshness: { status: "FAIL", fail_count: 6, warn_count: 2 },
};

const market = {
  trend: "bull",
  vix: 15.3,
  fg: 43.3,
  macroScore: 68,
  actualAllocation: { long: 78, short: 0, cash: 22 },
  targetAllocation: { long: 80, short: 0, cash: 20 },
  fallbackAllocation: { long: 0, short: 0, cash: 100 },
};

const freshnessItems = [
  { key: "prices", label: "주가 데이터", status: "PASS" as const, age_hours: 2, message: "ok" },
  { key: "macro_market", label: "매크로 시장지표", status: "FAIL" as const, age_hours: 906, message: "오래됨" },
  { key: "ark", label: "ARK 보유", status: "WARN" as const, age_hours: 60, message: "경고" },
];

describe("SystemHealthRail (#1652 — 시장 사실 + 신선도 흡수)", () => {
  it("keeps the three original rows without market facts", () => {
    render(<SystemHealthRail health={health} />);
    expect(screen.getByText("레짐")).toBeTruthy();
    expect(screen.getByText("매크로")).toBeTruthy();
    expect(screen.getByText("데이터")).toBeTruthy();
    expect(screen.queryByText("VIX")).toBeNull();
    expect(screen.queryByText("배분")).toBeNull();
  });

  it("adds VIX, 심리 and 배분 rows from the market facts, in the same row format", () => {
    render(<SystemHealthRail health={health} market={market} />);
    expect(screen.getByText("VIX")).toBeTruthy();
    expect(screen.getByText("15.3")).toBeTruthy();
    expect(screen.getByText("낮음")).toBeTruthy();
    expect(screen.getByText("심리")).toBeTruthy();
    expect(screen.getByText("43.3")).toBeTruthy();
    expect(screen.getByText("공포")).toBeTruthy();
    expect(screen.getByText("배분")).toBeTruthy();
    expect(screen.getByText("78%")).toBeTruthy();
    expect(screen.getByText(/권장 80% \/ 20%/)).toBeTruthy();
  });

  it("renders allocation as unknown (not 100% cash) when the backend says the denominator is unknown (#1284)", () => {
    render(<SystemHealthRail health={health} market={{ ...market, actualAllocation: null }} />);
    expect(screen.getByTestId("allocation-unknown")).toBeTruthy();
    expect(screen.queryByText(/권장/)).toBeNull();
  });

  it("omits the 심리 row when fear_greed is null and shows VIX as a dash", () => {
    render(<SystemHealthRail health={health} market={{ ...market, vix: null, fg: null }} />);
    expect(screen.queryByText("심리")).toBeNull();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });

  it("lists only WARN/FAIL freshness items under the 데이터 row", () => {
    render(<SystemHealthRail health={health} market={market} freshnessItems={freshnessItems} />);
    const list = screen.getByTestId("rail-freshness");
    expect(list.textContent).toContain("매크로 시장지표");
    expect(list.textContent).toContain("ARK 보유");
    expect(list.textContent).not.toContain("주가 데이터");
  });

  it("renders no freshness list when everything passes", () => {
    render(<SystemHealthRail health={health} market={market} freshnessItems={[freshnessItems[0]]} />);
    expect(screen.queryByTestId("rail-freshness")).toBeNull();
  });
});

describe("meaningfulTarget", () => {
  it("hides the 0/100 default and a target equal to actual", () => {
    expect(meaningfulTarget({ long: 50, short: 0, cash: 50 }, { long: 0, short: 0, cash: 100 })).toBeNull();
    expect(meaningfulTarget({ long: 50, short: 0, cash: 50 }, { long: 50, short: 0, cash: 50 })).toBeNull();
    expect(meaningfulTarget(null, { long: 80, short: 0, cash: 20 })).toBeNull();
  });
  it("returns a differing target", () => {
    expect(meaningfulTarget({ long: 50, short: 0, cash: 50 }, { long: 80, short: 0, cash: 20 })).toEqual({ long: 80, short: 0, cash: 20 });
  });
});

describe("formatAge", () => {
  it("matches the FreshnessBar scale", () => {
    expect(formatAge(0.4)).toBe("<1h");
    expect(formatAge(5.4)).toBe("5h");
    expect(formatAge(906)).toBe("37d");
    expect(formatAge(9000)).toBe("N/A");
  });
});
