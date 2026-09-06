"""기권 verdict 가 의견으로 집계되지 않는지 (#1436).

`#1028` 은 예외·타임아웃으로 죽은 에이전트의 HOLD/0 을 분자·분모에서 뺐다. 그런데 멀쩡히
돌고 확신도 0 을 내는 경로가 따로 있었고(`fundamental` 데이터 없음 · `technical` 데이터 부족 ·
주식 티커를 받은 `crypto`), 산출물이 똑같은 HOLD/0 이라 그쪽은 계속 의견으로 세어졌다.

프로덕션 실측이 이 테스트의 근거다 — 최신 1일치 180 셀 중 **36 개가 확신도 0** 인데
`degraded_agents` 는 전 18 행 `[]`, `panel_coverage` 는 전 행 `1.0` 이었다. HOLD 로 확정된
4 건은 동의율이 실제보다 **5.0~8.6pp 높았고**, 한 건은 10 에이전트 중 5 가 데이터 없이
계산돼 **20.0pp** 어긋났다.
"""

import pytest

from nuri.trading.agents.base import AgentVerdict
from nuri.trading.agents.consensus.scoring import _build_consensus

WEIGHTS = {f"a{i}": 0.1 for i in range(10)} | {"risk": 0.1, "technical": 0.1, "crypto": 0.1}


def v(name: str, action: str, conf: float, *, degraded: bool = False) -> AgentVerdict:
    return AgentVerdict(name, "TEST", action, conf, f"{name} says {action}", degraded=degraded)


class TestAbstainedFlag:
    """`abstained` 는 확신도에서 파생된다 — 에이전트가 손으로 붙이지 않는다."""

    def test_zero_confidence_is_abstained(self):
        assert v("crypto", "HOLD", 0).abstained is True

    def test_any_confidence_is_not_abstained(self):
        assert v("macro", "HOLD", 1).abstained is False
        assert v("macro", "BUY", 50).abstained is False

    def test_degraded_is_not_also_abstained(self):
        """두 축은 배타적이다 — 안 그러면 사고가 기권 통계에 섞인다."""
        crashed = v("macro", "HOLD", 0, degraded=True)
        assert crashed.degraded is True
        assert crashed.abstained is False


class TestAbstainedExcludedFromAgreement:
    def test_abstained_hold_does_not_inflate_hold_agreement(self):
        """실측된 역전: HOLD 합의에서 기권이 동의로 세어져 동의율이 부풀었다."""
        verdicts = [
            v("a0", "HOLD", 50),
            v("a1", "HOLD", 50),
            v("a2", "BUY", 60),
            v("crypto", "HOLD", 0),  # 기권 — HOLD 로 세면 3/4 가 된다
        ]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        # 기권 제외: HOLD 2 / live 3
        assert r.agreement_rate == pytest.approx(2 / 3, abs=0.01)
        assert r.scoring_detail["abstained_agents"] == ["crypto"]

    def test_abstained_dissent_does_not_deflate_agreement(self):
        """반대 방향 — BUY 합의에서 기권이 반대표로 세어져 동의율이 눌렸다."""
        verdicts = [
            v("a0", "BUY", 80),
            v("a1", "BUY", 70),
            v("crypto", "HOLD", 0),
            v("retail", "HOLD", 0),
        ]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.agreement_rate == pytest.approx(1.0, abs=0.01)  # 2/2, not 2/4
        assert sorted(r.scoring_detail["abstained_agents"]) == ["crypto", "retail"]

    def test_abstained_not_listed_as_dissent(self):
        verdicts = [v("a0", "BUY", 80), v("crypto", "HOLD", 0)]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert all("crypto" not in d for d in r.dissent)

    def test_panel_coverage_counts_only_live(self):
        verdicts = [v("a0", "BUY", 80), v("a1", "HOLD", 50), v("crypto", "HOLD", 0), v("retail", "HOLD", 0)]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.scoring_detail["panel_coverage"] == pytest.approx(0.5)

    def test_degraded_and_abstained_are_reported_separately(self):
        """섞으면 진짜 사고가 상시 기권 노이즈에 묻힌다 — 축을 나눈 이유."""
        verdicts = [
            v("a0", "BUY", 80),
            v("macro", "HOLD", 0, degraded=True),  # 크래시
            v("crypto", "HOLD", 0),  # 기권
        ]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.scoring_detail["degraded_agents"] == ["macro"]
        assert r.scoring_detail["abstained_agents"] == ["crypto"]


class TestRiskVetoAvailability:
    def test_abstaining_risk_marks_veto_unavailable(self):
        """#1028 이 기록하려던 사실 — '거부권을 평가할 수 없었다'."""
        verdicts = [v("a0", "BUY", 80), v("risk", "HOLD", 0)]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.scoring_detail["risk_veto_available"] is False

    def test_live_risk_marks_veto_available(self):
        verdicts = [v("a0", "BUY", 80), v("risk", "HOLD", 30)]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.scoring_detail["risk_veto_available"] is True

    def test_abstaining_risk_does_not_change_the_action(self):
        """행동은 안 바뀐다 — 확신도 0 은 `>= 80` 을 통과할 수 없었다. 기록만 정확해진다."""
        base = [v("a0", "BUY", 80), v("a1", "BUY", 60)]
        with_risk = _build_consensus("TEST", [*base, v("risk", "SELL", 0)], WEIGHTS)
        without = _build_consensus("TEST", base, WEIGHTS)
        assert with_risk.final_action == without.final_action == "BUY"
        assert with_risk.final_confidence == pytest.approx(without.final_confidence)
        assert with_risk.scoring_detail["risk_veto_fired"] is False


class TestNoBehaviourChange:
    """이 변경은 판정을 바꾸지 않는다 — 확신도 0 은 가중합에 0 을 더하기 때문이다."""

    def test_final_action_and_confidence_unchanged_by_abstentions(self):
        opinions = [v("a0", "BUY", 80), v("a1", "HOLD", 40), v("a2", "SELL", 20)]
        plain = _build_consensus("TEST", opinions, WEIGHTS)
        padded = _build_consensus("TEST", [*opinions, v("crypto", "HOLD", 0), v("retail", "HOLD", 0)], WEIGHTS)
        assert padded.final_action == plain.final_action
        assert padded.final_confidence == pytest.approx(plain.final_confidence)
        assert padded.scoring_detail["action_scores"] == plain.scoring_detail["action_scores"]

    def test_all_abstained_does_not_divide_by_zero(self):
        r = _build_consensus("TEST", [v("crypto", "HOLD", 0), v("retail", "HOLD", 0)], WEIGHTS)
        assert r.agreement_rate == 0
        assert r.scoring_detail["panel_coverage"] == 0.0
