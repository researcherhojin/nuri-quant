import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ExploreSearch } from "@/app/explore/search";
import { EXPLORE } from "@/lib/strings";

// next/navigation mock — router.push 캡처
const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

describe("ExploreSearch (branch coverage — loading arm L91)", () => {
  beforeEach(() => {
    pushMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  // 250ms 디바운스 setTimeout 발화 → setLoading(true). fetch 가 pending 인 동안
  // finally{setLoading(false)} 가 돌지 않아 L91 `{loading && (...)}` truthy arm 이 렌더된다.
  // 실타이머 + waitFor (기존 search.coverage.test.tsx 스타일과 일치).
  it("shows the loading indicator while a fetch is in flight", async () => {
    // 절대 resolve 되지 않는 fetch → loading 상태 유지
    const fetchMock = vi.fn(() => new Promise<Response>(() => {}));
    vi.stubGlobal("fetch", fetchMock);

    render(<ExploreSearch />);
    fireEvent.change(screen.getByTestId("explore-search-input"), {
      target: { value: "AAPL" },
    });

    // L91 truthy arm: 로딩 표시 span 렌더 검증
    await waitFor(() => {
      expect(screen.getByText(EXPLORE.LOADING)).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/tickers/search?q=AAPL");
  });
});
