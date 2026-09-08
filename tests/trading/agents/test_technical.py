"""Tests for technical agent — split from test_trading_agents_all.py."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


class TestTechnicalAgent:
    def test_returns_verdict(self, agent_data):
        from nuri.trading.agents.technical import TechnicalAgent

        v = TechnicalAgent().analyze("TEST", db_path=agent_data)
        assert v.agent_name == "technical"
        assert v.action in ("BUY", "SELL", "HOLD")
        assert 0 <= v.confidence <= 100

    def test_no_data(self, db_path):
        from nuri.trading.agents.technical import TechnicalAgent

        v = TechnicalAgent().analyze("NONE", db_path=db_path)
        assert v.action == "HOLD"
        assert v.confidence == 0


class TestTechnicalAgent_R26:
    def test_no_data(self, db_path):
        from nuri.trading.agents.technical import TechnicalAgent

        result = TechnicalAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"
        assert "부족" in result.reasoning

    def test_with_price_data(self, db_path):
        _seed_ticker(db_path, "AAPL", n=60)
        from nuri.trading.agents.technical import TechnicalAgent

        result = TechnicalAgent().analyze("AAPL", db_path=db_path)
        assert result.action in ("BUY", "SELL", "HOLD")
        assert result.data_points.get("rsi") is not None

    def test_trailing_null_close_does_not_poison_data_points(self, db_path):
        """#1479 — prices 에 close NULL 행이 하나 있으면 latest/sma 가 NaN 이 돼 API JSON 직렬화가 500 으로 죽었다.
        starlette 와 같은 `allow_nan=False` 로 잠근다."""
        _seed_ticker(db_path, "AAPL", n=60)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("AAPL", "2025-03-31", None, None, None, None, 0),
            )
        from nuri.trading.agents.technical import TechnicalAgent

        result = TechnicalAgent().analyze("AAPL", db_path=db_path)
        json.dumps(asdict(result), allow_nan=False)  # NaN 이 하나라도 있으면 ValueError
        assert result.data_points["price"] == pytest.approx(result.data_points["price"])  # NaN != NaN
        assert result.action in ("BUY", "SELL", "HOLD")

    def test_infinite_close_is_rejected_like_null(self, db_path):
        """dropna 는 ±inf 를 못 거른다 — 같은 strict-JSON 500 경로 (Codex P2, #1479)."""
        _seed_ticker(db_path, "AAPL", n=60)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("AAPL", "2025-03-31", 1.0, 1.0, 1.0, float("inf"), 1),
            )
        from nuri.trading.agents.technical import TechnicalAgent

        result = TechnicalAgent().analyze("AAPL", db_path=db_path)
        json.dumps(asdict(result), allow_nan=False)
        assert result.data_points["price"] == pytest.approx(result.data_points["price"])

    def test_null_rows_do_not_count_toward_min_data_points(self, db_path, monkeypatch):
        """유효 49 + NULL 1 = 50행은 min_data_points 를 채운 게 아니다 — '데이터 부족' 으로 가야 한다 (Codex P2)."""
        from nuri.trading.agents import technical as mod

        min_dp = mod._CFG.get("min_data_points", 50)
        _seed_ticker(db_path, "AAPL", n=min_dp - 1)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("AAPL", "2025-03-31", None, None, None, None, 0),
            )
        result = mod.TechnicalAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "HOLD"
        assert result.confidence == 0
        assert "부족" in result.reasoning

    def test_null_rows_do_not_block_the_yfinance_fallback(self, monkeypatch):
        """Codex P2 (#1479): 유효 49 + NULL 1 = 50행이 min_dp 를 '채운' 척하면 폴백을 건너뛰고 '데이터 부족' 이 된다.
        정제가 자격 판정 *앞* 에 있어야 폴백이 돈다. db_path=None 은 conftest 가 per-test 복사본으로 격리한다."""
        import sys as _sys

        from nuri.trading.agents import technical as mod

        min_dp = mod._CFG.get("min_data_points", 50)
        dates = pd.bdate_range(end="2025-03-28", periods=min_dp - 1).strftime("%Y-%m-%d").tolist()
        with get_db(None) as conn:  # 기본 DB = 격리 복사본
            for i, d in enumerate(dates):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("FBK", d, 50.0, 50.0, 50.0, 50.0 + i * 0.1, 1),
                )
            conn.execute(  # upsert_prices 가 NULL 을 거르게 되어도(#1480) 이 행은 남도록 raw INSERT
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("FBK", "2025-03-31", None, None, None, None, 0),
            )
        fake_yf = MagicMock()
        fake_yf.download.return_value = pd.DataFrame({"Close": [60.0 + i * 0.1 for i in range(min_dp + 10)]})
        monkeypatch.setitem(_sys.modules, "yfinance", fake_yf)

        result = mod.TechnicalAgent().analyze("FBK", db_path=None)

        fake_yf.download.assert_called_once()
        assert "부족" not in result.reasoning
        assert result.confidence > 0
        json.dumps(asdict(result), allow_nan=False)

    def test_finite_closes_drops_nan_none_and_inf_only(self):
        """폴백 프레임도 이 함수로 정제한 뒤 min_dp 를 센다 — NaN/None/±inf 만 빠지고 0 과 음수는 남는다."""
        from nuri.trading.agents.technical import _finite_closes

        df = pd.DataFrame({"close": [50.0, float("nan"), None, float("inf"), -float("inf"), 0.0, -1.0]})
        assert _finite_closes(df)["close"].tolist() == [50.0, 0.0, -1.0]
        assert _finite_closes(pd.DataFrame()).empty

    def test_yfinance_fallback_no_db_path(self, db_path, monkeypatch):
        """Cover yfinance fallback when prices table empty."""
        from nuri.trading.agents.technical import TechnicalAgent

        result = TechnicalAgent().analyze("NONEXIST", db_path=db_path)
        assert result.action == "HOLD"


def _insert_finviz_signal(db_path, ticker, signal, date_str=None):
    """external_analysis에 FINVIZ 시그널 삽입 헬퍼."""
    from nuri.core.timezone import today_kst

    if date_str is None:
        date_str = today_kst()
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO external_analysis "
            "(date, source, ticker, data_type, value) "
            "VALUES (?, 'FINVIZ', ?, 'finviz_signal', ?)",
            (date_str, ticker, signal),
        )


class TestTechnicalFinviz:
    """FINVIZ 스크리너 보조 시그널 통합 테스트."""

    def test_finviz_oversold_boosts_buy(self, db_path):
        """oversold_rsi FINVIZ 시그널이 buy_signals를 증가시킴."""
        _seed_ticker(db_path, "AAPL", n=60)
        _insert_finviz_signal(db_path, "AAPL", "oversold_rsi")

        from nuri.trading.agents.technical import TechnicalAgent

        result = TechnicalAgent().analyze("AAPL", db_path=db_path)
        assert "FINVIZ oversold_rsi" in result.reasoning
        assert "finviz_signals" in result.data_points
        assert "oversold_rsi" in result.data_points["finviz_signals"]

    def test_finviz_overbought_boosts_sell(self, db_path):
        """overbought_rsi FINVIZ 시그널이 sell_signals를 증가시킴."""
        _seed_ticker(db_path, "TSLA", n=60)
        _insert_finviz_signal(db_path, "TSLA", "overbought_rsi")

        from nuri.trading.agents.technical import TechnicalAgent

        result = TechnicalAgent().analyze("TSLA", db_path=db_path)
        assert "FINVIZ overbought_rsi" in result.reasoning

    def test_finviz_new_high_boosts_sell(self, db_path):
        """new_high FINVIZ 시그널이 sell_signals에 가산."""
        _seed_ticker(db_path, "MSFT", n=60)
        _insert_finviz_signal(db_path, "MSFT", "new_high")

        from nuri.trading.agents.technical import TechnicalAgent

        result = TechnicalAgent().analyze("MSFT", db_path=db_path)
        assert "FINVIZ new_high" in result.reasoning

    def test_finviz_new_low_boosts_buy(self, db_path):
        """new_low FINVIZ 시그널이 buy_signals에 가산."""
        _seed_ticker(db_path, "GOOG", n=60)
        _insert_finviz_signal(db_path, "GOOG", "new_low")

        from nuri.trading.agents.technical import TechnicalAgent

        result = TechnicalAgent().analyze("GOOG", db_path=db_path)
        assert "FINVIZ new_low" in result.reasoning

    def test_finviz_no_data_graceful(self, db_path):
        """FINVIZ 데이터 없으면 기존 동작 변경 없음."""
        _seed_ticker(db_path, "NVDA", n=60)

        from nuri.trading.agents.technical import TechnicalAgent

        result = TechnicalAgent().analyze("NVDA", db_path=db_path)
        assert result.action in ("BUY", "SELL", "HOLD")
        assert "FINVIZ" not in result.reasoning
        assert "finviz_signals" not in result.data_points

    def test_finviz_stale_data_ignored(self, db_path):
        """max_age_days 초과 데이터는 무시."""
        from datetime import timedelta

        from nuri.core.timezone import kst_now

        old_date = (kst_now() - timedelta(days=10)).strftime("%Y-%m-%d")
        _seed_ticker(db_path, "META", n=60)
        _insert_finviz_signal(db_path, "META", "oversold_rsi", date_str=old_date)

        from nuri.trading.agents.technical import TechnicalAgent

        result = TechnicalAgent().analyze("META", db_path=db_path)
        assert "FINVIZ" not in result.reasoning

    def test_finviz_neutral_signal_ignored(self, db_path):
        """unusual_volume 같은 중립 시그널은 buy/sell에 가산하지 않음."""
        _seed_ticker(db_path, "AMZN", n=60)
        _insert_finviz_signal(db_path, "AMZN", "unusual_volume")

        from nuri.trading.agents.technical import TechnicalAgent

        result = TechnicalAgent().analyze("AMZN", db_path=db_path)
        assert "FINVIZ unusual_volume" not in result.reasoning

    def test_finviz_multiple_signals(self, db_path):
        """복수 FINVIZ 시그널이 모두 반영됨 (다른 날짜로 저장 — UNIQUE 제약 우회)."""
        from datetime import timedelta

        from nuri.core.timezone import kst_now

        _seed_ticker(db_path, "NFLX", n=60)
        today = kst_now().strftime("%Y-%m-%d")
        yesterday = (kst_now() - timedelta(days=1)).strftime("%Y-%m-%d")
        _insert_finviz_signal(db_path, "NFLX", "oversold_rsi", date_str=today)
        _insert_finviz_signal(db_path, "NFLX", "new_low", date_str=yesterday)

        from nuri.trading.agents.technical import TechnicalAgent

        result = TechnicalAgent().analyze("NFLX", db_path=db_path)
        assert "FINVIZ oversold_rsi" in result.reasoning
        assert "FINVIZ new_low" in result.reasoning
        assert len(result.data_points["finviz_signals"]) == 2
