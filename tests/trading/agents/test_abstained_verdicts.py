"""기권 verdict 가 의견으로 집계되지 않는지 (#1436).

`#1028` 은 예외·타임아웃으로 죽은 에이전트의 HOLD/0 을 분자·분모에서 뺐다. 그런데 멀쩡히
돌고 자리표시자를 내는 경로가 따로 있었고(crypto "크립토 변동 없음", retail "리테일 데이터
부족", fundamental "펀더멘탈 데이터 없음"…), 산출물이 같은 모양이라 계속 의견으로 세어졌다.

프로덕션 실측이 근거다 — 최신 1일치 180 셀 중 **51 개(28.3%)가 기권**인데 `degraded_agents` 는
전 18 행 `[]`, `panel_coverage` 는 전 행 `1.0` 이었다 (실제 커버리지 중앙값 0.70, 최소 0.40).
동의율은 6/18 건이 10pp 이상 어긋났다 (최대 +30.0pp / -13.3pp).

⚠️ **기권을 확신도로 판정하지 않는다.** 첫 구현이 `confidence == 0` 으로 유도했는데 틀렸다
(codex R1): `normalize_confidence` 가 낮은 원점수를 0 으로 깎아서, `risk` 는 raw 0~40 이,
`macro` 는 0~30 이 전부 0.0 이 된다. 실측에서 `risk` 의 **"리스크 정상"** — 평가해서 위험
없음을 확인한 진짜 판단 — 3 건이 확신도 0 이었고, 파생 방식은 그걸 기권으로 오분류해
`risk_veto_available=False` 로 뒤집어 적었다. 그래서 생산 지점이 선언한다.
"""

import ast
from pathlib import Path

import pytest

from nuri.trading.agents.base import AgentVerdict
from nuri.trading.agents.consensus.scoring import _build_consensus

WEIGHTS = {f"a{i}": 0.1 for i in range(10)} | {"risk": 0.1, "technical": 0.1, "crypto": 0.1, "retail": 0.1}
AGENTS_DIR = Path(__file__).resolve().parents[3] / "nuri" / "trading" / "agents"


def v(name, action, conf, *, degraded=False, abstained=False) -> AgentVerdict:
    return AgentVerdict(name, "TEST", action, conf, f"{name}: {action}", degraded=degraded, abstained=abstained)


class TestTwoAxes:
    def test_abstained_defaults_false(self):
        """확신도 0 이라고 자동으로 기권이 되지 않는다 — 이게 codex R1 이 잡은 회귀다."""
        assert v("risk", "HOLD", 0).abstained is False

    def test_real_low_confidence_judgment_stays_live(self):
        """`risk` 의 '리스크 정상' 은 raw<=40 이 0.0 으로 정규화된 **판단**이다.

        기권으로 오분류하면 거부권을 평가하고도 '평가 못 함' 으로 기록하게 된다.
        """
        verdicts = [v("a0", "BUY", 80), v("risk", "HOLD", 0, abstained=False)]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.scoring_detail["risk_veto_available"] is True
        assert r.scoring_detail["abstained_agents"] == []
        assert r.agreement_rate == pytest.approx(0.5)  # live 2 개, BUY 동의 1

    def test_degraded_and_abstained_are_separate(self):
        """섞으면 진짜 크래시가 상시 기권 노이즈에 묻힌다 — 축을 나눈 이유."""
        verdicts = [
            v("a0", "BUY", 80),
            v("a1", "HOLD", 0, degraded=True),
            v("crypto", "HOLD", 0, abstained=True),
        ]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.scoring_detail["degraded_agents"] == ["a1"]
        assert r.scoring_detail["abstained_agents"] == ["crypto"]


class TestAbstainedExcludedFromPanel:
    def test_abstention_does_not_inflate_hold_agreement(self):
        """#1028 이 예측한 역전 — HOLD 합의에서 자리표시자가 동의로 세어졌다."""
        verdicts = [
            v("a0", "HOLD", 50),
            v("a1", "HOLD", 50),
            v("a2", "BUY", 60),
            v("crypto", "HOLD", 0, abstained=True),
        ]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.agreement_rate == pytest.approx(2 / 3, abs=0.01)

    def test_abstention_does_not_deflate_non_hold_agreement(self):
        verdicts = [
            v("a0", "BUY", 80),
            v("a1", "BUY", 70),
            v("crypto", "HOLD", 0, abstained=True),
            v("retail", "HOLD", 0, abstained=True),
        ]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.agreement_rate == pytest.approx(1.0, abs=0.01)

    def test_abstention_not_listed_as_dissent(self):
        r = _build_consensus("TEST", [v("a0", "BUY", 80), v("crypto", "HOLD", 0, abstained=True)], WEIGHTS)
        assert all("crypto" not in d for d in r.dissent)

    def test_abstention_not_credited_as_supporter_in_reasoning(self):
        """codex R1 P2 — `reasoning` 은 supporters 를 나열하는데 verdicts 전체를 봤다."""
        r = _build_consensus("TEST", [v("a0", "HOLD", 60), v("crypto", "HOLD", 0, abstained=True)], WEIGHTS)
        assert "crypto" not in r.reasoning

    def test_abstention_not_counted_for_basis_action(self):
        """codex R1 P2 — contributions 의 기여 표시도 같은 정의를 써야 한다."""
        r = _build_consensus("TEST", [v("a0", "HOLD", 60), v("crypto", "HOLD", 0, abstained=True)], WEIGHTS)
        contrib = {c["agent_name"]: c for c in r.scoring_detail["contributions"]}
        assert contrib["crypto"]["counted_for_basis_action"] is False
        assert contrib["crypto"]["abstained"] is True

    def test_panel_coverage_counts_only_live(self):
        verdicts = [
            v("a0", "BUY", 80),
            v("a1", "HOLD", 50),
            v("crypto", "HOLD", 0, abstained=True),
            v("retail", "HOLD", 0, abstained=True),
        ]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.scoring_detail["panel_coverage"] == pytest.approx(0.5)

    def test_abstaining_risk_marks_veto_unavailable(self):
        r = _build_consensus("TEST", [v("a0", "BUY", 80), v("risk", "HOLD", 0, abstained=True)], WEIGHTS)
        assert r.scoring_detail["risk_veto_available"] is False


class TestNoBehaviourChange:
    """판정은 안 바뀐다 — 자리표시자 확신도는 가중합에 0 을 더하기 때문이다."""

    def test_final_action_and_confidence_unchanged(self):
        opinions = [v("a0", "BUY", 80), v("a1", "HOLD", 40), v("a2", "SELL", 20)]
        plain = _build_consensus("TEST", opinions, WEIGHTS)
        padded = _build_consensus(
            "TEST",
            [*opinions, v("crypto", "HOLD", 0, abstained=True), v("retail", "HOLD", 0, abstained=True)],
            WEIGHTS,
        )
        assert padded.final_action == plain.final_action
        assert padded.final_confidence == pytest.approx(plain.final_confidence)

    def test_all_abstained_does_not_divide_by_zero(self):
        r = _build_consensus(
            "TEST", [v("crypto", "HOLD", 0, abstained=True), v("retail", "HOLD", 0, abstained=True)], WEIGHTS
        )
        assert r.agreement_rate == 0
        assert r.scoring_detail["panel_coverage"] == 0.0


class TestProducersDeclareAbstention:
    """자리표시자를 내는 새 경로가 플래그를 빠뜨리면 여기서 잡는다.

    손으로 붙이는 방식의 유일한 약점이 '빠뜨림' 이므로, 그것만 기계로 막는다.
    판정 기준은 `no_data` 설정을 쓰거나 확신도 리터럴 0 으로 `AgentVerdict` 를 만드는 것.
    """

    @staticmethod
    def _placeholder_calls():
        found = []
        for path in sorted(AGENTS_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "AgentVerdict"):
                    continue
                src = ast.get_source_segment(path.read_text(), node) or ""
                conf = node.args[3] if len(node.args) > 3 else None
                is_zero_literal = isinstance(conf, ast.Constant) and conf.value == 0
                if is_zero_literal or '"no_data"' in src or "'no_data'" in src:
                    kwargs = {k.arg for k in node.keywords}
                    found.append((path.name, node.lineno, kwargs))
        return found

    def test_every_placeholder_declares_its_kind(self):
        offenders = [
            f"{name}:{line}" for name, line, kw in self._placeholder_calls() if not ({"abstained", "degraded"} & kw)
        ]
        assert offenders == [], (
            f"자리표시자 verdict 인데 abstained/degraded 를 선언하지 않았다: {offenders}. "
            "정상 실행 중 데이터 부재면 abstained=True, 예외·타임아웃이면 degraded=True."
        )

    def test_the_sweep_actually_finds_the_known_sites(self):
        """스윕이 0 건을 훑으며 초록인 상태를 막는 카나리아 (#910 죽은 게이트)."""
        assert len(self._placeholder_calls()) >= 11
