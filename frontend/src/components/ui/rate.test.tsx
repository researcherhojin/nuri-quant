import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { Rate } from "./rate";
import { RATE } from "@/lib/strings";

// 실측 표본 (2026-09-06 dev DB): success 43 · failure 19 · neutral 15 · pending 568 · total 645.
// 이 숫자로 고정하는 이유는 회귀가 났을 때 "9.6% 로 계산된 69%" 라는 사고 자체가
// 테스트에 남아 있어야 하기 때문이다.
const REAL = { numerator: 43, denominator: 62, universe: 645, neutral: 15, pending: 568 };

describe("Rate — 분모 없이는 렌더되지 않는다 (#1429)", () => {
  it("비율과 분모를 함께 보인다", () => {
    render(
      <Rate label="Hit Rate" numerator={REAL.numerator} denominator={REAL.denominator} universe={REAL.universe} />,
    );
    expect(screen.getByText("69%")).toBeInTheDocument();
    expect(screen.getByText("43/62")).toBeInTheDocument();
  });

  it("커버리지를 모집단으로 분모 잡아 보인다 — 62/645 가 9.6%", () => {
    render(
      <Rate label="Hit Rate" numerator={REAL.numerator} denominator={REAL.denominator} universe={REAL.universe} />,
    );
    expect(screen.getByText(`62 / 645 ${RATE.ADJUDICATED} (9.6%)`)).toBeInTheDocument();
  });

  it("커버리지 바는 모집단 대비 폭을 갖는다 — 판정분이 아니라 전체가 분모", () => {
    const { container } = render(
      <Rate label="Hit Rate" numerator={REAL.numerator} denominator={REAL.denominator} universe={REAL.universe} />,
    );
    const fill = container.querySelector<HTMLElement>("[role=presentation] > div");
    // 62/645 = 9.61% — 100% 로 그리면(분모를 denominator 로 잡으면) 이 단언이 깨진다
    expect(fill?.style.width).toBe(`${(62 / 645) * 100}%`);
  });

  it("분모에서 빠진 것을 이름으로 밝힌다 — 조용한 탈락 금지", () => {
    render(
      <Rate
        label="Hit Rate"
        numerator={REAL.numerator}
        denominator={REAL.denominator}
        universe={REAL.universe}
        excluded={[
          { label: "중립", value: REAL.neutral },
          { label: "대기", value: REAL.pending },
        ]}
      />,
    );
    expect(screen.getByText(/중립 15/)).toBeInTheDocument();
    expect(screen.getByText(/대기 568/)).toBeInTheDocument();
  });

  it("0건 탈락 항목은 렌더하지 않는다", () => {
    render(
      <Rate
        label="Hit Rate"
        numerator={5}
        denominator={10}
        universe={10}
        excluded={[{ label: "중립", value: 0 }]}
      />,
    );
    expect(screen.queryByText(/중립/)).not.toBeInTheDocument();
  });

  it("모집단이 분모보다 크면 표본 미완결을 밝힌다", () => {
    render(<Rate label="Hit Rate" numerator={43} denominator={62} universe={645} />);
    expect(screen.getByText(RATE.OPEN_SAMPLE)).toBeInTheDocument();
  });

  it("표본이 닫히면 미완결 문구가 사라진다", () => {
    render(<Rate label="Hit Rate" numerator={6} denominator={10} universe={10} />);
    expect(screen.queryByText(RATE.OPEN_SAMPLE)).not.toBeInTheDocument();
  });

  it("분모 0 은 NaN 이 아니라 — 로 렌더한다", () => {
    render(<Rate label="Hit Rate" numerator={0} denominator={0} universe={0} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("모집단 0 이어도 바 폭이 NaN 이 되지 않는다", () => {
    const { container } = render(<Rate label="Hit Rate" numerator={0} denominator={0} universe={0} />);
    const fill = container.querySelector<HTMLElement>("[role=presentation] > div");
    expect(fill?.style.width).toBe("0%");
  });
});

describe("Rate — 색은 비율에 붙지 않는다 (#1429 회귀 잠금)", () => {
  // 이 스위트가 잠그는 사고: `successRate >= 50 ? "green" : "red"`.
  // 렌더 단언만으로는 부족하다 — 누군가 조건부 클래스를 되살려도 50% 이상 표본
  // 하나만 테스트하면 통과하므로, 양쪽 arm 을 다 렌더해 색이 **변하지 않음**을 본다.
  const hue = /text-(emerald|green|red|rose|amber)-/;

  it("50% 이상에서 성과색이 붙지 않는다", () => {
    const { container } = render(<Rate label="Hit Rate" numerator={9} denominator={10} universe={10} />);
    expect(container.innerHTML).not.toMatch(hue);
  });

  it("50% 미만에서도 성과색이 붙지 않는다", () => {
    const { container } = render(<Rate label="Hit Rate" numerator={1} denominator={10} universe={10} />);
    expect(container.innerHTML).not.toMatch(hue);
  });

  it("두 arm 의 비율 클래스가 동일하다 — 조건부 착색이 되살아나면 깨진다", () => {
    const high = render(<Rate label="Hit Rate" numerator={9} denominator={10} universe={10} />);
    const highCls = high.getByText("90%").className;
    high.unmount();
    const low = render(<Rate label="Hit Rate" numerator={1} denominator={10} universe={10} />);
    expect(low.getByText("10%").className).toBe(highCls);
  });
});

describe("decisions 페이지 배선 — 실제 요약값으로 렌더한다 (#1429)", () => {
  // codex P2: 소스 문자열 검사는 `universe` 가 **틀린 값에 배선돼도** 통과한다
  // (`universe={success+failure}` 로 바꾸면 커버리지가 100% 가 되는데 정규식은 그대로 매치).
  // 그래서 페이지를 실제 픽스처로 렌더해 화면에 나온 수치를 본다 — 배선 축의 잠금은
  // 컴포넌트 단독 테스트가 아니라 여기에 있다.
  const REAL_SUMMARY = { total: 645, pending: 568, success: 43, failure: 19, neutral: 15 };

  beforeEach(() => {
    vi.resetModules();
    vi.doMock("@/lib/api", () => ({
      fetchAPI: vi.fn().mockResolvedValue({ decisions: [], count: 0, summary: REAL_SUMMARY }),
    }));
    vi.doMock("next/navigation", () => ({ useRouter: () => ({}), useSearchParams: () => new URLSearchParams() }));
  });

  afterEach(() => {
    vi.doUnmock("@/lib/api");
    vi.doUnmock("next/navigation");
  });

  async function renderPage() {
    const { DecisionsSection } = await import("@/app/decisions/page");
    return render(await DecisionsSection());
  }

  it("커버리지를 모집단 645 로 분모 잡는다 — 판정분(62)으로 잡으면 깨진다", async () => {
    const { getByText } = await renderPage();
    expect(getByText(`62 / 645 ${RATE.ADJUDICATED} (9.6%)`)).toBeInTheDocument();
  });

  it("비율과 분모를 함께 보인다", async () => {
    const { getByText } = await renderPage();
    expect(getByText("69%")).toBeInTheDocument();
    expect(getByText(/43\/62/)).toBeInTheDocument();
  });

  it("탈락한 중립 15 · 대기 568 을 이름으로 밝힌다 — excluded 를 떼면 깨진다", async () => {
    const { getByText } = await renderPage();
    expect(getByText(/중립 15/)).toBeInTheDocument();
    expect(getByText(/대기 568/)).toBeInTheDocument();
  });

  it("Hit Rate 어디에도 성과색이 붙지 않는다", async () => {
    const { getByTestId } = await renderPage();
    expect(getByTestId("rate").innerHTML).not.toMatch(/text-(emerald|green|red|rose|amber)-/);
  });
});
