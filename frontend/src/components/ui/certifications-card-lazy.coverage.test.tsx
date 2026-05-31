import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  CertificationsListResponse,
  CertificationsSummary,
} from "@/components/ui/certifications-card";

import { CertificationsCardLazy } from "@/components/ui/certifications-card-lazy";

// 핵심: 기존 certifications-card-lazy.test.tsx 는 next/dynamic 을 identity 로
// mock 해서 loader factory (line 22) 와 loading fallback (line 26) 이 실행되지
// 않아 statement 가 50% 에 머문다. 이 파일은 next/dynamic 을 mock 하지 않고
// (실제 next/dynamic 사용), 내부 './certifications-card' 모듈만 가벼운 stub 으로
// 대체해 dynamic() 이 loader 를 실제로 호출 → lazy resolve 까지 돌게 한다.
vi.mock("@/components/ui/certifications-card", () => ({
  CertificationsCard: (props: Record<string, unknown>) => (
    <div data-testid="resolved-card">{Object.keys(props).length} props</div>
  ),
}));

// 중립 placeholder props (실거래 데이터 아님 — public repo 규칙 준수)
const summary: CertificationsSummary = {
  total: 2,
  pass: 1,
  reject: 1,
  rate: 0.5,
} as unknown as CertificationsSummary;

const history: CertificationsListResponse = {
  items: [],
} as unknown as CertificationsListResponse;

describe("CertificationsCardLazy (coverage)", () => {
  it("renders the loading fallback then resolves the dynamic CertificationsCard", async () => {
    render(<CertificationsCardLazy history={history} summary={summary} />);

    // next/dynamic loader 가 실제로 호출되어 stub 모듈이 mount 된다.
    await waitFor(() => {
      expect(screen.getByTestId("resolved-card")).toBeInTheDocument();
    });

    // history + summary 두 prop 이 lazy child 로 그대로 전달되었는지 확인
    expect(screen.getByTestId("resolved-card")).toHaveTextContent("2 props");
  });
});
