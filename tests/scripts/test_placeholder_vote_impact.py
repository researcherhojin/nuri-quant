"""#1437 측정 스크립트 잠금 — 재구성이나 보고 수치가 어긋나면 FAIL 한다.

취약점이 셋이다.

**문자열 재구성.** 과거 원장에는 `abstained` 플래그가 없어(#1436 이 2026-09-07 머지)
자리표시자 문구로 되짚는데, 문구가 바뀌면 측정은 **조용히** 자리표시자를 살아 있는 의견으로
세기 시작한다. 이미 두 번 갈렸다 — `fundamental` 은 원장 486 셀이 `"데이터 제한적"` 인데 현재
소스는 `"펀더멘탈 데이터 제한적"` 이고, `smart_money` 는 날짜가 박힌 note 를 이어 붙여 고정
문구 자체가 없다.

**V0 와 V0' 의 분리.** 원장 기준 뒤집힘과 현재 코드 기준 뒤집힘이 섞이면 #1436 이 이미
걷어간 몫을 #1437 의 효과로 청구하게 된다(실측 252 vs 197). 두 축이 **다른 값을 내는**
픽스처가 없으면 그 분리는 어떤 테스트도 밟지 않는다 — codex 4 라운드가 이 구멍으로 들어와
`flipped` 의 비교 대상을 바꿔도 전부 초록인 것을 실측했다.

**보고 수치.** 결과가 1 건인 픽스처만 두면 분위수 세 개가 전부 같은 값이 되어
`_quantiles` 가 무엇을 내든 통과한다. 헤드라인(중앙값 · p95 · 최대)이 거기서 나온다.

⚠️ **재생 충실도는 재구성을 검증하지 못한다.** 스크립트가 persist 된 판정을 1,629/1,629
재현하지만, `abstained` 는 V0 의 `final_action` 에 애초에 영향이 없다(그게 #1437 이 미뤄진
이유다). 그 일치가 증명하는 건 가중치·verdict 복원뿐이다. 그래서 여기서 에이전트를 실제로
자리표시자 출구로 몰아 **생산 플래그**와 대조한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.analysis.placeholder_vote_impact import (
    CURRENT_CODE_ZEROED,
    FIX_MERGED,
    RowResult,
    as_current_code,
    build_parser,
    classify,
    format_report,
    rescore,
    to_verdict,
)


def verdict_dict(agent: str, reasoning: str, *, action="HOLD", confidence=0.0, data_points=None) -> dict:
    return {
        "agent_name": agent,
        "ticker": "TESTTICKER",
        "action": action,
        "confidence": confidence,
        "reasoning": reasoning,
        "data_points": data_points or {},
    }


class TestClassifyMatchesProduction:
    """에이전트를 자리표시자 출구로 몰아 **생산이 선언한 플래그**와 재구성을 대조한다."""

    def test_every_placeholder_exit_is_reconstructed(self, tmp_path):
        """문구가 바뀌면 여기서 FAIL 한다 — 측정이 조용히 틀리는 대신."""
        from nuri.core.db import init_db
        from nuri.trading.agents.base import QueryRows
        from nuri.trading.agents.crypto_agent import CryptoAgent
        from nuri.trading.agents.fundamental import FundamentalAgent
        from nuri.trading.agents.korean_market import KoreanMarketAgent
        from nuri.trading.agents.macro_agent import MacroAgent
        from nuri.trading.agents.options_agent import OptionsAgent
        from nuri.trading.agents.retail_agent import RetailAgent
        from nuri.trading.agents.smart_money import SmartMoneyAgent
        from nuri.trading.agents.technical import TechnicalAgent
        from nuri.trading.agents.wallstreet import WallStreetAgent

        empty = tmp_path / "empty.db"
        init_db(empty)

        def pcr_rows_all_null(agent):
            agent._safe_query = lambda sql, params=(), db_path=None: QueryRows([{"value": None}])

        cases = [
            ("korean_market/US", KoreanMarketAgent(), "TESTTICKER", None),
            ("korean_market/KR-무데이터", KoreanMarketAgent(), "000000.KS", None),
            ("wallstreet/.KS", WallStreetAgent(), "000000.KS", None),
            ("wallstreet/US-빈소스", WallStreetAgent(), "TESTTICKER", None),
            ("options/PCR-null", OptionsAgent(), "TESTTICKER", pcr_rows_all_null),
            ("macro/no-SPY", MacroAgent(), "TESTTICKER", None),
            ("crypto/무데이터", CryptoAgent(), "TESTTICKER", None),
            ("retail/무데이터", RetailAgent(), "TESTTICKER", None),
            ("fundamental/무데이터", FundamentalAgent(), "TESTTICKER", None),
            ("smart_money/무데이터", SmartMoneyAgent(), "TESTTICKER", None),
            ("technical/무데이터", TechnicalAgent(), "TESTTICKER", None),
        ]

        offenders: list[str] = []
        abstentions = 0
        for name, agent, ticker, prep in cases:
            if prep:
                prep(agent)
            v = agent.analyze(ticker, db_path=empty)
            truth = (v.degraded, v.abstained)
            guess = classify(
                verdict_dict(v.agent_name, v.reasoning, confidence=v.confidence, data_points=v.data_points)
            )
            abstentions += int(v.abstained)
            if truth != guess:
                offenders.append(f"{name}: 생산={truth} 재구성={guess} reasoning={v.reasoning!r}")

        assert offenders == [], (
            f"자리표시자 문구가 바뀌어 재구성이 어긋난다 — `PLACEHOLDER_REASONS` 를 갱신할 것: {offenders}"
        )
        # 카나리아: 전부 live 로 나오면 위 단언이 공허하다 (#910 dead-gate 형태).
        assert abstentions >= 8, f"자리표시자 출구를 {abstentions} 개만 밟았다 — 몰이가 깨졌다"

    def test_a_read_failure_is_reconstructed_as_degraded(self, monkeypatch):
        """실패는 기권이 아니다 — 축이 섞이면 인시던트가 상시 부재로 위장된다."""
        # 파사드(`nuri.core.db`)의 `DB_PATH` 를 간다 — `tests/CLAUDE.md` 가 정한 방식이고
        # `query`/`query_df` monkeypatch 는 금지다 (#1149).
        import nuri.core.db as dbmod
        from nuri.trading.agents.fundamental import FundamentalAgent

        monkeypatch.setattr(dbmod, "DB_PATH", Path("/nonexistent-dir-for-1437/no.db"))
        v = FundamentalAgent().analyze("TESTTICKER")
        assert (v.degraded, v.abstained) == (True, False)
        assert classify(verdict_dict(v.agent_name, v.reasoning, confidence=v.confidence)) == (True, False)

    def test_runner_exception_prefix_is_degraded(self):
        """러너는 `f"에러: {e}"` 를 쓴다 — 예외 문구가 매번 달라 접두사로 본다."""
        assert classify(verdict_dict("risk", "에러: unable to open database file")) == (True, False)
        assert classify(verdict_dict("risk", "타임아웃")) == (True, False)

    def test_a_real_low_confidence_judgment_stays_live(self):
        """`risk` 의 "리스크 정상" 은 raw≤40 이 0 으로 정규화된 **판단**이다 (#1436 codex R1)."""
        assert classify(verdict_dict("risk", "리스크 정상", confidence=0.0)) == (False, False)


class TestHistoricalStringVariants:
    """#1436 이전 원장의 문구도 되짚어야 한다 — 현재 소스만 보면 486 셀을 통째로 놓친다."""

    def test_pre_1436_fundamental_wording_is_recognised(self):
        assert classify(
            verdict_dict("fundamental", "데이터 제한적", confidence=50.0, data_points={"pe": None, "roe": None})
        ) == (False, True)

    @pytest.mark.parametrize(("field", "value"), [("pe", 18.0), ("roe", 12.4), ("growth", 0.08), ("debt", 0.9)])
    def test_the_same_wording_with_values_is_a_judgment(self, field, value):
        """그 문구는 과거 `"; ".join(reasons) or ...` 의 폴백이라 **판단도** 통과했다 (#1436 codex R9).

        네 필드를 각각 단독으로 민다 — 하나만 검사하면 `FUNDAMENTAL_FIELDS` 에서 나머지
        셋을 지워도 통과한다.
        """
        assert classify(verdict_dict("fundamental", "데이터 제한적", confidence=50.0, data_points={field: value})) == (
            False,
            False,
        )

    def test_wording_is_scoped_to_its_agent(self):
        assert classify(verdict_dict("technical", "데이터 부족")) == (False, True)
        assert classify(verdict_dict("risk", "데이터 부족")) == (False, False)

    def test_the_pre_1436_macro_exit_is_recognised(self):
        """현재 소스 문자열만 훑는 스윕으로는 안 잡힌다 — 원장에만 있는 문구다."""
        assert classify(verdict_dict("macro", "레짐/매크로 데이터 부족", confidence=0.0)) == (False, True)

    def test_a_neutral_kr_read_is_a_judgment(self):
        """`"Korean market neutral"` 은 자리표시자처럼 읽히지만 **아니다**.

        원장 16 셀 전부 `fx_rate` 와 `momentum_20d` 를 담고 있어 현재 부재 게이트 기준으로는
        값을 읽고 중립을 확인한 판단이다. 넣으면 codex R9 의 과교정을 반복한다.
        """
        assert classify(
            verdict_dict(
                "korean_market",
                "Korean market neutral",
                confidence=0.0,
                data_points={"is_korean": True, "fx_rate": 1483.0, "momentum_20d": -6.95, "foreign_net": None},
            )
        ) == (False, False)


class TestSmartMoneyStaleNotes:
    """`smart_money` 의 자리표시자는 **고정 문구가 아니다** — 집합으로는 영영 못 담는다."""

    def test_an_all_stale_note_reason_is_an_abstention(self):
        """`"; ".join(notes)` 폴백. 날짜가 박혀 있어 문자열 집합으로는 못 잡는다.

        놓치면 #1187 이 일부러 만든 분기가 **확신도 30 짜리 살아 있는 HOLD** 로 집계돼
        `fundamental "데이터 제한적"` 과 같은 형태의 오분류가 된다.
        """
        reason = "슈퍼투자자 13F 낡음(최신 2026-01-02) — 제외; ARK 매매 낡음(최신 2025-12-30) — 제외"
        assert classify(verdict_dict("smart_money", reason, confidence=30.0)) == (False, True)

    def test_a_reason_that_also_carries_evidence_stays_live(self):
        """짝 — note 가 섞여 있어도 **점수를 만든 근거**가 하나라도 있으면 판단이다."""
        reason = "슈퍼투자자 13F 낡음(최신 2026-01-02) — 제외; 애널리스트: buy (9명)"
        assert classify(verdict_dict("smart_money", reason, confidence=45.0)) == (False, False)

    def test_the_shape_is_scoped_to_smart_money(self):
        """다른 에이전트가 같은 모양의 문구를 내도 이 규칙을 빌려 쓰지 않는다."""
        assert classify(verdict_dict("technical", "무언가 낡음(최신 2026-01-02) — 제외")) == (False, False)

    def test_production_actually_emits_this_shape(self, tmp_path):
        """**생산을 몰아서** 확인한다 — 삭제 잠금만으로는 문구 드리프트를 못 잡는다.

        `TestClassifyMatchesProduction` 의 몰이는 빈 DB 를 쓰므로 `notes` 가 비어 고정 문구
        분기로만 빠진다. 그래서 프로덕션의 note 문구를 `— 제외` → `— 미반영` 으로 바꿔도
        모든 테스트가 초록이었다 (codex 3 라운드 실측). 낡은 소스를 실제로 심어 그 분기를
        밟게 하고, 생산이 선언한 플래그와 재구성을 대조한다.
        """
        from nuri.core.db import get_db, init_db
        from nuri.trading.agents.smart_money import SmartMoneyAgent

        db = tmp_path / "stale.db"
        init_db(db)
        with get_db(db) as conn:
            # conviction 제출분이 전부 cutoff 보다 낡으면 `_source_is_fresh` 가 False 를 내고
            # 생산이 "낡음 — 제외" note 를 만든다. 다른 소스는 비어 있어 근거가 0 이 된다.
            conn.execute(
                "INSERT INTO superinvestors (ticker, investor, investor_class, portfolio_pct, filing_date) "
                "VALUES ('TESTTICKER', 'Investor A', 'conviction', 8.0, '2020-01-01')"
            )

        v = SmartMoneyAgent().analyze("TESTTICKER", db_path=db)
        assert "낡음" in v.reasoning, f"이 분기를 못 밟았다 — 시드가 낡지 않았나: {v.reasoning!r}"
        assert (v.degraded, v.abstained) == (False, True), "생산이 자리표시자로 선언하지 않았다"
        assert classify(
            verdict_dict(v.agent_name, v.reasoning, confidence=v.confidence, data_points=v.data_points)
        ) == (False, True), f"재구성이 생산과 어긋난다 — `STALE_NOTE` 를 갱신할 것: {v.reasoning!r}"


class TestCurrentCodeCounterfactual:
    """#1436 이 이미 걷어간 몫을 이 이슈의 효과로 청구하지 않는다."""

    def test_only_the_changed_site_is_zeroed(self):
        legacy = to_verdict(verdict_dict("fundamental", "데이터 제한적", confidence=50.0))
        assert as_current_code(legacy).confidence == 0.0

    def test_a_live_judgment_with_the_same_wording_keeps_its_confidence(self):
        """`classify` 가 판단이라고 한 행까지 0 으로 깎으면 그 판단을 지우는 것이다."""
        live = to_verdict(verdict_dict("fundamental", "데이터 제한적", confidence=50.0, data_points={"pe": 18.0}))
        assert live.abstained is False
        assert as_current_code(live).confidence == 50.0

    def test_every_failed_read_is_zeroed_whatever_its_ledger_confidence(self):
        """오늘의 코드에서 실패한 조회는 **어떤 경로로도** 표를 못 던진다.

        `base.py::_no_data` 의 실패 분기가 `confidence` 인자를 버리고(#1436 codex R6) 러너의
        degraded 도 처음부터 0 이다. 원장의 확신도를 그대로 두면 V0' 가 "현재 코드" 를
        참칭한다 — 이 원장에서는 degraded 7 셀이 전부 0 이라 수치는 안 움직이지만, 그건
        데이터의 성질이지 코드의 성질이 아니다.
        """
        for agent, reason in (("smart_money", "스마트머니 조회 실패"), ("risk", "에러: unable to open database file")):
            v = to_verdict(verdict_dict(agent, reason, confidence=30.0))
            assert v.degraded is True
            assert as_current_code(v).confidence == 0.0, f"{agent} degraded 가 표를 유지했다"

    def test_other_placeholders_keep_their_confidence(self):
        for agent, reason, conf in (
            ("smart_money", "스마트머니 데이터 없음", 30.0),
            ("wallstreet", "Wall Street 데이터 미지원 종목", 20.0),
            ("korean_market", "US ticker — Korean market agent neutral", 50.0),
        ):
            v = to_verdict(verdict_dict(agent, reason, confidence=conf))
            assert as_current_code(v).confidence == conf, f"{agent} 확신도가 바뀌었다"

    def test_the_zeroed_set_is_not_empty(self):
        """카나리아 — 집합이 비면 V0 와 V0' 가 같아져 분리가 사라진다."""
        assert CURRENT_CODE_ZEROED


def _row(
    verdicts: list[dict], weights: dict, *, action: str, date="2026-05-01", ticker="TESTTICKER", confidence=None
) -> dict:
    """합성 원장 행. `confidence` 를 안 주면 **커널이 냈을 값**을 쓴다.

    `replay_matches_ledger` 가 확신도까지 대조하므로 아무 값이나 박으면 픽스처가 "재현 실패"
    로 분류돼 테스트가 엉뚱한 이유로 통과/실패한다.
    """
    if confidence is None:
        from nuri.trading.agents.consensus.scoring import _build_consensus

        confidence = _build_consensus(ticker, [to_verdict(v) for v in verdicts], weights).final_confidence
    return {
        "date": date,
        "ticker": ticker,
        "action": action,
        "confidence": confidence,
        "agent_verdicts": json.dumps(verdicts, ensure_ascii=False),
        "scoring_detail": json.dumps({"source": "consensus", "weights": weights}, ensure_ascii=False),
    }


# 자리표시자 HOLD 0.09+0.06 = 0.15 이 살아 있는 BUY 0.12 을 이긴다 → V0'=HOLD.
# 빼면 BUY 0.12 vs SELL 0.04 → BUY. 즉 HOLD → BUY 뒤집힘.
FLIP_VERDICTS = [
    verdict_dict("technical", "SMA50>SMA200 (골든크로스)", action="BUY", confidence=60.0),
    verdict_dict("risk", "고변동성 (일간σ 5.2%)", action="SELL", confidence=20.0),
    verdict_dict("smart_money", "스마트머니 데이터 없음", confidence=30.0),
    verdict_dict("wallstreet", "Wall Street 데이터 부족", confidence=20.0),
]
FLIP_WEIGHTS = {"technical": 0.2, "risk": 0.2, "smart_money": 0.3, "wallstreet": 0.3}

# 자리표시자 하나만 단독 후보인 배치 — smart_money 가 HOLD 0.17 중 0.15 를 낸다.
SOLE_VERDICTS = [
    verdict_dict("technical", "골든크로스", action="BUY", confidence=60.0),
    verdict_dict("risk", "고변동성", action="SELL", confidence=20.0),
    verdict_dict("smart_money", "스마트머니 데이터 없음", confidence=30.0),
    verdict_dict("wallstreet", "Wall Street 데이터 부족", confidence=20.0),
]
SOLE_WEIGHTS = {"technical": 0.2, "risk": 0.2, "smart_money": 0.5, "wallstreet": 0.1}


def _report(results, **kw):
    kw.setdefault("mismatched", 0)
    return format_report(results, **kw)


def _result(*, share, ledger, current, excluded, live_panel=5, date="2026-05-01") -> RowResult:
    """보고 층 픽스처 — `rescore` 를 거치지 않고 `format_report` 의 **입력**을 직접 만든다.

    결과가 1 건인 픽스처만 두면 분위수 셋이 전부 같은 값이 되고 두 뒤집힘 집합도 항상
    일치해서, 보고 층 코드가 무엇을 하든 통과한다 (codex 4 라운드 실측).
    """
    return RowResult(
        date=date,
        ticker="TESTTICKER",
        ledger_action=ledger,
        ledger_confidence=50.0,
        current_action=current,
        excluded_action=excluded,
        current_confidence=50.0,
        excluded_confidence=55.0,
        middle_confidence=45.0,
        placeholder_share=share,
        sole_flippers=[],
        placeholder_agents=["smart_money"],
        live_panel=live_panel,
        panel=live_panel + 1,
    )


# 두 뒤집힘 집합이 **다른 크기**를 갖는 최소 배치. 원장 기준 3 · 현재 코드 기준 2.
TWO_AXIS_RESULTS = [
    _result(share=0.40, ledger="HOLD", current="HOLD", excluded="SELL", live_panel=9),
    _result(share=0.10, ledger="HOLD", current="HOLD", excluded="BUY", live_panel=3),
    _result(share=0.30, ledger="BUY", current="BUY", excluded="BUY", live_panel=7),
    _result(share=0.20, ledger="HOLD", current="BUY", excluded="BUY", live_panel=5),
]


class TestRescore:
    def test_a_placeholder_majority_flips_once_excluded(self):
        r = rescore(_row(FLIP_VERDICTS, FLIP_WEIGHTS, action="HOLD"))
        assert r is not None
        assert (r.ledger_action, r.current_action, r.excluded_action) == ("HOLD", "HOLD", "BUY")
        assert r.flipped is True
        # 분모는 세 버킷 전체다 — BUY 0.12 + SELL 0.04 + HOLD 0.15.
        assert r.placeholder_share == pytest.approx(0.15 / 0.31)

    def test_attribution_names_the_agents_that_voted(self):
        r = rescore(_row(FLIP_VERDICTS, FLIP_WEIGHTS, action="HOLD"))
        assert r is not None
        assert sorted(r.placeholder_agents) == ["smart_money", "wallstreet"]
        assert sorted(r.sole_flippers) == ["smart_money", "wallstreet"]

    def test_a_live_majority_does_not_flip(self):
        verdicts = [
            verdict_dict("technical", "골든크로스", action="BUY", confidence=90.0),
            verdict_dict("smart_money", "스마트머니 데이터 없음", confidence=30.0),
        ]
        r = rescore(_row(verdicts, {"technical": 0.5, "smart_money": 0.5}, action="BUY"))
        assert r is not None and r.flipped is False and r.sole_flippers == []

    def test_non_consensus_scoring_detail_is_skipped(self):
        """`candidates.py` 도 같은 컬럼을 쓴다 — discriminator 없이 읽으면 남의 스키마를 센다."""
        row = _row(FLIP_VERDICTS, FLIP_WEIGHTS, action="HOLD")
        row["scoring_detail"] = json.dumps({"source": "candidates", "tier": 1})
        assert rescore(row) is None

    def test_unparseable_row_is_skipped(self):
        row = _row(FLIP_VERDICTS, FLIP_WEIGHTS, action="HOLD")
        row["agent_verdicts"] = "{not json"
        assert rescore(row) is None

    def test_a_failed_read_is_a_ledger_flip_but_not_a_current_code_flip(self):
        """**두 축이 갈리는 유일한 픽스처** — #1436 이 이미 걷어간 몫은 #1437 의 효과가 아니다.

        실패(degraded)도 V1 에서 빠지지만, 현재 코드는 이미 그 표를 0 으로 만든다
        (`base.py::_no_data` 가 `confidence` 인자를 의도적으로 버린다). 그래서 원장 기준으로는
        뒤집히고 현재 코드 기준으로는 **안 뒤집힌다**. 이 픽스처가 없으면 `RowResult.flipped`
        의 비교 대상을 `current` → `ledger` 로 바꿔도, 보고서가 두 집합을 맞바꿔도 전부
        초록이다 (codex 4 라운드 실측).
        """
        verdicts = [
            verdict_dict("technical", "골든크로스", action="BUY", confidence=60.0),
            verdict_dict("risk", "고변동성", action="SELL", confidence=20.0),
            verdict_dict("smart_money", "스마트머니 조회 실패", confidence=30.0),
            verdict_dict("wallstreet", "Wall Street 조회 실패", confidence=20.0),
        ]
        r = rescore(_row(verdicts, FLIP_WEIGHTS, action="HOLD"))
        assert r is not None
        assert r.live_panel == 2, "실패 verdict 가 live 패널에 남았다"
        assert (r.ledger_action, r.current_action, r.excluded_action) == ("HOLD", "BUY", "BUY")
        assert r.flipped_vs_ledger is True and r.flipped is False
        # 표를 던지는 자리표시자는 기권뿐 — degraded 는 현재 코드에서 이미 0 이다.
        assert r.placeholder_agents == [] and r.sole_flippers == []

    def test_an_all_placeholder_panel_is_not_counted(self):
        """live 가 비면 커널 `max()` 가 전부 0 인 dict 에서 'BUY' 를 뽑아 **없던 뒤집힘**을 만든다."""
        verdicts = [
            verdict_dict("smart_money", "스마트머니 데이터 없음", confidence=30.0),
            verdict_dict("wallstreet", "Wall Street 데이터 부족", confidence=20.0),
        ]
        assert rescore(_row(verdicts, {"smart_money": 0.5, "wallstreet": 0.5}, action="HOLD")) is None


class TestReplayFidelity:
    def test_confidence_is_compared_not_just_action(self):
        """action 은 3 지 선다라 우연 일치가 흔하다 — 확신도가 훨씬 강한 복원 잠금이다."""
        from scripts.analysis.placeholder_vote_impact import replay_matches_ledger

        row = _row(FLIP_VERDICTS, FLIP_WEIGHTS, action="HOLD")
        r = rescore(row)
        assert r is not None and replay_matches_ledger(row, r) is True

        # 허용 오차는 커널의 4 자리 반올림 폭이다. 5.0 을 밀면 오차를 4.9 로 넓혀도 잡히므로
        # **경계 바로 바깥**을 민다 — 이 값이 느슨해지면 재현 실패가 성공으로 집계된다.
        row["confidence"] = float(row["confidence"]) + 0.2
        assert replay_matches_ledger(row, r) is False

    def test_the_tolerance_absorbs_the_kernels_own_rounding(self):
        """짝 — 오차를 0 으로 조이면 반올림 차이가 전부 "재현 실패" 가 된다."""
        from scripts.analysis.placeholder_vote_impact import replay_matches_ledger

        row = _row(FLIP_VERDICTS, FLIP_WEIGHTS, action="HOLD")
        r = rescore(row)
        assert r is not None
        row["confidence"] = float(row["confidence"]) + 0.1
        assert replay_matches_ledger(row, r) is True


class TestStructuralProperties:
    def test_a_flip_can_only_leave_hold(self):
        """자리표시자는 전부 HOLD 라 제외하면 HOLD 점수만 내려간다.

        BUY·SELL 은 그대로이므로 반대 방향 전환은 원리상 불가능하다. 즉 이 변경은 중립적
        정확도 수정이 아니라 **HOLD 를 매매로 바꾸는 편향 변경**이다.
        """
        r = rescore(_row(FLIP_VERDICTS, FLIP_WEIGHTS, action="HOLD"))
        assert r is not None
        assert r.current_action == "HOLD" and r.excluded_action in ("BUY", "SELL")

    def test_the_middle_option_is_rounded_where_the_kernel_rounds(self):
        """V2 확신도는 커널과 **같은 자리**에서 반올림해야 한다.

        raw 로 두면 V1(커널이 이미 반올림한 값)과 V2 를 서로 다르게 반올림된 수로 비교하게
        된다. 하류 소비자가 임계를 걸 때도 그쪽이 보는 것은 반올림된 값이다 — 이 스크립트는
        그 임계를 세지 않지만(모듈 독스트링), 값의 형태는 프로덕션과 같아야 한다.
        """
        r = rescore(_row(FLIP_VERDICTS, FLIP_WEIGHTS, action="HOLD"))
        assert r is not None
        assert r.middle_confidence == round(r.middle_confidence, 1), "게이트가 보는 자리에서 반올림해야 한다"
        assert r.middle_confidence < 50.0
        assert r.excluded_confidence >= 50.0

    def test_rounding_can_lift_the_middle_option_over_a_half_point(self):
        """반올림이 경계를 넘길 수 있다 — raw 49.96 은 저장값 50.0 이다.

        "V2 는 알제브라상 항상 50 미만" 이라는 진술이 **반올림 뒤에는 거짓**이라는 것을
        잠근다. 이 사실이 없으면 V2 를 "구조적으로 안전" 이라고 쓰게 된다.
        """
        verdicts = [
            verdict_dict("technical", "골든크로스", action="BUY", confidence=49.96),
            verdict_dict("smart_money", "스마트머니 데이터 없음", confidence=50.04),
        ]
        r = rescore(_row(verdicts, {"technical": 1.0, "smart_money": 1.0}, action="HOLD"))
        assert r is not None and r.flipped and r.excluded_action == "BUY"
        assert r.middle_confidence >= 50.0


class TestSoleAttribution:
    def test_a_single_placeholder_can_own_the_flip(self):
        """축소판이 가능한지가 여기서 갈린다 — 실측에서 `korean_market` 이 44 건을 단독 소유."""
        r = rescore(_row(SOLE_VERDICTS, SOLE_WEIGHTS, action="HOLD"))
        assert r is not None and r.flipped is True
        assert r.sole_flippers == ["smart_money"]
        assert "smart_money 1" in _report([r])


class TestReportAndCli:
    def test_quantiles_of_nothing_are_zero_not_an_error(self):
        from scripts.analysis.placeholder_vote_impact import _quantiles

        assert _quantiles([]) == (0.0, 0.0, 0.0)

    def test_the_three_quantiles_are_distinct_and_order_independent(self):
        """헤드라인 세 수가 여기서 나온다 — 셋이 갈리는 표본이 없으면 무엇을 내든 통과한다.

        21 개를 쓰는 이유는 `int(0.95 * n)` 이 그보다 작은 표본에서 **최대와 같은 인덱스**를
        가리켜 p95 와 최대가 구분되지 않기 때문이다. 입력은 일부러 섞어 넣는다 — `sorted()`
        를 지워도 통과하면 잠금이 아니다.
        """
        from scripts.analysis.placeholder_vote_impact import _quantiles

        shuffled = [7.0, 20.0, 3.0, 14.0, 0.0, 11.0, 18.0, 5.0, 9.0, 16.0, 2.0]
        shuffled += [12.0, 19.0, 6.0, 1.0, 15.0, 8.0, 17.0, 4.0, 13.0, 10.0]
        assert len(shuffled) == 21
        assert _quantiles(shuffled) == (10.0, 19.0, 20.0)

    def test_the_report_keeps_the_two_flip_axes_apart(self):
        """원장 기준과 현재 코드 기준이 **다른 수**로 나와야 한다.

        섞이면 #1436 이 이미 걷어간 몫을 #1437 의 효과로 청구한다 (실측 252 vs 197).
        """
        text = _report(TWO_AXIS_RESULTS)
        assert "원장 기준 3 / 4" in text
        assert "현재 코드 기준 2 / 4" in text
        assert "HOLD → SELL: 1" in text and "HOLD → BUY: 1" in text

    def test_the_report_quantiles_are_not_all_the_same_number(self):
        """표 비중 줄 — 중앙값과 최대가 갈린 표본으로 렌더한다."""
        text = _report(TWO_AXIS_RESULTS)
        assert "중앙값 30.0% · p95 40.0% · 최대 40.0%" in text

    def test_the_thin_panel_count_includes_the_boundary(self):
        """`≤3` 은 경계 포함이다 — `<3` 으로 좁히면 얇은 패널이 조용히 사라진다."""
        assert "그중 ≤3 인 것 1 건" in _report(TWO_AXIS_RESULTS)

    def test_the_residual_is_scoped_to_every_v0_prime_number(self):
        """잔차 경고가 뒤집힘 한 줄에만 붙으면 나머지 수가 무조건적 추정으로 읽힌다.

        같은 구분 불가가 표 비중·V0' 분포·|Δ confidence|·귀속에 **똑같이** 실린다.
        """
        text = _report(TWO_AXIS_RESULTS)
        # **같은 줄**에서 본다 — 보고서 아무 데나 찾으면 "자리표시자 표 비중" 헤더가 대신
        # 매치돼 잔차 항에서 열거를 통째로 지워도 통과한다 (이 세션에서 실제로 밟은 형태).
        residual = next(line for line in text.splitlines() if "측정되지 않은 잔차" in line)
        for axis in ("표 비중", "V0' 분포", "뒤집힘", "|Δ confidence|", "귀속"):
            assert axis in residual, f"잔차 항이 {axis} 축을 안 덮는다: {residual}"
        assert "점 추정이 아니라 상한" in residual
        assert "상한" in text.split("뒤집힘 — ")[1].split("\n")[0], "뒤집힘 줄이 상한이라고 말하지 않는다"

    def test_the_report_says_whether_the_residual_can_be_bounded_at_all(self):
        """#1436 이후 결정이 0 건이면 잔차는 **미관측**이고 그 사실이 결과의 일부다."""
        before = _report(TWO_AXIS_RESULTS)
        assert f"#1436 머지({FIX_MERGED}) **다음날부터**의 결정 0 / 4 건" in before
        assert "잔차는 **미관측**이다" in before

    def test_the_merge_day_itself_is_not_a_post_fix_sample(self):
        """경계는 `>` 다 — PR #1449 는 20:49 KST 머지고 consensus cron 은 07:05 KST 다.

        머지일 당일 결정은 옛 코드가 냈다. `>=` 로 넓히면 잔차를 가둘 표본을 실제보다 많이
        세어 "가둘 수 있다" 를 과장한다. 원장은 시각 없이 날짜만 담아 이 하루는 되찾을 수 없다.
        """
        same_day = [
            *TWO_AXIS_RESULTS[:3],
            _result(share=0.2, ledger="HOLD", current="BUY", excluded="BUY", date=FIX_MERGED),
        ]
        assert "결정 0 / 4 건" in _report(same_day)

        next_day = [
            *TWO_AXIS_RESULTS[:3],
            _result(share=0.2, ledger="HOLD", current="BUY", excluded="BUY", date="2026-09-08"),
        ]
        text = _report(next_day)
        assert "결정 1 / 4 건" in text
        assert "미관측" not in text

    def test_report_names_the_net_effect_and_the_residual(self):
        r = rescore(_row(FLIP_VERDICTS, FLIP_WEIGHTS, action="HOLD"))
        assert r is not None
        text = _report([r])
        assert "HOLD → BUY: 1" in text
        assert "재현 실패 0 건" in text
        # 잔차를 안 적으면 197 이 무조건적 점 추정으로 읽힌다.
        assert "측정되지 않은 잔차" in text
        # V1 확신도가 오르는 이유(분모 축소)를 안 적으면 "제외하니 더 확신하게 됐다" 로 읽힌다.
        assert "live 패널 분포" in text and "분모 축소이지 신호가 아니다" in text

    def test_the_report_states_what_it_does_not_measure(self):
        """이번 축소의 핵심 진술 — 이 산출물은 **변경을 정당화하는 데 쓸 수 없다**.

        하류 노출과 수익 축은 세 라운드 연속 틀려서 걷어냈다. 그 사실을 보고서가 말하지
        않으면 "판정이 12% 바뀐다" 가 승격 근거처럼 읽힌다.
        """
        r = rescore(_row(FLIP_VERDICTS, FLIP_WEIGHTS, action="HOLD"))
        assert r is not None
        text = _report([r])
        assert "판정 축만" in text
        assert "정당화할 수 없다" in text

    def test_a_report_with_no_flips_still_reports(self):
        """뒤집힘 0 건도 관측이다 — 패널 분포 줄만 빠지고 나머지는 그대로 나와야 한다.

        0 건에서 죽거나 침묵하면 "변화 없음" 과 "측정 실패" 가 구분되지 않는다.
        """
        verdicts = [
            verdict_dict("technical", "골든크로스", action="BUY", confidence=90.0),
            verdict_dict("smart_money", "스마트머니 데이터 없음", confidence=30.0),
        ]
        r = rescore(_row(verdicts, {"technical": 0.5, "smart_money": 0.5}, action="BUY"))
        assert r is not None and r.flipped is False

        text = _report([r])
        assert "현재 코드 기준 0 / 1" in text
        assert "live 패널 분포" not in text
        assert "자리표시자 표 비중" in text

    def test_db_argument_is_a_path_not_a_string(self):
        """`str` 이면 `connection.py` 의 `path.parent` 에서 AttributeError 로 죽는다."""
        args = build_parser().parse_args(["--db", "/tmp/x.db"])
        assert isinstance(args.db, Path)

    def test_parser_defaults(self):
        args = build_parser().parse_args([])
        assert args.db is None

    def test_main_reports_failure_when_there_is_nothing_to_measure(self, monkeypatch, capsys):
        from scripts.analysis import placeholder_vote_impact as mod

        monkeypatch.setattr(mod, "load_rows", lambda _db: [])
        assert mod.main([]) == 1
        assert "측정할 것이 없다" in capsys.readouterr().err

    def test_main_reports_failure_when_the_replay_reproduces_nothing(self, monkeypatch, capsys):
        """재생이 원장을 못 맞추면 **초록으로 끝내지 않는다** — 미실행을 통과로 읽는 부류."""
        from scripts.analysis import placeholder_vote_impact as mod

        row = _row(FLIP_VERDICTS, FLIP_WEIGHTS, action="SELL")  # 재생은 HOLD 를 낸다
        monkeypatch.setattr(mod, "load_rows", lambda _db: [row])
        assert mod.main([]) == 1
        assert "재현하지 못했다" in capsys.readouterr().err

    def test_main_prints_the_report_on_the_happy_path(self, monkeypatch, capsys):
        from scripts.analysis import placeholder_vote_impact as mod

        monkeypatch.setattr(mod, "load_rows", lambda _db: [_row(FLIP_VERDICTS, FLIP_WEIGHTS, action="HOLD")])
        assert mod.main([]) == 0
        assert "순효과" in capsys.readouterr().out

    def test_main_skips_rows_it_cannot_rescore(self, monkeypatch, capsys):
        from scripts.analysis import placeholder_vote_impact as mod

        bad = _row(FLIP_VERDICTS, FLIP_WEIGHTS, action="HOLD")
        bad["scoring_detail"] = json.dumps({"source": "candidates"})
        good = _row(FLIP_VERDICTS, FLIP_WEIGHTS, action="HOLD")
        monkeypatch.setattr(mod, "load_rows", lambda _db: [bad, good])
        assert mod.main([]) == 0
        assert "재현된 결정 1 건" in capsys.readouterr().out


class TestDbBackedHelpers:
    """DB 를 실제로 읽는 헬퍼 — 얇지만 여기서 틀리면 표본이 통째로 빈다."""

    @staticmethod
    def _seed(tmp_path):
        from nuri.core.db import init_db

        db = tmp_path / "impact.db"
        init_db(db)
        return db

    def test_load_rows_returns_only_scored_consensus_rows(self, tmp_path):
        from nuri.core.db import get_db
        from scripts.analysis.placeholder_vote_impact import load_rows

        db = self._seed(tmp_path)
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, agent_verdicts, scoring_detail) "
                "VALUES ('2026-05-01','TESTTICKER','HOLD',48.4,?,?)",
                (
                    json.dumps(FLIP_VERDICTS, ensure_ascii=False),
                    json.dumps({"source": "consensus", "weights": FLIP_WEIGHTS}),
                ),
            )
            # 점수 없는 행은 재채점할 수 없다 — 세면 분모만 부풀린다.
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence) VALUES ('2026-05-02','OTHER','BUY',10.0)"
            )

        rows = load_rows(db)
        assert [r["ticker"] for r in rows] == ["TESTTICKER"]
        assert rescore(rows[0]) is not None
