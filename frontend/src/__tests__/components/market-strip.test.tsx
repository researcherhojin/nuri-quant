/**
 * MarketStrip (#1204 U2a) — 추출 시 유일한 의도적 의미 변화의 잠금.
 * 원본 page.tsx 는 d.macro 가 없으면 macroLevel(d.macro.score) 에서 크래시했다.
 * 추출본은 macroScore=undefined 를 허용하고 경제 칩만 생략한다 (codex P2 — 안전화 채택).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarketStrip } from "@/components/dashboard/market-strip";
import { MARKET } from "@/lib/strings";

const base = {
  trend: "bull",
  vix: 14.9,
  fg: 52,
  actualAllocation: { long: 57, short: 0, cash: 43 },
  targetAllocation: { long: 50, short: 0, cash: 50 },
  fallbackAllocation: null,
};

describe("MarketStrip", () => {
  it("renders economy chip when macroScore > 0", () => {
    render(<MarketStrip {...base} macroScore={70} />);
    expect(screen.getByText(MARKET.ECONOMY)).toBeInTheDocument();
    expect(screen.getByText("70")).toBeInTheDocument();
  });

  it("omits economy chip without crashing when macroScore is undefined (missing d.macro)", () => {
    render(<MarketStrip {...base} macroScore={undefined} />);
    expect(screen.queryByText(MARKET.ECONOMY)).not.toBeInTheDocument();
    // verdict 는 VerdictBanner 소관 (#1206) — 스트립은 시장 사실만
  });

  it("omits economy chip when macroScore is 0 (no data sentinel)", () => {
    render(<MarketStrip {...base} macroScore={0} />);
    expect(screen.queryByText(MARKET.ECONOMY)).not.toBeInTheDocument();
  });

  it("hides target when it matches actual or is the 0/100 default", () => {
    render(
      <MarketStrip
        {...base}
        macroScore={70}
        targetAllocation={{ long: 57, short: 0, cash: 43 }}
      />,
    );
    expect(screen.queryByText(MARKET.TARGET)).not.toBeInTheDocument();
  });
});
