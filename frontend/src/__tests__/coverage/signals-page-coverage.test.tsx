/**
 * Signals page — error branch (API returns error object).
 * Split from coverage-push-5.test.tsx (lines 229-238).
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

describe("Signals page error", () => {
  beforeEach(() => { mockFetchAPI.mockReset(); });

  it("API error object → error display", async () => {
    mockFetchAPI.mockImplementation(() => ({ error: "CSV not found" }));
    const Page = await import("@/app/signals/page");
    await act(async () => { render(<Page.default />); });
    await waitFor(() => { expect(screen.getByText("CSV not found")).toBeInTheDocument(); });
  });
});
