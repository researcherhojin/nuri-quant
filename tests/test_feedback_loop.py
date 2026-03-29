"""피드백 루프 개선 테스트 — hit 판정, trades 테이블, agent_verdicts, scoring_detail."""
import json

import pandas as pd
import pytest

from nuri.core.db import get_db, get_trades, init_db, query, upsert_prices, upsert_trade


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _seed_recommendation(db_path, date, ticker, action, entry_price, confidence=70.0):
    """추천 레코드 삽입."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO recommendations (date, ticker, action, confidence, entry_price) "
            "VALUES (?, ?, ?, ?, ?)",
            (date, ticker, action, confidence, entry_price),
        )


# ═══════════════════════════════════════════════════════
# Task 1-1: hit 판정 개선
# ═══════════════════════════════════════════════════════


class TestHitCalculation:
    """hit 판정 기준: BUY +5% 이상, SELL -2% 이하."""

    def test_buy_hit_meaningful_gain(self, db_path):
        """BUY + 8% 수익 → hit=True (5% 이상)."""
        from datetime import datetime, timedelta

        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "GOOD", "BUY", 100.0)

        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{
            "ticker": "GOOD", "date": d30,
            "open": 107, "high": 110, "low": 106, "close": 108.0,
            "volume": 1000000, "adj_close": 108.0,
        }])
        upsert_prices(prices, db_path)

        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)

        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == 8.0
        assert rows[0]["hit"] == 1  # +8% >= +5%
        assert rows[0]["hit_quality"] == 0.4  # 8/20 = 0.4

    def test_buy_small_gain_not_hit(self, db_path):
        """BUY + 3% 수익 → hit=False (5% 미만은 노이즈)."""
        from datetime import datetime, timedelta

        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "MEH", "BUY", 100.0)

        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{
            "ticker": "MEH", "date": d30,
            "open": 102, "high": 104, "low": 101, "close": 103.0,
            "volume": 1000000, "adj_close": 103.0,
        }])
        upsert_prices(prices, db_path)

        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)

        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == 3.0
        assert rows[0]["hit"] == 0  # +3% < +5% → not hit
        assert rows[0]["hit_quality"] == 0.15  # 3/20 = 0.15

    def test_buy_loss_not_hit(self, db_path):
        """BUY + 가격 하락 → hit=False, hit_quality=0."""
        from datetime import datetime, timedelta

        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "LOSS", "BUY", 100.0)

        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{
            "ticker": "LOSS", "date": d30,
            "open": 94, "high": 96, "low": 93, "close": 95.0,
            "volume": 1000000, "adj_close": 95.0,
        }])
        upsert_prices(prices, db_path)

        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)

        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == -5.0
        assert rows[0]["hit"] == 0
        assert rows[0]["hit_quality"] == 0.0

    def test_sell_meaningful_decline_hit(self, db_path):
        """SELL + 가격 -5% 하락 → hit=True (-2% 이하)."""
        from datetime import datetime, timedelta

        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "DROP", "SELL", 100.0)

        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{
            "ticker": "DROP", "date": d30,
            "open": 96, "high": 97, "low": 94, "close": 95.0,
            "volume": 1000000, "adj_close": 95.0,
        }])
        upsert_prices(prices, db_path)

        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)

        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == -5.0
        assert rows[0]["hit"] == 1  # -5% < -2% → hit
        assert rows[0]["hit_quality"] == 0.5  # abs(-5)/10 = 0.5

    def test_sell_small_decline_not_hit(self, db_path):
        """SELL + 가격 -1% 하락 → hit=False (-1% > -2%)."""
        from datetime import datetime, timedelta

        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "FLAT", "SELL", 100.0)

        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{
            "ticker": "FLAT", "date": d30,
            "open": 99.5, "high": 100, "low": 98.5, "close": 99.0,
            "volume": 1000000, "adj_close": 99.0,
        }])
        upsert_prices(prices, db_path)

        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)

        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == -1.0
        assert rows[0]["hit"] == 0  # -1% > -2% → not hit
        assert rows[0]["hit_quality"] == 0.1  # abs(-1)/10 = 0.1 (하락했지만 미미한 수준)

    def test_sell_price_up_not_hit(self, db_path):
        """SELL + 가격 상승 → hit=False, hit_quality=0."""
        from datetime import datetime, timedelta

        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "UP", "SELL", 100.0)

        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{
            "ticker": "UP", "date": d30,
            "open": 104, "high": 106, "low": 103, "close": 105.0,
            "volume": 1000000, "adj_close": 105.0,
        }])
        upsert_prices(prices, db_path)

        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)

        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == 5.0
        assert rows[0]["hit"] == 0
        assert rows[0]["hit_quality"] == 0.0

    def test_hit_quality_column_exists(self, db_path):
        """hit_quality 컬럼이 recommendations 테이블에 존재."""
        rows = query("PRAGMA table_info(recommendations)", db_path=db_path)
        columns = [r["name"] for r in rows]
        assert "hit_quality" in columns


# ═══════════════════════════════════════════════════════
# Task 1-2: trades 테이블 + API
# ═══════════════════════════════════════════════════════


class TestTradesTable:

    def test_trades_table_exists(self, db_path):
        """trades 테이블 생성 확인."""
        rows = query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'",
            db_path=db_path,
        )
        assert len(rows) == 1

    def test_upsert_trade_insert(self, db_path):
        """매매 기록 삽입."""
        trade_id = upsert_trade({
            "ticker": "AAPL",
            "action": "BUY",
            "executed_at": "2026-03-29",
            "entry_price": 180.0,
            "shares": 10,
            "notes": "테스트 매매",
        }, db_path)
        assert trade_id > 0

        trades = get_trades(db_path=db_path)
        assert len(trades) == 1
        assert trades[0]["ticker"] == "AAPL"
        assert trades[0]["shares"] == 10

    def test_upsert_trade_update(self, db_path):
        """매매 기록 업데이트 (종료 정보)."""
        trade_id = upsert_trade({
            "ticker": "TSLA",
            "action": "BUY",
            "executed_at": "2026-03-28",
            "entry_price": 250.0,
            "shares": 5,
        }, db_path)

        # 종료 정보 업데이트
        upsert_trade({
            "id": trade_id,
            "exit_price": 280.0,
            "exit_date": "2026-03-29",
            "exit_reason": "take_profit",
        }, db_path)

        trades = get_trades(ticker="TSLA", db_path=db_path)
        assert len(trades) == 1
        assert trades[0]["exit_price"] == 280.0
        assert trades[0]["exit_reason"] == "take_profit"

    def test_get_trades_ticker_filter(self, db_path):
        """ticker 필터링 조회."""
        upsert_trade({"ticker": "AAPL", "action": "BUY", "executed_at": "2026-03-29"}, db_path)
        upsert_trade({"ticker": "TSLA", "action": "SELL", "executed_at": "2026-03-29"}, db_path)

        aapl = get_trades(ticker="AAPL", db_path=db_path)
        assert len(aapl) == 1
        assert aapl[0]["ticker"] == "AAPL"

        all_trades = get_trades(db_path=db_path)
        assert len(all_trades) == 2

    def test_trade_with_recommendation_id(self, db_path):
        """recommendation_id 연결."""
        _seed_recommendation(db_path, "2026-03-29", "NVDA", "BUY", 150.0)
        recs = query("SELECT id FROM recommendations", db_path=db_path)
        rec_id = recs[0]["id"]

        upsert_trade({
            "recommendation_id": rec_id,
            "ticker": "NVDA",
            "action": "BUY",
            "executed_at": "2026-03-29",
            "entry_price": 150.0,
        }, db_path)

        trades = get_trades(ticker="NVDA", db_path=db_path)
        assert trades[0]["recommendation_id"] == rec_id


class TestTradesAPI:
    """trades API 엔드포인트 테스트."""

    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        db_path = tmp_path / "test.db"
        init_db(db_path)
        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        return TestClient(app)

    def test_create_trade(self, client):
        r = client.post("/api/trades", json={
            "ticker": "AAPL",
            "action": "BUY",
            "executed_at": "2026-03-29",
            "entry_price": 180.0,
            "shares": 10,
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert "trade_id" in r.json()

    def test_list_trades_empty(self, client):
        r = client.get("/api/trades")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 0
        assert data["trades"] == []

    def test_list_trades_with_filter(self, client):
        client.post("/api/trades", json={
            "ticker": "AAPL", "action": "BUY", "executed_at": "2026-03-29",
        })
        client.post("/api/trades", json={
            "ticker": "TSLA", "action": "SELL", "executed_at": "2026-03-29",
        })

        r = client.get("/api/trades?ticker=AAPL")
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_update_trade(self, client):
        r = client.post("/api/trades", json={
            "ticker": "NVDA", "action": "BUY", "executed_at": "2026-03-29",
            "entry_price": 150.0,
        })
        trade_id = r.json()["trade_id"]

        r2 = client.put(f"/api/trades/{trade_id}", json={
            "exit_price": 170.0,
            "exit_date": "2026-04-15",
            "exit_reason": "take_profit",
        })
        assert r2.status_code == 200

    def test_create_trade_invalid_action(self, client):
        r = client.post("/api/trades", json={
            "ticker": "AAPL", "action": "HOLD", "executed_at": "2026-03-29",
        })
        assert r.status_code == 422

    def test_create_trade_invalid_date(self, client):
        r = client.post("/api/trades", json={
            "ticker": "AAPL", "action": "BUY", "executed_at": "not-a-date",
        })
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════
# Task 1-3: agent_verdicts 저장
# ═══════════════════════════════════════════════════════


class TestAgentVerdicts:

    def test_agent_verdicts_column_exists(self, db_path):
        """agent_verdicts 컬럼 존재 확인."""
        rows = query("PRAGMA table_info(recommendations)", db_path=db_path)
        columns = [r["name"] for r in rows]
        assert "agent_verdicts" in columns

    def test_save_with_verdicts(self, db_path):
        """verdict 포함 추천 저장."""
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations

        candidates = [
            Candidate("TEST1", "rsi_oversold", "2026-03-29", "BUY",
                       75.0, 0.6, 2.0, True, 100.0, "test"),
        ]
        verdicts = {
            "TEST1": [
                {"agent_name": "technical", "action": "BUY", "confidence": 80.0, "reasoning": "RSI oversold"},
                {"agent_name": "fundamental", "action": "HOLD", "confidence": 50.0, "reasoning": "Fair value"},
                {"agent_name": "risk", "action": "BUY", "confidence": 60.0, "reasoning": "Low risk"},
            ]
        }

        n = save_recommendations(candidates, verdicts=verdicts, db_path=db_path)
        assert n == 1

        rows = query("SELECT agent_verdicts FROM recommendations", db_path=db_path)
        assert rows[0]["agent_verdicts"] is not None
        parsed = json.loads(rows[0]["agent_verdicts"])
        assert len(parsed) == 3
        assert parsed[0]["agent_name"] == "technical"

    def test_save_without_verdicts(self, db_path):
        """verdict 없이도 정상 저장."""
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations

        candidates = [
            Candidate("TEST1", "macd_golden", "2026-03-29", "BUY",
                       65.0, 0.5, 1.5, True, 90.0, "no verdicts"),
        ]
        n = save_recommendations(candidates, db_path=db_path)
        assert n == 1

        rows = query("SELECT agent_verdicts FROM recommendations", db_path=db_path)
        assert rows[0]["agent_verdicts"] is None

    def test_serialize_verdicts(self):
        """ConsensusResult → verdict dict 변환."""
        from dataclasses import dataclass

        from nuri.trading.recommend.tracker import _serialize_verdicts

        @dataclass
        class FakeVerdict:
            agent_name: str
            action: str
            confidence: float
            reasoning: str

        @dataclass
        class FakeResult:
            ticker: str
            verdicts: list

        results = [
            FakeResult(
                ticker="AAPL",
                verdicts=[
                    FakeVerdict("technical", "BUY", 80.0, "RSI oversold signal detected"),
                    FakeVerdict("risk", "HOLD", 50.0, "Moderate risk" + "x" * 200),
                ],
            ),
        ]

        verdicts_map = _serialize_verdicts(results)
        assert "AAPL" in verdicts_map
        assert len(verdicts_map["AAPL"]) == 2
        # reasoning이 100자로 잘리는지 확인
        assert len(verdicts_map["AAPL"][1]["reasoning"]) == 100


# ═══════════════════════════════════════════════════════
# Task 1-4: scoring_detail 저장
# ═══════════════════════════════════════════════════════


class TestScoringDetail:

    def test_scoring_detail_column_exists(self, db_path):
        """scoring_detail 컬럼 존재 확인."""
        rows = query("PRAGMA table_info(recommendations)", db_path=db_path)
        columns = [r["name"] for r in rows]
        assert "scoring_detail" in columns

    def test_candidate_has_scoring_detail(self, db_path):
        """Candidate dataclass에 scoring_detail 필드."""
        from nuri.trading.recommend.candidates import Candidate

        c = Candidate(
            "TEST", "rsi_oversold", "2026-03-29", "BUY",
            75.0, 0.6, 2.0, True, 100.0, "test",
            scoring_detail={"base_confidence": 60.0, "final_confidence": 75.0},
        )
        assert c.scoring_detail is not None
        assert c.scoring_detail["base_confidence"] == 60.0

    def test_save_with_scoring_detail(self, db_path):
        """scoring_detail 포함 추천 저장."""
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations

        candidates = [
            Candidate(
                "TEST1", "rsi_oversold", "2026-03-29", "BUY",
                75.0, 0.6, 2.0, True, 100.0, "test",
                scoring_detail={
                    "base_confidence": 60.0,
                    "regime_win_rate": 0.65,
                    "regime_pf": 2.1,
                    "drift_multiplier": 1.0,
                    "conflict_penalty": 1.0,
                    "regime_fit_penalty": 1.0,
                    "position_penalty": 1.0,
                    "final_confidence": 75.0,
                },
            ),
        ]
        save_recommendations(candidates, db_path=db_path)

        rows = query("SELECT scoring_detail FROM recommendations", db_path=db_path)
        assert rows[0]["scoring_detail"] is not None
        parsed = json.loads(rows[0]["scoring_detail"])
        assert parsed["base_confidence"] == 60.0
        assert parsed["regime_win_rate"] == 0.65
        assert parsed["final_confidence"] == 75.0


# ═══════════════════════════════════════════════════════
# DB 마이그레이션 테스트
# ═══════════════════════════════════════════════════════


class TestFeedbackLoopMigrations:

    def test_schema_version_includes_new_migrations(self, db_path):
        """새 마이그레이션 (3~6) 적용 확인."""
        from nuri.core.db import get_schema_version
        version = get_schema_version(db_path)
        assert version >= 6

    def test_migrations_idempotent(self, db_path):
        """init_db 재실행해도 에러 없음."""
        init_db(db_path)
        init_db(db_path)
        rows = query("SELECT COUNT(*) as c FROM schema_version", db_path=db_path)
        # 총 마이그레이션 수만큼만 있어야 함
        from nuri.core.db import _MIGRATIONS
        assert rows[0]["c"] == len(_MIGRATIONS)

    def test_all_new_columns_exist(self, db_path):
        """recommendations 테이블에 새 컬럼 3개 존재."""
        rows = query("PRAGMA table_info(recommendations)", db_path=db_path)
        columns = [r["name"] for r in rows]
        assert "hit_quality" in columns
        assert "agent_verdicts" in columns
        assert "scoring_detail" in columns
