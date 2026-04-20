/**
 * CertificationsCardLazy — next/dynamic wrapper smoke.
 *
 * Dynamic import 의 실제 ssr:false 동작은 Next.js runtime 에서만 검증 가능
 * (vitest/jsdom 은 suspend 안 됨). 여기서는 `next/dynamic` 을 identity
 * passthrough 로 mock 해서 (a) wrapper 가 inner 컴포넌트를 마운트하고
 * (b) props 가 그대로 전달되는 것만 검증.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// next/dynamic 을 identity 로 mock — loader 는 Promise 를 반환하지만
// 본 테스트는 Promise 해결을 기다릴 수 없으므로 즉시 resolve 된 것처럼
// passthrough 하는 stub 컴포넌트를 리턴.
vi.mock("next/dynamic", () => ({
  default: () => {
    const Stub = (props: Record<string, unknown>) => (
      <div data-testid="dynamic-stub">
        <span data-testid="stub-has-history">{String("history" in props)}</span>
        <span data-testid="stub-has-summary">{String("summary" in props)}</span>
      </div>
    );
    return Stub;
  },
}));

import { CertificationsCardLazy } from "@/components/ui/certifications-card-lazy";

describe("CertificationsCardLazy", () => {
  it("exports a component function", () => {
    expect(typeof CertificationsCardLazy).toBe("function");
  });

  it("renders the dynamic stub and passes history/summary props through", () => {
    render(
      <CertificationsCardLazy
        history={{ items: [], count: 0, total_in_db: 0 }}
        summary={{
          days: 30,
          count: 0,
          certified_rate: null,
          avg_score: null,
          by_caller: {},
          by_regime: {},
          latest: null,
        }}
      />,
    );
    expect(screen.getByTestId("dynamic-stub")).toBeInTheDocument();
    expect(screen.getByTestId("stub-has-history").textContent).toBe("true");
    expect(screen.getByTestId("stub-has-summary").textContent).toBe("true");
  });
});
