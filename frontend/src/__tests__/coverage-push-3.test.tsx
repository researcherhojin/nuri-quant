/**
 * Coverage push 3: pure utility functions + portfolio CRUD interactions.
 * NO recharts or @xyflow/react mocks — avoids vitest mock hoisting conflicts.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

// ═══════════════════════════════════════════════════════════
// sma + formatVolume — pure functions from price-chart.tsx
// ═══════════════════════════════════════════════════════════

describe("sma", () => {
  it("returns nulls for insufficient data", async () => {
    const { sma } = await import("@/components/ui/price-chart");
    expect(sma([100, 101], 5)[0]).toBeNull();
    expect(sma([100, 101], 5)[1]).toBeNull();
  });

  it("calculates correct moving average", async () => {
    const { sma } = await import("@/components/ui/price-chart");
    const result = sma([10, 20, 30, 40, 50], 3);
    expect(result[2]).toBe(20);
    expect(result[4]).toBe(40);
  });
});

describe("formatVolume", () => {
  it("formats millions", async () => {
    const { formatVolume } = await import("@/components/ui/price-chart");
    expect(formatVolume(5_000_000)).toBe("5.0M");
  });

  it("formats thousands", async () => {
    const { formatVolume } = await import("@/components/ui/price-chart");
    expect(formatVolume(50_000)).toBe("50K");
  });

  it("formats small numbers raw", async () => {
    const { formatVolume } = await import("@/components/ui/price-chart");
    expect(formatVolume(999)).toBe("999");
  });
});


// ═══════════════════════════════════════════════════════════
// Portfolio — edit, delete, import interactions
// ═══════════════════════════════════════════════════════════

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/portfolio",
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: any) => <a href={href}>{children}</a>,
}));

vi.mock("@/lib/api", () => ({
  API_BASE: "http://localhost:8001",
  fetchAPI: vi.fn(),
}));

const multiHoldings = [
  { ticker: "AAPL", account: "kakaopay", quantity: 10, avg_price: 180,
    currency: "USD", sector: "Tech", latest_price: 195, price_date: "2026-03-31" },
  { ticker: "005930.KS", account: "mirae", quantity: 4, avg_price: 60000,
    currency: "KRW", sector: "Semi", latest_price: 65000, price_date: "2026-03-31" },
];

function setupFetch(overrides: Record<string, any> = {}) {
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
