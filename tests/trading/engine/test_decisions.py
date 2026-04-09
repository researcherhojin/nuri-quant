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
            "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
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
        dec_id = upsert_decision(
            {"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0}, db_path
        )
        records = [
            {"source_type": "agent", "source_key": "technical", "action": "BUY", "confidence": 80.0,
             "detail": json.dumps({"rsi": 28})},
            {"source_type": "agent", "source_key": "fundamental", "action": "BUY", "confidence": 72.0,
             "detail": json.dumps({"pe": 36})},
        ]
        count = upsert_decision_evidence(dec_id, records, db_path)
        assert count == 2

    def test_evidence_idempotent(self, db_path):
        """같은 decision_id + source_type + source_key → UPDATE."""
        dec_id = upsert_decision(
            {"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0}, db_path
        )
        records = [
            {"source_type": "agent", "source_key": "technical", "action": "BUY", "confidence": 80.0,
             "detail": json.dumps({"rsi": 28})},
        ]
        upsert_decision_evidence(dec_id, records, db_path)

        # 같은 source_type+source_key로 재실행 (confidence 변경)
        records[0]["confidence"] = 85.0
        upsert_decision_evidence(dec_id, records, db_path)

        evidence = query(
            "SELECT * FROM decision_evidence WHERE decision_id = ? AND source_key = 'technical'",
            (dec_id,), db_path,
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
        dec_id = upsert_decision(
            {"date": "2026-04-10", "ticker": "NVDA", "action": "BUY", "confidence": 75.0}, db_path
        )
        upsert_decision_evidence(dec_id, [
            {"source_type": "agent", "source_key": "technical", "action": "BUY", "confidence": 80.0,
             "detail": json.dumps({"rsi": 28})},
        ], db_path)

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
            ticker="NVDA", final_action="BUY", final_confidence=70.0,
            agreement_rate=0.7, verdicts=[
                MockAgentVerdict("technical", "NVDA", "BUY", 80.0, "RSI low", {"rsi": 30}),
            ], dissent=[], reasoning="First run",
        )
        result2 = MockConsensusResult(
            ticker="NVDA", final_action="BUY", final_confidence=80.0,
            agreement_rate=0.9, verdicts=[
                MockAgentVerdict("technical", "NVDA", "BUY", 85.0, "RSI very low", {"rsi": 25}),
            ], dissent=[], reasoning="Second run",
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
                ticker="NVDA", final_action="BUY", final_confidence=75.0,
                agreement_rate=0.8, verdicts=[
                    MockAgentVerdict("technical", "NVDA", "BUY", 80.0, "ok", {}),
                ], dissent=[], reasoning="NVDA buy",
            ),
            MockConsensusResult(
                ticker="TSLA", final_action="SELL", final_confidence=60.0,
                agreement_rate=0.6, verdicts=[
                    MockAgentVerdict("risk", "TSLA", "SELL", 90.0, "high risk", {}),
                ], dissent=[], reasoning="TSLA sell",
            ),
        ]

        count = record_decisions(results, db_path)
        assert count == 2
        assert len(get_decisions(db_path=db_path)) == 2


# ═══════════════════════════════════════════════════════
# track_decision_outcomes 멱등성 테스트
# ═══════════════════════════════════════════════════════


class TestTrackOutcomes:
    def test_no_pending_decisions(self, db_path):
        from nuri.trading.engine.decisions import track_decision_outcomes
        assert track_decision_outcomes(db_path) == 0

    def test_7d_outcome_filled(self, db_path):
        """7일 경과 → pnl_7d만 채워짐."""
        from nuri.trading.engine.decisions import track_decision_outcomes

        _insert_price(db_path, "NVDA", 120.0, "2026-04-01")
        _insert_price(db_path, "NVDA", 132.0, "2026-04-08")  # 7일 후 +10%

        upsert_decision({
            "date": "2026-04-01",
            "ticker": "NVDA",
            "action": "BUY",
            "confidence": 75.0,
            "entry_price": 120.0,
        }, db_path)

        updated = track_decision_outcomes(db_path)
        assert updated == 1

        rows = get_decisions(ticker="NVDA", db_path=db_path)
        assert rows[0]["pnl_7d"] == 10.0
        assert rows[0]["pnl_30d"] is None  # 아직 30일 미경과
        assert rows[0]["outcome"] == "pending"

    def test_outcome_idempotent(self, db_path):
        """이미 채워진 PnL은 재실행해도 변경 없음."""
        from nuri.trading.engine.decisions import track_decision_outcomes

        _insert_price(db_path, "NVDA", 120.0, "2026-04-01")
        _insert_price(db_path, "NVDA", 132.0, "2026-04-08")

        upsert_decision({
            "date": "2026-04-01",
            "ticker": "NVDA",
            "action": "BUY",
            "confidence": 75.0,
            "entry_price": 120.0,
        }, db_path)

        track_decision_outcomes(db_path)  # 1회
        rows1 = get_decisions(ticker="NVDA", db_path=db_path)

        # 가격 변경 후 재실행
        _insert_price(db_path, "NVDA", 150.0, "2026-04-08")
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

        upsert_decision({
            "date": "2026-01-01",
            "ticker": "NVDA",
            "action": "BUY",
            "confidence": 75.0,
            "entry_price": 100.0,
        }, db_path)

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

        upsert_decision({
            "date": "2026-01-01",
            "ticker": "BAD",
            "action": "SELL",
            "confidence": 80.0,
            "entry_price": 100.0,
        }, db_path)

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
