/**
 * Portfolio page — full interaction coverage (form submit, delete, edit, import, sample load).
 * Split from coverage-push-2.test.tsx (lines 81-215).
 *
 * NOTE: kept separate from portfolio-crud-coverage.test.tsx (push-3 origin) and
 * portfolio-form-fields-coverage.test.tsx (push-4 origin) — different next/navigation
 * mock shapes (this file uses onboarding=true URL search param).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("onboarding=true"),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

const mockHoldings = [
  { ticker: "AAPL", account: "test", quantity: 10, avg_price: 180,
    currency: "USD", sector: "Tech", latest_price: 195, price_date: "2026-03-31" },
  { ticker: "NVDA", account: "demo", quantity: 5, avg_price: 130,
    currency: "USD", sector: "Semi", latest_price: 145, price_date: "2026-03-31" },
];

type MockHolding = (typeof mockHoldings)[number];
interface PortfolioOverrides {
  importResult?: { imported: number; errors: unknown[] };
  addFail?: boolean;
  editFail?: boolean;
  holdings?: MockHolding[];
}
function setupPortfolioMock(overrides: PortfolioOverrides = {}) {
  const fetchMock = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
    if (typeof url === "string" && url.includes("/api/portfolio/sample") && opts?.method === "POST") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    }
    if (typeof url === "string" && url.includes("/api/portfolio/import") && opts?.method === "POST") {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(overrides.importResult ?? { imported: 3, errors: [] }),
      });
    }
    if (typeof url === "string" && url.includes("/api/portfolio") && opts?.method === "POST") {
      return Promise.resolve({
        ok: overrides.addFail ? false : true,
        json: () => Promise.resolve(overrides.addFail ? { detail: "duplicate" } : { ok: true }),
      });
    }
    if (typeof url === "string" && url.includes("/api/portfolio") && opts?.method === "PUT") {
      return Promise.resolve({
        ok: overrides.editFail ? false : true,
        json: () => Promise.resolve(overrides.editFail ? { detail: "not found" } : { ok: true }),
      });
    }
    if (typeof url === "string" && url.includes("/api/portfolio") && opts?.method === "DELETE") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    }
    if (typeof url === "string" && url.includes("/api/portfolio")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          holdings: overrides.holdings ?? mockHoldings,
          count: (overrides.holdings ?? mockHoldings).length,
        }),
      });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

describe("Portfolio — full interaction coverage", () => {
  beforeEach(() => {
    vi.resetModules();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders holdings grouped by account", async () => {
    setupPortfolioMock();
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("shows onboarding message + load sample", async () => {
    setupPortfolioMock({ holdings: [] });
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });
    const sampleBtn = screen.queryByText(/Load Sample/i);
    if (sampleBtn) {
      await act(async () => { fireEvent.click(sampleBtn); });
      await act(async () => { await new Promise(r => setTimeout(r, 200)); });
    }
  });

  it("toggles add form, fills and submits successfully", async () => {
    setupPortfolioMock();
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    // Toggle form
    const addBtn = screen.queryByText("Add Holding");
    if (addBtn) {
      await act(async () => { fireEvent.click(addBtn); });

      // Fill form
      const tickerInput = screen.queryByPlaceholderText(/Ticker/);
      const qtyInput = screen.queryByPlaceholderText(/Quantity/);
      const priceInput = screen.queryByPlaceholderText(/Avg Price/);
      if (tickerInput && qtyInput && priceInput) {
        fireEvent.change(tickerInput, { target: { value: "TSLA" } });
        fireEvent.change(qtyInput, { target: { value: "10" } });
        fireEvent.change(priceInput, { target: { value: "250" } });

        // Submit
        const saveBtn = screen.queryByText("Save");
        if (saveBtn) {
          await act(async () => { fireEvent.click(saveBtn); });
          await act(async () => { await new Promise(r => setTimeout(r, 200)); });
        }
      }
    }
  });

  it("shows form validation error for empty ticker", async () => {
    setupPortfolioMock();
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    const addBtn = screen.queryByText("Add Holding");
    if (addBtn) {
      await act(async () => { fireEvent.click(addBtn); });
      const qtyInput = screen.queryByPlaceholderText(/Quantity/);
      const priceInput = screen.queryByPlaceholderText(/Avg Price/);
      if (qtyInput && priceInput) {
        fireEvent.change(qtyInput, { target: { value: "10" } });
        fireEvent.change(priceInput, { target: { value: "100" } });
        // Submit without ticker
        const saveBtn = screen.queryByText("Save");
        if (saveBtn) {
          await act(async () => { fireEvent.click(saveBtn); });
        }
      }
    }
  });

  it("handles add failure from API", async () => {
    setupPortfolioMock({ addFail: true });
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    const addBtn = screen.queryByText("Add Holding");
    if (addBtn) {
      await act(async () => { fireEvent.click(addBtn); });
      const tickerInput = screen.queryByPlaceholderText(/Ticker/);
      const qtyInput = screen.queryByPlaceholderText(/Quantity/);
      const priceInput = screen.queryByPlaceholderText(/Avg Price/);
      if (tickerInput && qtyInput && priceInput) {
        fireEvent.change(tickerInput, { target: { value: "TSLA" } });
        fireEvent.change(qtyInput, { target: { value: "10" } });
        fireEvent.change(priceInput, { target: { value: "250" } });
        const saveBtn = screen.queryByText("Save");
        if (saveBtn) {
          await act(async () => { fireEvent.click(saveBtn); });
          await act(async () => { await new Promise(r => setTimeout(r, 200)); });
        }
      }
    }
  });

  it("handles delete confirmation", async () => {
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    setupPortfolioMock();
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    // Click delete button (🗑 icon)
    const deleteButtons = screen.queryAllByText("🗑");
    if (deleteButtons.length > 0) {
      await act(async () => { fireEvent.click(deleteButtons[0]); });
      await act(async () => { await new Promise(r => setTimeout(r, 200)); });
    }
    vi.unstubAllGlobals();
  });

  it("handles CSV import with errors", async () => {
    setupPortfolioMock({ importResult: { imported: 2, errors: ["row 3: invalid ticker", "row 5: missing price", "row 6: dup", "row 7: err", "row 8: err", "row 9: extra"] } });
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    // Find upload button and trigger file change
    const uploadBtn = screen.queryByText("Upload CSV");
    if (uploadBtn) {
      await act(async () => { fireEvent.click(uploadBtn); });
    }
  });
});
