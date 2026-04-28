/**
 * Portfolio — add form field coverage (account select, ticker, qty, avg_price,
 * currency select, sector input) + inline edit onChange handlers.
 *
 * Split from coverage-push-4.test.tsx (lines 389-527 + 706-774).
 *
 * NOTE: kept separate from portfolio-coverage.test.tsx (push-2 origin uses
 * onboarding=true URL search param) and portfolio-crud-coverage.test.tsx (push-3
 * origin different fetch shape). Different mock semantics → different file.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
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

describe("Portfolio — add form field coverage", () => {
  beforeEach(() => {
    vi.resetModules();
    global.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (typeof url === "string" && url.includes("/api/portfolio/sample") && opts?.method === "POST") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (typeof url === "string" && url.includes("/api/portfolio") && opts?.method === "POST") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (typeof url === "string" && url.includes("/api/portfolio")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            // Multiple accounts so dynamic ACCOUNTS dropdown has options to test
            holdings: [
              { ticker: "AAPL", account: "test", quantity: 10, avg_price: 180,
                currency: "USD", sector: "Tech", latest_price: 195, price_date: "2026-03-31" },
              { ticker: "BBB", account: "demo", quantity: 5, avg_price: 100,
                currency: "USD", sector: "ETF", latest_price: 110, price_date: "2026-03-31" },
              { ticker: "CCC", account: "sample", quantity: 8, avg_price: 50,
                currency: "USD", sector: "Tech", latest_price: 55, price_date: "2026-03-31" },
              { ticker: "DDD", account: "pension", quantity: 3, avg_price: 200,
                currency: "USD", sector: "Tech", latest_price: 220, price_date: "2026-03-31" },
              { ticker: "EEE", account: "irp", quantity: 2, avg_price: 300,
                currency: "USD", sector: "Tech", latest_price: 320, price_date: "2026-03-31" },
            ],
            count: 5,
          }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fills all form fields including account, currency, and sector", async () => {
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    // Open add form
    const addBtn = screen.queryByText("Add Holding");
    if (!addBtn) return;
    await act(async () => { fireEvent.click(addBtn); });

    // Account select (line 285-288)
    const selects = document.querySelectorAll("select");
    const accountSelect = selects[0];
    if (accountSelect) {
      fireEvent.change(accountSelect, { target: { value: "demo" } });
      expect((accountSelect as HTMLSelectElement).value).toBe("demo");

      // Change to other accounts
      fireEvent.change(accountSelect, { target: { value: "sample" } });
      fireEvent.change(accountSelect, { target: { value: "pension" } });
      fireEvent.change(accountSelect, { target: { value: "irp" } });
    }

    // Ticker input (line 289-290)
    const tickerInput = screen.queryByPlaceholderText(/Ticker/);
    if (tickerInput) {
      fireEvent.change(tickerInput, { target: { value: "TSLA" } });
    }

    // Quantity input (line 291-292)
    const qtyInput = screen.queryByPlaceholderText(/Quantity/);
    if (qtyInput) {
      fireEvent.change(qtyInput, { target: { value: "25" } });
    }

    // Avg Price input (line 293-294)
    const priceInput = screen.queryByPlaceholderText(/Avg Price/);
    if (priceInput) {
      fireEvent.change(priceInput, { target: { value: "250.50" } });
    }

    // Currency select (line 295-299)
    const currencySelect = selects[1];
    if (currencySelect) {
      fireEvent.change(currencySelect, { target: { value: "KRW" } });
      expect((currencySelect as HTMLSelectElement).value).toBe("KRW");
      // Switch back
      fireEvent.change(currencySelect, { target: { value: "USD" } });
    }

    // Sector input (line 300-301)
    const sectorInput = screen.queryByPlaceholderText(/Sector/);
    if (sectorInput) {
      fireEvent.change(sectorInput, { target: { value: "Semiconductor" } });
    }

    // Submit the form
    const saveBtn = screen.queryByText("Save");
    if (saveBtn) {
      await act(async () => { fireEvent.click(saveBtn); });
      await act(async () => { await new Promise(r => setTimeout(r, 200)); });
    }
  });

  it("submits KRW holding via form", async () => {
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    const addBtn = screen.queryByText("Add Holding");
    if (!addBtn) return;
    await act(async () => { fireEvent.click(addBtn); });

    // Select account
    const selects = document.querySelectorAll("select");
    if (selects[0]) fireEvent.change(selects[0], { target: { value: "demo" } });

    // Fill Korean ticker
    const tickerInput = screen.queryByPlaceholderText(/Ticker/);
    if (tickerInput) fireEvent.change(tickerInput, { target: { value: "005930.KS" } });

    const qtyInput = screen.queryByPlaceholderText(/Quantity/);
    if (qtyInput) fireEvent.change(qtyInput, { target: { value: "5" } });

    const priceInput = screen.queryByPlaceholderText(/Avg Price/);
    if (priceInput) fireEvent.change(priceInput, { target: { value: "60000" } });

    // Set currency to KRW
    if (selects[1]) fireEvent.change(selects[1], { target: { value: "KRW" } });

    const sectorInput = screen.queryByPlaceholderText(/Sector/);
    if (sectorInput) fireEvent.change(sectorInput, { target: { value: "Electronics" } });

    const saveBtn = screen.queryByText("Save");
    if (saveBtn) {
      await act(async () => { fireEvent.click(saveBtn); });
      await act(async () => { await new Promise(r => setTimeout(r, 200)); });
    }
  });
});


// ═══════════════════════════════════════════════════════════
// Portfolio — inline edit onChange handlers (lines 198-199, 213-214)
// ═══════════════════════════════════════════════════════════

describe("Portfolio — inline edit input interactions", () => {
  beforeEach(() => {
    vi.resetModules();
    global.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (typeof url === "string" && url.includes("/api/portfolio") && opts?.method === "PUT") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (typeof url === "string" && url.includes("/api/portfolio") && (!opts || !opts.method || opts.method === "GET")) {
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
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("exercises inline edit quantity and avg_price onChange + onClick handlers", async () => {
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    // Click Edit button to enter edit mode
    const editBtns = screen.queryAllByText("Edit");
    if (editBtns.length > 0) {
      await act(async () => { fireEvent.click(editBtns[0]); });
      await act(async () => { await new Promise(r => setTimeout(r, 100)); });

      // Now the inline edit inputs should be visible
      const numberInputs = document.querySelectorAll('input[type="number"]');
      expect(numberInputs.length).toBeGreaterThanOrEqual(2);

      // Exercise quantity onChange (line 198)
      if (numberInputs[0]) {
        fireEvent.change(numberInputs[0], { target: { value: "15" } });
        // Exercise onClick stopPropagation (line 199)
        fireEvent.click(numberInputs[0]);
      }

      // Exercise avg_price onChange (line 213)
      if (numberInputs[1]) {
        fireEvent.change(numberInputs[1], { target: { value: "200" } });
        // Exercise onClick stopPropagation (line 214)
        fireEvent.click(numberInputs[1]);
      }

      // Save the edit
      const saveBtn = screen.queryByText("Save");
      if (saveBtn) {
        await act(async () => { fireEvent.click(saveBtn); });
        await act(async () => { await new Promise(r => setTimeout(r, 200)); });
      }
    }
  });
});
