import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  ConsensusTable,
  type ConsensusRow,
  type ScoringDetail,
} from "./consensus-table";

// 같은 vitest 워커 내 다른 파일의 getByTestId 가 우리 row 의 잔여 DOM 을
// 잡지 않도록 명시적 unmount (auto-cleanup 미설정 환경 방어).
afterEach(() => {
  cleanup();
});

function makeRow(overrides: Partial<ConsensusRow>): ConsensusRow {
  return {
    ticker: "TST",
    final_action: "BUY",
    final_confidence: 72.5,
    agreement_rate: 0.8,
    verdicts: [],
    dissent: [],
    reasoning: "",
    ...overrides,
  };
}

// scoring_detail 의 두 fallback 분기 (line 159 / 162) 커버 목적:
// final_action_source 가 SOURCE_META 키가 아닌 미지의 값 → `?.tip || raw` 와 `?.icon || "·"`
// 두 우변 fallback arm (branch 11/12 arm=1) 이 실행된다.
function makeScoringDetail(
  source: ScoringDetail["final_action_source"],
): ScoringDetail {
  return {
    source: "consensus",
    schema_version: 1,
    weights: {},
    action_scores: { BUY: 1, SELL: 0, HOLD: 0 },
    contributions: [],
    final_action: "BUY",
    final_confidence: 72.5,
    final_action_source: source,
    basis_action: "BUY",
    agreement_rate: 0.8,
    risk_veto_fired: false,
    divergence_flag: false,
    penalty_applied: false,
    pre_penalty_action: "",
  };
}

describe("ConsensusTable — SOURCE_META fallback arms", () => {
  it("unknown final_action_source falls back to raw string tip + '·' icon (lines 159/162 right arms)", () => {
    // final_action_source 가 SOURCE_META 에 없는 미지 값 (런타임 미지 enum 시뮬레이션).
    const unknownSource =
      "future_source" as ScoringDetail["final_action_source"];
    const data: ConsensusRow[] = [
      makeRow({ scoring_detail: makeScoringDetail(unknownSource) }),
    ];

    render(<ConsensusTable data={data} />);

    const badge = screen.getByTestId("action-source-badge");
    // icon fallback: SOURCE_META[unknown]?.icon || "·" → "·"
    expect(badge.textContent).toBe("·");
    // tip fallback: SOURCE_META[unknown]?.tip || raw source → raw source string
    expect(badge.getAttribute("title")).toBe("future_source");
  });

  it("known non-weighted_sum source uses SOURCE_META icon + tip (left arms — control)", () => {
    const data: ConsensusRow[] = [
      makeRow({ scoring_detail: makeScoringDetail("risk_veto") }),
    ];

    render(<ConsensusTable data={data} />);

    const badge = screen.getByTestId("action-source-badge");
    // F-003: 이모지 → lucide — 아이콘은 svg 로 렌더되고 의미는 title 이 잠근다
    expect(badge.querySelector("svg")).not.toBeNull();
    expect(badge.getAttribute("title")).toContain("리스크");
  });
});
