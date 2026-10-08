/**
 * #1750 — 탭은 라우터가 아니라 실제 브라우저 URL 을 따른다.
 *
 * `ticker-preview.test.tsx` 의 next/navigation mock 은 useSearchParams 가 window.location 을 늘
 * 정확히 따라가게 만들어져, 라우터가 popstate 를 놓치는 경우를 재현할 수 없었다. 여기서는
 * useSearchParams 를 옛 값에 고정한다 — CI 에서 뒤로 가기 후 15 초 동안 옛 탭에 머문 상황이다.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchTabs } from "@/app/ticker-next/[symbol]/research-tabs";
import { TICKER_PREVIEW as T } from "@/lib/strings";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams("tab=research") }));

afterEach(cleanup);

const tabs = () => (
  <ResearchTabs brief={<p>brief</p>} evidence={<p>evidence</p>} research={<p>research</p>} history={<p>history</p>} />
);

describe("ResearchTabs follows the browser URL, not only the router", () => {
  it("restores the tab on Back even when the router's search params stay stale", () => {
    window.history.replaceState(null, "", "/ticker-next/DEMO?tab=research");
    render(tabs());
    expect(screen.getByRole("tab", { name: T.RESEARCH })).toHaveAttribute("aria-selected", "true");
    window.history.replaceState(null, "", "/ticker-next/DEMO?tab=history");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(screen.getByRole("tab", { name: T.HISTORY })).toHaveAttribute("aria-selected", "true");
  });

  it("selecting a tab updates both the URL and the selection without the router", () => {
    window.history.replaceState(null, "", "/ticker-next/DEMO?tab=research");
    render(tabs());
    fireEvent.click(screen.getByRole("tab", { name: T.EVIDENCE }));
    expect(window.location.search).toBe("?tab=evidence");
    expect(screen.getByRole("tab", { name: T.EVIDENCE })).toHaveAttribute("aria-selected", "true");
  });
});
