import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// Mock next/navigation — shared mock push for assertion
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  usePathname: () => "/explore",
  useSearchParams: () => new URLSearchParams(),
}));

// Mock @/lib/api
vi.mock("@/lib/api", () => ({
  fetchAPI: vi.fn().mockResolvedValue({}),
  API_BASE: "http://localhost:8001",
}));

// Mock lucide-react
vi.mock("lucide-react", () => {
  const Icon = (props: Record<string, unknown>) => <svg data-testid="icon" {...props} />;
  return { Search: Icon };
});

describe("ExploreSearch component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn();
  });

  it("renders search input with placeholder", async () => {
    const { ExploreSearch } = await import("@/app/explore/search");
    render(<ExploreSearch />);

    const input = screen.getByTestId("explore-search-input");
    expect(input).toBeDefined();
    expect(input.getAttribute("placeholder")).toContain("종목 검색");
  });

  it("shows dropdown on search results", async () => {
    (global.fetch as unknown as Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        results: [
          { ticker: "NVDA", name: "NVIDIA", price: 185.0, date: "2026-04-10" },
        ],
        count: 1,
      }),
    });

    const { ExploreSearch } = await import("@/app/explore/search");
    render(<ExploreSearch />);

    const input = screen.getByTestId("explore-search-input");
    fireEvent.change(input, { target: { value: "NVDA" } });

    await waitFor(
      () => {
        const dropdown = screen.queryByTestId("explore-search-dropdown");
        expect(dropdown).toBeTruthy();
      },
      { timeout: 2000 },
    );
  });

  it("shows no results message when search returns empty", async () => {
    (global.fetch as unknown as Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ results: [], count: 0 }),
    });

    const { ExploreSearch } = await import("@/app/explore/search");
    render(<ExploreSearch />);

    const input = screen.getByTestId("explore-search-input");
    fireEvent.change(input, { target: { value: "XYZZZZ" } });

    await waitFor(
      () => {
        const dropdown = screen.queryByTestId("explore-search-dropdown");
        expect(dropdown).toBeTruthy();
      },
      { timeout: 2000 },
    );
  });

  it("navigates on Enter key", async () => {
    const { ExploreSearch } = await import("@/app/explore/search");
    render(<ExploreSearch />);

    const input = screen.getByTestId("explore-search-input");
    fireEvent.change(input, { target: { value: "TSLA" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(mockPush).toHaveBeenCalledWith("/ticker/TSLA");
  });

  it("closes dropdown on Escape key", async () => {
    (global.fetch as unknown as Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        results: [{ ticker: "NVDA", name: "NVIDIA", price: 185, date: "2026-04-10" }],
        count: 1,
      }),
    });

    const { ExploreSearch } = await import("@/app/explore/search");
    render(<ExploreSearch />);

    const input = screen.getByTestId("explore-search-input");
    fireEvent.change(input, { target: { value: "NVDA" } });

    await waitFor(() => {
      expect(screen.queryByTestId("explore-search-dropdown")).toBeTruthy();
    }, { timeout: 2000 });

    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByTestId("explore-search-dropdown")).toBeNull();
  });

  it("navigates on result click", async () => {
    (global.fetch as unknown as Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        results: [{ ticker: "AAPL", name: "Apple", price: 220, date: "2026-04-10" }],
        count: 1,
      }),
    });

    const { ExploreSearch } = await import("@/app/explore/search");
    render(<ExploreSearch />);

    const input = screen.getByTestId("explore-search-input");
    fireEvent.change(input, { target: { value: "AAPL" } });

    await waitFor(() => {
      expect(screen.queryByTestId("search-result-AAPL")).toBeTruthy();
    }, { timeout: 2000 });

    fireEvent.click(screen.getByTestId("search-result-AAPL"));
    expect(mockPush).toHaveBeenCalledWith("/ticker/AAPL");
  });

  it("shows KR price format in dropdown", async () => {
    (global.fetch as unknown as Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        results: [{ ticker: "005930.KS", name: "삼성전자", price: 206000, date: "2026-04-10" }],
        count: 1,
      }),
    });

    const { ExploreSearch } = await import("@/app/explore/search");
    render(<ExploreSearch />);

    fireEvent.change(screen.getByTestId("explore-search-input"), { target: { value: "삼성" } });

    await waitFor(() => {
      expect(screen.queryByTestId("search-result-005930.KS")).toBeTruthy();
    }, { timeout: 2000 });

    const result = screen.getByTestId("search-result-005930.KS");
    expect(result.textContent).toContain("삼성전자");
    expect(result.textContent).toContain("₩");
  });

  it("clears results when input is emptied", async () => {
    (global.fetch as unknown as Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        results: [{ ticker: "NVDA", name: "NVIDIA", price: 185, date: "2026-04-10" }],
        count: 1,
      }),
    });

    const { ExploreSearch } = await import("@/app/explore/search");
    render(<ExploreSearch />);

    const input = screen.getByTestId("explore-search-input");
    fireEvent.change(input, { target: { value: "NVDA" } });

    await waitFor(() => {
      expect(screen.queryByTestId("explore-search-dropdown")).toBeTruthy();
    }, { timeout: 2000 });

    fireEvent.change(input, { target: { value: "" } });
    expect(screen.queryByTestId("explore-search-dropdown")).toBeNull();
  });

  it("handles fetch error gracefully (covers catch branch)", async () => {
    (global.fetch as unknown as Mock).mockRejectedValueOnce(new Error("Network error"));

    const { ExploreSearch } = await import("@/app/explore/search");
    render(<ExploreSearch />);

    const input = screen.getByTestId("explore-search-input");
    fireEvent.change(input, { target: { value: "NVDA" } });

    // Wait for debounce + catch to fire
    await waitFor(() => {
      // After error, results should be empty and dropdown closed
      expect(screen.queryByTestId("explore-search-dropdown")).toBeNull();
    }, { timeout: 2000 });
  });

  it("onFocus does not open dropdown when no results", async () => {
    const { ExploreSearch } = await import("@/app/explore/search");
    render(<ExploreSearch />);

    const input = screen.getByTestId("explore-search-input");
    // Focus with no prior search — should NOT open dropdown
    fireEvent.focus(input);
    expect(screen.queryByTestId("explore-search-dropdown")).toBeNull();
  });

  // outside click is tested by Playwright E2E (jsdom doesn't reliably support ref.contains)
});

describe("Explore page strings", () => {
  it("EXPLORE strings are properly exported", async () => {
    const { EXPLORE } = await import("@/lib/strings");
    expect(EXPLORE.SEARCH_PLACEHOLDER).toContain("종목 검색");
    expect(EXPLORE.US_POPULAR).toBe("US 인기 종목");
    expect(EXPLORE.KR_POPULAR).toBe("KR 인기 종목");
    expect(EXPLORE.NO_RESULTS).toContain("일치하는");
    expect(EXPLORE.LOAD_SAMPLE).toContain("sample");
    expect(EXPLORE.NO_PRICE).toBe("미수집");
    expect(EXPLORE.COLLECT_HINT).toContain("make scan-extended");
  });

  it("REGIME_GUIDE has all trend keys", async () => {
    const { REGIME_GUIDE } = await import("@/lib/strings");
    expect(REGIME_GUIDE.bull).toContain("매수");
    expect(REGIME_GUIDE.bear).toContain("방어");
    expect(REGIME_GUIDE.sideways).toContain("관망");
  });

  it("SIGNAL constants cover all signal IDs", async () => {
    const { SIGNAL } = await import("@/lib/strings");
    const ids = ["BB_BOUNCE", "MACD_BULLISH_TURN", "MACD_BEARISH_TURN", "MACD_GOLDEN", "MACD_DEAD",
      "RSI_OVERSOLD", "RSI_OVERBOUGHT", "SMA_GOLDEN", "SMA_DEAD", "VOLUME_SPIKE",
      "GAP_UP", "GAP_DOWN", "BB_SQUEEZE_BREAKOUT", "NEAR_52W_LOW_BOUNCE", "VOLUME_PROFILE_RESISTANCE"];
    for (const id of ids) {
      expect((SIGNAL as Record<string, unknown>)[id]).toBeTruthy();
    }
  });

  it("PIPELINE strings are properly exported", async () => {
    const { PIPELINE } = await import("@/lib/strings");
    expect(PIPELINE.LEGEND_OK).toBe("정상");
    expect(PIPELINE.LEGEND_ERROR).toBe("에러");
    expect(PIPELINE.AUTO_REFRESH).toContain("자동");
  });

  it("TICKER_DETAIL strings cover price targets", async () => {
    const { TICKER_DETAIL } = await import("@/lib/strings");
    expect(TICKER_DETAIL.STOP_LOSS).toBe("손절가");
    expect(TICKER_DETAIL.TARGET_1).toBe("1차 익절");
    expect(TICKER_DETAIL.TARGET_2).toBe("2차 익절");
    expect(TICKER_DETAIL.TRAILING).toBe("트레일링");
    expect(TICKER_DETAIL.ANALYST).toBe("애널리스트");
  });
});
