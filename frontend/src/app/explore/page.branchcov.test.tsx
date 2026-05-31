import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

// next/navigation: page.tsx import chain (search.tsx) 가 useRouter() 호출
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));

// next/link → 단순 anchor (recharts 미사용 — hoist gotcha 무관)
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// @/lib/api fetchAPI: 엔드포인트별 응답 주입
const fetchAPIMock = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => fetchAPIMock(...args),
}));

import { RecentSignals } from "./page";
import { signalKo } from "./helpers";

beforeEach(() => {
  fetchAPIMock.mockReset();
});

// page.coverage.test.tsx 가 60/61 branch 커버.
// 남은 1개: line 141 `signalKo(c.signal_id ?? "")` 의 `?? ""` 우변 —
// signal_id 가 nullish 일 때만 실행. 기존 fixture 는 항상 string 을 줘서 미커버.
// async RSC 라 부모 <Page/> 렌더로는 children 이 jsdom 에서 resolve 안 됨 →
// export 한 RecentSignals 를 직접 await + render.
describe("RecentSignals — signal_id nullish fallback (line 141 `?? \"\"`)", () => {
  it("renders empty signal label when candidate.signal_id is missing (triggers `?? \"\"`)", async () => {
    fetchAPIMock.mockResolvedValue({
      candidates: [
        // signal_id 명시 → 좌변(truthy) arm + 알려진 매핑
        { ticker: "AAPL", direction: "BUY", signal_id: "rsi_oversold", confidence: 0.9 },
        // signal_id 누락 → `c.signal_id ?? ""` 우변 fallback arm
        { ticker: "MSFT", direction: "HOLD", confidence: 0.5 },
      ],
    });

    const jsx = await RecentSignals();
    const { container } = render(jsx);

    // 알려진 signal 은 한국어 라벨로 렌더 (좌변 arm 동작 확인)
    expect(container).toHaveTextContent(signalKo("rsi_oversold"));

    // signal_id 누락 카드: `?? ""` → signalKo("") === "" → signal-label span 은 빈 텍스트.
    // signalKo("") 가 "" 임을 명시적으로 검증 (fallback 결과의 정확성).
    expect(signalKo("")).toBe("");

    // MSFT 카드의 두 번째 span(시그널 라벨)이 비어 있는지 확인
    const msftLink = Array.from(container.querySelectorAll("a")).find((a) =>
      a.getAttribute("href")?.includes("MSFT"),
    );
    expect(msftLink).toBeDefined();
    const labelSpans = msftLink!.querySelectorAll("span");
    // span[0] = ticker, span[1] = signalKo(fallback) === ""
    expect(labelSpans[1]?.textContent).toBe("");
  });
});
