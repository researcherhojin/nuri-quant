/**
 * Branch-coverage push for src/app/portfolio/page.tsx (coverage/frontend-branch-100).
 *
 * Self-contained: covers ALL branch arms in isolation (does not rely on the sibling
 * page.coverage.test.tsx running in the same suite). Every arm is reached through a
 * real user interaction or fixture shape — no v8-ignore needed.
 *
 * No recharts import here, so the file-level recharts hoist gotcha does not apply.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import PortfolioPage from "./page";

// next/navigation mock — searchParams.get controllable per test
const mockGet = vi.fn();
vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: mockGet }),
}));

// strings mock mirrors the existing page.coverage.test.tsx style
vi.mock("@/lib/strings", () => ({
  PORTFOLIO: {
    QTY_ERROR: "Quantity must be positive",
    PRICE_ERROR: "Price must be positive",
    TICKER_ERROR: "Ticker required",
    ADD_FAILED: "Add failed",
    EDIT_FAILED: "Edit failed",
  },
}));

const mockFetch = vi.fn();
global.fetch = mockFetch as unknown as typeof fetch;
const mockConfirm = vi.fn(() => true);
global.confirm = mockConfirm as unknown as typeof confirm;

function jsonRes(body: unknown, ok = true) {
  return Promise.resolve({ ok, json: () => Promise.resolve(body) } as Response);
}

type PartialHolding = Partial<{
  ticker: string;
  account: string;
  quantity: number | null;
  avg_price: number | null;
  currency: string;
  sector: string;
  latest_price: number | null;
  price_date: string | null;
}>;

function holding(over: PartialHolding) {
  return {
    ticker: "AAPL",
    account: "test",
    quantity: 10,
    avg_price: 100,
    currency: "USD",
    sector: "Tech",
    latest_price: 150,
    price_date: "2025-01-01",
    ...over,
  };
}

// Default GET returns holdings; later mockReturnValueOnce overrides take priority.
function get(holdings: ReturnType<typeof holding>[]) {
  mockFetch.mockReturnValue(jsonRes({ holdings }));
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGet.mockReturnValue(null);
  mockConfirm.mockReturnValue(true);
  cleanup();
});

async function openAddForm() {
  await waitFor(() => screen.getByText("Add Holding"));
  fireEvent.click(screen.getByText("Add Holding"));
}

describe("PortfolioPage branch coverage", () => {
  // L86 `data.holdings || []` arm1 — response object missing `holdings`
  it("falls back to [] when fetch response has no holdings key", async () => {
    mockFetch.mockReturnValue(jsonRes({}));
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText(/Start by adding/i)).toBeInTheDocument());
  });

  // ── handleAdd validation early-returns ──
  // L105 `!qty || qty <= 0`
  it("handleAdd: QTY_ERROR when quantity is 0", async () => {
    get([]);
    render(<PortfolioPage />);
    await openAddForm();
    fireEvent.change(screen.getByPlaceholderText("Ticker (e.g. AAPL)"), { target: { value: "MSFT" } });
    fireEvent.change(screen.getByPlaceholderText("Quantity"), { target: { value: "0" } });
    fireEvent.change(screen.getByPlaceholderText("Avg Price"), { target: { value: "10" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(screen.getByText("Quantity must be positive")).toBeInTheDocument());
  });

  // L106 `!avg || avg <= 0`
  it("handleAdd: PRICE_ERROR when avg price is 0", async () => {
    get([]);
    render(<PortfolioPage />);
    await openAddForm();
    fireEvent.change(screen.getByPlaceholderText("Ticker (e.g. AAPL)"), { target: { value: "MSFT" } });
    fireEvent.change(screen.getByPlaceholderText("Quantity"), { target: { value: "5" } });
    fireEvent.change(screen.getByPlaceholderText("Avg Price"), { target: { value: "0" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(screen.getByText("Price must be positive")).toBeInTheDocument());
  });

  // L107 `!form.ticker.trim()`
  it("handleAdd: TICKER_ERROR when ticker is blank", async () => {
    get([]);
    render(<PortfolioPage />);
    await openAddForm();
    fireEvent.change(screen.getByPlaceholderText("Ticker (e.g. AAPL)"), { target: { value: "   " } });
    fireEvent.change(screen.getByPlaceholderText("Quantity"), { target: { value: "5" } });
    fireEvent.change(screen.getByPlaceholderText("Avg Price"), { target: { value: "200" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(screen.getByText("Ticker required")).toBeInTheDocument());
  });

  // L117 arm1 — failed POST without `detail` (ADD_FAILED fallback)
  it("handleAdd: ADD_FAILED fallback when POST fails with no detail", async () => {
    mockFetch
      .mockReturnValueOnce(jsonRes({ holdings: [] }))
      .mockReturnValueOnce(jsonRes({}, false));
    render(<PortfolioPage />);
    await openAddForm();
    fireEvent.change(screen.getByPlaceholderText("Ticker (e.g. AAPL)"), { target: { value: "MSFT" } });
    fireEvent.change(screen.getByPlaceholderText("Quantity"), { target: { value: "3" } });
    fireEvent.change(screen.getByPlaceholderText("Avg Price"), { target: { value: "200" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(screen.getByText("Add failed")).toBeInTheDocument());
  });

  // L117 arm0 — failed POST WITH `detail`
  it("handleAdd: uses server detail when POST fails with detail", async () => {
    mockFetch
      .mockReturnValueOnce(jsonRes({ holdings: [] }))
      .mockReturnValueOnce(jsonRes({ detail: "Duplicate ticker" }, false));
    render(<PortfolioPage />);
    await openAddForm();
    fireEvent.change(screen.getByPlaceholderText("Ticker (e.g. AAPL)"), { target: { value: "MSFT" } });
    fireEvent.change(screen.getByPlaceholderText("Quantity"), { target: { value: "3" } });
    fireEvent.change(screen.getByPlaceholderText("Avg Price"), { target: { value: "200" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(screen.getByText("Duplicate ticker")).toBeInTheDocument());
  });

  // L121 arm0 (`ACCOUNTS[0]` truthy) — successful POST resets the form using first account.
  // Empty-holdings -> ACCOUNTS falls back to ["test",...] so ACCOUNTS[0] === "test" (truthy => arm0).
  it("handleAdd: successful POST resets form and closes it (ACCOUNTS[0] truthy)", async () => {
    mockFetch
      .mockReturnValueOnce(jsonRes({ holdings: [] })) // initial fetch
      .mockReturnValueOnce(jsonRes({ ok: true }, true)) // POST ok
      .mockReturnValueOnce(jsonRes({ holdings: [] })); // refetch
    render(<PortfolioPage />);
    await openAddForm();
    fireEvent.change(screen.getByPlaceholderText("Ticker (e.g. AAPL)"), { target: { value: "MSFT" } });
    fireEvent.change(screen.getByPlaceholderText("Quantity"), { target: { value: "3" } });
    fireEvent.change(screen.getByPlaceholderText("Avg Price"), { target: { value: "200" } });
    fireEvent.click(screen.getByText("Save"));
    // form closes on success -> "Add Holding" button text returns
    await waitFor(() => expect(screen.getByText("Add Holding")).toBeInTheDocument());
    expect(screen.queryByPlaceholderText("Ticker (e.g. AAPL)")).toBeNull();
  });

  // ── handleDelete ──
  // L129 arm0 (confirm false -> early return, no DELETE)
  it("handleDelete: early-returns when confirm cancelled", async () => {
    mockConfirm.mockReturnValue(false);
    get([holding({ ticker: "DEL", account: "test" })]);
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("DEL")).toBeInTheDocument());
    const before = mockFetch.mock.calls.filter((c) => c[1]?.method === "DELETE").length;
    fireEvent.click(screen.getByText("Delete"));
    expect(mockConfirm).toHaveBeenCalled();
    const after = mockFetch.mock.calls.filter((c) => c[1]?.method === "DELETE").length;
    expect(after).toBe(before);
  });

  // L129 arm1 (confirm true -> DELETE fires)
  it("handleDelete: fires DELETE when confirmed", async () => {
    mockConfirm.mockReturnValue(true);
    mockFetch
      .mockReturnValueOnce(jsonRes({ holdings: [holding({ ticker: "DEL2", account: "test" })] }))
      .mockReturnValueOnce(jsonRes({ ok: true })) // DELETE
      .mockReturnValueOnce(jsonRes({ holdings: [] })); // refetch
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("DEL2")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Delete"));
    await waitFor(() =>
      expect(mockFetch.mock.calls.some((c) => c[1]?.method === "DELETE")).toBe(true)
    );
  });

  // L140 arm1 (`row.sector || ""`) — startEdit with falsy sector
  it("startEdit: handles holding with empty sector", async () => {
    get([holding({ ticker: "NOSEC", account: "test", sector: "" })]);
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("NOSEC")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Edit"));
    // edit inputs appear
    await waitFor(() => expect(screen.getByDisplayValue("10")).toBeInTheDocument());
  });

  // ── saveEdit validation ──
  // L153 (`!qty || qty <= 0`)
  it("saveEdit: QTY_ERROR when quantity is 0", async () => {
    get([holding({ ticker: "EQ", account: "test", quantity: 10, avg_price: 100 })]);
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("EQ")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Edit"));
    const qty = await screen.findByDisplayValue("10");
    fireEvent.change(qty, { target: { value: "0" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(screen.getByText("Quantity must be positive")).toBeInTheDocument());
  });

  // L154 (`!avg || avg <= 0`)
  it("saveEdit: PRICE_ERROR when avg price is 0", async () => {
    get([holding({ ticker: "EP", account: "test", quantity: 10, avg_price: 100 })]);
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("EP")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Edit"));
    const avg = await screen.findByDisplayValue("100");
    fireEvent.change(avg, { target: { value: "0" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(screen.getByText("Price must be positive")).toBeInTheDocument());
  });

  // L165 arm1 (`data.detail || EDIT_FAILED`) + L422 truthy/matching arms — PUT fails, no detail
  it("saveEdit: EDIT_FAILED fallback and per-account error when PUT fails", async () => {
    mockFetch
      .mockReturnValueOnce(jsonRes({ holdings: [holding({ ticker: "EDT", account: "test", quantity: 10, avg_price: 100 })] }))
      .mockReturnValueOnce(jsonRes({}, false));
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("EDT")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Edit"));
    const qty = await screen.findByDisplayValue("10");
    fireEvent.change(qty, { target: { value: "20" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(screen.getByText("Edit failed")).toBeInTheDocument());
  });

  // L165 arm0 — PUT fails WITH detail
  it("saveEdit: uses server detail when PUT fails with detail", async () => {
    mockFetch
      .mockReturnValueOnce(jsonRes({ holdings: [holding({ ticker: "EDT2", account: "test", quantity: 10, avg_price: 100 })] }))
      .mockReturnValueOnce(jsonRes({ detail: "Locked position" }, false));
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("EDT2")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Edit"));
    const qty = await screen.findByDisplayValue("10");
    fireEvent.change(qty, { target: { value: "20" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(screen.getByText("Locked position")).toBeInTheDocument());
  });

  // L165 success path — PUT ok closes edit mode (covers !res.ok false arm)
  it("saveEdit: successful PUT closes edit mode", async () => {
    mockFetch
      .mockReturnValueOnce(jsonRes({ holdings: [holding({ ticker: "EDOK", account: "test", quantity: 10, avg_price: 100 })] }))
      .mockReturnValueOnce(jsonRes({ ok: true }, true)) // PUT ok
      .mockReturnValueOnce(jsonRes({ holdings: [holding({ ticker: "EDOK", account: "test", quantity: 20, avg_price: 100 })] }));
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("EDOK")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Edit"));
    const qty = await screen.findByDisplayValue("10");
    fireEvent.change(qty, { target: { value: "20" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(screen.getByText("Edit")).toBeInTheDocument());
  });

  // L422 cancelEdit — covers the Cancel button branch
  it("cancelEdit: exits edit mode without saving", async () => {
    get([holding({ ticker: "CAN", account: "test", quantity: 10, avg_price: 100 })]);
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("CAN")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Edit"));
    await screen.findByDisplayValue("10");
    fireEvent.click(screen.getByText("Cancel"));
    await waitFor(() => expect(screen.getByText("Edit")).toBeInTheDocument());
  });

  // ── handleImport ──
  // L177 (no file -> early return)
  it("handleImport: early-returns when no file selected", async () => {
    get([]);
    render(<PortfolioPage />);
    await waitFor(() => screen.getByText("Upload CSV"));
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const before = mockFetch.mock.calls.filter((c) => typeof c[0] === "string" && c[0].includes("/import")).length;
    fireEvent.change(fileInput, { target: { files: [] } });
    const after = mockFetch.mock.calls.filter((c) => typeof c[0] === "string" && c[0].includes("/import")).length;
    expect(after).toBe(before);
  });

  // L185 arm1 (`data.errors || []`) — successful import without `errors` key
  it("handleImport: falls back to [] errors on success with no errors key", async () => {
    mockFetch
      .mockReturnValueOnce(jsonRes({ holdings: [] }))
      .mockReturnValueOnce(jsonRes({ imported: 4 }, true)) // no errors key
      .mockReturnValueOnce(jsonRes({ holdings: [] }));
    render(<PortfolioPage />);
    await waitFor(() => screen.getByText("Upload CSV"));
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["a,b"], "p.csv", { type: "text/csv" });
    fireEvent.change(fileInput, { target: { files: [file] } });
    await waitFor(() => expect(screen.getByText(/4 holdings imported/i)).toBeInTheDocument());
  });

  // L354 arm1 (`errors.length > 5` -> "...and N more") + L185 arm0 (errors present)
  it("handleImport: shows '...and N more' when more than 5 errors", async () => {
    const errors = ["e1", "e2", "e3", "e4", "e5", "e6", "e7"];
    mockFetch
      .mockReturnValueOnce(jsonRes({ holdings: [] }))
      .mockReturnValueOnce(jsonRes({ imported: 0, errors }, true))
      .mockReturnValueOnce(jsonRes({ holdings: [] }));
    render(<PortfolioPage />);
    await waitFor(() => screen.getByText("Upload CSV"));
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["a,b"], "p.csv", { type: "text/csv" });
    fireEvent.change(fileInput, { target: { files: [file] } });
    await waitFor(() => expect(screen.getByText(/and 2 more errors/i)).toBeInTheDocument());
  });

  // L188 arm1 (`data.detail || "Import failed"`) — failed import without detail
  it("handleImport: 'Import failed' fallback when import fails with no detail", async () => {
    mockFetch
      .mockReturnValueOnce(jsonRes({ holdings: [] }))
      .mockReturnValueOnce(jsonRes({}, false));
    render(<PortfolioPage />);
    await waitFor(() => screen.getByText("Upload CSV"));
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["a,b"], "p.csv", { type: "text/csv" });
    fireEvent.change(fileInput, { target: { files: [file] } });
    await waitFor(() => expect(screen.getByText("Import failed")).toBeInTheDocument());
  });

  // L188 arm0 — failed import WITH detail
  it("handleImport: uses server detail when import fails with detail", async () => {
    mockFetch
      .mockReturnValueOnce(jsonRes({ holdings: [] }))
      .mockReturnValueOnce(jsonRes({ detail: "Bad CSV header" }, false));
    render(<PortfolioPage />);
    await waitFor(() => screen.getByText("Upload CSV"));
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["a,b"], "p.csv", { type: "text/csv" });
    fireEvent.change(fileInput, { target: { files: [file] } });
    await waitFor(() => expect(screen.getByText("Bad CSV header")).toBeInTheDocument());
  });

  // ── render branches ──
  // L218/L233 arm1 (`v?.toLocaleString`) — nullish qty/avg cells
  it("renders nullish quantity and avg_price cells", async () => {
    get([holding({ ticker: "NUL", quantity: null, avg_price: null, latest_price: null })]);
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("NUL")).toBeInTheDocument());
  });

  // L239 arm0 (`currency === "KRW"` true -> "₩") and arm1 ($ for USD)
  it("renders KRW currency symbol for Current price", async () => {
    get([holding({ ticker: "KRW1", currency: "KRW", latest_price: 5000, avg_price: 4000 })]);
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("KRW1")).toBeInTheDocument());
    const cells = Array.from(document.querySelectorAll("td"));
    expect(cells.some((c) => (c.textContent ?? "").includes("₩5,000"))).toBe(true);
  });

  it("renders USD currency symbol for Current price", async () => {
    get([holding({ ticker: "USD1", currency: "USD", latest_price: 250, avg_price: 100 })]);
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("USD1")).toBeInTheDocument());
    const cells = Array.from(document.querySelectorAll("td"));
    expect(cells.some((c) => (c.textContent ?? "").includes("$250"))).toBe(true);
  });

  // L239 arm (latest_price falsy -> "—") + L244 (P&L early return "—")
  it("renders dash for missing latest_price in Current and P&L", async () => {
    get([holding({ ticker: "NOLP", latest_price: null })]);
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("NOLP")).toBeInTheDocument());
    const cells = Array.from(document.querySelectorAll("td"));
    expect(cells.filter((c) => c.textContent === "—").length).toBeGreaterThanOrEqual(2);
  });

  // L247/L248 — negative P&L (red, no "+")
  it("renders negative P&L with red class", async () => {
    get([holding({ ticker: "DOWN", avg_price: 100, latest_price: 50 })]);
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("DOWN")).toBeInTheDocument());
    const span = Array.from(document.querySelectorAll("span")).find((s) => s.textContent === "-50.0%")!;
    expect(span).toBeTruthy();
    expect(span.className).toContain("text-red-400");
    expect(span.textContent).not.toContain("+");
  });

  // L247/L248 — positive P&L (emerald, "+")
  it("renders positive P&L with emerald class and plus sign", async () => {
    get([holding({ ticker: "UP", avg_price: 100, latest_price: 150 })]);
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("UP")).toBeInTheDocument());
    const span = Array.from(document.querySelectorAll("span")).find((s) => s.textContent === "+50.0%")!;
    expect(span).toBeTruthy();
    expect(span.className).toContain("text-emerald-400");
  });

  // ── empty-state / onboarding ──
  // L366 arm0 (isOnboarding true) + L369 (Welcome banner) + L402 (loadingSample)
  it("renders onboarding banner and loads sample portfolio", async () => {
    mockGet.mockImplementation((k: string) => (k === "onboarding" ? "true" : null));
    mockFetch
      .mockReturnValueOnce(jsonRes({ holdings: [] })) // initial empty
      .mockReturnValueOnce(jsonRes({ ok: true })) // POST sample
      .mockReturnValueOnce(jsonRes({ holdings: [] })); // refetch
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText(/Welcome to Nuri-Quant/i)).toBeInTheDocument());
    fireEvent.click(screen.getByText("Load Sample Portfolio"));
    // loadingSample true -> button text becomes "Loading..."
    await waitFor(() =>
      expect(mockFetch.mock.calls.some((c) => typeof c[0] === "string" && c[0].includes("/sample"))).toBe(true)
    );
  });

  // L366 arm (isOnboarding false) — empty state without banner
  it("renders empty state without onboarding banner when flag absent", async () => {
    mockGet.mockReturnValue(null);
    get([]);
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText(/Start by adding/i)).toBeInTheDocument());
    expect(screen.queryByText(/Welcome to Nuri-Quant/i)).toBeNull();
  });

  // ── sort reducer fallbacks (L410 aVal / L411 bVal) ──
  // Comparator is Object.entries(grouped).sort(([,a],[,b]) => ...). For a 2-element
  // array V8 calls it once with a=entries[0], b=entries[1]. Insertion order of `grouped`
  // follows holdings order, so the FIRST holding's account becomes `a` and the SECOND
  // becomes `b`. Putting an all-falsy account first then second exercises both reducers'
  // `quantity || 0` and `latest_price || avg_price || 0` (incl. the final `|| 0`) arms.
  it("sorts accounts handling falsy quantity / latest_price / avg_price on both sides", async () => {
    get([
      // entries[0] -> aVal side: all falsy (quantity 0, no latest_price, no avg_price)
      holding({ ticker: "A1", account: "alpha", quantity: 0, latest_price: null, avg_price: null }),
      // entries[1] -> bVal side: all falsy too -> hits L411 `|| 0` (arm2)
      holding({ ticker: "B1", account: "beta", quantity: 0, latest_price: null, avg_price: null }),
    ]);
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("A1")).toBeInTheDocument());
    expect(screen.getByText("B1")).toBeInTheDocument();
  });

  // Mixed account exercising the latest_price-present and avg_price-fallback arms.
  it("sorts accounts using latest_price then avg_price fallback", async () => {
    get([
      holding({ ticker: "C1", account: "ca", quantity: 10, latest_price: 200, avg_price: 100 }),
      holding({ ticker: "D1", account: "cb", quantity: 5, latest_price: null, avg_price: 50 }),
    ]);
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("C1")).toBeInTheDocument());
    expect(screen.getByText("D1")).toBeInTheDocument();
  });

  // L422 false-side: editError truthy but a non-matching account block does NOT render it
  it("does not show edit error under a non-matching account block", async () => {
    mockFetch
      .mockReturnValueOnce(
        jsonRes({
          holdings: [
            holding({ ticker: "AAA", account: "alpha", quantity: 10, avg_price: 100, latest_price: 200 }),
            holding({ ticker: "BBB", account: "beta", quantity: 10, avg_price: 100, latest_price: 50 }),
          ],
        })
      )
      .mockReturnValueOnce(jsonRes({}, false)); // PUT fails
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("AAA")).toBeInTheDocument());
    const editButtons = screen.getAllByText("Edit");
    fireEvent.click(editButtons[0]); // edit alpha
    const qty = await screen.findByDisplayValue("10");
    fireEvent.change(qty, { target: { value: "20" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(screen.getByText("Edit failed")).toBeInTheDocument());
    expect(screen.getAllByText("Edit failed")).toHaveLength(1);
  });
});
