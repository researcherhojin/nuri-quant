/**
 * Consensus page — VIX threshold branches (no banner / 25-30 warning).
 * Split from coverage-push-5.test.tsx (lines 194-223).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

const mockFetchAPI = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

describe("Consensus page VIX branches", () => {
  beforeEach(() => { mockFetchAPI.mockReset(); });

  it("VIX < 25 → no banner", async () => {
    mockFetchAPI.mockImplementation(() => ({
      regime: { vix: 18, regime: "bull_low_vol" },
      results: [{ ticker: "AAPL", final_action: "BUY", final_confidence: 85,
        agreement_rate: 0.8, dissent: [], verdicts: [], reasoning: "" }],
      count: 1,
    }));

    const Page = await import("@/app/consensus/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => { expect(screen.getByText("AAPL")).toBeInTheDocument(); });
    expect(screen.queryByText(/신규 매수/)).not.toBeInTheDocument();
  });

  it("VIX 25-30 → warning banner", async () => {
    mockFetchAPI.mockImplementation(() => ({
      regime: { vix: 27.5, regime: "bear" },
      results: [{ ticker: "AAPL", final_action: "HOLD", final_confidence: 50,
        agreement_rate: 0.5, dissent: ["Risk high"], verdicts: [], reasoning: "" }],
      count: 1,
    }));

    const Page = await import("@/app/consensus/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => { expect(screen.getByText(/VIX/)).toBeInTheDocument(); });
  });
});
