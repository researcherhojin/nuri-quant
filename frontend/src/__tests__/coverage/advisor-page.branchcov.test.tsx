import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// Server Component: fetchAPI from @/lib/api 를 모킹한다
const fetchAPIMock = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => fetchAPIMock(...args),
}));

// ClientTable 는 client component — 렌더 단순화를 위해 stub
vi.mock("@/components/ui/client-table", () => ({
  ClientTable: ({ data }: { data: unknown[] }) => (
    <div data-testid="client-table">rows:{data.length}</div>
  ),
}));

import { AdvisorSection } from "@/app/advisor/page";
import { ADVISOR as A, COMMON } from "@/lib/strings";

describe("advisor page branch coverage", () => {
  beforeEach(() => {
    fetchAPIMock.mockReset();
  });

  // L44 catch arm: fetchAPI 가 throw → API_ERROR 렌더
  it("renders API error when fetchAPI throws", async () => {
    fetchAPIMock.mockRejectedValueOnce(new Error("boom"));
    const jsx = await AdvisorSection();
    render(jsx);
    expect(screen.getByText(COMMON.API_ERROR)).toBeInTheDocument();
  });

  // L48 true arm: total_violations === 0 → NO_VIOLATIONS ready card
  it("renders no-violations card when total_violations is 0", async () => {
    fetchAPIMock.mockResolvedValueOnce({
      actions: [],
      total_violations: 0,
      total_recovery_usd: 0,
      violations_by_type: {},
      violations_by_severity: {},
      has_critical: false,
    });
    const jsx = await AdvisorSection();
    render(jsx);
    expect(screen.getByText(A.NO_VIOLATIONS)).toBeInTheDocument();
  });

  // L61/L62 left arms (critical/high present, truthy), L67 "red", L77 true (has_critical)
  it("renders critical+high metrics and critical banner when severities present", async () => {
    fetchAPIMock.mockResolvedValueOnce({
      actions: [
        {
          ticker: "AAA",
          violation_type: "position_limit",
          priority: 1,
          current_value: 12,
          limit_value: 10,
          severity: "critical",
          action: "TRIM",
          sell_shares: 5,
          sell_value_usd: 1000,
          reason: "over limit",
        },
      ],
      total_violations: 3,
      total_recovery_usd: 12345,
      violations_by_type: { position_limit: 2, sector_limit: 1 },
      violations_by_severity: { critical: 2, high: 1 },
      has_critical: true,
    });
    const { container } = render(await AdvisorSection());
    // critical banner present (L77 true arm) — red banner card 가 렌더됨
    expect(container.textContent).toContain(A.CRITICAL_PREFIX);
    // table rendered with the violations
    expect(screen.getByTestId("client-table")).toHaveTextContent("rows:1");
    // total count rendered
    expect(
      screen.getByText(`3${COMMON.COUNT_SUFFIX}`)
    ).toBeInTheDocument();
    // recovery dollar value rendered (toLocaleString, maximumFractionDigits 0)
    expect(screen.getByText("$12,345")).toBeInTheDocument();
  });

  // L61/L62 RIGHT arms (|| 0): violations_by_severity lacks critical & high,
  // L67 "default" (critical === 0), L77 false (has_critical false)
  it("falls back to 0 for missing severities, default color, no critical banner", async () => {
    fetchAPIMock.mockResolvedValueOnce({
      actions: [
        {
          ticker: "BBB",
          violation_type: "sector_limit",
          priority: 2,
          current_value: 30,
          limit_value: 25,
          severity: "medium",
          action: "REBALANCE",
          sell_shares: 2,
          sell_value_usd: 500,
          reason: "sector",
        },
      ],
      total_violations: 1,
      total_recovery_usd: 500,
      // critical 과 high 키가 없음 → `|| 0` 우측 arm 트리거
      violations_by_severity: { medium: 1 },
      violations_by_type: { sector_limit: 1 },
      has_critical: false,
    });
    const { container } = render(await AdvisorSection());
    // critical banner 가 없어야 함 (L77 false arm)
    expect(container.textContent).not.toContain(A.CRITICAL_PREFIX);
    // 테이블은 렌더됨
    expect(screen.getByTestId("client-table")).toHaveTextContent("rows:1");
    // violation distribution chip 렌더 (Object.entries map)
    expect(screen.getByText(A.VIOLATION_DIST)).toBeInTheDocument();
  });
});
