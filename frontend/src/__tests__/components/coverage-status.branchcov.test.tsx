import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CoverageStatus, type CoverageData } from "@/components/ui/coverage-status";

// CoverageStatus 는 prop 만으로 렌더되는 순수 컴포넌트라 fetch/mock 불필요.
// line 41 의 ternary `match ? match[1] : c.detail` 중 fallback(`: c.detail`)
// arm 을 커버한다 — non-US-only + detail 에 `\d+/\d+` 조각이 없을 때만 도달.

describe("CoverageStatus — branch coverage", () => {
  it("krColumnText fallback: non-US-only detail without X/Y fragment shows raw detail", () => {
    const data: CoverageData = {
      pass: 0,
      fail: 1,
      exit_code: 1,
      checks: [
        {
          name: "data.macro_events",
          actual: 0.42,
          threshold: 0.8,
          status: "FAIL",
          detail: "no data collected",
          us_only: false,
        },
      ],
    };
    render(<CoverageStatus data={data} />);
    // ternary falsy arm → c.detail 원문 그대로 렌더
    expect(screen.getByText("no data collected")).toBeInTheDocument();
  });
});
