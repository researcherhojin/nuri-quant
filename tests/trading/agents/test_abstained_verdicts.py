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

from pathlib import Path

import pytest

from nuri.trading.agents.base import AgentVerdict
from nuri.trading.agents.consensus.scoring import _build_consensus

WEIGHTS = {f"a{i}": 0.1 for i in range(10)} | {"risk": 0.1, "technical": 0.1, "crypto": 0.1, "retail": 0.1}


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

    def test_contribution_flags_stay_faithful_to_the_score(self):
        """`counted_for_basis_action` 은 **점수 기여** 표시다 (codex R2).

        기권을 여기서 빼면 `action_scores` 와 모순된다 — 기권도 점수에는 기여하기
        때문이다(#1437). 기권 여부는 별도 필드로 노출하고, 소비자가 둘을 조합한다.
        """
        r = _build_consensus("TEST", [v("a0", "HOLD", 60), v("sm", "HOLD", 37.5, abstained=True)], WEIGHTS)
        contrib = {c["agent_name"]: c for c in r.scoring_detail["contributions"]}
        # 기권이지만 HOLD 점수에 실제로 기여했으므로 True 여야 한다
        assert contrib["sm"]["counted_for_basis_action"] is True
        assert contrib["sm"]["abstained"] is True
        assert contrib["sm"]["weighted"] > 0

    def test_abstention_still_moves_the_score_because_1437_is_deferred(self):
        """#1437 은 **미룬 것**이지 고친 게 아니다 — 그 유예 자체를 점수로 잠근다 (codex R7).

        위 `contribution` 테스트는 직렬화된 필드만 본다. `action_scores` 루프에 `if
        v.abstained: continue` 를 넣는 회귀는 그 단언을 **전부 통과하면서** 판정을 바꾼다.
        여기서는 같은 verdict 를 기권 표시 전/후로 넣어 점수와 최종 판정이 동일한지 본다.

        BUY 30 vs 기권 HOLD 37.5 — 기권 기여를 빼면 HOLD 0.0375 가 사라져 **판정이 HOLD 에서
        BUY 로 뒤집힌다.** 그 뒤집힘이 바로 #1437 이 백테스트를 요구하는 이유이고, 그래서
        여기서 조용히 일어나면 안 된다.
        """
        opinions = [v("a0", "BUY", 30)]
        live = _build_consensus("TEST", [*opinions, v("crypto", "HOLD", 37.5)], WEIGHTS)
        flagged = _build_consensus("TEST", [*opinions, v("crypto", "HOLD", 37.5, abstained=True)], WEIGHTS)

        assert flagged.scoring_detail["action_scores"] == live.scoring_detail["action_scores"]
        assert flagged.final_action == live.final_action == "HOLD"
        assert flagged.final_confidence == pytest.approx(live.final_confidence)
        # 카나리아 — 기권을 빼면 실제로 뒤집히는 구성이어야 이 테스트가 의미를 갖는다
        without = _build_consensus("TEST", opinions, WEIGHTS)
        assert without.final_action == "BUY", "구성이 약하다 — 기권을 빼도 판정이 안 바뀐다"

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


class TestFailureIsNeverReportedAsAbstention:
    """DB 조회가 **실패**하면 어떤 에이전트도 기권으로 보고하지 않는다 (#1436, codex R4).

    앞선 판들은 AST 스윕으로 생성 지점을 분류하려 했는데 계속 샜다 — 지역변수·키워드 인자·
    정규화 호출·중복된 근거 문구, 그리고 마지막엔 자리표시자가 `AgentVerdict()` 가 아니라
    헬퍼 뒤로 옮겨가면서. **구조를 보는 게이트는 리팩터마다 눈이 먼다.**

    그래서 성질을 직접 잰다: DB 를 죽이고 모든 에이전트를 돌려, 실패가 `degraded` 로
    분류되는지 본다. 생성 형태가 어떻게 바뀌든 이 단언은 유효하다.

    근본 원인은 `BaseAgent._safe_query` 가 예외를 삼키고 `[]` 를 돌려준 것이었다 — 호출부에서
    "테이블이 빔" 과 "DB 죽음" 이 완전히 같아 보였고, 그 결과 6 개 에이전트가 DB 장애를
    정상 기권으로 기록했다.
    """

    @staticmethod
    def _verdicts_with_dead_db(monkeypatch, ticker="000000.KS"):
        """DB 를 **열 수 없게** 만들고 전 에이전트를 돌린다.

        ⚠️ `query` / `query_df` 를 monkeypatch 하지 않는다. `tests/CLAUDE.md` 가 금지한
        패턴이고(#1149), 실제로 처음엔 그렇게 짰다가 `test_data_integrity` 와
        `test_rebalance` 6 건을 오염시켰다 — patch 창 안에서 first-import 된 모듈이 mock 을
        자기 전역에 복사해 창 밖까지 들고 간다. 대신 레포가 정한 방식대로 `DB_PATH` 를
        갈아끼워 **진짜 조회 실패**를 만든다.
        """
        import nuri.core.db as dbmod
        from nuri.trading.agents.consensus.registry import build_all_agents

        monkeypatch.setattr(dbmod, "DB_PATH", Path("/nonexistent-dir-for-1436/no.db"))
        out = {}
        for agent in build_all_agents():
            try:
                out[agent.name] = agent.analyze(ticker)
            except Exception:
                out[agent.name] = None  # 예외 전파는 consensus 러너가 degraded 로 흡수한다
        return out

    def test_no_agent_calls_a_db_failure_a_routine_abstention(self, monkeypatch):
        """티커 2 종으로 훑고, **어느 한쪽에서든** degraded 면 통과.

        전문 범위 밖 경로는 DB 상태와 무관하게 기권이 맞다 — `korean_market` 은 US 티커에서,
        `wallstreet` 는 `.KS` 에서 그렇다. 한 티커로만 재면 그 구조적 기권이 오탐으로 잡힌다.
        """
        kr = self._verdicts_with_dead_db(monkeypatch, "000000.KS")
        us = self._verdicts_with_dead_db(monkeypatch, "TESTTICKER")
        offenders = []
        for name in kr:
            probes = [kr.get(name), us.get(name)]
            # 예외 전파(None)는 consensus 러너가 degraded 로 흡수하므로 정상 처리로 친다
            if any(v is None or v.degraded for v in probes):
                continue
            v = kr[name]
            if v.abstained:
                offenders.append(f"{name}({v.reasoning[:24]})")
        assert offenders == [], (
            f"DB 장애를 정상 기권으로 보고한 에이전트: {offenders}. "
            "`_safe_query` 결과의 `.failed` 를 보고 degraded 로 분류할 것 (BaseAgent._no_data)."
        )

    def test_the_probe_actually_reaches_every_agent(self, monkeypatch):
        """0 개를 검사하며 초록인 상태를 막는 카나리아 (#910)."""
        verdicts = self._verdicts_with_dead_db(monkeypatch)
        assert len(verdicts) >= 10

    @staticmethod
    def _partial_failure_cases():
        """에이전트 → (인스턴스, sql→QueryRows 스텁). 형제 쿼리는 **성공하되 신호를 못 만든다.**"""
        from nuri.trading.agents.base import QueryRows
        from nuri.trading.agents.crypto_agent import CryptoAgent
        from nuri.trading.agents.retail_agent import RetailAgent
        from nuri.trading.agents.risk_agent import RiskAgent
        from nuri.trading.agents.smart_money import SmartMoneyAgent
        from nuri.trading.agents.wallstreet import WallStreetAgent

        def rows(*dicts):
            return QueryRows(list(dicts))

        return {
            # ark 조회만 실패 — 나머지 소스는 정상적으로 비어 있다
            "smart_money": (
                SmartMoneyAgent(),
                lambda sql: QueryRows(failed=True) if "FROM ark WHERE" in sql else QueryRows(),
            ),
            # 변화율 실패 + 지배력은 중립값(50)으로 성공 → 어느 임계도 안 건드려 reasons 가 빈다
            "crypto": (
                CryptoAgent(),
                lambda sql: (
                    QueryRows(failed=True)
                    if "btc_24h_change_pct" in sql
                    else (rows({"value": 50.0}) if "btc_dominance" in sql else QueryRows())
                ),
            ),
            # 티커 언급 실패 + 전체 게시물 수는 과열 임계 아래로 성공
            "retail": (
                RetailAgent(),
                lambda sql: QueryRows(failed=True) if "indicator=?" in sql else rows({"value": 10.0}),
            ),
            # 캐시 테이블 조회 실패 (연결은 살아 있다) + yfinance 는 비어서 반환
            "wallstreet": (
                WallStreetAgent(),
                lambda sql: QueryRows() if sql == "SELECT 1" else QueryRows(failed=True),
            ),
            # 보유 조회 실패 → "리스크 정상" 을 살아있는 판단으로 적으면 거부권이 있는 것으로 기록된다
            "risk": (RiskAgent(), lambda sql: QueryRows(failed=True) if "FROM portfolio" in sql else QueryRows()),
        }

    def test_degraded_verdicts_carry_zero_confidence(self):
        """degraded 는 확신도 0 이어야 한다 (#1436, codex R6 P1).

        `action_scores[action] += w * (conf/100)` 이라 0 이 아니면 **죽은 에이전트가 계속
        투표한다.** 러너가 만드는 degraded 는 처음부터 0 이었는데, `_no_data` 가 에이전트별
        `no_data`(smart_money 30 · wallstreet 20 · macro 30)를 물려주면서 0 이 아닌 첫
        degraded 가 생겼다 — 실측으로 final_confidence 가 79.3 → 71.9 로 밀렸다. 그동안 UI 는
        degraded 를 "가중치 0 — 합의에 미반영" 이라고 적고 있었다.
        """
        offenders = []
        for name, (agent, stub) in self._partial_failure_cases().items():
            agent._safe_query = lambda sql, params=(), db_path=None, _s=stub: _s(sql)
            verdict = agent.analyze("TESTTICKER")
            if verdict.confidence != 0:
                offenders.append(f"{name}(conf={verdict.confidence})")
        assert offenders == [], f"degraded 인데 확신도가 0 이 아니다 — 합의에 표를 더한다: {offenders}"

    def test_a_degraded_placeholder_does_not_move_the_consensus(self):
        """위 성질의 소비 지점 — 확신도 0 이면 가중합이 그대로다."""
        opinions = [v("a0", "BUY", 70), v("a1", "BUY", 60), v("a2", "HOLD", 40)]
        plain = _build_consensus("TEST", opinions, WEIGHTS)
        padded = _build_consensus("TEST", [*opinions, v("crypto", "HOLD", 0, degraded=True)], WEIGHTS)
        assert padded.final_action == plain.final_action
        assert padded.final_confidence == pytest.approx(plain.final_confidence)

    def test_a_failed_read_is_not_masked_by_a_reason_the_failure_itself_produced(self, tmp_path):
        """`risk` 의 게이트는 `not reasons` 가 아니라 `not stop_loss_fired` 다 (codex R6 P1).

        보유 조회가 실패해도 `prices` 가 살아 있으면 변동성 근거("저변동성")가 `reasons` 를
        채운다. `not reasons` 게이트는 거기서 열려, **손절선을 한 번도 못 본** verdict 가
        `risk_veto_available=True` 로 기록된다. 실패를 가리는 근거가 실패 자신이 만든
        근거였다. 예외는 실제로 감지된 손절선 돌파 하나뿐이다 — 그건 유일한 기계적 alpha
        신호라 조회 하나가 실패했다고 버릴 수 없다.
        """
        from nuri.core.db import get_db, init_db
        from nuri.trading.agents.base import QueryRows
        from nuri.trading.agents.risk_agent import RiskAgent

        db = tmp_path / "risk.db"
        init_db(db)
        with get_db(db) as conn:
            for i in range(30):  # 거의 일정한 가격 → 저변동성 근거가 생긴다
                conn.execute(
                    "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                    ("TESTTICKER", f"2026-01-{i + 1:02d}", 100.0 + i * 0.01),
                )

        agent = RiskAgent()
        agent._safe_query = lambda sql, params=(), db_path=None: QueryRows(failed=True)
        verdict = agent.analyze("TESTTICKER", db_path=db)
        assert verdict.degraded is True, f"손절선을 못 봤는데 살아있는 판단으로 나갔다: {verdict.reasoning!r}"
        r = _build_consensus("TEST", [v("a0", "BUY", 80), verdict], WEIGHTS)
        assert r.scoring_detail["risk_veto_available"] is False

    def test_a_failed_freshness_probe_does_not_claim_staleness(self):
        """`smart_money._source_is_fresh` 의 프로브 실패가 사실 주장이 되면 안 된다 (codex R6 P1).

        프로브가 실패하면 소스가 낡았는지 **모른다.** 그런데 전 판은 bool 하나만 돌려줘
        실패를 "낡음" 으로 적었고, 그 문구가 `reasons` 를 채우는 바람에 `_no_data` 의 실패
        분기까지 우회했다 — 억제는 유지하되 말은 하지 않아야 한다.
        """
        from nuri.trading.agents.base import QueryRows
        from nuri.trading.agents.smart_money import SmartMoneyAgent

        stale_row = {
            "recommendation": "buy",
            "target_mean": 130.0,
            "current_price": 100.0,
            "num_analysts": 5,
            "date": "2000-01-01",  # 컷오프보다 한참 낡음 → 신선도 프로브를 태운다
        }

        def stub(sql, params=(), db_path=None):
            if "FROM estimates WHERE ticker" in sql:
                return QueryRows([stale_row])
            if "MAX(date) FROM estimates" in sql:
                return QueryRows(failed=True)  # 소스-레벨 프로브만 실패
            return QueryRows()

        agent = SmartMoneyAgent()
        agent._safe_query = stub
        verdict = agent.analyze("TESTTICKER")
        assert "낡음" not in verdict.reasoning, f"검증 못 한 staleness 를 사실로 주장했다: {verdict.reasoning!r}"
        assert verdict.degraded is True and verdict.abstained is False

    def test_partial_failure_is_not_an_abstention(self):
        """**한 소스만** 실패하고 형제 쿼리는 성공하는 경우 (#1436, codex R5 P2).

        위 죽은-DB 프로브는 연결 전체를 끊으므로 이 부류를 못 잡는다 — 실패 누적기를 "전부
        비었음" 분기에서만 참조하고 뒤의 "신호 없음" 출구는 `abstained=True` 를 하드코딩한
        결함이 그래서 4 개 에이전트에 남아 있었다. 형제 쿼리는 **성공하되 신호를 못 만드는**
        값을 돌려줘야 재현된다 (전부 비게 하면 앞 분기가 대신 잡아버린다).

        `korean_market` 은 여기 없다 (#1446) — 헬퍼 5 개가 각자 예외를 삼켜 실패 신호가
        `analyze()` 까지 오지 않는 별개 형태이고, 시그니처 5 개를 바꿔야 해서 분리했다.
        연결 전체가 죽는 경우는 `_calibrate_fx_thresholds` 의 raw `query_df` 가 예외를 올려
        러너가 degraded 로 흡수하므로 이미 덮인다.
        """
        offenders = []
        for name, (agent, stub) in self._partial_failure_cases().items():
            agent._safe_query = lambda sql, params=(), db_path=None, _s=stub: _s(sql)
            v = agent.analyze("TESTTICKER")
            if not v.degraded or v.abstained:
                offenders.append(f"{name}(degraded={v.degraded}, abstained={v.abstained}, {v.reasoning!r})")
        assert offenders == [], (
            f"형제 쿼리가 성공할 때 조회 실패를 정상 기권으로 보고한 에이전트: {offenders}. "
            "실패 누적기를 **모든 출구**에서 봐야 한다 — 마지막 '신호 없음' 분기 포함."
        )

    def test_a_failed_risk_read_does_not_claim_the_veto_was_evaluated(self):
        """`risk` 의 실패는 방향이 가장 나쁘다 — 하드 거부권 축이다 (#1436).

        조회 실패가 "리스크 정상" 으로 남으면 `risk_veto_available=True` 가 되어, 거부권을
        평가하지도 못한 채 **평가했다**고 기록한다. codex R1 의 반대편 오류다: 저쪽은 진짜
        판단을 기권으로 깎았고, 이쪽은 실패를 판단으로 승격한다.
        """
        from nuri.trading.agents.base import QueryRows
        from nuri.trading.agents.risk_agent import RiskAgent

        agent = RiskAgent()
        agent._safe_query = lambda sql, params=(), db_path=None: QueryRows(failed=True)
        r = _build_consensus("TEST", [v("a0", "BUY", 80), agent.analyze("TESTTICKER")], WEIGHTS)
        assert r.scoring_detail["risk_veto_available"] is False
        assert r.scoring_detail["degraded_agents"] == ["risk"]

    def test_a_real_risk_judgment_still_carries_the_veto(self):
        """짝 테스트 — 조회가 **성공**해서 보유가 없으면 '리스크 정상' 은 판단이다 (codex R1).

        위 수정이 이쪽까지 삼키면 R1 이 잡은 회귀를 되돌리는 것이다.
        """
        from nuri.trading.agents.base import QueryRows
        from nuri.trading.agents.risk_agent import RiskAgent

        agent = RiskAgent()
        agent._safe_query = lambda sql, params=(), db_path=None: QueryRows()
        verdict = agent.analyze("TESTTICKER")
        assert verdict.degraded is False and verdict.abstained is False
        assert verdict.reasoning == "리스크 정상"
        r = _build_consensus("TEST", [v("a0", "BUY", 80), verdict], WEIGHTS)
        assert r.scoring_detail["risk_veto_available"] is True

    def test_a_row_of_nulls_is_not_an_opinion(self, tmp_path):
        """행은 있는데 소비 필드가 전부 NULL — 읽은 게 없다 (#1436, codex R8 P1).

        `fundamental` 은 `"; ".join(reasons) or "데이터 제한적"` 로 빠져나가 확신도 50 짜리
        살아 있는 HOLD 를 냈다. 조회는 성공했으니 `_no_data` 의 앞 게이트(`if not rows`)에
        안 걸리고, 자리표시자인데 플래그가 없어 supporters·커버리지·동의율에 전부 집계됐다.
        """
        from nuri.core.db import get_db, init_db
        from nuri.trading.agents.fundamental import FundamentalAgent

        db = tmp_path / "fund.db"
        init_db(db)
        with get_db(db) as conn:
            conn.execute("INSERT INTO fundamentals (ticker, date) VALUES ('NULLROW', '2026-09-01')")
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe) VALUES ('REAL', '2026-09-01', 12.0, 0.25)"
            )

        blank = FundamentalAgent().analyze("NULLROW", db_path=db)
        assert blank.abstained is True and blank.degraded is False, f"자리표시자가 의견으로 나갔다: {blank!r}"

        # 짝 — 값이 실제로 있으면 판단이다. 위 게이트가 이쪽까지 삼키면 안 된다.
        real = FundamentalAgent().analyze("REAL", db_path=db)
        assert real.abstained is False and real.degraded is False
        assert "PE" in real.reasoning

    def test_a_neutral_row_is_a_judgment_not_an_abstention(self, tmp_path):
        """값을 **읽고 중립을 확인한** 행은 판단이다 (#1436, codex R9 P1).

        첫 수정은 게이트를 `not reasons` 로 썼는데 너무 넓었다. ROE 5% · 매출성장 5% ·
        부채 1.0 은 어느 임계도 안 건드려 근거 문구가 비지만, 에이전트는 실제 데이터를
        평가했다. 그걸 기권으로 깎으면 커버리지·동의율이 반대로 깎인다 — codex R1 이
        `risk` 의 "리스크 정상" 에서 잡은 오류와 같은 형태다.

        위 NULL-행 테스트만으로는 안 잡힌다: 거기 쓰는 값은 임계를 확실히 넘는 PE 12 /
        ROE 25% 라, 게이트를 `not reasons` 로 되돌려도 통과한다.
        """
        from nuri.core.db import get_db, init_db
        from nuri.trading.agents.fundamental import FundamentalAgent

        db = tmp_path / "fund.db"
        init_db(db)
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, roe, revenue_growth, debt_to_equity) "
                "VALUES ('NEUTRAL', '2026-09-01', 0.05, 0.05, 1.0)"
            )

        verdict = FundamentalAgent().analyze("NEUTRAL", db_path=db)
        assert verdict.abstained is False, f"평가한 중립 판단을 기권으로 깎았다: {verdict!r}"
        assert verdict.degraded is False
        assert verdict.reasoning  # 빈 문자열이 아니라 판단임을 말해야 한다

    def test_cached_and_live_read_paths_agree_on_dissent(self, monkeypatch):
        """캐시 경로가 dissent 를 **재구성**하며 두 축을 안 거르면 계약이 갈린다 (codex R9 P2).

        `api/routes/ticker.py` 는 캐시 적중 시 저장된 verdict 로 dissent 를 다시 만들고,
        미적중 시엔 `ConsensusResult.dissent` 를 쓴다. 후자는 자리표시자를 빼는데 전자가
        안 빼면 같은 엔드포인트가 캐시 상태에 따라 기권을 반대 의견이라고 답한다.
        """
        import json

        from nuri.api.routes import ticker as ticker_route
        from nuri.core.timezone import today_kst

        live = _build_consensus("TEST", [v("technical", "BUY", 70), v("crypto", "HOLD", 0, abstained=True)], WEIGHTS)
        cached_row = {
            "action": live.final_action,
            "confidence": live.final_confidence,
            "signals": json.dumps({"agreement_rate": live.agreement_rate}),
            "agent_verdicts": json.dumps(
                [
                    {
                        "agent_name": x.agent_name,
                        "action": x.action,
                        "confidence": x.confidence,
                        "reasoning": x.reasoning,
                        "degraded": x.degraded,
                        "abstained": x.abstained,
                    }
                    for x in live.verdicts
                ]
            ),
            # 리터럴 날짜 금지 — `_read_consensus_from_db` 에 freshness 컷오프가 있어
            # 고정일로 두면 며칠 뒤 조용히 None 이 되고 테스트가 공허 통과한다.
            "date": today_kst(),
        }

        def _fake_query(*_a, **_k):
            return [cached_row]

        # 라우트 모듈 **자신의** 바인딩만 갈아끼운다. `nuri.core.db.query` 를 건드리는
        # 것과 다르다 — 그쪽은 #1149 로 금지돼 있고 다른 모듈까지 오염시킨다.
        monkeypatch.setattr(ticker_route, "query", _fake_query)
        cached = ticker_route._read_consensus_from_db("TEST")

        assert cached is not None
        assert cached["dissent"] == live.dissent == []
        assert all("crypto" not in d for d in cached["dissent"])

    def test_persisted_verdicts_carry_both_axes(self, tmp_path):
        """저장 경로가 축을 빠뜨리면 **캐시 상태에 따라 API 계약이 달라진다** (codex R8 P1).

        `api/routes/ticker.py` 는 캐시 적중 시 저장된 `agent_verdicts` 를, 미적중 시
        `asdict()` 결과를 준다. 저장 쪽에만 축이 없으면 같은 엔드포인트가 캐시 상태에 따라
        기권을 구분할 수 있기도 없기도 하다 — 그 구분이 이 이슈의 전부다.
        """
        import json

        from nuri.core.db import init_db, query
        from nuri.trading.agents.consensus.persistence import save_to_recommendations

        db = tmp_path / "persist.db"
        init_db(db)
        result = _build_consensus(
            "TESTTICKER",
            [v("a0", "BUY", 70), v("crypto", "HOLD", 0, abstained=True), v("a1", "HOLD", 0, degraded=True)],
            WEIGHTS,
        )
        assert save_to_recommendations([result], db_path=db) == 1

        rows = query("SELECT agent_verdicts FROM recommendations WHERE ticker = ?", ("TESTTICKER",), db_path=db)
        stored = {d["agent_name"]: d for d in json.loads(rows[0]["agent_verdicts"])}
        assert stored["crypto"]["abstained"] is True and stored["crypto"]["degraded"] is False
        assert stored["a1"]["degraded"] is True and stored["a1"]["abstained"] is False
        assert stored["a0"]["abstained"] is False and stored["a0"]["degraded"] is False

    def test_every_known_placeholder_exit_declares_abstention(self, tmp_path):
        """알려진 자리표시자 출구를 하나씩 **몰아본다** (#1436, codex R10 P2).

        위 죽은-DB 프로브는 "실패를 기권이라 부르는" 오분류만 잡는다. **플래그를 아예 안
        붙인** 자리표시자는 그냥 의견으로 보이므로 안 걸린다 — `korean_market` 의 US 반환에서
        `abstained=True` 를 지워도 통과했다. 그게 원래 버그(커버리지·동의율 부풀림) 그 자체다.

        구조 스윕으로 잡으려던 시도는 네 번 샜고, 애초에 자리표시자와 진짜 저확신 판단은
        코드 모양으로 안 갈린다(`risk` 의 "리스크 정상"). 그래서 **조건으로 몰아 결과를 본다** —
        각 항목은 "이 상황에 놓이면 기권이어야 한다" 는 진술이고, 생성 형태가 바뀌어도 유효하다.

        여기 없는 출구는 다른 테스트가 덮는다: fundamental NULL 행 ·
        crypto/retail/smart_money/wallstreet 부분 실패 · technical 데이터 부족.
        """
        from nuri.core.db import init_db
        from nuri.trading.agents.base import QueryRows
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        from nuri.trading.agents.macro_agent import MacroAgent
        from nuri.trading.agents.options_agent import OptionsAgent
        from nuri.trading.agents.wallstreet import WallStreetAgent

        empty = tmp_path / "empty.db"
        init_db(empty)

        def pcr_rows_all_null(_agent):
            # 조회는 성공하고 행도 있는데 값이 전부 NULL — 실패가 아니라 부재다
            _agent._safe_query = lambda sql, params=(), db_path=None: QueryRows([{"value": None}])

        cases = [
            # (이름, 에이전트, 티커, 준비, 왜 자리표시자인가)
            ("korean_market/US", KoreanMarketAgent(), "TESTTICKER", None, "전문 범위 밖 — US 티커"),
            # 범위 **안**인데 데이터가 없는 경로는 위와 별개다 (codex R11). 이쪽이 안 잡혀
            # "Korean market neutral" 이 살아 있는 의견으로 세어지고 있었다.
            ("korean_market/KR-무데이터", KoreanMarketAgent(), "000000.KS", None, "범위 안이나 값 입력 전무"),
            ("wallstreet/.KS", WallStreetAgent(), "000000.KS", None, "전문 범위 밖 — 미지원 종목"),
            # 지원 US 티커에서 캐시·yfinance 가 **전부 비는** 경로 — 위 미지원 경로와 다른
            # 출구다 (codex R11). conftest 의 전역 yfinance mock 이 빈 결과를 준다.
            ("wallstreet/US-빈소스", WallStreetAgent(), "TESTTICKER", None, "지원 종목이나 전 소스 부재"),
            ("options/PCR-null", OptionsAgent(), "TESTTICKER", pcr_rows_all_null, "PCR 값이 전부 NULL"),
            ("macro/no-SPY", MacroAgent(), "TESTTICKER", None, "빈 DB — 레짐 산출 불가"),
        ]

        offenders = []
        for name, agent, ticker, prep, why in cases:
            if prep:
                prep(agent)
            verdict = agent.analyze(ticker, db_path=empty)
            if not (verdict.abstained or verdict.degraded):
                offenders.append(f"{name}({why}) → conf={verdict.confidence} {verdict.reasoning!r}")
        assert offenders == [], (
            f"자리표시자가 살아 있는 의견으로 집계된다: {offenders}. "
            "생산 지점에서 `abstained=True` 를 선언할 것 (BaseAgent._no_data 또는 직접)."
        )

    def test_a_kr_ticker_with_any_data_is_still_a_judgment(self, tmp_path):
        """짝 — 값이 **하나라도** 있으면 판단이다 (#1436, codex R11).

        위 표가 `korean_market` 의 무데이터 경로를 기권으로 돌리는데, 그 게이트가 넓어지면
        값을 읽고 중립을 확인한 KR 판단까지 깎인다. `fundamental` 에서 R9 가 잡은 과교정과
        같은 형태라 양쪽을 같이 잠근다.
        """
        from nuri.core.db import get_db, init_db
        from nuri.trading.agents.korean_market import KoreanMarketAgent

        db = tmp_path / "kr.db"
        init_db(db)
        with get_db(db) as conn:
            # 외국인 수급만 있다 — 임계를 넘지 않는 중립값
            conn.execute(
                "INSERT INTO institutional_flows (ticker, date, market, foreign_net) "
                "VALUES ('000000.KS', '2026-09-01', 'KOSPI', 0)"
            )

        verdict = KoreanMarketAgent().analyze("000000.KS", db_path=db)
        assert verdict.abstained is False, f"읽은 값이 있는데 기권으로 깎였다: {verdict!r}"
        assert verdict.degraded is False

    def test_macro_events_that_cancel_out_are_still_evaluated_input(self, tmp_path):
        """순 0 은 "이벤트 없음" 이 아니다 (#1436, codex R12).

        수출 섹터 종목에 demand_growth(+6)와 trade_war(-6)가 함께 오면 `macro_boost` 는
        0 이지만 **양쪽을 다 평가한 것**이다. 점수로 부재를 판정하면 근거가 있는 판단이
        기권으로 깎인다 — 이 이슈에서 반복해 밟은 함정의 또 다른 판이라, 점수가 아니라
        **입력의 존재**를 본다.
        """
        from nuri.core.db import get_db, init_db
        from nuri.core.timezone import kst_now
        from nuri.trading.agents.korean_market import KoreanMarketAgent

        db = tmp_path / "kr_macro.db"
        init_db(db)
        # 리터럴 날짜 금지 — 쿼리가 `date('now','-3 days')` 창을 쓴다 (tests/CLAUDE.md 시한폭탄)
        today = kst_now().strftime("%Y-%m-%d")
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, sector, quantity, avg_price) VALUES (?, ?, ?, ?, ?)",
                ("Brokerage Alpha", "000000.KS", "Semiconductor", 1, 1.0),
            )
            # +int(min(3·cnt·conf, 8)) 와 -int(min(2·cnt·conf, 6)) 가 상쇄되는 조합:
            # demand_growth 2건 → +6, trade_war 3건 → -6 (codex R12 가 든 예). cnt >= 2 는
            # 노이즈 필터를 통과하기 위한 하한이다.
            for cat, n in (("demand_growth", 2), ("trade_war", 3)):
                for i in range(n):
                    conn.execute(
                        "INSERT INTO macro_events "
                        "(published_at, source, headline, url, category, sentiment, confidence) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (today, "test", f"{cat} 이벤트", f"https://example.test/{cat}/{i}", cat, 0.0, 1.0),
                    )

        agent = KoreanMarketAgent()
        seen: list[str] = []
        boost = agent._get_macro_event_boost("Semiconductor", db_path=db, saw_input=seen)
        assert boost == 0, f"이 픽스처는 상쇄되어야 의미가 있다 (boost={boost})"  # 카나리아
        assert seen, "입력 존재가 기록되지 않았다 — 점수 0 과 구분 불가"

        verdict = agent.analyze("000000.KS", db_path=db)
        assert verdict.abstained is False, f"상쇄된 매크로 평가를 부재로 읽었다: {verdict!r}"

    def test_the_decision_path_persists_both_axes_too(self, tmp_path):
        """persist 경로가 **둘**이다 — 한쪽만 고친 상태가 더 나쁘다 (#1436, codex R12).

        `consensus/persistence.py` 는 고쳤는데 `engine/decisions.py` 를 놓쳤다. 그러면
        같은 `/decisions/{id}` 화면에서 위쪽은 `scoring_detail` 로 "의견 없음" 이라 쓰고
        아래 verdict 표는 평범한 HOLD 로 보인다 — 화면이 자기 자신과 모순된다.
        """
        import json

        from nuri.core.db import init_db, query
        from nuri.trading.engine.decisions import record_decision

        db = tmp_path / "dec.db"
        init_db(db)
        result = _build_consensus(
            "TESTTICKER",
            [v("technical", "BUY", 70), v("crypto", "HOLD", 0, abstained=True), v("a1", "HOLD", 0, degraded=True)],
            WEIGHTS,
        )
        record_decision(result, db_path=db)

        rows = query("SELECT agent_verdicts FROM decisions WHERE ticker = ?", ("TESTTICKER",), db_path=db)
        stored = {d["agent_name"]: d for d in json.loads(rows[0]["agent_verdicts"])}
        assert stored["crypto"]["abstained"] is True and stored["crypto"]["degraded"] is False
        assert stored["a1"]["degraded"] is True and stored["a1"]["abstained"] is False
        assert stored["technical"]["abstained"] is False and stored["technical"]["degraded"] is False

        # 근거 사슬도 축을 실어야 한다 — 타입 컬럼의 HOLD 만 보면 자리표시자가 근거로 세어진다
        ev = query("SELECT source_key, detail FROM decision_evidence WHERE source_type = 'agent'", (), db_path=db)
        detail = {r["source_key"]: json.loads(r["detail"]) for r in ev}
        assert detail["crypto"]["abstained"] is True
        assert detail["technical"]["abstained"] is False

    def test_korean_market_reports_read_failure_instead_of_absence(self):
        """헬퍼가 삼킨 실패가 `analyze()` 까지 도달한다 (#1446).

        `korean_market` 은 DB 를 헬퍼 5 개를 통해서만 읽는데, 그 헬퍼들이 각자 예외를 삼키고
        `None`/`""`/`0` 을 돌려줬다. 반환값만 보면 "값이 없다" 와 "조회가 실패했다" 가
        구분되지 않아, DB 장애가 상시 부재로 기록됐다 — #1436 이 다른 9 개 에이전트에서
        없앤 형태가 여기만 남아 있었다.

        총체적 장애가 그동안 안 새어나간 것은 `_calibrate_fx_thresholds` 가 `_safe_query` 가
        아니라 raw `query_df` 를 써서 예외가 올라간 **우연** 덕이었다. 여기서는 헬퍼 경로만
        죽여 그 우연에 기대지 않고 잰다.
        """
        from nuri.trading.agents.base import QueryRows
        from nuri.trading.agents.korean_market import KoreanMarketAgent

        rows21 = QueryRows([{"close": 100.0 + i} for i in range(21)])
        cases = [
            ("전 조회 실패", lambda sql: QueryRows(failed=True), "degraded"),
            ("성공하나 비어 있음", lambda sql: QueryRows(), "abstained"),
            # 부분 실패라도 실제로 읽은 값이 있으면 **판단**이다 — 여기서 degrade 하면
            # #1436 이 세 번 밟은 과교정(진짜 판단을 자리표시자로 깎기)의 재발이다.
            ("모멘텀만 있음", lambda sql: rows21 if "FROM prices" in sql else QueryRows(failed=True), "live"),
        ]
        for name, stub, expect in cases:
            agent = KoreanMarketAgent()
            agent._safe_query = lambda sql, params=(), db_path=None, _s=stub: _s(sql)
            v = agent.analyze("000000.KS")
            got = "degraded" if v.degraded else "abstained" if v.abstained else "live"
            assert got == expect, f"{name}: {expect} 여야 하는데 {got} ({v.reasoning!r})"

    def test_each_korean_market_helper_reports_its_own_failure(self):
        """헬퍼 **하나씩** 죽여서 잠근다 (#1446).

        위 "전 조회 실패" 케이스는 다섯이 동시에 실패하므로 한 헬퍼의 보고를 지워도 나머지가
        대신 보고해 통과한다 — 실측으로 확인했다(뮤테이션 2 건이 그대로 빠져나갔다).
        한 경로만 잠그면 나머지는 무방비라는 것이 이 레포가 반복해 겪은 형태다.
        """
        from nuri.trading.agents.base import QueryRows
        from nuri.trading.agents.korean_market import KoreanMarketAgent

        # 헬퍼 → 그 헬퍼의 쿼리를 알아보는 표식
        helpers = {
            "fx": "indicator='usd_krw'",
            "sector": "FROM portfolio",
            "foreign_flow": "FROM institutional_flows",
            "momentum": "FROM prices",
            "macro_events": "FROM macro_events",
        }
        offenders = []
        for name, marker in helpers.items():
            agent = KoreanMarketAgent()
            # 그 헬퍼만 실패, 나머지는 **성공하되 비어 있다** — 실패가 부재에 묻히는지 본다
            agent._safe_query = lambda sql, params=(), db_path=None, _m=marker: (
                QueryRows(failed=True) if _m in sql else QueryRows()
            )
            v = agent.analyze("000000.KS")
            if not v.degraded:
                offenders.append(f"{name}(degraded={v.degraded}, abstained={v.abstained})")
        assert offenders == [], f"실패를 보고하지 않는 헬퍼: {offenders} — `failures` out-param 을 확인할 것"

    def test_query_failure_is_distinguishable_from_empty(self):
        """`_safe_query` 의 두 결과가 실제로 구분되는지 — 이 구분이 위 단언의 기반이다."""
        from nuri.trading.agents.base import QueryRows

        empty, failed = QueryRows(), QueryRows(failed=True)
        assert not empty and not failed  # 둘 다 falsy — 기존 `if not rows` 호출부 보존
        assert empty.failed is False and failed.failed is True


class TestPlaceholdersAreNotOpinionsOnAnySurface:
    """읽기 표면마다 따로 잠근다 (#1436, codex R13/R14).

    백엔드는 자리표시자를 동의율·패널 커버리지에서 뺀다. 어떤 표면이든 그걸 확신도 붙은
    의견으로 그리면 **같은 출력이 자기 자신과 모순**된다 — "동의율 100%" 옆에 10 표가
    나란히 선다. 한 표면만 고친 상태가 안 고친 것보다 나쁘고, 이 이슈에서 실제로 세 번
    반복됐다(persist 경로 2, 프론트 4, CLI/LLM 2).
    """

    @staticmethod
    def _result():
        return _build_consensus(
            "TESTTICKER",
            [
                v("technical", "BUY", 75),
                v("korean_market", "HOLD", 50, abstained=True),
                v("crypto", "HOLD", 0, degraded=True),
            ],
            WEIGHTS,
        )

    def test_cli_table_does_not_print_a_confidence_for_placeholders(self, capsys):
        from nuri.trading.agents.consensus.presentation import print_consensus

        print_consensus([self._result()])
        out = capsys.readouterr().out
        assert "H50" not in out, "기권에 확신도를 찍었다 — 같은 줄의 동의율과 모순된다"
        assert "H0" not in out
        assert "B75" in out  # 카나리아 — 진짜 의견은 그대로 나온다

    def test_the_llm_prompt_does_not_hand_placeholders_over_as_votes(self):
        """LLM 이 `korean_market=HOLD` 를 진짜 표로 읽으면 프롬프트가 거짓을 담는다."""
        from nuri.llm.report import format_agent_summary

        summary = format_agent_summary(self._result().verdicts)
        assert "korean_market=HOLD" not in summary
        assert "crypto=HOLD" not in summary
        assert "technical=BUY" in summary  # 카나리아
