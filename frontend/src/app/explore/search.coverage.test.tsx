import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ExploreSearch } from "@/app/explore/search";

// next/navigation mock — capture router.push calls
const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

// Real timers throughout — the 250ms debounce resolves well within the
// default 5s test timeout, and waitFor relies on real timers internally.
function mockFetchOk(results: unknown[]) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ results }),
  });
}

describe("ExploreSearch (coverage)", () => {
  beforeEach(() => {
    pushMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("renders the search input", () => {
    render(<ExploreSearch />);
    expect(screen.getByTestId("explore-search-input")).toBeInTheDocument();
  });

  it("debounced fetch populates results and opens dropdown (US + KR price formatting)", async () => {
    const results = [
      { ticker: "AAPL", name: "Apple Inc", price: 250.5, date: "2026-05-30" }, // >=100 -> rounded
      { ticker: "MSFT", name: null, price: 42.123, date: null }, // <100 -> toFixed(2), no name
      { ticker: "005930.KS", name: "Samsung", price: 71234.7, date: null }, // KR -> ₩ rounded
      { ticker: "035720.KQ", name: "KosdaqCo", price: null, date: null }, // KR, null price -> no priceStr
    ];
    const fetchMock = mockFetchOk(results);
    vi.stubGlobal("fetch", fetchMock);

    render(<ExploreSearch />);
    const input = screen.getByTestId("explore-search-input");
    fireEvent.change(input, { target: { value: "a" } });

    await waitFor(() => {
      expect(screen.getByTestId("explore-search-dropdown")).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/tickers/search?q=a");
    expect(screen.getByTestId("search-result-AAPL")).toBeInTheDocument();
    expect(screen.getByText("$251")).toBeInTheDocument(); // rounded >=100
    expect(screen.getByText("$42.12")).toBeInTheDocument(); // toFixed(2) <100
    expect(screen.getByText("₩71,235")).toBeInTheDocument(); // KR rounded
    expect(screen.getByText("Apple Inc")).toBeInTheDocument();
  });

  it("selecting a result navigates to the ticker page", async () => {
    const fetchMock = mockFetchOk([
      { ticker: "AAPL", name: "Apple Inc", price: 250, date: null },
    ]);
    vi.stubGlobal("fetch", fetchMock);

    render(<ExploreSearch />);
    fireEvent.change(screen.getByTestId("explore-search-input"), {
      target: { value: "aapl" },
    });
    await waitFor(() => screen.getByTestId("search-result-AAPL"));

    fireEvent.click(screen.getByTestId("search-result-AAPL"));
    expect(pushMock).toHaveBeenCalledWith("/ticker/AAPL");
  });

  it("Enter key navigates directly using uppercased trimmed query", () => {
    vi.stubGlobal("fetch", mockFetchOk([]));
    render(<ExploreSearch />);
    const input = screen.getByTestId("explore-search-input");
    fireEvent.change(input, { target: { value: "  msft  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(pushMock).toHaveBeenCalledWith("/ticker/MSFT");
  });

  it("Enter key with blank query does nothing", () => {
    vi.stubGlobal("fetch", mockFetchOk([]));
    render(<ExploreSearch />);
    fireEvent.keyDown(screen.getByTestId("explore-search-input"), { key: "Enter" });
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("Escape key closes the dropdown", async () => {
    const fetchMock = mockFetchOk([
      { ticker: "AAPL", name: "Apple Inc", price: 250, date: null },
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<ExploreSearch />);
    const input = screen.getByTestId("explore-search-input");
    fireEvent.change(input, { target: { value: "aapl" } });
    await waitFor(() => screen.getByTestId("explore-search-dropdown"));

    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByTestId("explore-search-dropdown")).not.toBeInTheDocument();
    });
  });

  it("empty query resets results and closes dropdown", async () => {
    const fetchMock = mockFetchOk([
      { ticker: "AAPL", name: "Apple Inc", price: 250, date: null },
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<ExploreSearch />);
    const input = screen.getByTestId("explore-search-input");
    fireEvent.change(input, { target: { value: "aapl" } });
    await waitFor(() => screen.getByTestId("explore-search-dropdown"));

    // clearing the query hits the length===0 branch (setResults([]), setOpen(false), return)
    fireEvent.change(input, { target: { value: "" } });
    await waitFor(() => {
      expect(screen.queryByTestId("explore-search-dropdown")).not.toBeInTheDocument();
    });
  });

  it("shows NO_RESULTS when fetch returns an empty list", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}), // no results key -> ?? [] fallback
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ExploreSearch />);
    fireEvent.change(screen.getByTestId("explore-search-input"), {
      target: { value: "zzz" },
    });
    await waitFor(() => screen.getByTestId("explore-search-dropdown"));
    // empty results + not loading -> NO_RESULTS paragraph branch (data.results ?? [])
    expect(screen.getByTestId("explore-search-dropdown").querySelector("p")).toBeTruthy();
  });

  it("fetch rejection is caught and results are cleared (line 51 catch)", async () => {
    // First open dropdown with a successful result, then make next fetch reject.
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ results: [{ ticker: "AAPL", name: "Apple Inc", price: 250, date: null }] }),
      })
      .mockRejectedValueOnce(new Error("network down"));
    vi.stubGlobal("fetch", fetchMock);

    render(<ExploreSearch />);
    const input = screen.getByTestId("explore-search-input");
    fireEvent.change(input, { target: { value: "aa" } });
    await waitFor(() => screen.getByTestId("search-result-AAPL"));

    fireEvent.change(input, { target: { value: "aab" } });
    // catch -> setResults([]); the previously rendered result disappears
    await waitFor(() => {
      expect(screen.queryByTestId("search-result-AAPL")).not.toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("non-ok response leaves dropdown closed (skips setOpen)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    render(<ExploreSearch />);
    fireEvent.change(screen.getByTestId("explore-search-input"), {
      target: { value: "x" },
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByTestId("explore-search-dropdown")).not.toBeInTheDocument();
  });

  it("onFocus opens dropdown when results already exist", async () => {
    const fetchMock = mockFetchOk([
      { ticker: "AAPL", name: "Apple Inc", price: 250, date: null },
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<ExploreSearch />);
    const input = screen.getByTestId("explore-search-input");
    fireEvent.change(input, { target: { value: "aapl" } });
    await waitFor(() => screen.getByTestId("explore-search-dropdown"));

    // close via Escape then refocus -> onFocus branch with results.length > 0
    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByTestId("explore-search-dropdown")).not.toBeInTheDocument();
    });
    fireEvent.focus(input);
    await waitFor(() => {
      expect(screen.getByTestId("explore-search-dropdown")).toBeInTheDocument();
    });
  });

  it("outside mousedown closes dropdown; inside mousedown keeps it open (line 27 both branches)", async () => {
    const fetchMock = mockFetchOk([
      { ticker: "AAPL", name: "Apple Inc", price: 250, date: null },
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<ExploreSearch />);
    fireEvent.change(screen.getByTestId("explore-search-input"), {
      target: { value: "aapl" },
    });
    await waitFor(() => screen.getByTestId("explore-search-dropdown"));

    // mousedown INSIDE the component -> ref.current.contains(target) true -> stays open
    fireEvent.mouseDown(screen.getByTestId("explore-search"));
    expect(screen.getByTestId("explore-search-dropdown")).toBeInTheDocument();

    // mousedown OUTSIDE -> contains() false -> setOpen(false)
    fireEvent.mouseDown(document.body);
    await waitFor(() => {
      expect(screen.queryByTestId("explore-search-dropdown")).not.toBeInTheDocument();
    });
  });
});
