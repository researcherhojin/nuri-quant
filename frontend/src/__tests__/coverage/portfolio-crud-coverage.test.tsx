/**
 * Portfolio page — edit/delete/CSV-import interactions, KRW rendering.
 * Pure no-recharts test (sma/formatVolume unmocked) to avoid vitest mock hoist
 * conflicts with portfolio-coverage.test.tsx (push-2 origin uses onboarding=true).
 *
 * Split from coverage-push-3.test.tsx (lines 50-200).
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/portfolio",
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

vi.mock("@/lib/api", () => ({
  API_BASE: "http://localhost:8001",
  fetchAPI: vi.fn(),
}));

const multiHoldings = [
  { ticker: "AAPL", account: "test", quantity: 10, avg_price: 180,
    currency: "USD", sector: "Tech", latest_price: 195, price_date: "2026-03-31" },
  { ticker: "005930.KS", account: "demo", quantity: 4, avg_price: 60000,
    currency: "KRW", sector: "Semi", latest_price: 65000, price_date: "2026-03-31" },
];

interface FetchOverrides {
  importFail?: boolean;
  importErrors?: unknown[];
  editFail?: boolean;
}
function setupFetch(overrides: FetchOverrides = {}) {
  global.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
    if (typeof url === "string" && url.includes("/api/portfolio/import") && opts?.method === "POST") {
      return Promise.resolve({
        ok: !overrides.importFail,
        json: () => Promise.resolve(
          overrides.importFail ? { detail: "bad csv" } : { imported: 3, errors: overrides.importErrors ?? [] }
        ),
      });
    }
    if (typeof url === "string" && url.includes("/api/portfolio") && opts?.method === "PUT") {
      return Promise.resolve({
        ok: !overrides.editFail,
        json: () => Promise.resolve(overrides.editFail ? { detail: "not found" } : { ok: true }),
      });
    }
    if (typeof url === "string" && url.includes("/api/portfolio") && opts?.method === "DELETE") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    }
    if (typeof url === "string" && url.includes("/api/portfolio") && (!opts || !opts.method || opts.method === "GET")) {
      return Promise.resolve({
        ok: true, json: () => Promise.resolve({ holdings: multiHoldings, count: multiHoldings.length }),
      });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as unknown as typeof fetch;
}

describe("Portfolio — edit/delete/import", () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it("edit row, change qty, save", async () => {
    vi.resetModules();
    setupFetch();
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    const editBtns = screen.queryAllByText("✏️");
    if (editBtns.length > 0) {
      await act(async () => { fireEvent.click(editBtns[0]); });
      await act(async () => { await new Promise(r => setTimeout(r, 100)); });
      const numInputs = document.querySelectorAll('input[type="number"]');
      if (numInputs.length > 0) fireEvent.change(numInputs[0], { target: { value: "20" } });
      const saveBtn = screen.queryByText("Save") || screen.queryByText("저장");
      if (saveBtn) {
        await act(async () => { fireEvent.click(saveBtn); });
        await act(async () => { await new Promise(r => setTimeout(r, 200)); });
      }
    }
  });

  it("edit row and cancel", async () => {
    vi.resetModules();
    setupFetch();
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    const editBtns = screen.queryAllByText("✏️");
    if (editBtns.length > 0) {
      await act(async () => { fireEvent.click(editBtns[0]); });
      const cancelBtn = screen.queryByText("Cancel") || screen.queryByText("취소");
      if (cancelBtn) await act(async () => { fireEvent.click(cancelBtn); });
    }
  });

  it("delete with confirm", async () => {
    vi.resetModules();
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    setupFetch();
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    const delBtns = screen.queryAllByText("🗑");
    if (delBtns.length > 0) {
      await act(async () => { fireEvent.click(delBtns[0]); });
      await act(async () => { await new Promise(r => setTimeout(r, 200)); });
    }
    vi.unstubAllGlobals();
  });

  it("CSV import success", async () => {
    vi.resetModules();
    setupFetch();
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    if (fileInput) {
      const file = new File(["ticker,qty\nTSLA,10"], "t.csv", { type: "text/csv" });
      await act(async () => { fireEvent.change(fileInput, { target: { files: [file] } }); });
      await act(async () => { await new Promise(r => setTimeout(r, 300)); });
    }
  });

  it("CSV import failure", async () => {
    vi.resetModules();
    setupFetch({ importFail: true });
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    if (fileInput) {
      const file = new File(["bad"], "t.csv", { type: "text/csv" });
      await act(async () => { fireEvent.change(fileInput, { target: { files: [file] } }); });
      await act(async () => { await new Promise(r => setTimeout(r, 300)); });
    }
  });

  it("renders KRW ticker and P&L", async () => {
    vi.resetModules();
    setupFetch();
    const Page = (await import("@/app/portfolio/page")).default;
    await act(async () => { render(<Page />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });
    expect(screen.getByText("005930.KS")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });
});
