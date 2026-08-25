import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  CompositionBar,
  toBarSegments,
  CHART_COLORS,
  OTHER_COLOR,
} from "@/components/dashboard/composition-bar";

// #1210: 도넛 대체 스택 바 — 상위 5 + 기타 병합 규칙과 색 상수를 잠근다.

describe("toBarSegments", () => {
  // toBarSegments 는 색을 재할당하지 않는다 — 재매핑은 composition-section 한 곳.
  const slice = (label: string, value: number, i: number) => ({
    label, value, color: CHART_COLORS[i % CHART_COLORS.length],
  });

  it("keeps up to 5 slices verbatim (colors untouched) and no 기타", () => {
    const segs = toBarSegments([slice("A", 60, 0), slice("B", 40, 1)], "기타");
    expect(segs).toHaveLength(2);
    expect(segs[0]).toEqual({ label: "A", value: 60, color: CHART_COLORS[0] });
    expect(segs[1]).toEqual({ label: "B", value: 40, color: CHART_COLORS[1] });
  });

  it("merges everything past the 5th slice into a single 기타 segment", () => {
    const many = [
      slice("A", 30, 0), slice("B", 20, 1), slice("C", 15, 2), slice("D", 12, 3),
      slice("E", 10, 4), slice("F", 8, 0), slice("G", 5, 1),
    ];
    const segs = toBarSegments(many, "기타");
    expect(segs).toHaveLength(6);
    expect(segs[5]).toEqual({ label: "기타", value: 13, color: OTHER_COLOR });
  });

  it("returns empty for empty input", () => {
    expect(toBarSegments([], "기타")).toEqual([]);
  });

  // P1 잠금 (codex R1): summary 자체 Other 버킷은 **집계 행**이라 개별 상위 5위
  // 안에 드는 크기여도 카테고리 세그먼트로 승격되지 않고 항상 기타에 합산된다.
  it("folds the upstream Other bucket into 기타 even when its weight ranks top-5", () => {
    const segs = toBarSegments(
      [
        slice("A", 30, 0), slice("B", 25, 1),
        { label: "Other (7)", value: 20, color: OTHER_COLOR, isOther: true },
        slice("C", 15, 2), slice("D", 10, 3),
      ],
      "기타",
    );
    expect(segs.map((s) => s.label)).toEqual(["A", "B", "C", "D", "기타"]);
    expect(segs[4]).toEqual({ label: "기타", value: 20, color: OTHER_COLOR });
  });

  it("sums upstream Other together with individual slices past the 5th", () => {
    const segs = toBarSegments(
      [
        slice("A", 25, 0), slice("B", 20, 1), slice("C", 15, 2),
        slice("D", 12, 3), slice("E", 10, 4), slice("F", 8, 0),
        { label: "Other (3)", value: 10, color: OTHER_COLOR, isOther: true },
      ],
      "기타",
    );
    expect(segs).toHaveLength(6);
    expect(segs[5]).toEqual({ label: "기타", value: 18, color: OTHER_COLOR });
  });

  // globals.css --chart-1..5 미러 잠금 — CSS 변수를 SSR inline style 에서 못 읽어
  // 상수로 복제했으므로, 값이 어긋나면 여기서 잡는다 (composition-bar.tsx 헤더 주석).
  it("mirrors the --chart-1..5 hex values from globals.css", () => {
    expect(CHART_COLORS).toEqual(["#4C90F0", "#3FA6DA", "#43BF4D", "#F0B726", "#9179F2"]);
  });
});

describe("CompositionBar", () => {
  it("renders one segment per input with width/style/tooltip", () => {
    render(
      <CompositionBar
        segments={[
          { label: "A", value: 60.5, color: "#4C90F0" },
          { label: "B", value: 39.5, color: "#3FA6DA" },
        ]}
      />,
    );
    const bar = screen.getByTestId("composition-bar");
    const segs = screen.getAllByTestId("composition-bar-segment");
    expect(bar).toBeInTheDocument();
    expect(segs).toHaveLength(2);
    expect(segs[0].getAttribute("style")).toContain("width: 60.5%");
    expect(segs[0].getAttribute("title")).toBe("A 60.5%");
    // 접근성 (codex R1 P2): title 은 포인터 전용 — accessible name 이 구성을 열거해야
    // 스크린리더가 읽는다. 세그먼트는 장식(aria-hidden).
    expect(bar.getAttribute("aria-label")).toBe("포트폴리오 구성: A 60.5%, B 39.5%");
    expect(segs[0].getAttribute("aria-hidden")).toBe("true");
  });

  it("renders nothing for empty segments", () => {
    const { container } = render(<CompositionBar segments={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
