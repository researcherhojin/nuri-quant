/**
 * Statement-coverage push for src/app/portfolio/page.tsx (#coverage/full-push).
 *
 * Targets the uncovered validation / early-return / error branches:
 *  - handleAdd: avg<=0 (L106), empty ticker (L107)
 *  - handleDelete: confirm() cancel early-return (L129)
 *  - saveEdit: qty<=0 (L153), avg<=0 (L154), !res.ok error path (L164-167)
 *  - handleImport: no-file early-return (L177)
 *
 * All branches are reachable through real user interactions — no v8-ignore needed.
 * No recharts import here, so the file-level recharts hoist gotcha does not apply.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import PortfolioPage from "@/app/portfolio/page";
import { PORTFOLIO } from "@/lib/strings";

vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: string; [k: string]: unknown }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

// Neutral placeholder holdings — no real tickers/accounts/prices (public repo).
const HOLDINGS = [
  {
    ticker: "AAPL",
    account: "Brokerage Alpha",
    quantity: 10,
    avg_price: 100,
    currency: "USD",
    sector: "Tech",
    latest_price: 120,
    price_date: "2026-01-01",
  },
];

function jsonResponse(body: unknown, ok = true) {
  return Promise.resolve({ ok, json: () => Promise.resolve(body) } as Response);
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  // Default GET /api/portfolio returns one holding so the table + Edit/Delete render.
  fetchMock.mockImplementation((url: string) => {
    if (typeof url === "string" && url.startsWith("/api/portfolio")) {
      return jsonResponse({ holdings: HOLDINGS });
    }
    return jsonResponse({});
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function renderLoaded() {
  await act(async () => {
    render(<PortfolioPage />);
  });
  await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
}

describe("portfolio page — validation & early-return coverage", () => {
  it("handleAdd surfaces PRICE_ERROR when avg price is 0 (L106)", async () => {
    await renderLoaded();
    fireEvent.click(screen.getByText("Add Holding"));

    fireEvent.change(screen.getByPlaceholderText("Ticker (e.g. AAPL)"), { target: { value: "MSFT" } });
    fireEvent.change(screen.getByPlaceholderText("Quantity"), { target: { value: "5" } });
    fireEvent.change(screen.getByPlaceholderText("Avg Price"), { target: { value: "0" } });

    const postBefore = fetchMock.mock.calls.filter((c) => c[1]?.method === "POST").length;
    await act(async () => {
      fireEvent.click(screen.getByText("Save"));
    });

    expect(await screen.findByText(PORTFOLIO.PRICE_ERROR)).toBeInTheDocument();
    const postAfter = fetchMock.mock.calls.filter((c) => c[1]?.method === "POST").length;
    expect(postAfter).toBe(postBefore); // POST not fired — early return
  });

  it("handleAdd surfaces TICKER_ERROR when ticker is blank (L107)", async () => {
    await renderLoaded();
    fireEvent.click(screen.getByText("Add Holding"));

    fireEvent.change(screen.getByPlaceholderText("Ticker (e.g. AAPL)"), { target: { value: "   " } });
    fireEvent.change(screen.getByPlaceholderText("Quantity"), { target: { value: "5" } });
    fireEvent.change(screen.getByPlaceholderText("Avg Price"), { target: { value: "150" } });

    await act(async () => {
      fireEvent.click(screen.getByText("Save"));
    });

    expect(await screen.findByText(PORTFOLIO.TICKER_ERROR)).toBeInTheDocument();
  });

  it("handleDelete early-returns when confirm() is cancelled (L129)", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    await renderLoaded();

    const deleteCallsBefore = fetchMock.mock.calls.filter((c) => c[1]?.method === "DELETE").length;
    await act(async () => {
      fireEvent.click(screen.getByText("Delete"));
    });

    const deleteCallsAfter = fetchMock.mock.calls.filter((c) => c[1]?.method === "DELETE").length;
    expect(deleteCallsAfter).toBe(deleteCallsBefore); // DELETE never fired
    expect(window.confirm).toHaveBeenCalled();
  });

  it("saveEdit surfaces QTY_ERROR when quantity is 0 (L153)", async () => {
    await renderLoaded();
    fireEvent.click(screen.getByText("Edit"));

    const qtyInput = screen.getByDisplayValue("10");
    fireEvent.change(qtyInput, { target: { value: "0" } });

    await act(async () => {
      fireEvent.click(screen.getByText("Save"));
    });

    expect(await screen.findByText(PORTFOLIO.QTY_ERROR)).toBeInTheDocument();
  });

  it("saveEdit surfaces PRICE_ERROR when avg price is 0 (L154)", async () => {
    await renderLoaded();
    fireEvent.click(screen.getByText("Edit"));

    // qty stays valid (10), zero out the avg_price field (initial value "100").
    const avgInput = screen.getByDisplayValue("100");
    fireEvent.change(avgInput, { target: { value: "0" } });

    await act(async () => {
      fireEvent.click(screen.getByText("Save"));
    });

    expect(await screen.findByText(PORTFOLIO.PRICE_ERROR)).toBeInTheDocument();
  });

  it("saveEdit surfaces detail on PUT failure (L164-167)", async () => {
    fetchMock.mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "PUT") {
        return jsonResponse({ detail: "boom" }, false);
      }
      if (typeof url === "string" && url.startsWith("/api/portfolio")) {
        return jsonResponse({ holdings: HOLDINGS });
      }
      return jsonResponse({});
    });

    await renderLoaded();
    fireEvent.click(screen.getByText("Edit"));
    // Leave qty/avg at their valid initial values (10 / 100) so we hit the PUT path.

    await act(async () => {
      fireEvent.click(screen.getByText("Save"));
    });

    expect(await screen.findByText("boom")).toBeInTheDocument();
  });

  it("handleImport early-returns when no file is selected (L177)", async () => {
    await renderLoaded();

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeTruthy();

    const importCallsBefore = fetchMock.mock.calls.filter((c) =>
      typeof c[0] === "string" && c[0].includes("/api/portfolio/import"),
    ).length;

    await act(async () => {
      fireEvent.change(fileInput, { target: { files: [] } });
    });

    const importCallsAfter = fetchMock.mock.calls.filter((c) =>
      typeof c[0] === "string" && c[0].includes("/api/portfolio/import"),
    ).length;
    expect(importCallsAfter).toBe(importCallsBefore); // import POST never fired
  });
});
