"""Tests for risk agent — split from test_trading_agents_all.py."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.trading.agents._helpers import _seed_macro, _seed_portfolio, _seed_prices, _seed_ticker  # noqa: F401


class TestRiskAgent:
    def test_stop_loss_detected(self, db_path):
        """손절선 돌파 시 SELL + 높은 confidence."""
        from nuri.trading.agents.risk_agent import RiskAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("test", "CRASH", 100, 100.0, "USD"),
            )

        dates = pd.bdate_range("2025-01-01", periods=30)
        close = np.linspace(100, 70, 30)
        df = pd.DataFrame(
            {
                "ticker": "CRASH",
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": [100] * 30,
                "adj_close": close,
            }
        )
        upsert_prices(df, db_path)

        v = RiskAgent().analyze("CRASH", db_path=db_path)
        assert v.action == "SELL"
        assert v.confidence >= 80
        assert "손절선" in v.reasoning


class TestRiskAgent_R26:
    def test_no_data(self, db_path):
        from nuri.trading.agents.risk_agent import RiskAgent

        result = RiskAgent().analyze("AAPL", db_path=db_path)
        assert result.action in ("HOLD", "BUY")

    def test_stop_loss_triggered(self, db_path):
        _seed_ticker(db_path, "AAPL", n=30, base_price=50)
        with get_db(db_path) as conn:
            conn.execute("UPDATE portfolio SET avg_price = 100 WHERE ticker = 'AAPL'")
        from nuri.trading.agents.risk_agent import RiskAgent

        result = RiskAgent().analyze("AAPL", db_path=db_path)
        assert result.action == "SELL"
        assert "손절선" in result.reasoning

    def test_profit_positive(self, db_path):
        """Cover profit > profit_threshold path."""
        _seed_ticker(db_path, "AAPL", n=30, base_price=150)
        with get_db(db_path) as conn:
            conn.execute("UPDATE portfolio SET avg_price = 100 WHERE ticker = 'AAPL'")
        from nuri.trading.agents.risk_agent import RiskAgent

        result = RiskAgent().analyze("AAPL", db_path=db_path)
        assert "수익" in result.reasoning


class TestRiskAgentA3PerAccountThreshold:
    """A-3 Unified sell engine — risk_agent 가 ticker 보유 계좌의 strategy 기반
    threshold 를 사용하는지 검증. 이전 동작: 전 계좌 STOCK_STOP_LOSS=-7 고정.
    Regression lock: threshold 가 다시 global 로 돌아가면 이 테스트들이 fail."""

    def _setup_portfolio_yaml(self, tmp_path, strategy: str):
        from unittest.mock import patch as _patch

        import yaml as _yaml

        portfolio_yaml = tmp_path / "portfolio.yaml"
        portfolio_yaml.write_text(_yaml.dump({"accounts": {"TestAcct": {"strategy": strategy}}}))
        real_open = open

        def _opener(path, **kwargs):
            if str(path).endswith("portfolio.yaml"):
                return real_open(portfolio_yaml, **kwargs)
            return real_open(path, **kwargs)

        return _patch("builtins.open", side_effect=_opener)

    def _seed_ticker_with_loss(self, db_path, ticker, account, avg_price, current_price):
        """Portfolio + 30-day price series 가 current_price 로 끝나게 seed."""
        dates = pd.bdate_range("2026-01-01", periods=30)
        close = np.linspace(avg_price, current_price, 30)
        df = pd.DataFrame(
            {
                "ticker": ticker,
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": [100] * 30,
                "adj_close": close,
            }
        )
        from nuri.core.db import get_db as _get_db
        from nuri.core.db import upsert_prices as _upsert_prices

        with _get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                (account, ticker, 10, avg_price, "USD"),
            )
        _upsert_prices(df, db_path)

    def test_long_term_account_at_minus_10_does_not_fire_stop_loss(self, db_path, tmp_path):
        """long_term 계좌(-20) 의 -10% 손실 → 손절선 돌파 NOT 발동.
        이전 동작(-7 global): 돌파 발동 (잘못). A-3 fix: holding row 의 account
        (TestAcct → long_term) 로 threshold 조회 → -20 이므로 -10% 는 breach 아님."""
        from nuri.trading.agents.risk_agent import RiskAgent

        self._seed_ticker_with_loss(db_path, "LTMX", "TestAcct", avg_price=100.0, current_price=90.0)
        with self._setup_portfolio_yaml(tmp_path, "long_term"):
            v = RiskAgent().analyze("LTMX", db_path=db_path)

        assert "손절선 돌파" not in v.reasoning
        # -10% 는 loss_threshold (-10) 과 동률이므로 "손실 중" 경로도 안 탐
        assert v.action in ("HOLD", "BUY")

    def test_long_term_account_at_minus_22_fires_stop_loss(self, db_path, tmp_path):
        """long_term(-20) 계좌 -22% 손실 → 실제 breach 이므로 손절선 돌파 발동 (A-3 operator: <)."""
        from nuri.trading.agents.risk_agent import RiskAgent

        self._seed_ticker_with_loss(db_path, "LTMX", "TestAcct", avg_price=100.0, current_price=78.0)
        with self._setup_portfolio_yaml(tmp_path, "long_term"):
            v = RiskAgent().analyze("LTMX", db_path=db_path)

        assert "손절선 돌파" in v.reasoning
        assert v.action == "SELL"

    def test_core_account_at_minus_8_still_fires(self, db_path, tmp_path):
        """core(-7) 계좌 -8% → breach (pnl < threshold), 기존 동작 유지."""
        from nuri.trading.agents.risk_agent import RiskAgent

        self._seed_ticker_with_loss(db_path, "CORE1", "TestAcct", avg_price=100.0, current_price=92.0)
        with self._setup_portfolio_yaml(tmp_path, "core"):
            v = RiskAgent().analyze("CORE1", db_path=db_path)

        assert "손절선 돌파" in v.reasoning
        assert v.action == "SELL"

    def test_safely_above_threshold_does_not_fire(self, db_path, tmp_path):
        """core(-7) 계좌 -5% (threshold 대비 여유) → 손절선 돌파 안 함.
        A-3 operator 가 `<` 임을 확인 (이전은 `<=`). 정확한 -7.0 boundary 는 float
        imprecision 으로 불안정 (93.0/100*100 = -7.000000000000001) → 안전 마진."""
        from nuri.trading.agents.risk_agent import RiskAgent

        self._seed_ticker_with_loss(db_path, "CORE1", "TestAcct", avg_price=100.0, current_price=95.0)
        with self._setup_portfolio_yaml(tmp_path, "core"):
            v = RiskAgent().analyze("CORE1", db_path=db_path)

        assert "손절선 돌파" not in v.reasoning

    def test_multi_account_breach_not_masked_by_non_breaching_row(self, db_path, tmp_path):
        """A-4 codex P2 lock: 동일 ticker 가 여러 계좌 보유될 때, 첫 row 가 breach 안
        해도 다른 row 가 breach 하면 detect 해야 함. 이전 `holding[0]` 사용 →
        SQLite 순서에 따라 breach 가 masking 될 수 있었음 (certification.py 는
        per-row iterate 로 correct)."""
        from unittest.mock import patch as _patch

        import yaml as _yaml

        from nuri.core.db import get_db as _get_db
        from nuri.core.db import upsert_prices as _upsert_prices
        from nuri.trading.agents.risk_agent import RiskAgent

        # SharedTicker: Main(core -7) 에서 -3% (no breach), Toss(long_term -20) 에서
        # -25% (breach). 첫 row 가 Main 이더라도 Toss 의 breach 가 감지돼야 함.
        dates = pd.bdate_range("2026-01-01", periods=30)
        close = np.linspace(100, 75, 30)  # 마지막 75 → Main(avg=100)=-25%, Toss(avg=75)=0%
        df = pd.DataFrame(
            {
                "ticker": "SHARED",
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": [100] * 30,
                "adj_close": close,
            }
        )
        _upsert_prices(df, db_path)

        with _get_db(db_path) as conn:
            # 순서 바꿔 insert: Toss(long_term -20, 0% pnl, no breach) 먼저
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("Toss", "SHARED", 5, 75.0, "USD"),
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("Main", "SHARED", 10, 100.0, "USD"),  # -25% breach on -7 core
            )

        portfolio_yaml = tmp_path / "portfolio.yaml"
        portfolio_yaml.write_text(
            _yaml.dump(
                {
                    "accounts": {
                        "Toss": {"strategy": "long_term"},
                        "Main": {"strategy": "core"},
                    }
                }
            )
        )
        real_open = open

        def _opener(path, **kwargs):
            if str(path).endswith("portfolio.yaml"):
                return real_open(portfolio_yaml, **kwargs)
            return real_open(path, **kwargs)

        with _patch("builtins.open", side_effect=_opener):
            v = RiskAgent().analyze("SHARED", db_path=db_path)

        assert "손절선 돌파" in v.reasoning
        assert "-25" in v.reasoning  # Main 계좌의 breach 정보가 올라옴
        assert v.action == "SELL"

    def test_concentration_aggregates_across_accounts(self, db_path, tmp_path):
        """A-4 codex Round 2 P2 lock: 같은 ticker 가 여러 계좌에 분산 보유될 때,
        비중 계산이 모든 row 를 합산해야 함. 이전 `holding[0]` 사용 시 첫 row 만
        카운트 → 실제 집중도 undercount. 예: Main 60% + Toss 60% 공동 보유 시
        전체 portfolio 기준 비중은 합쳐서 계산."""
        from unittest.mock import patch as _patch

        import yaml as _yaml

        from nuri.core.db import get_db as _get_db
        from nuri.trading.agents.risk_agent import RiskAgent

        # CONC: 2 계좌 공동 보유. 합 exposure 가 매우 크면 비중 초과 감지.
        self._seed_ticker_with_loss(db_path, "CONC", "Main", avg_price=100.0, current_price=101.0)
        with _get_db(db_path) as conn:
            # 추가 계좌에 같은 ticker — exposure 2배
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("Toss", "CONC", 10, 100.0, "USD"),
            )

        portfolio_yaml = tmp_path / "portfolio.yaml"
        portfolio_yaml.write_text(
            _yaml.dump(
                {
                    "accounts": {
                        "Main": {"strategy": "core"},
                        "Toss": {"strategy": "long_term"},
                    }
                }
            )
        )
        real_open = open

        def _opener(path, **kwargs):
            if str(path).endswith("portfolio.yaml"):
                return real_open(portfolio_yaml, **kwargs)
            return real_open(path, **kwargs)

        # portfolio 전체가 CONC 만 있으므로 비중 = 100% > MAX_SINGLE_POSITION(15%)
        # → "비중 초과" 경고가 2 row 합산 기준으로 trigger
        with _patch("builtins.open", side_effect=_opener):
            v = RiskAgent().analyze("CONC", db_path=db_path)

        assert "비중 초과" in v.reasoning
        # 합산 비중이 리포트에 반영됐는지 숫자 확인 (100.0% expected, 50.0% 아님)
        assert "100.0%" in v.reasoning


# ─── Phase 3-D #616: branch coverage ──────────────────────────────────


class TestRiskAgentBranches:
    def test_volatility_normal_range_skips_vol_branch(self, db_path):
        """77→86: vol 이 low~high 사이 → elif/elif False → concentration 블록으로."""
        from nuri.core.db import get_db
        from nuri.trading.agents.risk_agent import RiskAgent

        # ±2.5% 변동 (vol≈3%, low=2 ~ high=5 사이)
        with get_db(db_path) as conn:
            price = 100.0
            for i in range(1, 31):
                price *= 1.025 if i % 2 == 0 else 0.975
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("VRNG", f"2026-04-{i:02d}", price, price * 1.01, price * 0.99, price, 1000),
                )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES ('test', 'VRNG', 10, 100, 'USD', 'Tech')"
            )
        v = RiskAgent().analyze("VRNG", db_path=db_path)
        # vol 메시지 둘 다 제외 (정상 범위)
        assert "고변동성" not in v.reasoning
        assert "저변동성" not in v.reasoning

    def test_sell_without_stop_loss_smoke(self, db_path):
        """110→120 smoke: SELL 진입은 코드 상 어렵지만 stop_loss 미발화 path 가 정상 동작 검증."""
        from nuri.core.db import get_db
        from nuri.trading.agents.risk_agent import RiskAgent

        # 손익 양호 (avg=100, current=105) → stop_loss 미발화
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES ('test', 'SAFE', 10, 100, 'USD', 'Tech')"
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES ('SAFE', '2026-05-06', 105, 106, 104, 105, 1000)"
            )
        v = RiskAgent().analyze("SAFE", db_path=db_path)
        assert "손절선" not in v.reasoning  # stop_loss 미발화 확인

    def test_multi_holding_second_row_not_worse(self, db_path):
        """46→39: 다계좌 보유 — 첫 row 큰 손실 (worst_breach 설정), 두번째 row 작은 손실 (worst 유지).

        if worst_breach is None or row_pnl < worst_breach[0]:  # 두번째 row 에서 False path
        """
        from nuri.core.db import get_db
        from nuri.trading.agents.risk_agent import RiskAgent

        # current=85, avg1=100 (loss=-15%, breach), avg2=90 (loss=-5.5%, no breach)
        # → 첫 row -15% breach 됨, 두번째 row 의 -5.5% 는 breach 아니라
        #   if worst_breach[0]=-15.0 의 False path 필요 → 첫 row 큰 breach + 두번째 row
        #   더 작은 breach 만들어야 if 가 False 됨.
        # current=80, avg1=100 (loss=-20%, breach), avg2=90 (loss=-11%, breach but less negative)
        # → -11 < -20 False → if False 진입.
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) "
                "VALUES ('Main', 'MULTI', 10, 100.0, 'USD')"
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) "
                "VALUES ('Toss', 'MULTI', 5, 90.0, 'USD')"
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES ('MULTI', '2026-05-06', 80, 82, 78, 80, 1000)"
            )
        v = RiskAgent().analyze("MULTI", db_path=db_path)
        # 첫 row 손실 -20% 가 worst_breach 로 보고됨 (두번째 -11% 가 덮어쓰지 않음)
        assert "손절선 돌파" in v.reasoning
        assert "-20.0%" in v.reasoning  # 첫 row 손실
