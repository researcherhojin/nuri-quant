import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CoverageStatus, type CoverageData } from "@/components/ui/coverage-status";

function makeData(overrides: Partial<CoverageData> = {}): CoverageData {
  return {
    pass: 5,
    fail: 0,
    exit_code: 0,
    checks: [
      { name: "data.prices", actual: 0.99, threshold: 0.95, status: "PASS",
        detail: "537/543 US tickers", us_only: false },
      { name: "data.fundamentals", actual: 0.99, threshold: 0.80, status: "PASS",
        detail: "537/543 US tickers", us_only: false },
      { name: "data.analyst_ratings", actual: 0.97, threshold: 0.70, status: "PASS",
        detail: "528/543 US tickers (KR n/a — 소스 미지원)", us_only: true },
      { name: "data.insider_trades", actual: 0.97, threshold: 0.50, status: "PASS",
        detail: "526/543 US tickers (KR n/a — 소스 미지원)", us_only: true },
      { name: "data.superinvestors", actual: 0.97, threshold: 0.80, status: "PASS",
        detail: "524/543 US tickers (KR n/a — 소스 미지원)", us_only: true },
    ],
    ...overrides,
  };
}

describe("CoverageStatus", () => {
  it("renders 5/5 PASS header when all checks pass", () => {
    render(<CoverageStatus data={makeData()} />);
    expect(screen.getByText(/5\/5 PASS/)).toBeInTheDocument();
  });

  it("renders FAIL header when any check fails", () => {
    const data = makeData({ pass: 3, fail: 2, exit_code: 1 });
    data.checks[0] = { ...data.checks[0], status: "FAIL" };
    data.checks[1] = { ...data.checks[1], status: "FAIL" };
    render(<CoverageStatus data={data} />);
    expect(screen.getByText(/3\/5 PASS/)).toBeInTheDocument();
  });

  it("renders table with all 5 checks and strips 'data.' prefix", () => {
    render(<CoverageStatus data={makeData()} />);
    expect(screen.getByText("prices")).toBeInTheDocument();
    expect(screen.getByText("fundamentals")).toBeInTheDocument();
    expect(screen.getByText("analyst_ratings")).toBeInTheDocument();
    expect(screen.getByText("insider_trades")).toBeInTheDocument();
    expect(screen.getByText("superinvestors")).toBeInTheDocument();
  });

  it("shows 'n/a (US-only)' label in KR column for US_ONLY_TABLES (#288)", () => {
    render(<CoverageStatus data={makeData()} />);
    const naLabels = screen.getAllByText("n/a (US-only)");
    // 3 US_ONLY tables (analyst_ratings, insider_trades, superinvestors)
    expect(naLabels).toHaveLength(3);
  });

  it("shows real KR match count for non-US-only tables", () => {
    const data = makeData();
    // Mutate detail for prices to include explicit "537/543"
    data.checks[0] = { ...data.checks[0], detail: "537/543 US tickers" };
    render(<CoverageStatus data={data} />);
    // 537/543 appears in the KR column (non-US-only extracts it from detail)
    expect(screen.getAllByText("537/543").length).toBeGreaterThan(0);
  });

  it("includes footer note explaining 'n/a (US-only)' semantics", () => {
    render(<CoverageStatus data={makeData()} />);
    expect(screen.getByText(/소스가 KR 종목 미지원/)).toBeInTheDocument();
  });

  it("omits footer note when no US_ONLY tables present", () => {
    const data = makeData();
    data.checks = data.checks.map((c) => ({ ...c, us_only: false }));
    render(<CoverageStatus data={data} />);
    expect(screen.queryByText(/소스가 KR 종목 미지원/)).not.toBeInTheDocument();
  });

  it("renders error state when data.error is set", () => {
    const data: CoverageData = {
      pass: 0, fail: 0, exit_code: 1, checks: [],
      error: "coverage computation failed",
    };
    render(<CoverageStatus data={data} />);
    // 카피는 한국어 안내, 원문 에러는 title 로 강등 (design-review F-002)
    const banner = screen.getByText(/Coverage 확인 실패/);
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveAttribute("title", "coverage computation failed");
    expect(screen.queryByText(/coverage computation failed/)).toBeNull();
  });

  it("displays percentage formatting for actual and threshold columns", () => {
    render(<CoverageStatus data={makeData()} />);
    // prices: 99% actual, ≥95% threshold
    expect(screen.getAllByText("99%").length).toBeGreaterThan(0);
    expect(screen.getByText("≥95%")).toBeInTheDocument();
  });

  // #1210 접기 잠금: 기본은 닫힌 <details> — 한 줄 요약(헤더+카운트)만 노출,
  // 테이블은 펼쳐야 보인다. client JS 없이 server component 를 유지하는 게 요점.
  it("renders collapsed by default as a native <details> with the one-line summary", () => {
    render(<CoverageStatus data={makeData()} />);
    const details = screen.getByTestId("coverage-details") as HTMLDetailsElement;
    expect(details.tagName).toBe("DETAILS");
    expect(details.open).toBe(false);
    const summary = details.querySelector("summary")!;
    expect(summary.textContent).toContain("Data Coverage");
    expect(summary.textContent).toContain("5/5 PASS");
  });

  it("error state renders the plain error box, not a details fold", () => {
    render(
      <CoverageStatus
        data={{ pass: 0, fail: 0, exit_code: 1, checks: [], error: "boom" }}
      />,
    );
    expect(screen.queryByTestId("coverage-details")).not.toBeInTheDocument();
  });
});
