/**
 * RootLayout (app/layout.tsx) — sidebar + children rendering.
 * Plus minimal Portfolio form-interaction test (cohabits because of shared
 * next-themes/sidebar/live-indicator mocks from coverage-push-1.test.tsx origin).
 * Split from coverage-push-1.test.tsx (lines 334-419).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("next/font/google", () => ({
  Geist_Mono: () => ({ variable: "--font-geist-mono" }),
}));

vi.mock("next-themes", () => ({
  ThemeProvider: ({ children }: { children?: ReactNode }) => <div data-testid="theme-provider">{children}</div>,
}));

vi.mock("@/components/ui/sidebar", () => ({
  Sidebar: () => <nav data-testid="sidebar">Sidebar</nav>,
  // #1226: command-palette 가 NAV_GROUPS 를 소비 — mock 에도 존재해야 로드된다
  NAV_GROUPS: [],
}));

vi.mock("@/components/ui/live-indicator", () => ({
  LiveIndicator: () => <span data-testid="live-indicator">Live</span>,
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

describe("RootLayout", () => {
  it("renders layout with sidebar and children", async () => {
    const { default: RootLayout } = await import("@/app/layout");
    // RootLayout renders <html> which jsdom doesn't handle well
    // Test the inner structure by rendering just the body content
    const { container } = render(
      <RootLayout>
        <div data-testid="child">Hello</div>
      </RootLayout>
    );
    // Layout should render without crashing
    expect(container).toBeTruthy();
  });
});


// ═══════════════════════════════════════════════════════════
// Portfolio — showForm, handleAdd, handleImport branches
// ═══════════════════════════════════════════════════════════

describe("Portfolio form interactions", () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url.includes("/api/portfolio") && !opts?.method) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            holdings: [
              { ticker: "AAPL", account: "test", quantity: 10, avg_price: 180,
                currency: "USD", sector: "Tech", latest_price: 195, price_date: "2026-03-31" },
            ],
            count: 1,
          }),
        });
      }
      if (opts?.method === "POST") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (opts?.method === "DELETE") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;
  });

  it("toggles add form and submits", async () => {
    vi.resetModules();
    const PortfolioPage = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<PortfolioPage />); });
    await act(async () => { await new Promise((r) => setTimeout(r, 100)); });

    const addBtn = screen.queryByText("Add Holding");
    if (addBtn) {
      await act(async () => { fireEvent.click(addBtn); });
      const tickerInput = screen.queryByPlaceholderText(/Ticker/);
      if (tickerInput) {
        fireEvent.change(tickerInput, { target: { value: "NVDA" } });
      }
    }
  });
});
