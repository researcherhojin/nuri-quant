"""죽은 에이전트가 진짜 HOLD 표로 둔갑하지 않게 (#1028, 이슈 #1027).

에이전트가 예외/타임아웃이면 `consensus/__init__.py` 가 `HOLD/0/"에러: …"` verdict 로
흡수한다. 패널이 통째로 무너지지 않게 하는 올바른 처리지만(#130), **하류에서 진짜
HOLD 와 구분이 안 됐다** — 유일한 표식이 free-text `reasoning` 의 한국어 접두사였다.

세 가지가 조용히 일어났다:
  1. **거부권 무력화** — `_build_consensus` 는 `risk_v.confidence >= 80` 으로 판정하는데
     죽은 risk 에이전트는 confidence 0 이라 그냥 거짓이 된다. Hard veto(§2.6)가
     사라지는데 아무 기록이 없다.
  2. **divergence penalty 무력화** — technical 이 죽으면 같은 방식으로 발동 불가.
  3. **동의율 부풀림** — 죽은 에이전트가 분모에 들어가고, 합의가 HOLD 면 분자에도
     들어간다. 패널이 망가질수록 더 만장일치로 보이는 역전.

2026-08-11 프로덕션 실측: 최근 1,399 추천(13,990 verdict) 중 에러/타임아웃 7건(0.05%),
그중 **4건이 risk** — 거부권 없이 낸 판정 4건을 사후에 식별할 방법이 없었다.

**행동은 바꾸지 않는다** (Surface rung). 열화 패널이 차단·강등돼야 하는지는 증거가
필요한 정책 문제이고, 사다리 승급은 STRATEGY PR 사항이다.
"""

from __future__ import annotations

from nuri.trading.agents.base import AgentVerdict
from nuri.trading.agents.consensus.scoring import _build_consensus

WEIGHTS = {"risk": 0.19, "technical": 0.152, "fundamental": 0.114, "macro": 0.114}


def _v(name, action, conf, *, degraded=False, alpha=None):
    return AgentVerdict(
        agent_name=name,
        ticker="TEST",
        action=action,
        confidence=conf,
        reasoning="에러: boom" if degraded else "reason",
        alpha_action=alpha,
        degraded=degraded,
    )


class TestDegradedRiskAgentIsVisible:
    def test_dead_risk_agent_marks_the_veto_unavailable(self):
        """거부권을 못 쓴 판정을 사후에 식별할 수 있어야 한다."""
        verdicts = [
            _v("risk", "HOLD", 0, degraded=True),
            _v("technical", "BUY", 90),
            _v("fundamental", "BUY", 80),
        ]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.scoring_detail["risk_veto_available"] is False, (
            "risk 가 죽었는데 거부권이 '가용' 으로 기록되면 열화가 사후에 안 보인다"
        )
        assert "risk" in r.scoring_detail["degraded_agents"]
        assert r.final_action == "BUY"  # 행동은 그대로 — Surface rung

    def test_live_risk_agent_marks_the_veto_available(self):
        verdicts = [_v("risk", "HOLD", 40), _v("technical", "BUY", 90)]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.scoring_detail["risk_veto_available"] is True

    def test_a_live_risk_agent_can_still_veto(self):
        """열화 표식이 정상 거부권을 막지 않는다 (짝 테스트)."""
        verdicts = [_v("risk", "SELL", 90, alpha="FLAT"), _v("technical", "BUY", 95)]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.final_action == "SELL"
        assert r.scoring_detail["risk_veto_fired"] is True


class TestAgreementRateExcludesDeadAgents:
    def test_dead_agent_does_not_inflate_agreement_on_hold(self):
        """죽은 에이전트의 HOLD 가 동의로 세어지면 망가진 패널이 만장일치로 보인다."""
        verdicts = [
            _v("technical", "HOLD", 60),
            _v("fundamental", "HOLD", 60),
            _v("risk", "HOLD", 0, degraded=True),
            _v("macro", "HOLD", 0, degraded=True),
        ]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.final_action == "HOLD"
        assert r.agreement_rate == 1.0  # 살아있는 2개 모두 HOLD → 2/2
        assert r.scoring_detail["panel_coverage"] == 0.5
        # 죽은 둘을 세면 4/4 로 똑같이 1.0 이 나오므로, coverage 가 구분자다.

    def test_dead_agent_is_not_counted_as_a_supporter(self):
        """죽은 에이전트의 action 이 합의 방향과 **같을 때**를 봐야 한다.

        방향이 다르면 `v.action == basis_action` 만으로도 False 가 나와, 표식이
        빠져도 테스트가 통과한다 (뮤테이션으로 실제 확인). HOLD 합의 + HOLD 대체
        verdict 조합이 진짜 카나리아다.
        """
        verdicts = [
            _v("technical", "HOLD", 60),
            _v("risk", "HOLD", 0, degraded=True),
        ]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.final_action == "HOLD"
        dead = next(c for c in r.scoring_detail["contributions"] if c["agent_name"] == "risk")
        assert dead["degraded"] is True
        assert dead["counted_for_basis_action"] is False, (
            "죽은 에이전트가 합의 방향 '지지자' 로 표시되면 UI 가 없는 지지를 그린다"
        )
        alive = next(c for c in r.scoring_detail["contributions"] if c["agent_name"] == "technical")
        assert alive["counted_for_basis_action"] is True

    def test_dead_agent_is_not_listed_as_dissent(self):
        """죽은 에이전트를 반대 의견으로 적으면 없는 반대를 지어내는 것이다."""
        verdicts = [_v("technical", "BUY", 90), _v("risk", "HOLD", 0, degraded=True)]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert not any("risk" in d for d in r.dissent), f"죽은 에이전트가 반대 의견에 있다: {r.dissent}"


class TestHealthyPanelIsUnchanged:
    def test_no_degradation_means_full_coverage(self):
        verdicts = [_v("technical", "BUY", 90), _v("risk", "HOLD", 40), _v("macro", "BUY", 70)]
        r = _build_consensus("TEST", verdicts, WEIGHTS)
        assert r.scoring_detail["panel_coverage"] == 1.0
        assert r.scoring_detail["degraded_agents"] == []
        assert r.agreement_rate == round(2 / 3, 2)


class TestErrorVerdictsAreConstructedDegraded:
    def test_the_absorber_marks_them(self):
        """`consensus/__init__.py` 의 흡수 지점이 실제로 표식을 단다.

        여기서 놓치면 위 잠금 전부가 공짜로 통과한다 — 스코어링은 옳은데 아무도
        degraded=True 를 안 넣는 상태.
        """
        from pathlib import Path

        src = Path("nuri/trading/agents/consensus/__init__.py").read_text(encoding="utf-8")
        for marker in ('f"에러: {e}"', '"타임아웃"'):
            for line in src.splitlines():
                if marker in line and "AgentVerdict(" in line:
                    assert "degraded=True" in line, f"흡수 지점에 표식이 없다: {line.strip()}"
