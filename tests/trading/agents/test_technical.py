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

    def test_finite_helpers_cover_every_kind(self):
        """base.finite_or_none / finite_or_zero — 숫자가 아니면 그대로, bool 은 보존, NaN/inf/None 은 None/0."""
        from nuri.trading.agents.base import finite_or_none, finite_or_zero

        assert finite_or_none("up") == "up"
        assert finite_or_none(True) is True
        assert finite_or_none(None) is None
        assert finite_or_none(3) == 3
        assert finite_or_none(float("nan")) is None
        assert finite_or_none(float("-inf")) is None
        assert finite_or_zero(float("nan")) == 0.0
        assert finite_or_zero(None) == 0.0
        assert finite_or_zero("n/a") == 0.0
        assert finite_or_zero(2.5) == 2.5
        from nuri.trading.agents.base import finite_values

        assert finite_values([1, "2.5", None, "n/a", float("nan"), float("inf"), True]) == [1.0, 2.5, 1.0]
        # numpy 스칼라 — np.float32 는 float 서브클래스가 아니고 json 이 못 직렬화한다 (Codex P2)
        assert finite_or_none(np.float32(1.25)) == 1.25 and type(finite_or_none(np.float32(1.25))) is float
        assert type(finite_or_none(np.int64(7))) is int
        assert finite_or_none(np.float64("nan")) is None
        assert finite_or_zero(np.float32(1.25)) == 1.25
        json.dumps({"v": finite_or_none(np.float32(1.25)), "i": finite_or_none(np.int64(7))}, allow_nan=False)

    def test_fallback_frame_short_after_sanitising_is_not_adopted(self, monkeypatch):
        """폴백 6mo 프레임이 정제 후 min_dp 미만이면 채택하지 않고 '데이터 부족' 으로 간다 (#1482 patch gap)."""
        import sys as _sys

        from nuri.trading.agents import technical as mod

        min_dp = mod._CFG.get("min_data_points", 50)
        fake_yf = MagicMock()
        fake_yf.download.return_value = pd.DataFrame({"Close": [60.0] * (min_dp - 1) + [float("nan")] * 5})
        monkeypatch.setitem(_sys.modules, "yfinance", fake_yf)
        result = mod.TechnicalAgent().analyze("SHRT", db_path=None)
        fake_yf.download.assert_called_once()
        assert result.confidence == 0
        assert "부족" in result.reasoning

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
