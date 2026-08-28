"""Decision Intelligence 테스트 — 멱등성, 기록, 결과 추적."""

import json
from dataclasses import dataclass, field
from datetime import datetime

import pytest

from nuri.core.db import (
    get_db,
    get_decision_with_evidence,
    get_decisions,
    init_db,
    query,
    upsert_decision,
    upsert_decision_evidence,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _insert_price(db_path, ticker, close, date="2026-04-10"):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, date, close * 0.99, close * 1.02, close * 0.98, close, 1000000),
        )


# ═══════════════════════════════════════════════════════
# 스키마 마이그레이션 테스트
# ═══════════════════════════════════════════════════════


class TestDecisionsMigration:
    def test_decisions_table_exists(self, db_path):
        rows = query("PRAGMA table_info(decisions)", db_path=db_path)
        cols = [r["name"] for r in rows]
        assert "id" in cols
        assert "date" in cols
        assert "ticker" in cols
        assert "action" in cols
        assert "regime" in cols
        assert "macro_score" in cols
        assert "event_score" in cols
        assert "pnl_7d" in cols
        assert "pnl_30d" in cols
        assert "pnl_90d" in cols
        assert "outcome" in cols

    def test_decision_evidence_table_exists(self, db_path):
        rows = query("PRAGMA table_info(decision_evidence)", db_path=db_path)
        cols = [r["name"] for r in rows]
        assert "decision_id" in cols
        assert "source_type" in cols
        assert "source_key" in cols

    def test_migration_versions_14_15(self, db_path):
        rows = query("SELECT version FROM schema_version ORDER BY version", db_path=db_path)
        versions = [r["version"] for r in rows]
        assert 14 in versions
        assert 15 in versions


# ═══════════════════════════════════════════════════════
# upsert_decision 멱등성 테스트
# ═══════════════════════════════════════════════════════


class TestUpsertDecision:
    def test_insert_new_decision(self, db_path):
        data = {
            "date": "2026-04-10",
            "ticker": "NVDA",
            "action": "BUY",
            "confidence": 75.0,
            "entry_price": 120.0,
        }
        dec_id = upsert_decision(data, db_path)
        assert dec_id > 0

        rows = query("SELECT * FROM decisions WHERE id = ?", (dec_id,), db_path)
        assert len(rows) == 1
        assert rows[0]["ticker"] == "NVDA"
        assert rows[0]["outcome"] == "pending"

    def test_idempotent_same_day_ticker(self, db_path):
        """같은 날 같은 티커 → UPDATE, 중복 없음."""
        data1 = {"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 70.0}
        data2 = {"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 80.0}

        upsert_decision(data1, db_path)
        upsert_decision(data2, db_path)

        # 같은 레코드 업데이트
        rows = query("SELECT * FROM decisions WHERE date = '2026-04-10' AND ticker = 'NVDA'", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["confidence"] == 80.0  # 최신 값

    def test_different_ticker_creates_new(self, db_path):
        """같은 날 다른 티커 → 별도 레코드."""
        upsert_decision({"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 70.0}, db_path)
        upsert_decision({"date": "2026-04-10", "ticker": "TSLA", "action": "SELL", "confidence": 60.0}, db_path)

        rows = query("SELECT * FROM decisions WHERE date = '2026-04-10'", db_path=db_path)
        assert len(rows) == 2

    def test_different_day_creates_new(self, db_path):
        """다른 날 같은 티커 → 별도 레코드 (의사결정 히스토리)."""
        upsert_decision({"date": "2026-04-09", "ticker": "NVDA", "action": "BUY", "confidence": 70.0}, db_path)
        upsert_decision({"date": "2026-04-10", "ticker": "NVDA", "action": "HOLD", "confidence": 65.0}, db_path)

        rows = query("SELECT * FROM decisions WHERE ticker = 'NVDA' ORDER BY date", db_path=db_path)
        assert len(rows) == 2
        assert rows[0]["action"] == "BUY"
        assert rows[1]["action"] == "HOLD"


# ═══════════════════════════════════════════════════════
# upsert_decision_evidence 멱등성 테스트
# ═══════════════════════════════════════════════════════


class TestUpsertEvidence:
    def test_insert_evidence(self, db_path):
        dec_id = upsert_decision({"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0}, db_path)
        records = [
            {
                "source_type": "agent",
                "source_key": "technical",
                "action": "BUY",
                "confidence": 80.0,
                "detail": json.dumps({"rsi": 28}),
            },
            {
                "source_type": "agent",
                "source_key": "fundamental",
                "action": "BUY",
                "confidence": 72.0,
                "detail": json.dumps({"pe": 36}),
            },
        ]
        count = upsert_decision_evidence(dec_id, records, db_path)
        assert count == 2

    def test_evidence_idempotent(self, db_path):
        """같은 decision_id + source_type + source_key → UPDATE."""
        dec_id = upsert_decision({"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0}, db_path)
        records = [
            {
                "source_type": "agent",
                "source_key": "technical",
                "action": "BUY",
                "confidence": 80.0,
                "detail": json.dumps({"rsi": 28}),
            },
        ]
        upsert_decision_evidence(dec_id, records, db_path)

        # 같은 source_type+source_key로 재실행 (confidence 변경)
        records[0]["confidence"] = 85.0
        upsert_decision_evidence(dec_id, records, db_path)

        evidence = query(
            "SELECT * FROM decision_evidence WHERE decision_id = ? AND source_key = 'technical'",
            (dec_id,),
            db_path,
        )
        assert len(evidence) == 1
        assert evidence[0]["confidence"] == 85.0  # 최신 값

    def test_empty_records(self, db_path):
        assert upsert_decision_evidence(1, [], db_path) == 0


# ═══════════════════════════════════════════════════════
# get_decisions / get_decision_with_evidence 테스트
# ═══════════════════════════════════════════════════════


class TestQueryDecisions:
    def test_get_decisions_all(self, db_path):
        upsert_decision({"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0}, db_path)
        upsert_decision({"date": "2026-04-10", "ticker": "TSLA", "action": "SELL", "confidence": 60.0}, db_path)

        rows = get_decisions(db_path=db_path)
        assert len(rows) == 2

    def test_get_decisions_filter_ticker(self, db_path):
        upsert_decision({"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0}, db_path)
        upsert_decision({"date": "2026-04-10", "ticker": "TSLA", "action": "SELL", "confidence": 60.0}, db_path)

        rows = get_decisions(ticker="NVDA", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["ticker"] == "NVDA"

    def test_get_decisions_filter_outcome(self, db_path):
        upsert_decision({"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0}, db_path)
        rows = get_decisions(outcome="pending", db_path=db_path)
        assert len(rows) == 1

        rows = get_decisions(outcome="success", db_path=db_path)
        assert len(rows) == 0

    def test_get_decision_with_evidence(self, db_path):
        dec_id = upsert_decision({"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0}, db_path)
        upsert_decision_evidence(
            dec_id,
            [
                {
                    "source_type": "agent",
                    "source_key": "technical",
                    "action": "BUY",
                    "confidence": 80.0,
                    "detail": json.dumps({"rsi": 28}),
                },
            ],
            db_path,
        )

        result = get_decision_with_evidence(dec_id, db_path)
        assert result is not None
        assert result["ticker"] == "NVDA"
        assert len(result["evidence"]) == 1
        assert result["evidence"][0]["source_key"] == "technical"

    def test_get_nonexistent_decision(self, db_path):
        assert get_decision_with_evidence(999, db_path) is None


# ═══════════════════════════════════════════════════════
# record_decision (통합 테스트)
# ═══════════════════════════════════════════════════════


@dataclass
class MockAgentVerdict:
    agent_name: str
    ticker: str
    action: str
    confidence: float
    reasoning: str
    data_points: dict = field(default_factory=dict)


@dataclass
class MockConsensusResult:
    ticker: str
    final_action: str
    final_confidence: float
    agreement_rate: float
    verdicts: list
    dissent: list
    reasoning: str
    scoring_detail: dict | None = None  # #1256: 실 ConsensusResult 와 동일하게 optional


class TestRecordDecision:
    def test_record_from_consensus(self, db_path):
        """ConsensusResult → decisions + evidence 자동 기록."""
        from nuri.trading.engine.decisions import record_decision

        _insert_price(db_path, "NVDA", 120.0)

        result = MockConsensusResult(
            ticker="NVDA",
            final_action="BUY",
            final_confidence=75.0,
            agreement_rate=0.8,
            verdicts=[
                MockAgentVerdict("technical", "NVDA", "BUY", 80.0, "RSI oversold", {"rsi": 28}),
                MockAgentVerdict("fundamental", "NVDA", "BUY", 72.0, "PE reasonable", {"pe": 36}),
                MockAgentVerdict("risk", "NVDA", "HOLD", 55.0, "Position near limit", {}),
            ],
            dissent=["risk"],
            reasoning="Technical + fundamental consensus",
        )

        dec_id = record_decision(result, db_path)
        assert dec_id > 0

        decision = get_decision_with_evidence(dec_id, db_path)
        assert decision is not None
        assert decision["ticker"] == "NVDA"
        assert decision["action"] == "BUY"
        assert decision["entry_price"] == 120.0
        assert decision["outcome"] == "pending"

        # Evidence: 3 agents
        agent_evidence = [e for e in decision["evidence"] if e["source_type"] == "agent"]
        assert len(agent_evidence) == 3

    def test_record_idempotent(self, db_path):
        """같은 날 같은 티커 2회 실행 → 1개 레코드만."""
        from nuri.trading.engine.decisions import record_decision

        _insert_price(db_path, "NVDA", 120.0)

        result1 = MockConsensusResult(
            ticker="NVDA",
            final_action="BUY",
            final_confidence=70.0,
            agreement_rate=0.7,
            verdicts=[
                MockAgentVerdict("technical", "NVDA", "BUY", 80.0, "RSI low", {"rsi": 30}),
            ],
            dissent=[],
            reasoning="First run",
        )
        result2 = MockConsensusResult(
            ticker="NVDA",
            final_action="BUY",
            final_confidence=80.0,
            agreement_rate=0.9,
            verdicts=[
                MockAgentVerdict("technical", "NVDA", "BUY", 85.0, "RSI very low", {"rsi": 25}),
            ],
            dissent=[],
            reasoning="Second run",
        )

        record_decision(result1, db_path)
        record_decision(result2, db_path)

        rows = get_decisions(ticker="NVDA", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["confidence"] == 80.0  # 최신

    def test_record_decisions_batch(self, db_path):
        """record_decisions 일괄 기록."""
        from nuri.trading.engine.decisions import record_decisions

        _insert_price(db_path, "NVDA", 120.0)
        _insert_price(db_path, "TSLA", 250.0)

        results = [
            MockConsensusResult(
                ticker="NVDA",
                final_action="BUY",
                final_confidence=75.0,
                agreement_rate=0.8,
                verdicts=[
                    MockAgentVerdict("technical", "NVDA", "BUY", 80.0, "ok", {}),
                ],
                dissent=[],
                reasoning="NVDA buy",
            ),
            MockConsensusResult(
                ticker="TSLA",
                final_action="SELL",
                final_confidence=60.0,
                agreement_rate=0.6,
                verdicts=[
                    MockAgentVerdict("risk", "TSLA", "SELL", 90.0, "high risk", {}),
                ],
                dissent=[],
                reasoning="TSLA sell",
            ),
        ]

        count = record_decisions(results, db_path)
        assert count == 2
        assert len(get_decisions(db_path=db_path)) == 2


# ═══════════════════════════════════════════════════════
# #1256 — scoring_detail persist + regime fallback (Gotcha-Test Pair)
# ═══════════════════════════════════════════════════════


class TestScoringDetailIsPersisted:
    """scoring.py 가 계산한 판정 감사 정보가 decisions 행까지 도달하는지 잠금.

    #1256 이전: ConsensusResult.scoring_detail 은 recommendations 경로만 persist 되고
    record_decision 이 버려서 387행 전부 NULL 이었다. persist 줄을 지우면 FAIL.
    """

    def test_scoring_detail_round_trips(self, db_path):
        from nuri.trading.engine.decisions import record_decision

        _insert_price(db_path, "NVDA", 120.0)
        detail = {
            "source": "consensus",
            "schema_version": 1,
            "final_action_source": "risk_veto",
            "degraded_agents": ["smart_money"],
            "panel_coverage": 0.9,
        }
        result = MockConsensusResult(
            ticker="NVDA",
            final_action="SELL",
            final_confidence=100.0,
            agreement_rate=0.2,
            verdicts=[MockAgentVerdict("risk", "NVDA", "SELL", 100.0, "stop breach", {})],
            dissent=[],
            reasoning="리스크 에이전트 거부권 발동: 손절선 돌파",
            scoring_detail=detail,
        )

        dec_id = record_decision(result, db_path)
        row = query("SELECT scoring_detail FROM decisions WHERE id = ?", (dec_id,), db_path)[0]
        assert row["scoring_detail"] is not None
        assert json.loads(row["scoring_detail"]) == detail

    def test_absent_scoring_detail_stays_null(self, db_path):
        """scoring_detail 없는 결과(구 호출자·구 mock)는 NULL — 빈 dict/문자열 오염 금지."""
        from nuri.trading.engine.decisions import record_decision

        _insert_price(db_path, "NVDA", 120.0)
        result = MockConsensusResult(
            ticker="NVDA",
            final_action="BUY",
            final_confidence=70.0,
            agreement_rate=0.7,
            verdicts=[MockAgentVerdict("technical", "NVDA", "BUY", 80.0, "ok", {})],
            dissent=[],
            reasoning="plain consensus",
        )

        dec_id = record_decision(result, db_path)
        row = query("SELECT scoring_detail FROM decisions WHERE id = ?", (dec_id,), db_path)[0]
        assert row["scoring_detail"] is None


class TestRegimeFallsBackToClassifier:
    """decisions.regime NULL 상근 버그 (#1256) 잠금.

    _snapshot_market_context 는 pipeline_events.regime_changed 만 읽었는데 그 이벤트는
    dev/prod 모두 0건 — frozen 컨텍스트의 Regime 이 항상 "—" 였다. fallback 을 지우면 FAIL.
    """

    def _record_one(self, db_path):
        from nuri.trading.engine.decisions import record_decision

        _insert_price(db_path, "NVDA", 120.0)
        result = MockConsensusResult(
            ticker="NVDA",
            final_action="BUY",
            final_confidence=70.0,
            agreement_rate=0.7,
            verdicts=[MockAgentVerdict("technical", "NVDA", "BUY", 80.0, "ok", {})],
            dissent=[],
            reasoning="regime test",
        )
        return record_decision(result, db_path)

    def test_no_event_falls_back_to_classifier(self, db_path, monkeypatch):
        import nuri.quant.regime.classifier as classifier

        class _State:
            regime = "bull_low_vol"

        monkeypatch.setattr(classifier, "classify_regime", lambda db_path=None: _State())
        dec_id = self._record_one(db_path)
        row = query("SELECT regime FROM decisions WHERE id = ?", (dec_id,), db_path)[0]
        assert row["regime"] == "bull_low_vol"

    def test_event_still_wins_over_classifier(self, db_path, monkeypatch):
        """이벤트가 있으면 그 값이 우선 — fallback 이 스냅샷 의미를 바꾸면 안 된다.

        ⚠️ 스텁은 **예외를 던지지 않는다.** 이전 판은 `AssertionError("classifier must not
        be called")` 를 던졌는데, 프로덕션이 `decisions.py` 의 `except Exception: pass` 로
        그걸 삼켜서 이벤트 값이 그대로 남고 단언이 통과했다 — 즉 **우선순위를 전혀
        잠그지 못했다**. 뮤테이션 실측으로 확인: `if not context.get("regime"):` 를
        `if True:` 로 바꿔도 3 passed, fallback 이 이벤트 값을 덮어쓰게 바꿔도 3 passed.

        레포는 이 교훈을 이미 갖고 있다 (`tests/CLAUDE.md`): `_forbid_production_db` 의
        예외가 `BaseException` 을 직접 상속하는 것도 같은 이유이고, 거기 결론이
        "삼켜지는 백스톱은 백스톱이 아니다" 다.

        그래서 스텁은 **다른 canonical regime 을 반환**한다. fallback 이 이벤트 값을
        덮으면 그 값이 나타나 단언이 깨진다.
        """
        import nuri.quant.regime.classifier as classifier
        from nuri.core.events import emit_event

        class _State:
            regime = "bull_low_vol"  # 이벤트 값과 다른 canonical 값

        emit_event("regime_changed", payload={"regime": "bear_high_vol"}, db_path=db_path)
        monkeypatch.setattr(classifier, "classify_regime", lambda db_path=None: _State())
        dec_id = self._record_one(db_path)
        row = query("SELECT regime FROM decisions WHERE id = ?", (dec_id,), db_path)[0]
        assert row["regime"] == "bear_high_vol", "분류기 값이 이벤트 값을 덮었다 — 우선순위 역전"

    def test_classifier_failure_leaves_regime_null(self, db_path, monkeypatch):
        """분류기 실패는 soft-fail — 관측이 본 작업(기록)을 게이트하면 안 된다 (#894)."""
        import nuri.quant.regime.classifier as classifier

        def _boom(db_path=None):
            raise RuntimeError("no SPY data")

        monkeypatch.setattr(classifier, "classify_regime", _boom)
        dec_id = self._record_one(db_path)
        row = query("SELECT regime FROM decisions WHERE id = ?", (dec_id,), db_path)[0]
        assert row["regime"] is None


# ═══════════════════════════════════════════════════════
# track_decision_outcomes 멱등성 테스트
# ═══════════════════════════════════════════════════════


class TestTrackOutcomes:
    def test_no_pending_decisions(self, db_path):
        from nuri.trading.engine.decisions import track_decision_outcomes

        assert track_decision_outcomes(db_path) == 0

    def test_7d_outcome_filled(self, db_path):
        """7일 경과 → pnl_7d만 채워짐.

        오늘 - 14일 (7~29일 윈도우 내) 로 픽: pnl_7d 는 채워지고 pnl_30d 는 미경과.
        과거 하드코딩 (2026-04-01) 패턴은 calendar drift 로 깨졌음 (오늘이 30일째 되는 날 fail).
        """
        from datetime import date as _date
        from datetime import timedelta

        from nuri.core.timezone import today_kst
        from nuri.trading.engine.decisions import track_decision_outcomes

        anchor = _date.fromisoformat(today_kst()) - timedelta(days=14)
        anchor_str = anchor.isoformat()
        plus_7 = (anchor + timedelta(days=7)).isoformat()

        _insert_price(db_path, "NVDA", 120.0, anchor_str)
        _insert_price(db_path, "NVDA", 132.0, plus_7)  # 7일 후 +10%

        upsert_decision(
            {
                "date": anchor_str,
                "ticker": "NVDA",
                "action": "BUY",
                "confidence": 75.0,
                "entry_price": 120.0,
            },
            db_path,
        )

        updated = track_decision_outcomes(db_path)
        assert updated == 1

        rows = get_decisions(ticker="NVDA", db_path=db_path)
        assert rows[0]["pnl_7d"] == 10.0
        assert rows[0]["pnl_30d"] is None  # 아직 30일 미경과
        assert rows[0]["outcome"] == "pending"

    def test_outcome_idempotent(self, db_path):
        """이미 채워진 PnL은 재실행해도 변경 없음."""
        from datetime import date as _date
        from datetime import timedelta

        from nuri.core.timezone import today_kst
        from nuri.trading.engine.decisions import track_decision_outcomes

        anchor = _date.fromisoformat(today_kst()) - timedelta(days=14)
        anchor_str = anchor.isoformat()
        plus_7 = (anchor + timedelta(days=7)).isoformat()

        _insert_price(db_path, "NVDA", 120.0, anchor_str)
        _insert_price(db_path, "NVDA", 132.0, plus_7)

        upsert_decision(
            {
                "date": anchor_str,
                "ticker": "NVDA",
                "action": "BUY",
                "confidence": 75.0,
                "entry_price": 120.0,
            },
            db_path,
        )

        track_decision_outcomes(db_path)  # 1회
        rows1 = get_decisions(ticker="NVDA", db_path=db_path)

        # 가격 변경 후 재실행
        _insert_price(db_path, "NVDA", 150.0, plus_7)
        track_decision_outcomes(db_path)  # 2회
        rows2 = get_decisions(ticker="NVDA", db_path=db_path)

        # pnl_7d는 첫 실행 값 유지 (멱등)
        assert rows1[0]["pnl_7d"] == rows2[0]["pnl_7d"]

    def test_90d_sets_outcome(self, db_path):
        """90일 경과 → outcome 판정."""
        from nuri.trading.engine.decisions import track_decision_outcomes

        _insert_price(db_path, "NVDA", 100.0, "2026-01-01")
        _insert_price(db_path, "NVDA", 107.0, "2026-01-08")
        _insert_price(db_path, "NVDA", 115.0, "2026-01-31")
        _insert_price(db_path, "NVDA", 120.0, "2026-03-02")
        _insert_price(db_path, "NVDA", 130.0, "2026-04-01")

        upsert_decision(
            {
                "date": "2026-01-01",
                "ticker": "NVDA",
                "action": "BUY",
                "confidence": 75.0,
                "entry_price": 100.0,
            },
            db_path,
        )

        updated = track_decision_outcomes(db_path)
        assert updated == 1

        rows = get_decisions(ticker="NVDA", db_path=db_path)
        assert rows[0]["pnl_90d"] is not None
        assert rows[0]["outcome"] == "success"  # +30% > 0

    def test_sell_outcome_success(self, db_path):
        """SELL 의사결정: 90일 후 하락 → success."""
        from nuri.trading.engine.decisions import track_decision_outcomes

        _insert_price(db_path, "BAD", 100.0, "2026-01-01")
        _insert_price(db_path, "BAD", 95.0, "2026-01-08")
        _insert_price(db_path, "BAD", 85.0, "2026-01-31")
        _insert_price(db_path, "BAD", 75.0, "2026-03-02")
        _insert_price(db_path, "BAD", 70.0, "2026-04-01")

        upsert_decision(
            {
                "date": "2026-01-01",
                "ticker": "BAD",
                "action": "SELL",
                "confidence": 80.0,
                "entry_price": 100.0,
            },
            db_path,
        )

        track_decision_outcomes(db_path)

        rows = get_decisions(ticker="BAD", db_path=db_path)
        assert rows[0]["outcome"] == "success"  # SELL 후 하락 = 성공


# ═══════════════════════════════════════════════════════
# get_decision_summary 테스트
# ═══════════════════════════════════════════════════════


class TestDecisionSummary:
    def test_empty_summary(self, db_path):
        from nuri.trading.engine.decisions import get_decision_summary

        summary = get_decision_summary(db_path)
        assert summary["total"] == 0
        assert summary["pending"] == 0

    def test_summary_counts(self, db_path):
        from nuri.trading.engine.decisions import get_decision_summary

        upsert_decision({"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0}, db_path)
        upsert_decision({"date": "2026-04-10", "ticker": "TSLA", "action": "SELL", "confidence": 60.0}, db_path)

        summary = get_decision_summary(db_path)
        assert summary["total"] == 2
        assert summary["pending"] == 2


# ═══════════════════════════════════════════════════════
# compute_agent_accuracy 학습 루프 테스트
# ═══════════════════════════════════════════════════════


def _insert_decision_with_outcome(db_path, ticker, action, outcome, verdicts, date="2026-04-10"):
    """테스트 헬퍼: outcome이 설정된 decision 삽입."""
    verdicts_json = json.dumps(verdicts)
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO decisions "
            "(date, ticker, action, confidence, agent_verdicts, outcome, entry_price) "
            "VALUES (?, ?, ?, 75.0, ?, ?, 100.0)",
            (date, ticker, action, verdicts_json, outcome),
        )


class TestComputeAgentAccuracy:
    def test_empty_decisions(self, db_path):
        """완료된 decisions 없으면 빈 dict 반환."""
        from nuri.trading.engine.decisions import compute_agent_accuracy

        result = compute_agent_accuracy(db_path)
        assert result == {}

    def test_pending_decisions_excluded(self, db_path):
        """outcome='pending'인 decisions는 제외."""
        from nuri.trading.engine.decisions import compute_agent_accuracy

        upsert_decision(
            {
                "date": "2026-04-10",
                "ticker": "NVDA",
                "action": "BUY",
                "confidence": 75.0,
                "agent_verdicts": json.dumps(
                    [
                        {"agent_name": "technical", "action": "BUY", "confidence": 80},
                    ]
                ),
            },
            db_path,
        )

        result = compute_agent_accuracy(db_path)
        assert result == {}

    def test_buy_success_is_hit(self, db_path):
        """BUY 판단 + outcome=success → 적중."""
        from nuri.trading.engine.decisions import compute_agent_accuracy

        _insert_decision_with_outcome(
            db_path,
            "NVDA",
            "BUY",
            "success",
            [
                {"agent_name": "technical", "action": "BUY", "confidence": 80},
                {"agent_name": "fundamental", "action": "BUY", "confidence": 70},
            ],
        )

        result = compute_agent_accuracy(db_path)
        assert result["technical"]["hits"] == 1
        assert result["technical"]["total"] == 1
        assert result["technical"]["hit_rate"] == 1.0
        assert result["fundamental"]["hits"] == 1

    def test_sell_failure_is_hit(self, db_path):
        """SELL 판단 + outcome=failure → 적중 (올바르게 회피)."""
        from nuri.trading.engine.decisions import compute_agent_accuracy

        _insert_decision_with_outcome(
            db_path,
            "BAD",
            "BUY",
            "failure",
            [
                {"agent_name": "risk", "action": "SELL", "confidence": 90},
            ],
        )

        result = compute_agent_accuracy(db_path)
        assert result["risk"]["hits"] == 1
        assert result["risk"]["total"] == 1
        assert result["risk"]["hit_rate"] == 1.0

    def test_buy_failure_is_miss(self, db_path):
        """BUY 판단 + outcome=failure → 미스."""
        from nuri.trading.engine.decisions import compute_agent_accuracy

        _insert_decision_with_outcome(
            db_path,
            "BAD",
            "BUY",
            "failure",
            [
                {"agent_name": "technical", "action": "BUY", "confidence": 80},
            ],
        )

        result = compute_agent_accuracy(db_path)
        assert result["technical"]["hits"] == 0
        assert result["technical"]["total"] == 1
        assert result["technical"]["hit_rate"] == 0.0

    def test_sell_success_is_miss(self, db_path):
        """SELL 판단 + outcome=success → 미스 (매도 권유했으나 상승)."""
        from nuri.trading.engine.decisions import compute_agent_accuracy

        _insert_decision_with_outcome(
            db_path,
            "NVDA",
            "BUY",
            "success",
            [
                {"agent_name": "risk", "action": "SELL", "confidence": 85},
            ],
        )

        result = compute_agent_accuracy(db_path)
        assert result["risk"]["hits"] == 0
        assert result["risk"]["total"] == 1
        assert result["risk"]["hit_rate"] == 0.0

    def test_hold_excluded(self, db_path):
        """HOLD 판단은 적중 판정에서 제외."""
        from nuri.trading.engine.decisions import compute_agent_accuracy

        _insert_decision_with_outcome(
            db_path,
            "NVDA",
            "BUY",
            "success",
            [
                {"agent_name": "technical", "action": "BUY", "confidence": 80},
                {"agent_name": "risk", "action": "HOLD", "confidence": 50},
            ],
        )

        result = compute_agent_accuracy(db_path)
        assert "technical" in result
        assert "risk" not in result  # HOLD은 제외

    def test_multiple_decisions_aggregation(self, db_path):
        """여러 decisions 결과 종합 — 2 success + 1 failure."""
        from nuri.trading.engine.decisions import compute_agent_accuracy

        # Decision 1: BUY NVDA → success (technical BUY=hit, risk SELL=miss)
        _insert_decision_with_outcome(
            db_path,
            "NVDA",
            "BUY",
            "success",
            [
                {"agent_name": "technical", "action": "BUY", "confidence": 80},
                {"agent_name": "risk", "action": "SELL", "confidence": 60},
            ],
            date="2026-01-01",
        )

        # Decision 2: BUY TSLA → success (technical BUY=hit, risk BUY=hit)
        _insert_decision_with_outcome(
            db_path,
            "TSLA",
            "BUY",
            "success",
            [
                {"agent_name": "technical", "action": "BUY", "confidence": 75},
                {"agent_name": "risk", "action": "BUY", "confidence": 55},
            ],
            date="2026-02-01",
        )

        # Decision 3: BUY BAD → failure (technical BUY=miss, risk SELL=hit)
        _insert_decision_with_outcome(
            db_path,
            "BAD",
            "BUY",
            "failure",
            [
                {"agent_name": "technical", "action": "BUY", "confidence": 70},
                {"agent_name": "risk", "action": "SELL", "confidence": 85},
            ],
            date="2026-03-01",
        )

        result = compute_agent_accuracy(db_path)

        # technical: 2 hits / 3 total = 66.7%
        assert result["technical"]["total"] == 3
        assert result["technical"]["hits"] == 2
        assert abs(result["technical"]["hit_rate"] - 0.6667) < 0.001

        # risk: 1 miss + 1 hit + 1 hit = 2 hits / 3 total = 66.7%
        assert result["risk"]["total"] == 3
        assert result["risk"]["hits"] == 2

    def test_weight_adjustment_clamping(self, db_path):
        """weight_adjustment는 [-0.30, +0.30] 범위로 클램핑."""
        from nuri.trading.engine.decisions import compute_agent_accuracy

        # 100% 적중 → raw adjustment = 0.5, clamped to 0.30
        _insert_decision_with_outcome(
            db_path,
            "A",
            "BUY",
            "success",
            [
                {"agent_name": "perfect_agent", "action": "BUY", "confidence": 90},
            ],
            date="2026-01-01",
        )

        result = compute_agent_accuracy(db_path)
        assert result["perfect_agent"]["weight_adjustment"] == 0.30  # clamped

    def test_weight_adjustment_clamping_negative(self, db_path):
        """0% 적중 → raw adjustment = -0.5, clamped to -0.30."""
        from nuri.trading.engine.decisions import compute_agent_accuracy

        _insert_decision_with_outcome(
            db_path,
            "A",
            "BUY",
            "failure",
            [
                {"agent_name": "bad_agent", "action": "BUY", "confidence": 90},
            ],
            date="2026-01-01",
        )

        result = compute_agent_accuracy(db_path)
        assert result["bad_agent"]["weight_adjustment"] == -0.30  # clamped

    def test_weight_adjustment_baseline(self, db_path):
        """50% 적중 → weight_adjustment = 0.0 (조정 없음)."""
        from nuri.trading.engine.decisions import compute_agent_accuracy

        # 1 hit + 1 miss = 50%
        _insert_decision_with_outcome(
            db_path,
            "A",
            "BUY",
            "success",
            [
                {"agent_name": "neutral_agent", "action": "BUY", "confidence": 80},
            ],
            date="2026-01-01",
        )
        _insert_decision_with_outcome(
            db_path,
            "B",
            "BUY",
            "failure",
            [
                {"agent_name": "neutral_agent", "action": "BUY", "confidence": 80},
            ],
            date="2026-02-01",
        )

        result = compute_agent_accuracy(db_path)
        assert result["neutral_agent"]["hit_rate"] == 0.5
        assert result["neutral_agent"]["weight_adjustment"] == 0.0

    def test_malformed_verdicts_json_skipped(self, db_path):
        """잘못된 JSON은 건너뛰고 나머지 처리."""
        from nuri.trading.engine.decisions import compute_agent_accuracy

        # 올바른 decision
        _insert_decision_with_outcome(
            db_path,
            "NVDA",
            "BUY",
            "success",
            [
                {"agent_name": "technical", "action": "BUY", "confidence": 80},
            ],
            date="2026-01-01",
        )

        # 잘못된 JSON 직접 삽입
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO decisions (date, ticker, action, confidence, agent_verdicts, outcome, entry_price) "
                "VALUES ('2026-02-01', 'BAD', 'BUY', 75.0, 'not-json', 'failure', 100.0)",
            )

        result = compute_agent_accuracy(db_path)
        assert result["technical"]["total"] == 1  # 잘못된 JSON은 무시


# ═══════════════════════════════════════════════════════
# save_agent_accuracy_snapshot 멱등성 테스트
# ═══════════════════════════════════════════════════════


class TestSaveAgentAccuracySnapshot:
    def test_empty_no_snapshot(self, db_path):
        """완료된 decisions 없으면 스냅샷 0건."""
        from nuri.trading.engine.decisions import save_agent_accuracy_snapshot

        assert save_agent_accuracy_snapshot(db_path) == 0

    def test_snapshot_saves_to_strategy_memory(self, db_path):
        """적중률이 strategy_memory에 저장됨."""
        from nuri.trading.engine.decisions import save_agent_accuracy_snapshot

        _insert_decision_with_outcome(
            db_path,
            "NVDA",
            "BUY",
            "success",
            [
                {"agent_name": "technical", "action": "BUY", "confidence": 80},
                {"agent_name": "fundamental", "action": "BUY", "confidence": 70},
            ],
        )

        count = save_agent_accuracy_snapshot(db_path)
        assert count == 2  # 2 agents

        rows = query(
            "SELECT * FROM strategy_memory WHERE signal_id LIKE 'agent_%_accuracy'",
            db_path=db_path,
        )
        assert len(rows) == 2

        tech_row = [r for r in rows if r["signal_id"] == "agent_technical_accuracy"][0]
        assert tech_row["regime"] == "all"
        assert tech_row["period"] == "all_time"
        assert tech_row["win_rate"] == 1.0  # 100% 적중

    def test_snapshot_idempotent(self, db_path):
        """같은 날 재실행 → 덮어쓰기 (UNIQUE 제약)."""
        from nuri.trading.engine.decisions import save_agent_accuracy_snapshot

        _insert_decision_with_outcome(
            db_path,
            "NVDA",
            "BUY",
            "success",
            [
                {"agent_name": "technical", "action": "BUY", "confidence": 80},
            ],
        )

        save_agent_accuracy_snapshot(db_path)
        save_agent_accuracy_snapshot(db_path)  # 2회 실행

        rows = query(
            "SELECT * FROM strategy_memory WHERE signal_id = 'agent_technical_accuracy'",
            db_path=db_path,
        )
        assert len(rows) == 1  # 중복 없음


# ═══════════════════════════════════════════════════════
# _snapshot_market_context — VIX / Fear&Greed / regime / macro_score branches
# ═══════════════════════════════════════════════════════


class TestSnapshotMarketContext:
    def test_vix_value_extracted(self, db_path):
        """Line 218: VIX row exists → context['vix'] set."""
        from nuri.trading.engine.decisions import _snapshot_market_context

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
                ("vix", "2026-04-10", 22.5, "test"),
            )
        ctx = _snapshot_market_context(db_path=db_path)
        assert ctx["vix"] == 22.5

    def test_fear_greed_value_extracted(self, db_path):
        """Line 226: fear_greed row exists → context['fear_greed'] set."""
        from nuri.trading.engine.decisions import _snapshot_market_context

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
                ("fear_greed", "2026-04-10", 64.0, "test"),
            )
        ctx = _snapshot_market_context(db_path=db_path)
        assert ctx["fear_greed"] == 64.0

    def test_regime_payload_parsed(self, db_path):
        """Lines 235-237: pipeline_events 'regime_changed' → regime extracted."""
        from nuri.trading.engine.decisions import _snapshot_market_context

        # 첫 번째 regime: payload "regime" 키
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_events (timestamp, event_type, payload) VALUES (?, ?, ?)",
                ("2026-04-10T10:00:00", "regime_changed", json.dumps({"regime": "risk_on"})),
            )
        ctx = _snapshot_market_context(db_path=db_path)
        assert ctx["regime"] == "risk_on"

    def test_regime_payload_new_regime_fallback(self, db_path):
        """Line 237: payload "regime" missing → fallback "new_regime" key."""
        from nuri.trading.engine.decisions import _snapshot_market_context

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_events (timestamp, event_type, payload) VALUES (?, ?, ?)",
                ("2026-04-10T10:00:00", "regime_changed", json.dumps({"new_regime": "risk_off"})),
            )
        ctx = _snapshot_market_context(db_path=db_path)
        assert ctx["regime"] == "risk_off"

    def test_regime_malformed_json_swallowed(self, db_path):
        """Lines 238-239: invalid JSON payload → except branch, no crash, regime not set."""
        from nuri.trading.engine.decisions import _snapshot_market_context

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_events (timestamp, event_type, payload) VALUES (?, ?, ?)",
                ("2026-04-10T10:00:00", "regime_changed", "not-json"),
            )
        ctx = _snapshot_market_context(db_path=db_path)
        assert "regime" not in ctx  # 파싱 실패 → 미설정

    def test_macro_score_exception_swallowed(self, db_path, monkeypatch):
        """Lines 247-248: compute_macro_score raises → except, macro_score not set."""
        from nuri.trading.engine.decisions import _snapshot_market_context

        def boom(*a, **kw):
            raise RuntimeError("synthetic")

        monkeypatch.setattr(
            "nuri.quant.regime.macro_score.compute_macro_score",
            boom,
        )
        ctx = _snapshot_market_context(db_path=db_path)
        # exception 흡수: macro_score / event_score 미설정
        assert "macro_score" not in ctx
        assert "event_score" not in ctx


# ═══════════════════════════════════════════════════════
# record_decision: regime evidence 추가 분기 (line 102)
# ═══════════════════════════════════════════════════════


class TestRecordDecisionRegimeEvidence:
    def test_regime_context_appended_as_evidence(self, db_path):
        """Lines 101-108: context['regime'] truthy → regime evidence record 추가."""
        from nuri.trading.engine.decisions import record_decision

        # Set regime via pipeline_events (truthy) so context.get('regime') returns a value
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_events (timestamp, event_type, payload) VALUES (?, ?, ?)",
                ("2026-04-10T10:00:00", "regime_changed", json.dumps({"regime": "risk_on"})),
            )
        _insert_price(db_path, "NVDA", 120.0)

        result = MockConsensusResult(
            ticker="NVDA",
            final_action="BUY",
            final_confidence=75.0,
            agreement_rate=0.8,
            verdicts=[
                MockAgentVerdict("technical", "NVDA", "BUY", 80.0, "ok", {"rsi": 28}),
            ],
            dissent=[],
            reasoning="regime evidence test",
        )
        dec_id = record_decision(result, db_path)

        decision = get_decision_with_evidence(dec_id, db_path)
        regime_evidence = [e for e in decision["evidence"] if e["source_type"] == "regime"]
        assert len(regime_evidence) == 1
        assert regime_evidence[0]["source_key"] == "current"
        # regime 값이 detail JSON 안에 들어 있음
        detail = json.loads(regime_evidence[0]["detail"])
        assert detail["regime"] == "risk_on"
        # decisions row 의 regime 컬럼 자체도 채워졌는지 확인
        assert decision["regime"] == "risk_on"


# ═══════════════════════════════════════════════════════
# track_decision_outcomes: HOLD action → outcome=neutral (line 171)
# ═══════════════════════════════════════════════════════


class TestTrackOutcomesNeutral:
    def test_hold_action_90d_yields_neutral(self, db_path):
        """Lines 170-171: action 이 BUY/SELL 이 아니면 outcome='neutral'.

        90 일 경과 + entry_price 양수 + HOLD action → outcome='neutral'.
        """
        # 100 일 전 anchor 로 90d 경과 보장
        from datetime import date as _date
        from datetime import timedelta

        from nuri.core.timezone import today_kst
        from nuri.trading.engine.decisions import track_decision_outcomes

        anchor = _date.fromisoformat(today_kst()) - timedelta(days=100)
        anchor_str = anchor.isoformat()
        plus_90 = (anchor + timedelta(days=90)).isoformat()

        _insert_price(db_path, "HLD", 100.0, anchor_str)
        _insert_price(db_path, "HLD", 110.0, plus_90)

        upsert_decision(
            {
                "date": anchor_str,
                "ticker": "HLD",
                "action": "HOLD",
                "confidence": 60.0,
                "entry_price": 100.0,
            },
            db_path,
        )
        track_decision_outcomes(db_path)

        rows = get_decisions(ticker="HLD", db_path=db_path)
        assert rows[0]["outcome"] == "neutral"
        assert rows[0]["pnl_90d"] == 10.0


# ═══════════════════════════════════════════════════════
# main() CLI entry — argparse + dispatch behavior
# ═══════════════════════════════════════════════════════


class TestMainCLI:
    def test_main_track_no_pending(self, db_path, capsys):
        """`main(['--track'])` → track_decision_outcomes() 실행, 0건 메시지 출력."""
        from nuri.trading.engine.decisions import main

        rc = main(["--track"], db_path=db_path)
        assert rc == 0
        out = capsys.readouterr().out
        assert "P&L 추적 업데이트: 0건" in out

    def test_main_track_updates_pending(self, db_path, capsys):
        """`main(['--track'])` 가 실제로 pending decision 의 P&L 을 갱신."""
        from datetime import date as _date
        from datetime import timedelta

        from nuri.core.timezone import today_kst
        from nuri.trading.engine.decisions import main

        anchor = _date.fromisoformat(today_kst()) - timedelta(days=14)
        anchor_str = anchor.isoformat()
        plus_7 = (anchor + timedelta(days=7)).isoformat()
        _insert_price(db_path, "TRK", 100.0, anchor_str)
        _insert_price(db_path, "TRK", 110.0, plus_7)
        upsert_decision(
            {
                "date": anchor_str,
                "ticker": "TRK",
                "action": "BUY",
                "confidence": 70.0,
                "entry_price": 100.0,
            },
            db_path,
        )

        rc = main(["--track"], db_path=db_path)
        assert rc == 0
        out = capsys.readouterr().out
        assert "P&L 추적 업데이트: 1건" in out
        rows = get_decisions(ticker="TRK", db_path=db_path)
        assert rows[0]["pnl_7d"] == 10.0

    def test_main_accuracy_empty(self, db_path, capsys):
        """`main(['--accuracy'])` 에 완료 decision 없음 → 안내 메시지."""
        from nuri.trading.engine.decisions import main

        rc = main(["--accuracy"], db_path=db_path)
        assert rc == 0
        out = capsys.readouterr().out
        assert "완료된 decisions 없음" in out

    def test_main_accuracy_with_data_prints_table(self, db_path, capsys):
        """완료 decision 존재 → Agent Accuracy 표 출력 (Agent / Total / Hits / Rate / Adj)."""
        from nuri.trading.engine.decisions import main

        _insert_decision_with_outcome(
            db_path,
            "NVDA",
            "BUY",
            "success",
            [{"agent_name": "technical", "action": "BUY", "confidence": 80}],
        )

        rc = main(["--accuracy"], db_path=db_path)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Agent Accuracy" in out
        assert "technical" in out
        # 100% 적중 → Rate 100.0%
        assert "100.0%" in out

    def test_main_snapshot_persists_and_prints(self, db_path, capsys):
        """`main(['--snapshot'])` → strategy_memory 저장 + '스냅샷 N건 저장' 메시지."""
        from nuri.trading.engine.decisions import main

        _insert_decision_with_outcome(
            db_path,
            "NVDA",
            "BUY",
            "success",
            [{"agent_name": "technical", "action": "BUY", "confidence": 80}],
        )

        rc = main(["--snapshot"], db_path=db_path)
        assert rc == 0
        out = capsys.readouterr().out
        assert "스냅샷 1건 저장 (strategy_memory)" in out
        rows = query(
            "SELECT * FROM strategy_memory WHERE signal_id = 'agent_technical_accuracy'",
            db_path=db_path,
        )
        assert len(rows) == 1

    def test_main_snapshot_skipped_when_no_accuracy(self, db_path, capsys):
        """`main(['--snapshot'])` 에 완료 decision 없으면 save_agent_accuracy_snapshot 미호출.

        empty acc → '완료된 decisions 없음' 만 출력, '스냅샷 N건 저장' 없음.
        """
        from nuri.trading.engine.decisions import main

        rc = main(["--snapshot"], db_path=db_path)
        assert rc == 0
        out = capsys.readouterr().out
        assert "완료된 decisions 없음" in out
        assert "스냅샷" not in out

    def test_main_summary(self, db_path, capsys):
        """`main(['--summary'])` → '의사결정 요약: total=N, pending=N, ...' 출력."""
        from nuri.trading.engine.decisions import main

        upsert_decision(
            {"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0},
            db_path,
        )
        rc = main(["--summary"], db_path=db_path)
        assert rc == 0
        out = capsys.readouterr().out
        assert "의사결정 요약: total=1, pending=1, success=0, failure=0, neutral=0" in out

    def test_main_no_flags_returns_zero(self, db_path, capsys):
        """플래그 없음 → init_db 만 실행하고 즉시 0 반환 (출력 없음)."""
        from nuri.trading.engine.decisions import main

        rc = main([], db_path=db_path)
        assert rc == 0
        # 어떤 분기도 실행되지 않으면 stdout 은 비어 있어야 함
        assert capsys.readouterr().out == ""
