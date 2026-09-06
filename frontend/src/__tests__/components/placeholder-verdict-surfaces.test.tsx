/**
 * 자리표시자 verdict 가 **어느 화면에서도** 의견처럼 보이지 않는지 (#1436).
 *
 * 백엔드는 기권·degraded 를 동의율과 패널 커버리지에서 뺀다. 그런데 읽기 표면이 그걸
 * 평범한 `H0` / `HOLD 0%` 로 그리면 **같은 화면이 자기 자신과 모순**된다 — "커버리지 60%"
 * 옆에 10 개의 의견이 나란히 선다. `/decisions/{id}` 만 고쳤을 때 codex 가 잡은 상태가
 * 정확히 이것이고, 한쪽만 고친 상태가 안 고친 것보다 나쁘다.
 *
 * 표면마다 따로 잠근다 — 한 곳만 잠그면 나머지는 무방비다(레포가 반복해 겪은 형태).
 */
import { describe, it, expect } from "vitest";
import { render, screen, within, fireEvent } from "@testing-library/react";
import { ConsensusTable } from "@/components/ui/consensus-table";
import { CONSENSUS } from "@/lib/strings";
import { parseDetailFlags, parseDetailKV } from "@/app/decisions/helpers";

const withPlaceholders = [
  {
    ticker: "TESTTICKER",
    final_action: "BUY",
    final_confidence: 70,
    agreement_rate: 1.0,
    verdicts: [
      {
        agent_name: "technical",
        ticker: "TESTTICKER",
        action: "BUY",
        confidence: 75,
        reasoning: "실제 의견",
        data_points: {},
      },
      {
        agent_name: "korean_market",
        ticker: "TESTTICKER",
        action: "HOLD",
        confidence: 50,
        reasoning: "US ticker — Korean market agent neutral",
        data_points: {},
        abstained: true,
      },
      {
        agent_name: "crypto",
        ticker: "TESTTICKER",
        action: "HOLD",
        confidence: 0,
        reasoning: "크립토 조회 실패",
        data_points: {},
        degraded: true,
      },
    ],
    dissent: [],
    reasoning: "테스트",
  },
];

describe("ConsensusTable — 자리표시자는 의견 셀이 아니다", () => {
  it("기권·degraded 셀에 확신도 숫자를 찍지 않는다", () => {
    render(<ConsensusTable data={withPlaceholders} />);
    const row = screen.getByText("TESTTICKER").closest("tr")!;

    // 진짜 의견은 그대로 숫자를 보여준다 — 카나리아. 이게 없으면 "아무것도 안 그린다"
    // 로도 통과해버린다.
    expect(within(row).getByText("B75")).toBeInTheDocument();

    // 자리표시자는 확신도가 아니라 부재 표식으로 나온다
    expect(within(row).queryByText("H50")).not.toBeInTheDocument();
    expect(within(row).queryByText("H0")).not.toBeInTheDocument();
    expect(within(row).getByText(CONSENSUS.CELL_ABSTAINED)).toBeInTheDocument();
    expect(within(row).getByText(CONSENSUS.CELL_DEGRADED)).toBeInTheDocument();
  });

  it("행을 펼쳐도 같은 규칙이 유지된다", () => {
    // 접힌 셀만 검사하면 클릭 한 번으로 "의견 없음" 이 "HOLD 50%" 가 되는 모순을 놓친다
    // (codex R14 가 이 테스트의 얕음을 지적했다).
    render(<ConsensusTable data={withPlaceholders} />);
    fireEvent.click(screen.getByText("TESTTICKER"));

    const krCard = screen.getByTestId("agent-card-korean_market");
    expect(within(krCard).queryByText("50%")).not.toBeInTheDocument();
    expect(within(krCard).getByText(CONSENSUS.PLACEHOLDER_ABSTAINED)).toBeInTheDocument();

    const cryptoCard = screen.getByTestId("agent-card-crypto");
    expect(within(cryptoCard).getByText(CONSENSUS.PLACEHOLDER_DEGRADED)).toBeInTheDocument();

    // 카나리아 — 진짜 의견 카드는 그대로 확신도를 보여준다
    const techCard = screen.getByTestId("agent-card-technical");
    expect(within(techCard).getByText("75%")).toBeInTheDocument();
  });

  it("축이 없는 과거 행은 예전대로 그린다 — 없던 정보를 지어내지 않는다", () => {
    const legacy = [
      {
        ...withPlaceholders[0],
        verdicts: withPlaceholders[0].verdicts.map(({ abstained: _a, degraded: _d, ...v }) => v),
      },
    ];
    render(<ConsensusTable data={legacy} />);
    const row = screen.getByText("TESTTICKER").closest("tr")!;
    expect(within(row).getByText("H50")).toBeInTheDocument();
    expect(within(row).getByText("H0")).toBeInTheDocument();
  });
});

describe("근거 사슬 — 자리표시자를 근거로 세지 않는다 (#1436, codex R15)", () => {
  it("evidence.detail 의 축을 읽어 배지·확신도 대신 라벨을 그린다", () => {
    const flags = parseDetailFlags(JSON.stringify({ pe: 12, abstained: true, degraded: false }));
    expect(flags.abstained).toBe(true);
    expect(flags.degraded).toBe(false);

    // 축은 **분류**지 데이터가 아니다 — KV 목록에 섞이면 근거처럼 읽힌다
    const kv = parseDetailKV(JSON.stringify({ pe: 12, abstained: true, degraded: false }));
    expect(kv).toEqual([["pe", "12"]]);
  });

  it("축이 없는 과거 evidence 행은 둘 다 false — 없던 분류를 지어내지 않는다", () => {
    expect(parseDetailFlags(JSON.stringify({ pe: 12 }))).toEqual({ degraded: false, abstained: false });
    expect(parseDetailFlags(null)).toEqual({ degraded: false, abstained: false });
    expect(parseDetailFlags("not json")).toEqual({ degraded: false, abstained: false });
  });
});
