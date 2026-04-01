"""Consolidated tests for nuri.trading.recommend.* modules.

Covers: candidates, rebalance, tracker, price_targets
Extracted from: test_recommend, test_rebalance_regime, test_tracker_extended,
    test_sixty_percent, test_engine, test_coverage_round{7,8,9,10,16,18,20,23,27},
    test_coverage_extra, test_new_modules, test_data_integrity, test_feedback_loop,
    test_regime, test_trading_engine_all.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, query, upsert_macro, upsert_portfolio, upsert_prices
from nuri.core.timezone import kst_now, today_kst

# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def db_path_with_dbmod(tmp_path, monkeypatch):
    """db_path + monkeypatch DB_PATH for modules that use default path."""
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def market_data(db_path):
    """포트폴리오 + 가격 데이터 (from test_recommend)."""
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("test", "TEST1", 100, 50.0, "USD", "Technology"),
                ("test", "TEST2", 50, 80.0, "USD", "Health Care"),
            ],
        )

    dates = pd.bdate_range("2025-01-01", periods=60)
    prices_down = np.linspace(100, 70, 30)
    prices_up = np.linspace(70, 110, 30)
    close1 = np.concatenate([prices_down, prices_up])
    close2 = np.concatenate([np.linspace(80, 60, 30), np.linspace(60, 90, 30)])

    for ticker, close in [("TEST1", close1), ("TEST2", close2)]:
        df = pd.DataFrame({
            "ticker": ticker,
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": [1000000] * 60,
            "adj_close": close,
        })
        upsert_prices(df, db_path)

    return db_path


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    """Full DB with portfolio, prices (SPY + tickers), macro (from test_coverage_round18)."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
    ], path)

    dates = pd.bdate_range("2024-06-01", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 5
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": p, "high": p + 3, "low": p - 2,
                "close": p + 1, "volume": 50_000_000, "adj_close": p + 1,
            })
    upsert_prices(pd.DataFrame(rows), path)

    macro = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro.append({"indicator": "vix", "date": ds, "value": 15 + np.sin(i / 30) * 8, "source": "test"})
        macro.append({"indicator": "fear_greed", "date": ds, "value": 50 + np.sin(i / 25) * 30, "source": "test"})
    upsert_macro(macro, path)
    return path


@pytest.fixture
def rich_db_full(tmp_path, monkeypatch):
    """Full DB with fundamentals, estimates, superinvestors (from test_coverage_round20)."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 150.0, "currency": "USD", "sector": "Technology"},
        {"account": "test", "ticker": "NVDA", "quantity": 5,
         "avg_price": 120.0, "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "005930.KS", "quantity": 100,
         "avg_price": 70000.0, "currency": "KRW", "sector": "반도체"},
    ], path)

    dates = pd.date_range("2024-01-01", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA", "005930.KS"]:
        base = {"SPY": 450, "AAPL": 150, "NVDA": 120, "005930.KS": 70000}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.3 + np.sin(i / 20) * 5
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "open": p, "high": p + 4, "low": p - 3,
                "close": p + 1, "volume": 50_000_000, "adj_close": p + 1,
            })
    upsert_prices(pd.DataFrame(rows), path)

    macro_records = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro_records.append({"indicator": "vix", "date": ds,
                              "value": 15 + np.sin(i / 30) * 8, "source": "test"})
        macro_records.append({"indicator": "fear_greed", "date": ds,
                              "value": 50 + np.sin(i / 25) * 30, "source": "test"})
        macro_records.append({"indicator": "usd_krw", "date": ds,
                              "value": 1350.0, "source": "test"})
    upsert_macro(macro_records, path)

    with get_db(path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, market_cap, beta, debt_to_equity)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("AAPL", "2025-01-01", 28.0, 0.35, 0.08, 3e12, 1.2, 1.5),
        )
        conn.execute(
            "INSERT OR REPLACE INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, market_cap, beta, debt_to_equity)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("NVDA", "2025-01-01", 55.0, 0.45, 0.25, 2e12, 1.8, 0.5),
        )
        conn.execute(
            "INSERT OR REPLACE INTO estimates (ticker, date, recommendation, target_high, target_low, target_mean, target_median, num_analysts, current_price)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("AAPL", "2025-01-01", "buy", 250.0, 180.0, 220.0, 215.0, 30, 200.0),
        )
        conn.execute(
            "INSERT OR REPLACE INTO estimates (ticker, date, recommendation, target_high, target_low, target_mean, target_median, num_analysts, current_price)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("NVDA", "2025-01-01", "strong_buy", 300.0, 200.0, 270.0, 265.0, 35, 250.0),
        )

    return path


@pytest.fixture
def full_db(tmp_path, monkeypatch):
    """풍부한 가격 + 시그널 + 매크로 (from test_sixty_percent)."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    today = today_kst()

    with get_db(path) as conn:
        for t, q, p, s in [("AAPL", 10, 150, "Technology"), ("MSFT", 5, 300, "Software"),
                            ("TSLA", 8, 340, "SectorA")]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)", ("test", t, q, p, "USD", s))

    dates = pd.date_range(end=today, periods=400)
    for ticker, base in [("SPY", 400), ("AAPL", 140), ("MSFT", 280), ("TSLA", 300)]:
        np.random.seed(42)
        close = np.linspace(base, base * 1.2, 400)
        noise = np.random.normal(0, base * 0.01, 400)
        close = close + noise
        high = close * 1.01
        low = close * 0.99
        volume = np.random.randint(500000, 2000000, 400)

        df = pd.DataFrame({
            "ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.998, "high": high, "low": low,
            "close": close, "volume": volume, "adj_close": close,
        })
        upsert_prices(df, path)

    with get_db(path) as conn:
        for i, d in enumerate(dates[-100:]):
            ds = d.strftime("%Y-%m-%d")
            for ticker in ["AAPL", "MSFT", "TSLA", "SPY"]:
                rsi = 30 + (i % 40)
                sma20 = 155 + i * 0.1
                sma50 = 150 + i * 0.08
                sma200 = 145 + i * 0.05
                bb_upper = sma20 * 1.04
                bb_lower = sma20 * 0.96
                macd = 0.5 * np.sin(i / 10) + np.random.normal(0, 0.2)
                macd_signal = 0.5 * np.sin((i - 3) / 10)

                conn.execute(
                    "INSERT OR IGNORE INTO signals "
                    "(ticker, date, rsi_14, sma_20, sma_50, sma_200, "
                    "bb_upper, bb_lower, bb_middle, macd, macd_signal) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ticker, ds, rsi, sma20, sma50, sma200,
                     bb_upper, bb_lower, sma20, macd, macd_signal),
                )

    upsert_macro([
        {"indicator": "vix", "date": today, "value": 18.0, "source": "test"},
        {"indicator": "fear_greed", "date": today, "value": 55.0, "source": "test"},
        {"indicator": "sp500_yoy", "date": today, "value": 15.0, "source": "test"},
        {"indicator": "usd_krw", "date": today, "value": 1380.0, "source": "test"},
    ], path)

    return path


# ═══════════════════════════════════════════════════════════════════════════════
# Helper functions
# ═══════════════════════════════════════════════════════════════════════════════


def _seed_recommendation(db_path, date, ticker, action, entry_price, confidence=70.0):
    """추천 레코드 삽입."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO recommendations (date, ticker, action, confidence, entry_price) "
            "VALUES (?, ?, ?, ?, ?)",
            (date, ticker, action, confidence, entry_price),
        )


def _seed_portfolio_r23(db_path, tickers=None):
    """Insert sample portfolio rows (from test_coverage_round23)."""
    tickers = tickers or [("test", "AAPL", 10, 150.0, "USD", "Technology"),
                          ("test", "MSFT", 5, 300.0, "USD", "Technology"),
                          ("test", "JNJ", 20, 160.0, "USD", "Health")]
    with get_db(db_path) as conn:
        for account, ticker, qty, avg_price, currency, sector in tickers:
            conn.execute(
                "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (account, ticker, qty, avg_price, currency, sector),
            )


def _seed_prices_r23(db_path, ticker="AAPL", close=170.0, high=180.0, days=5):
    """Insert sample price rows (from test_coverage_round23)."""
    with get_db(db_path) as conn:
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, date_str, close - 2, high, close - 5, close, 1000000),
            )


def _seed_macro_r23(db_path, indicator="vix", value=20.0, days=1):
    """Insert sample macro rows (from test_coverage_round23)."""
    with get_db(db_path) as conn:
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT OR REPLACE INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
                (indicator, date_str, value, "test"),
            )


def _seed_portfolio_nm(db_path, holdings=None):
    """테스트 포트폴리오 데이터 삽입 (from test_new_modules)."""
    if holdings is None:
        holdings = [
            ("test", "TSLA", 33, 200.0, "USD", "SectorA"),
            ("test", "NVDA", 20, 100.0, "USD", "Semiconductor"),
            ("test", "GOOGL", 5, 269.91, "USD", "BigTech"),
            ("test", "TSLL", 96, 20.0, "USD", "SectorB"),
            ("test", "LLY", 1, 1087.10, "USD", "Pharma"),
        ]
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            holdings,
        )


def _seed_prices_nm(db_path, prices=None):
    """테스트 가격 데이터 삽입 (from test_new_modules)."""
    if prices is None:
        prices = [
            ("2026-03-27", "TSLA", 355.0, 365.0, 350.0, 360.17, 1000000),
            ("2026-03-27", "NVDA", 165.0, 170.0, 163.0, 167.99, 2000000),
            ("2026-03-27", "GOOGL", 270.0, 278.0, 268.0, 274.26, 500000),
            ("2026-03-27", "TSLL", 11.0, 12.0, 10.5, 11.44, 300000),
            ("2026-03-27", "LLY", 880.0, 895.0, 875.0, 888.34, 100000),
        ]
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prices (date, ticker, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            prices,
        )


def _seed_fundamentals_nm(db_path, data=None):
    """펀더멘탈 데이터 삽입 (from test_new_modules)."""
    if data is None:
        data = [
            ("2026-03-27", "TSLA", 327.0),
            ("2026-03-27", "NVDA", 37.0),
            ("2026-03-27", "GOOGL", 22.0),
            ("2026-03-27", "LLY", 43.0),
        ]
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO fundamentals (date, ticker, pe_ratio) VALUES (?, ?, ?)",
            data,
        )


def _seed_estimates_nm(db_path, data=None):
    """애널리스트 목표가 삽입 (from test_new_modules)."""
    if data is None:
        data = [
            ("2026-03-27", "TSLA", 393.51),
            ("2026-03-27", "NVDA", 273.61),
            ("2026-03-27", "GOOGL", 376.57),
        ]
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO estimates (date, ticker, target_mean) VALUES (?, ?, ?)",
            data,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CANDIDATES — nuri.trading.recommend.candidates
# ═══════════════════════════════════════════════════════════════════════════════


class TestCandidates:
    """From test_recommend.py."""

    def test_screen_returns_list(self, market_data):
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=10, db_path=market_data)
        assert isinstance(candidates, list)

    def test_candidates_have_confidence(self, market_data):
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=30, db_path=market_data)
        for c in candidates:
            assert 0 <= c.confidence <= 100
            assert c.direction in ("BUY", "SELL")

    def test_candidates_sorted_by_confidence(self, market_data):
        """confidence 내림차순 정렬 확인."""
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=30, db_path=market_data)
        if len(candidates) >= 2:
            for i in range(len(candidates) - 1):
                assert candidates[i].confidence >= candidates[i + 1].confidence

    def test_empty_db_returns_empty(self, db_path):
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(db_path=db_path)
        assert candidates == []


class TestCandidatesDeep:
    """From test_sixty_percent.py."""

    def test_screen_with_signals(self, full_db):
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=30, db_path=full_db)
        assert isinstance(candidates, list)

    def test_confidence_range(self, full_db):
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=30, db_path=full_db)
        for c in candidates:
            assert 0 <= c.confidence <= 100

    def test_print_candidates(self, full_db, capsys):
        from nuri.trading.recommend.candidates import Candidate, print_candidates
        candidates = [
            Candidate("AAPL", "rsi_oversold", "2026-03-28", "BUY", 75.0, 0.65, 2.1, True, 155.0, "test"),
            Candidate("TSLA", "macd_golden", "2026-03-28", "BUY", 60.0, 0.55, 1.5, True, 350.0, "test"),
        ]
        print_candidates(candidates)
        output = capsys.readouterr().out
        assert "AAPL" in output


class TestCandidates_R10:
    """From test_coverage_round10.py."""

    def test_screen_candidates(self, rich_db):
        from nuri.trading.recommend.candidates import screen_candidates
        result = screen_candidates()
        assert isinstance(result, list)

    def test_tracker_save(self, rich_db):
        from nuri.trading.recommend.tracker import save_recommendations
        count = save_recommendations([])
        assert count == 0


class TestCandidatesExtended:
    """From test_coverage_extra.py."""

    def test_candidate_dataclass(self):
        from nuri.trading.recommend.candidates import Candidate
        c = Candidate("AAPL", "rsi_oversold", "2026-03-28", "BUY", 75.0, 0.65, 2.1, True, 155.0, "test")
        assert c.ticker == "AAPL"
        assert c.direction == "BUY"
        assert c.confidence == 75.0

    def test_screen_with_data(self, full_db):
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=10, db_path=full_db)
        assert isinstance(candidates, list)


class TestCandidatesVixGate:
    """VIX gate logic in candidates (from test_coverage_round18)."""

    def test_vix_blocked(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "vix.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        upsert_macro([
            {"indicator": "vix", "date": "2026-03-31", "value": 35.0, "source": "test"},
        ], path)

        from nuri.trading.recommend.candidates import _check_vix_gate
        result = _check_vix_gate(path)
        assert result["gate"] == "blocked"
        assert result["vix"] == 35.0

    def test_vix_caution(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "vix.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        upsert_macro([
            {"indicator": "vix", "date": "2026-03-31", "value": 27.0, "source": "test"},
        ], path)

        from nuri.trading.recommend.candidates import _check_vix_gate
        result = _check_vix_gate(path)
        assert result["gate"] == "caution"

    def test_vix_normal(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "vix.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        upsert_macro([
            {"indicator": "vix", "date": "2026-03-31", "value": 15.0, "source": "test"},
        ], path)

        from nuri.trading.recommend.candidates import _check_vix_gate
        result = _check_vix_gate(path)
        assert result["gate"] == "normal"

    def test_vix_no_data(self, tmp_path, monkeypatch):
        """No VIX data => value 0 => normal."""
        import nuri.core.db as db_mod
        path = tmp_path / "vix.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        from nuri.trading.recommend.candidates import _check_vix_gate
        result = _check_vix_gate(path)
        assert result["gate"] == "normal"
        assert result["vix"] == 0.0


class TestCandidatesDriftMultipliers:
    """DRIFT_MULTIPLIERS sanity (from test_coverage_round18)."""

    def test_drift_multiplier_values(self):
        from nuri.trading.recommend.candidates import DRIFT_MULTIPLIERS

        assert DRIFT_MULTIPLIERS["critical"] == 0.3
        assert DRIFT_MULTIPLIERS["degrading"] == 0.6
        assert DRIFT_MULTIPLIERS["improving"] == 1.1
        assert DRIFT_MULTIPLIERS["stable"] == 1.0


class TestScreenCandidates:
    """screen_candidates integration with mocked regime and scorecard (from test_coverage_round18)."""

    def test_empty_portfolio_returns_empty(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        from nuri.trading.recommend.candidates import screen_candidates

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=None):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    candidates = screen_candidates(lookback_days=5, db_path=path)

        assert candidates == []

    def test_screen_with_regime_avoid(self, rich_db):
        """Signals in avoid list get regime_fit=False and confidence penalty."""
        from nuri.trading.recommend.candidates import screen_candidates

        regime_ctx = {
            "regime": "bear_high_vol",
            "recommended": [],
            "avoid": ["rsi_oversold", "macd_golden", "sma_golden", "bb_bounce",
                       "volume_spike", "gap_up", "vix_reversal", "pcr_reversal",
                       "yield_curve_recovery", "insider_cluster", "short_squeeze"],
            "position": "minimal",
            "regime_stats": {},
        }
        scorecard = {
            "rsi_oversold": {"win_rate": 0.6, "profit_factor": 2.0, "avg_return": 3.0, "total_trades": 20},
        }

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=(scorecard, 1)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=regime_ctx):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                        candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        avoided = [c for c in candidates if not c.regime_fit]
        for c in avoided:
            assert c.confidence < 50

    def test_screen_with_drift_penalty(self, rich_db):
        """Signals with critical drift get heavily penalized."""
        from nuri.trading.recommend.candidates import screen_candidates

        drift_map = {
            "rsi_oversold": {"status": "critical", "drift_pct": -50},
        }

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=None):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value=drift_map):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                        candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        critical = [c for c in candidates if c.drift_status == "critical"]
        for c in critical:
            assert c.scoring_detail is not None
            assert c.scoring_detail["drift_multiplier"] == 0.3


class TestLoadScorecard:
    """_load_scorecard with and without CSV files (from test_coverage_round18)."""

    def test_no_report_dir(self, tmp_path, monkeypatch):
        from nuri.trading.recommend import candidates as cand_mod

        monkeypatch.setattr(cand_mod, "REPORT_DIR", tmp_path / "nonexistent")
        data, age = cand_mod._load_scorecard()
        assert data == {}
        assert age is None

    def test_with_scorecard_csv(self, tmp_path, monkeypatch):
        from nuri.trading.recommend import candidates as cand_mod

        report_dir = tmp_path / "reports"
        day_dir = report_dir / "2026-03-30"
        day_dir.mkdir(parents=True)

        csv_content = "ticker,signal_id,win_rate,profit_factor,avg_return,total_trades\n"
        csv_content += ",rsi_oversold,0.65,2.1,3.5,30\n"
        csv_content += ",macd_golden,0.55,1.5,2.0,20\n"
        (day_dir / "signal_scorecard.csv").write_text(csv_content)

        monkeypatch.setattr(cand_mod, "REPORT_DIR", report_dir)
        data, age = cand_mod._load_scorecard()
        assert "rsi_oversold" in data
        assert data["rsi_oversold"]["win_rate"] == 0.65
        assert age is not None

    def test_stale_scorecard_warning(self, tmp_path, monkeypatch):
        """Scorecard older than 7 days triggers warning."""
        from nuri.trading.recommend import candidates as cand_mod

        report_dir = tmp_path / "reports"
        day_dir = report_dir / "2025-01-01"
        day_dir.mkdir(parents=True)

        csv_content = "ticker,signal_id,win_rate,profit_factor,avg_return,total_trades\n"
        csv_content += ",rsi_oversold,0.65,2.1,3.5,30\n"
        (day_dir / "signal_scorecard.csv").write_text(csv_content)

        monkeypatch.setattr(cand_mod, "REPORT_DIR", report_dir)
        data, age = cand_mod._load_scorecard()
        assert age > 7
        assert "rsi_oversold" in data


class TestGetRegimeContext:
    """_get_regime_context with mocked regime classifier (from test_coverage_round18)."""

    def test_regime_returns_context(self, rich_db):
        from nuri.trading.recommend.candidates import _get_regime_context

        mock_regime = MagicMock(regime="bull_low_vol")
        mock_strategy = MagicMock(
            recommended_signals=["rsi_oversold"],
            avoid_signals=["rsi_overbought"],
            position_sizing="normal",
            signal_regime_stats={"rsi_oversold": {"win_rate": 0.7, "pf": 2.0, "trades": 10}},
        )

        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            with patch("nuri.quant.regime.strategy_map.map_regime_to_strategy", return_value=mock_strategy):
                ctx = _get_regime_context(rich_db)

        assert ctx is not None
        assert ctx["regime"] == "bull_low_vol"
        assert "rsi_oversold" in ctx["recommended"]
        assert ctx["regime_stats"]["rsi_oversold"]["win_rate"] == 0.7

    def test_regime_none_returns_none(self, rich_db):
        from nuri.trading.recommend.candidates import _get_regime_context

        with patch("nuri.quant.regime.classifier.classify_regime", return_value=None):
            ctx = _get_regime_context(rich_db)

        assert ctx is None

    def test_regime_exception_returns_none(self, rich_db):
        from nuri.trading.recommend.candidates import _get_regime_context

        with patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("fail")):
            ctx = _get_regime_context(rich_db)

        assert ctx is None


class TestPrintCandidates:
    """print_candidates output formatting (from test_coverage_round18)."""

    def test_print_empty(self, capsys):
        from nuri.trading.recommend.candidates import print_candidates

        print_candidates([])
        out = capsys.readouterr().out
        assert "매매 후보 없음" in out

    def test_print_with_candidates(self, capsys, rich_db):
        from nuri.trading.recommend.candidates import Candidate, print_candidates

        candidates = [
            Candidate(
                ticker="AAPL", signal_id="rsi_oversold", signal_date="2026-03-30",
                direction="BUY", confidence=75.0, win_rate=0.65, profit_factor=2.0,
                regime_fit=True, price=180.0, notes="과거 20건",
                drift_status="", conflict="", scoring_detail=None,
            ),
            Candidate(
                ticker="NVDA", signal_id="macd_dead", signal_date="2026-03-30",
                direction="SELL", confidence=60.0, win_rate=0.55, profit_factor=1.5,
                regime_fit=True, price=900.0, notes="",
                drift_status="degrading", conflict="", scoring_detail=None,
            ),
            Candidate(
                ticker="AAPL", signal_id="rsi_overbought", signal_date="2026-03-30",
                direction="SELL", confidence=30.0, win_rate=0.45, profit_factor=0.8,
                regime_fit=False, price=180.0, notes="레짐에서 비추천",
                drift_status="critical", conflict="direction_conflict", scoring_detail=None,
            ),
        ]

        with patch("nuri.trading.recommend.candidates._check_vix_gate",
                   return_value={"vix": 15, "gate": "normal", "msg": ""}):
            print_candidates(candidates)

        out = capsys.readouterr().out
        assert "Signal-Based Candidates" in out
        assert "AAPL" in out

    def test_print_vix_blocked(self, capsys, rich_db):
        from nuri.trading.recommend.candidates import Candidate, print_candidates

        candidates = [
            Candidate(
                ticker="AAPL", signal_id="rsi_oversold", signal_date="2026-03-30",
                direction="BUY", confidence=0.0, win_rate=0.65, profit_factor=2.0,
                regime_fit=True, price=180.0, notes="VIX > 30",
                drift_status="", conflict="", scoring_detail=None,
            ),
        ]

        with patch("nuri.trading.recommend.candidates._check_vix_gate",
                   return_value={"vix": 35, "gate": "blocked", "msg": "VIX 35.0 > 30 -> block"}):
            print_candidates(candidates)

        out = capsys.readouterr().out
        assert "VIX" in out


class TestCandidatesConflictDetection:
    """Conflict detection in screen_candidates (from test_coverage_round18)."""

    def test_conflict_penalty_applied(self, rich_db):
        """When detect_conflicts returns high severity, confidence is halved."""
        from nuri.trading.engine.conflicts import SignalConflict
        from nuri.trading.recommend.candidates import screen_candidates

        conflicts = [
            SignalConflict(
                ticker="AAPL",
                conflict_type="direction_conflict",
                severity="high",
                buy_signals=["rsi_oversold"],
                sell_signals=["rsi_overbought"],
                detail="방향 충돌",
                recommendation="관망",
            ),
        ]

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=None):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=conflicts):
                        candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        aapl_conflicted = [c for c in candidates if c.ticker == "AAPL" and c.conflict]
        for c in aapl_conflicted:
            assert c.conflict == "direction_conflict"
            if c.scoring_detail:
                assert c.scoring_detail.get("conflict_penalty") == 0.5


class TestCandidatesRegimeStats:
    """Test regime-specific stats path in confidence calculation (from test_coverage_round18)."""

    def test_regime_stats_used_when_available(self, rich_db):
        """When regime_stats has enough trades, uses regime-specific win_rate."""
        from nuri.trading.recommend.candidates import screen_candidates

        regime_ctx = {
            "regime": "bull_low_vol",
            "recommended": ["rsi_oversold", "macd_golden", "sma_golden", "bb_bounce", "volume_spike"],
            "avoid": [],
            "position": "normal",
            "regime_stats": {
                "rsi_oversold": {"win_rate": 0.8, "pf": 3.0, "trades": 15},
                "macd_golden": {"win_rate": 0.7, "pf": 2.5, "trades": 12},
            },
        }

        with patch("nuri.trading.recommend.candidates._load_scorecard", return_value=({}, None)):
            with patch("nuri.trading.recommend.candidates._get_regime_context", return_value=regime_ctx):
                with patch("nuri.trading.recommend.candidates._get_drift_map", return_value={}):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                        candidates = screen_candidates(lookback_days=500, db_path=rich_db)

        rsi_cands = [c for c in candidates if c.signal_id == "rsi_oversold"]
        for c in rsi_cands:
            if c.scoring_detail:
                assert "regime_win_rate" in c.scoring_detail


class TestCandidates_R27:
    """From test_coverage_round27.py."""

    def test_load_scorecard_no_reports(self, monkeypatch):
        """_load_scorecard with no report directory."""
        import nuri.trading.recommend.candidates as cand_mod
        from nuri.trading.recommend.candidates import _load_scorecard
        monkeypatch.setattr(cand_mod, "REPORT_DIR", Path("/nonexistent/path"))
        data, age = _load_scorecard()
        assert data == {}
        assert age is None

    def test_get_drift_map_exception(self, monkeypatch):
        """_get_drift_map handles exception."""
        from nuri.trading.recommend.candidates import _get_drift_map
        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift",
                            MagicMock(side_effect=Exception("no data")))
        result = _get_drift_map()
        assert result == {}

    def test_check_vix_gate_normal(self, db_path):
        """VIX gate normal when VIX is low."""
        from nuri.trading.recommend.candidates import _check_vix_gate
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
                         ("vix", "2025-03-28", 18.5))
        result = _check_vix_gate(db_path=db_path)
        assert result["gate"] == "normal"

    def test_check_vix_gate_blocked(self, db_path):
        """VIX gate blocked when VIX > 30."""
        from nuri.trading.recommend.candidates import _check_vix_gate
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
                         ("vix", "2025-03-28", 35.0))
        result = _check_vix_gate(db_path=db_path)
        assert result["gate"] == "blocked"

    def test_check_vix_gate_caution(self, db_path):
        """VIX gate caution when VIX 25-30."""
        from nuri.trading.recommend.candidates import _check_vix_gate
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)",
                         ("vix", "2025-03-28", 27.0))
        result = _check_vix_gate(db_path=db_path)
        assert result["gate"] == "caution"

    def test_print_candidates_empty(self, capsys, monkeypatch):
        """print_candidates with no candidates."""
        from nuri.trading.recommend.candidates import print_candidates
        monkeypatch.setattr("nuri.trading.recommend.candidates._check_vix_gate",
                            lambda **kw: {"vix": 18, "gate": "normal", "msg": ""})
        print_candidates([])
        captured = capsys.readouterr()
        assert "매매 후보 없음" in captured.out


class TestScorecardStaleness:
    """From test_data_integrity.py — scorecard freshness check."""

    def test_stale_scorecard_adds_note(self, tmp_path, db_path):
        """7일 초과 스코어카드 → 후보 노트에 경고 문구."""
        stale_date = (kst_now().replace(tzinfo=None) - timedelta(days=10)).strftime("%Y-%m-%d")
        report_dir = tmp_path / "reports" / stale_date
        report_dir.mkdir(parents=True)

        scorecard_df = pd.DataFrame({
            "ticker": [None, None],
            "signal_id": ["rsi_oversold", "macd_golden"],
            "win_rate": [0.6, 0.55],
            "profit_factor": [2.0, 1.5],
            "avg_return": [0.05, 0.03],
            "total_trades": [100, 80],
        })
        scorecard_df.to_csv(report_dir / "signal_scorecard.csv", index=False)

        from nuri.trading.recommend import candidates as cand_module
        original_report_dir = cand_module.REPORT_DIR

        try:
            cand_module.REPORT_DIR = tmp_path / "reports"
            data, age_days = cand_module._load_scorecard()
            assert age_days is not None
            assert age_days >= 9
            assert len(data) > 0
        finally:
            cand_module.REPORT_DIR = original_report_dir

    def test_fresh_scorecard_no_warning(self, tmp_path):
        """7일 이내 스코어카드 → 경고 없음."""
        today = today_kst()
        report_dir = tmp_path / "reports" / today
        report_dir.mkdir(parents=True)

        scorecard_df = pd.DataFrame({
            "ticker": [None],
            "signal_id": ["rsi_oversold"],
            "win_rate": [0.6],
            "profit_factor": [2.0],
            "avg_return": [0.05],
            "total_trades": [100],
        })
        scorecard_df.to_csv(report_dir / "signal_scorecard.csv", index=False)

        from nuri.trading.recommend import candidates as cand_module
        original_report_dir = cand_module.REPORT_DIR

        try:
            cand_module.REPORT_DIR = tmp_path / "reports"
            data, age_days = cand_module._load_scorecard()
            assert age_days is not None
            assert age_days <= 7
        finally:
            cand_module.REPORT_DIR = original_report_dir

    def test_no_scorecard_returns_none_age(self, tmp_path):
        """스코어카드 파일 없으면 age_days=None."""
        from nuri.trading.recommend import candidates as cand_module
        original_report_dir = cand_module.REPORT_DIR

        try:
            cand_module.REPORT_DIR = tmp_path / "nonexistent"
            data, age_days = cand_module._load_scorecard()
            assert data == {}
            assert age_days is None
        finally:
            cand_module.REPORT_DIR = original_report_dir


# ═══════════════════════════════════════════════════════════════════════════════
# REBALANCE — nuri.trading.recommend.rebalance
# ═══════════════════════════════════════════════════════════════════════════════


class TestSectorClassify:
    """From test_recommend.py."""

    def test_growth_sectors(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Technology") == "growth"
        assert _classify_sector("SectorA") == "growth"
        assert _classify_sector("Semiconductor") == "growth"

    def test_defensive_sectors(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Health Care") == "defensive"
        assert _classify_sector("Utilities") == "defensive"
        assert _classify_sector("Consumer Staples") == "defensive"

    def test_neutral_sectors(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Finance") == "neutral"
        assert _classify_sector("") == "neutral"
        assert _classify_sector("Unknown") == "neutral"


class TestClassifySector:
    """From test_rebalance_regime.py."""

    def test_defensive_keywords(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Health Care") == "defensive"
        assert _classify_sector("Utilities") == "defensive"
        assert _classify_sector("Real Estate") == "defensive"
        assert _classify_sector("Pharma") == "defensive"
        assert _classify_sector("Defense") == "defensive"

    def test_growth_keywords(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Technology") == "growth"
        assert _classify_sector("AI/Cloud") == "growth"
        assert _classify_sector("Semiconductor") == "growth"
        assert _classify_sector("SectorA") == "growth"
        assert _classify_sector("Software") == "growth"

    def test_neutral(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Finance") == "neutral"
        assert _classify_sector("") == "neutral"
        assert _classify_sector("Unknown") == "neutral"

    def test_case_insensitive(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("TECHNOLOGY") == "growth"
        assert _classify_sector("health care") == "defensive"


class TestSectorClassification:
    """From test_regime.py."""

    def test_classify_sector(self):
        from nuri.trading.recommend.rebalance import _classify_sector
        assert _classify_sector("Technology") == "growth"
        assert _classify_sector("SectorA") == "growth"
        assert _classify_sector("AI/Cloud") == "growth"
        assert _classify_sector("Consumer Staples") == "defensive"
        assert _classify_sector("Health Care") == "defensive"
        assert _classify_sector("Utilities") == "defensive"
        assert _classify_sector("Finance") == "neutral"
        assert _classify_sector("") == "neutral"
        assert _classify_sector("Semiconductor") == "growth"


class TestRebalanceAction:
    """From test_rebalance_regime.py."""

    def test_create(self):
        from nuri.trading.recommend.rebalance import RebalanceAction
        a = RebalanceAction(
            ticker="AAPL", sector="Technology", action="BUY",
            current_weight=5.0, target_weight=10.0, trade_value=5000,
            signals=["rsi_oversold(BUY)"], regime_note="[bull_strong]",
        )
        assert a.action == "BUY"
        assert a.trade_value == 5000

    def test_hold_action(self):
        from nuri.trading.recommend.rebalance import RebalanceAction
        a = RebalanceAction(
            ticker="MSFT", sector="Software", action="HOLD",
            current_weight=10.0, target_weight=10.0, trade_value=0,
            signals=[], regime_note="[bull_strong]",
        )
        assert a.action == "HOLD"


class TestCashTargets:
    """From test_rebalance_regime.py."""

    def test_values(self):
        from nuri.trading.recommend.rebalance import CASH_TARGETS
        assert CASH_TARGETS["aggressive"] == 0.0
        assert CASH_TARGETS["minimal"] == 0.40
        assert CASH_TARGETS["defensive"] == 0.20
        assert CASH_TARGETS["normal"] == 0.05


class TestPrintRebalance:
    """From test_rebalance_regime.py."""

    def test_empty(self, capsys):
        from nuri.trading.recommend.rebalance import print_rebalance
        print_rebalance([])
        output = capsys.readouterr().out
        assert "없음" in output

    def test_with_actions(self, capsys):
        from nuri.trading.recommend.rebalance import RebalanceAction, print_rebalance
        actions = [
            RebalanceAction("AAPL", "Technology", "BUY", 5.0, 10.0, 5000, ["rsi(BUY)"], "[bull_strong]"),
            RebalanceAction("MSFT", "Software", "HOLD", 10.0, 10.0, 0, [], "[bull_strong]"),
        ]
        print_rebalance(actions)
        output = capsys.readouterr().out
        assert "AAPL" in output
        assert "Rebalancing" in output

    def test_all_hold(self, capsys):
        from nuri.trading.recommend.rebalance import RebalanceAction, print_rebalance
        actions = [
            RebalanceAction("AAPL", "Technology", "HOLD", 10.0, 10.0, 0, [], "[bull]"),
        ]
        print_rebalance(actions)
        output = capsys.readouterr().out
        assert "불필요" in output


class TestRebalanceDeep:
    """From test_coverage_round7.py."""

    def test_regime_aware_rebalance(self, rich_db):
        from nuri.trading.recommend.rebalance import regime_aware_rebalance
        result = regime_aware_rebalance()
        assert isinstance(result, list)


class TestRebalanceRegimeAware:
    """From test_coverage_round8.py."""

    def test_with_gate_open(self, rich_db):
        from nuri.trading.recommend.rebalance import regime_aware_rebalance
        with patch("nuri.trading.engine.gate.check_gate") as mock_gate:
            mock_gate.return_value = {"status": "OPEN"}
            result = regime_aware_rebalance()
        assert isinstance(result, list)


class TestRebalance_R23:
    """From test_coverage_round23.py."""

    def test_classify_sector_defensive(self):
        from nuri.trading.recommend.rebalance import _classify_sector

        assert _classify_sector("Health Care") == "defensive"
        assert _classify_sector("Utilities") == "defensive"
        assert _classify_sector("") == "neutral"
        assert _classify_sector("Finance") == "neutral"

    def test_classify_sector_growth(self):
        from nuri.trading.recommend.rebalance import _classify_sector

        assert _classify_sector("Technology") == "growth"
        assert _classify_sector("AI/Cloud") == "growth"
        assert _classify_sector("Semiconductor") == "growth"

    def test_regime_aware_rebalance_with_mocks(self, db_path, monkeypatch):
        """Full rebalance flow with mocked dependencies."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        @dataclass
        class MockGateResult:
            ready: bool = False
            conditions: list = None

            def __post_init__(self):
                if self.conditions is None:
                    self.conditions = []

        @dataclass
        class MockGateCond:
            id: str = "test"
            passed: bool = False

        @dataclass
        class MockRegime:
            regime: str = "bear_high_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "minimal"

        base_df = pd.DataFrame({
            "ticker": ["AAPL", "MSFT", "JNJ"],
            "sector": ["Technology", "Technology", "Health"],
            "current_weight": [30.0, 25.0, 15.0],
            "optimal_weight": [20.0, 18.0, 22.0],
            "trade_value_usd": [-5000, -3500, 3500],
            "action": ["SELL", "REDUCE", "BUY"],
        })

        monkeypatch.setattr("nuri.trading.engine.gate.check_gate",
                            lambda *a, **kw: MockGateResult(ready=False, conditions=[MockGateCond(id="prices_data", passed=False)]))
        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda *a, **kw: MockStrategy())
        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", lambda **kw: [])
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda *a, **kw: [])

        actions = regime_aware_rebalance(method="rp", db_path=db_path)
        assert len(actions) == 3
        jnj = [a for a in actions if a.ticker == "JNJ"][0]
        assert jnj.action == "HOLD"

    def test_regime_aware_rebalance_with_conflicts(self, db_path, monkeypatch):
        """Conflict tickers forced HOLD."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        @dataclass
        class MockRegime:
            regime: str = "bull_low_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "normal"

        base_df = pd.DataFrame({
            "ticker": ["AAPL"],
            "sector": ["Technology"],
            "current_weight": [10.0],
            "optimal_weight": [20.0],
            "trade_value_usd": [5000],
            "action": ["BUY"],
        })

        @dataclass
        class MockConflict:
            ticker: str = "AAPL"
            conflict_type: str = "direction_conflict"
            severity: str = "high"

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda *a, **kw: MockStrategy())
        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", lambda **kw: [])
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda *a, **kw: [MockConflict()])

        actions = regime_aware_rebalance(db_path=db_path)
        assert actions[0].action == "HOLD"
        assert "충돌" in actions[0].regime_note

    def test_rebalance_empty_base(self, db_path, monkeypatch):
        """Empty base_df returns empty list."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: pd.DataFrame())
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: None)

        actions = regime_aware_rebalance(db_path=db_path)
        assert actions == []

    def test_print_rebalance_no_actions(self, capsys):
        """Print empty rebalance."""
        from nuri.trading.recommend.rebalance import print_rebalance

        print_rebalance([])
        captured = capsys.readouterr()
        assert "리밸런싱 데이터 없음" in captured.out

    def test_print_rebalance_with_actions(self, capsys):
        """Print with actionable items."""
        from nuri.trading.recommend.rebalance import RebalanceAction, print_rebalance

        actions = [
            RebalanceAction("AAPL", "Tech", "SELL", 30.0, 20.0, -5000.0, ["signal1"], "[bear_high_vol]"),
            RebalanceAction("MSFT", "Tech", "HOLD", 15.0, 15.0, 0.0, [], "[bear_high_vol]"),
        ]
        print_rebalance(actions)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out
        assert "HOLD: MSFT" in captured.out

    def test_defensive_sector_tilt(self, db_path, monkeypatch):
        """Defensive sector tilt in minimal regime."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        @dataclass
        class MockRegime:
            regime: str = "bear_high_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "defensive"

        base_df = pd.DataFrame({
            "ticker": ["JNJ", "NVDA"],
            "sector": ["Health Care", "Semiconductor"],
            "current_weight": [10.0, 10.0],
            "optimal_weight": [10.0, 10.0],
            "trade_value_usd": [0, 0],
            "action": ["HOLD", "HOLD"],
        })

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda *a, **kw: MockStrategy())
        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", lambda **kw: [])
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda *a, **kw: [])

        actions = regime_aware_rebalance(db_path=db_path)
        assert len(actions) == 2

    def test_hold_action_small_diff(self, db_path, monkeypatch):
        """Small weight difference -> HOLD."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        @dataclass
        class MockRegime:
            regime: str = "sideways_low_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "normal"

        base_df = pd.DataFrame({
            "ticker": ["AAPL"],
            "sector": ["Technology"],
            "current_weight": [15.0],
            "optimal_weight": [15.5],
            "trade_value_usd": [200],
            "action": ["BUY"],
        })

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda *a, **kw: MockStrategy())
        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", lambda **kw: [])
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda *a, **kw: [])

        actions = regime_aware_rebalance(db_path=db_path)
        assert actions[0].action == "HOLD"

    def test_rebalance_screen_exception(self, db_path, monkeypatch):
        """Screen candidates throws but rebalance continues."""
        from nuri.trading.recommend.rebalance import regime_aware_rebalance

        @dataclass
        class MockRegime:
            regime: str = "bull_low_vol"

        @dataclass
        class MockStrategy:
            position_sizing: str = "normal"

        base_df = pd.DataFrame({
            "ticker": ["AAPL"],
            "sector": ["Technology"],
            "current_weight": [10.0],
            "optimal_weight": [20.0],
            "trade_value_usd": [5000],
            "action": ["BUY"],
        })

        monkeypatch.setattr("nuri.analysis.rebalance.analyze_rebalance", lambda **kw: base_df)
        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", lambda **kw: MockRegime())
        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", lambda *a, **kw: MockStrategy())
        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates",
                            lambda **kw: (_ for _ in ()).throw(RuntimeError("fail")))

        actions = regime_aware_rebalance(db_path=db_path)
        assert len(actions) == 1
        assert actions[0].action == "BUY"


# ═══════════════════════════════════════════════════════════════════════════════
# TRACKER — nuri.trading.recommend.tracker
# ═══════════════════════════════════════════════════════════════════════════════


class TestTracker:
    """From test_recommend.py."""

    def test_save_and_query(self, market_data):
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import get_tracking_report, save_recommendations

        candidates = [
            Candidate("TEST1", "rsi_oversold", "2025-03-01", "BUY",
                       75.0, 0.6, 2.0, True, 100.0, "test"),
        ]
        n = save_recommendations(candidates, db_path=market_data)
        assert n == 1

        report = get_tracking_report(db_path=market_data)
        assert report["total_recommendations"] == 1

    def test_duplicate_ignored(self, market_data):
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations

        candidates = [
            Candidate("TEST1", "rsi_oversold", "2025-03-01", "BUY",
                       75.0, 0.6, 2.0, True, 100.0, "test"),
        ]
        save_recommendations(candidates, db_path=market_data)
        save_recommendations(candidates, db_path=market_data)

        rows = query("SELECT COUNT(*) as c FROM recommendations", db_path=market_data)
        assert rows[0]["c"] == 1

    def test_regime_filtered_not_saved(self, market_data):
        """regime_fit=False인 후보는 저장되지 않음."""
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations

        candidates = [
            Candidate("TEST1", "macd_golden", "2025-03-01", "BUY",
                       30.0, 0.4, 0.8, False, 100.0, "레짐 비적합"),
        ]
        save_recommendations(candidates, db_path=market_data)
        rows = query("SELECT COUNT(*) as c FROM recommendations", db_path=market_data)
        assert rows[0]["c"] == 0


class TestTrackOutcomes:
    """From test_tracker_extended.py."""

    def test_no_recommendations(self, db_path_with_dbmod):
        from nuri.trading.recommend.tracker import track_outcomes
        updated = track_outcomes(db_path=db_path_with_dbmod)
        assert updated == 0

    def test_30d_tracking(self, db_path_with_dbmod):
        """30일 경과 추천에 대해 수익률 업데이트."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path_with_dbmod, rec_date, "AAPL", "BUY", 150.0)

        target_date = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{
            "ticker": "AAPL", "date": target_date,
            "open": 160, "high": 165, "low": 158, "close": 162.0,
            "volume": 1000000, "adj_close": 162.0,
        }])
        upsert_prices(prices, db_path_with_dbmod)

        from nuri.trading.recommend.tracker import track_outcomes
        updated = track_outcomes(db_path=db_path_with_dbmod)
        assert updated == 1

        rows = query("SELECT outcome_30d, hit FROM recommendations", db_path=db_path_with_dbmod)
        assert rows[0]["outcome_30d"] is not None
        assert rows[0]["outcome_30d"] > 0
        assert rows[0]["hit"] == 1

    def test_60d_tracking(self, db_path_with_dbmod):
        """60일 경과 추천에 대해 수익률 업데이트."""
        rec_date = (datetime.now() - timedelta(days=65)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path_with_dbmod, rec_date, "MSFT", "SELL", 350.0)

        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        d60 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=60)).strftime("%Y-%m-%d")

        prices = pd.DataFrame([
            {"ticker": "MSFT", "date": d30, "open": 340, "high": 345, "low": 338, "close": 340.0, "volume": 1000000, "adj_close": 340.0},
            {"ticker": "MSFT", "date": d60, "open": 330, "high": 335, "low": 325, "close": 330.0, "volume": 1000000, "adj_close": 330.0},
        ])
        upsert_prices(prices, db_path_with_dbmod)

        from nuri.trading.recommend.tracker import track_outcomes
        updated = track_outcomes(db_path=db_path_with_dbmod)
        assert updated == 1

    def test_sell_hit_negative_return(self, db_path_with_dbmod):
        """SELL 추천 + 가격 하락 -> hit=True."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path_with_dbmod, rec_date, "BAD", "SELL", 100.0)

        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{
            "ticker": "BAD", "date": d30,
            "open": 90, "high": 92, "low": 88, "close": 90.0,
            "volume": 1000000, "adj_close": 90.0,
        }])
        upsert_prices(prices, db_path_with_dbmod)

        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path_with_dbmod)

        rows = query("SELECT hit FROM recommendations", db_path=db_path_with_dbmod)
        assert rows[0]["hit"] == 1

    def test_not_yet_30d(self, db_path_with_dbmod):
        """30일 미경과 -> 업데이트 안 함."""
        rec_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path_with_dbmod, rec_date, "NEW", "BUY", 100.0)

        from nuri.trading.recommend.tracker import track_outcomes
        updated = track_outcomes(db_path=db_path_with_dbmod)
        assert updated == 0


class TestGetTrackingReport:
    """From test_tracker_extended.py."""

    def test_empty(self, db_path_with_dbmod):
        from nuri.trading.recommend.tracker import get_tracking_report
        report = get_tracking_report(db_path=db_path_with_dbmod)
        assert report["total_recommendations"] == 0
        assert report["hit_rate"] == 0

    def test_with_data(self, db_path_with_dbmod):
        _seed_recommendation(db_path_with_dbmod, "2026-01-01", "AAPL", "BUY", 150.0)
        with get_db(db_path_with_dbmod) as conn:
            conn.execute(
                "UPDATE recommendations SET outcome_30d = 10.0, hit = 1 WHERE ticker = 'AAPL'"
            )

        from nuri.trading.recommend.tracker import get_tracking_report
        report = get_tracking_report(db_path=db_path_with_dbmod)
        assert report["total_recommendations"] == 1
        assert report["tracked"] == 1
        assert report["hit_rate"] == 1.0


class TestPrintTrackingReport:
    """From test_tracker_extended.py."""

    def test_empty_report(self, db_path_with_dbmod, capsys):
        from nuri.trading.recommend.tracker import print_tracking_report
        print_tracking_report(db_path=db_path_with_dbmod)
        output = capsys.readouterr().out
        assert "Tracking Report" in output

    def test_with_tracked(self, db_path_with_dbmod, capsys):
        _seed_recommendation(db_path_with_dbmod, "2026-01-01", "AAPL", "BUY", 150.0)
        with get_db(db_path_with_dbmod) as conn:
            conn.execute(
                "UPDATE recommendations SET outcome_30d = 10.0, hit = 1 WHERE ticker = 'AAPL'"
            )

        from nuri.trading.recommend.tracker import print_tracking_report
        print_tracking_report(db_path=db_path_with_dbmod)
        output = capsys.readouterr().out
        assert "Hit rate" in output or "AAPL" in output


class TestTrackerSaveRecommendations:
    """From test_coverage_round16.py."""

    def test_save_empty(self, rich_db):
        from nuri.trading.recommend.tracker import save_recommendations
        count = save_recommendations(candidates=None, actions=None, db_path=rich_db)
        assert count == 0

    def test_save_candidates_with_regime_fit(self, rich_db):
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations
        candidates = [
            Candidate("AAPL", "rsi_oversold", "2025-03-20", "BUY", 75.0, 0.6, 2.0, True, 170.0, "test"),
            Candidate("NVDA", "bb_bounce", "2025-03-20", "BUY", 65.0, 0.55, 1.5, False, 120.0, "skip"),
        ]
        count = save_recommendations(candidates=candidates, db_path=rich_db)
        assert count == 1

    def test_save_with_verdicts(self, rich_db):
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations
        candidates = [
            Candidate("AAPL", "rsi_oversold", "2025-03-20", "BUY", 75.0, 0.6, 2.0, True, 170.0, "test"),
        ]
        verdicts = {"AAPL": [{"agent_name": "technical", "action": "BUY", "confidence": 80, "reasoning": "RSI oversold"}]}
        count = save_recommendations(candidates=candidates, verdicts=verdicts, db_path=rich_db)
        assert count == 1

    def test_save_actions_with_price_lookup(self, rich_db):
        from nuri.trading.recommend.tracker import save_recommendations
        action = MagicMock()
        action.ticker = "AAPL"
        action.action = "BUY"
        action.signals = ["rsi_oversold"]
        action.regime_note = "bull_low_vol"
        count = save_recommendations(actions=[action], db_path=rich_db)
        assert count == 1

    def test_save_action_duplicate_merge(self, rich_db):
        """When candidate and action have same ticker+action, signals should merge."""
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations
        candidate = Candidate("AAPL", "rsi_oversold", "2025-03-20", "BUY", 75.0, 0.6, 2.0, True, 170.0, "")
        action = MagicMock()
        action.ticker = "AAPL"
        action.action = "BUY"
        action.signals = ["bb_bounce"]
        action.regime_note = "bull"
        count = save_recommendations(candidates=[candidate], actions=[action], db_path=rich_db)
        assert count == 1


class TestTrackerTrackOutcomes:
    """From test_coverage_round16.py."""

    def test_90d_tracking(self, rich_db):
        from nuri.trading.recommend.tracker import track_outcomes

        rec_date = (datetime.now() - timedelta(days=95)).strftime("%Y-%m-%d")
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rec_date, "AAPL", "BUY", 75.0, "bull", "[]", 170.0))
        updated = track_outcomes(db_path=rich_db)
        assert updated >= 1

    def test_sell_hit_quality(self, rich_db):
        """SELL action with negative return should have hit=True and hit_quality > 0."""
        from nuri.trading.recommend.tracker import track_outcomes

        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        target_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rec_date, "TSLA", "SELL", 60.0, "bear", "[]", 250.0))
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("TSLA", target_date, 200, 205, 195, 200, 1000000))

        updated = track_outcomes(db_path=rich_db)
        assert updated >= 1


class TestTrackerReport:
    """From test_coverage_round16.py."""

    def test_report_empty(self, rich_db):
        from nuri.trading.recommend.tracker import get_tracking_report
        report = get_tracking_report(db_path=rich_db)
        assert report["total_recommendations"] == 0
        assert report["hit_rate"] == 0

    def test_print_report_no_tracked(self, rich_db, capsys):
        from nuri.trading.recommend.tracker import print_tracking_report
        print_tracking_report(db_path=rich_db)
        out = capsys.readouterr().out
        assert "Recommendation Tracking Report" in out

    def test_print_report_with_tracked(self, rich_db, capsys):
        from nuri.trading.recommend.tracker import print_tracking_report

        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price, outcome_30d, hit) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("2025-01-01", "AAPL", "BUY", 80, "bull", "[]", 170.0, 12.5, 1))
        print_tracking_report(db_path=rich_db)
        out = capsys.readouterr().out
        assert "Hit rate" in out or "hit" in out.lower()


class TestTracker_R23:
    """From test_coverage_round23.py."""

    def test_save_recommendations_with_actions(self, db_path):
        """Save rebalance actions."""
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class MockAction:
            ticker: str
            action: str
            signals: list
            regime_note: str

        _seed_prices_r23(db_path, "AAPL", 170.0)

        actions = [
            MockAction("AAPL", "BUY", ["sig1"], "[bull] 비중 확대"),
            MockAction("MSFT", "HOLD", [], "[bull]"),
        ]

        verdicts = {
            "AAPL": [{"agent_name": "technical", "action": "BUY", "confidence": 70, "reasoning": "test"}],
        }

        n = save_recommendations(actions=actions, verdicts=verdicts, db_path=db_path)
        assert n == 1

    def test_save_recommendations_with_candidates(self, db_path):
        """Save candidates."""
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class MockCandidate:
            ticker: str = "NVDA"
            direction: str = "BUY"
            confidence: float = 75.0
            signal_id: str = "rsi_oversold"
            price: float = 850.0
            regime_fit: bool = True
            scoring_detail: dict = None

        n = save_recommendations(candidates=[MockCandidate()], db_path=db_path)
        assert n == 1

    def test_save_empty(self, db_path):
        """No records to save returns 0."""
        from nuri.trading.recommend.tracker import save_recommendations

        n = save_recommendations(db_path=db_path)
        assert n == 0

    def test_save_with_scoring_detail(self, db_path):
        """Save with scoring_detail attached."""
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class MockCandidate:
            ticker: str = "TSLA"
            direction: str = "BUY"
            confidence: float = 60.0
            signal_id: str = "macd_golden"
            price: float = 200.0
            regime_fit: bool = True
            scoring_detail: dict = None

            def __post_init__(self):
                self.scoring_detail = {"base": 50, "drift": 1.0}

        n = save_recommendations(candidates=[MockCandidate()], db_path=db_path)
        assert n == 1

    def test_print_tracking_report(self, db_path, capsys):
        """Print tracking report."""
        from nuri.trading.recommend.tracker import print_tracking_report

        print_tracking_report(db_path=db_path)
        captured = capsys.readouterr()
        assert "Recommendation Tracking Report" in captured.out

    def test_print_tracking_report_with_data(self, db_path, capsys):
        """Print report with tracked data."""
        from nuri.trading.recommend.tracker import print_tracking_report

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price, outcome_30d, hit) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("2026-01-01", "AAPL", "BUY", 70, "bull", '["sig1"]', 150.0, 8.5, 1),
            )

        print_tracking_report(db_path=db_path)
        captured = capsys.readouterr()
        assert "BUY" in captured.out

    def test_save_merge_existing(self, db_path):
        """Merge signals when same ticker+action exists."""
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class MockCandidate:
            ticker: str = "AAPL"
            direction: str = "BUY"
            confidence: float = 70.0
            signal_id: str = "rsi_oversold"
            price: float = 170.0
            regime_fit: bool = True
            scoring_detail: dict = None

        @dataclass
        class MockAction:
            ticker: str = "AAPL"
            action: str = "BUY"
            signals: list = None
            regime_note: str = "[bull]"

            def __post_init__(self):
                self.signals = ["macd_golden"]

        _seed_prices_r23(db_path, "AAPL", 170.0)
        n = save_recommendations(
            candidates=[MockCandidate()],
            actions=[MockAction()],
            db_path=db_path,
        )
        assert n == 1

    def test_tracker_track_outcomes(self, db_path):
        """Track outcomes for old recommendations."""
        from nuri.trading.recommend.tracker import track_outcomes

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2025-12-01", "AAPL", "BUY", 70, "bull", '["sig"]', 150.0),
            )
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)", ("AAPL", "2025-12-31", 160.0))
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)", ("AAPL", "2026-01-30", 165.0))
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)", ("AAPL", "2026-03-01", 170.0))

        updated = track_outcomes(db_path=db_path)
        assert updated >= 1

    def test_tracker_track_sell_outcome(self, db_path):
        """Track outcomes for SELL recommendations."""
        from nuri.trading.recommend.tracker import track_outcomes

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2025-12-01", "AAPL", "SELL", 70, "bear", '["sig"]', 150.0),
            )
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)", ("AAPL", "2025-12-31", 140.0))
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)", ("AAPL", "2026-01-30", 135.0))
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)", ("AAPL", "2026-03-01", 130.0))

        updated = track_outcomes(db_path=db_path)
        assert updated >= 1


class TestTracker_R27:
    """From test_coverage_round27.py."""

    def test_save_recommendations_empty(self, db_path):
        """save_recommendations with no candidates/actions returns 0."""
        from nuri.trading.recommend.tracker import save_recommendations
        assert save_recommendations(db_path=db_path) == 0

    def test_save_recommendations_with_candidates(self, db_path, monkeypatch):
        """save_recommendations with candidate data."""
        from nuri.trading.recommend.tracker import save_recommendations

        class MockCandidate:
            ticker = "AAPL"
            direction = "BUY"
            confidence = 75
            signal_id = "rsi_oversold"
            regime_fit = True
            price = 150
            scoring_detail = {"test": 1}

        n = save_recommendations(candidates=[MockCandidate()], db_path=db_path)
        assert n == 1

    def test_track_outcomes(self, db_path, monkeypatch):
        """track_outcomes updates 30d outcomes."""
        from nuri.core.timezone import kst_now
        from nuri.trading.recommend.tracker import track_outcomes

        rec_date = (kst_now().replace(tzinfo=None) - timedelta(days=35)).strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
                "VALUES (?,?,?,?,?,?,?)",
                (rec_date, "AAPL", "BUY", 70, "bull", '["rsi_oversold"]', 150),
            )
            target_date = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?,?,?)",
                ("AAPL", target_date, 160),
            )
        updated = track_outcomes(db_path=db_path)
        assert updated >= 1

    def test_get_tracking_report(self, db_path):
        """get_tracking_report returns report structure."""
        from nuri.trading.recommend.tracker import get_tracking_report
        report = get_tracking_report(db_path=db_path)
        assert "total_recommendations" in report
        assert "hit_rate" in report

    def test_print_tracking_report(self, db_path, capsys):
        """print_tracking_report outputs data."""
        from nuri.trading.recommend.tracker import print_tracking_report
        print_tracking_report(db_path=db_path)
        captured = capsys.readouterr()
        assert "Recommendation" in captured.out

    def test_serialize_verdicts(self):
        """_serialize_verdicts converts ConsensusResult verdicts."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.recommend.tracker import _serialize_verdicts

        class MockResult:
            ticker = "AAPL"
            verdicts = [AgentVerdict("technical", "AAPL", "BUY", 70, "RSI ok")]

        result = _serialize_verdicts([MockResult()])
        assert "AAPL" in result
        assert result["AAPL"][0]["agent_name"] == "technical"


class TestHitCalculation:
    """From test_feedback_loop.py — hit 판정 기준."""

    def test_buy_hit_meaningful_gain(self, db_path):
        """BUY + 8% 수익 -> hit=True (5% 이상)."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "GOOD", "BUY", 100.0)
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{"ticker": "GOOD", "date": d30, "open": 107, "high": 110, "low": 106, "close": 108.0, "volume": 1000000, "adj_close": 108.0}])
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)
        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == 8.0
        assert rows[0]["hit"] == 1
        assert rows[0]["hit_quality"] == 0.4

    def test_buy_small_gain_not_hit(self, db_path):
        """BUY + 3% 수익 -> hit=False (5% 미만)."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "MEH", "BUY", 100.0)
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{"ticker": "MEH", "date": d30, "open": 102, "high": 104, "low": 101, "close": 103.0, "volume": 1000000, "adj_close": 103.0}])
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)
        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == 3.0
        assert rows[0]["hit"] == 0
        assert rows[0]["hit_quality"] == 0.15

    def test_buy_loss_not_hit(self, db_path):
        """BUY + 가격 하락 -> hit=False, hit_quality=0."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "LOSS", "BUY", 100.0)
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{"ticker": "LOSS", "date": d30, "open": 94, "high": 96, "low": 93, "close": 95.0, "volume": 1000000, "adj_close": 95.0}])
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)
        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == -5.0
        assert rows[0]["hit"] == 0
        assert rows[0]["hit_quality"] == 0.0

    def test_sell_meaningful_decline_hit(self, db_path):
        """SELL + 가격 -5% 하락 -> hit=True (-2% 이하)."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "DROP", "SELL", 100.0)
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{"ticker": "DROP", "date": d30, "open": 96, "high": 97, "low": 94, "close": 95.0, "volume": 1000000, "adj_close": 95.0}])
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)
        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == -5.0
        assert rows[0]["hit"] == 1
        assert rows[0]["hit_quality"] == 0.5

    def test_sell_small_decline_not_hit(self, db_path):
        """SELL + 가격 -1% 하락 -> hit=False."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "FLAT", "SELL", 100.0)
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{"ticker": "FLAT", "date": d30, "open": 99.5, "high": 100, "low": 98.5, "close": 99.0, "volume": 1000000, "adj_close": 99.0}])
        upsert_prices(prices, db_path)
        from nuri.trading.recommend.tracker import track_outcomes
        track_outcomes(db_path=db_path)
        rows = query("SELECT outcome_30d, hit, hit_quality FROM recommendations", db_path=db_path)
        assert rows[0]["outcome_30d"] == -1.0
        assert rows[0]["hit"] == 0
        assert rows[0]["hit_quality"] == 0.1

    def test_sell_price_up_not_hit(self, db_path):
        """SELL + 가격 상승 -> hit=False, hit_quality=0."""
        rec_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        _seed_recommendation(db_path, rec_date, "UP", "SELL", 100.0)
        d30 = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        prices = pd.DataFrame([{"ticker": "UP", "date": d30, "open": 104, "high": 106, "low": 103, "close": 105.0, "volume": 1000000, "adj_close": 105.0}])
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


class TestAgentVerdicts:
    """From test_feedback_loop.py."""

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
        """ConsensusResult -> verdict dict 변환."""
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
        assert len(verdicts_map["AAPL"][1]["reasoning"]) == 100


class TestScoringDetail:
    """From test_feedback_loop.py."""

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


# ═══════════════════════════════════════════════════════════════════════════════
# PRICE_TARGETS — nuri.trading.recommend.price_targets
# ═══════════════════════════════════════════════════════════════════════════════


class TestClassifyStockType:
    """From test_new_modules.py."""

    def test_growth_by_pe(self, db_path):
        """PE > 30이면 성장주로 분류."""
        _seed_portfolio_nm(db_path)
        _seed_fundamentals_nm(db_path, [("2026-03-27", "TSLA", 327.0)])
        from nuri.trading.recommend.price_targets import classify_stock_type
        result = classify_stock_type("TSLA", db_path=db_path)
        assert result == "growth"

    def test_growth_by_sector(self, db_path):
        """섹터가 성장 섹터이면 PE 없어도 성장주."""
        _seed_portfolio_nm(db_path, [("test", "XYZ", 10, 100.0, "USD", "AI/Cloud")])
        from nuri.trading.recommend.price_targets import classify_stock_type
        result = classify_stock_type("XYZ", db_path=db_path)
        assert result == "growth"

    def test_value_by_low_pe(self, db_path):
        """PE < 30이고 비성장 섹터면 가치주."""
        _seed_portfolio_nm(db_path, [("test", "GOOGL", 5, 270.0, "USD", "BigTech")])
        _seed_fundamentals_nm(db_path, [("2026-03-27", "GOOGL", 22.0)])
        from nuri.trading.recommend.price_targets import classify_stock_type
        result = classify_stock_type("GOOGL", db_path=db_path)
        assert result == "value"

    def test_value_when_no_data(self, db_path):
        """데이터 없으면 기본 가치주."""
        from nuri.trading.recommend.price_targets import classify_stock_type
        result = classify_stock_type("UNKNOWN", db_path=db_path)
        assert result == "value"


class TestCalculateTargets:
    """From test_new_modules.py."""

    def test_growth_targets(self, db_path):
        """성장주 타겟: -7% 손절, +20%/+40% 익절."""
        _seed_portfolio_nm(db_path)
        _seed_prices_nm(db_path)
        _seed_fundamentals_nm(db_path)
        from nuri.trading.recommend.price_targets import calculate_targets
        result = calculate_targets("TSLA", entry_price=360.0, stock_type="growth", db_path=db_path)
        assert result["stock_type"] == "growth"
        assert result["stop_loss"] == pytest.approx(360.0 * 0.93, rel=0.01)
        assert result["target_1"] == pytest.approx(360.0 * 1.20, rel=0.01)
        assert result["target_2"] == pytest.approx(360.0 * 1.40, rel=0.01)
        assert result["target_1_sell_pct"] == 50
        assert result["target_2_sell_pct"] == 25
        assert result["trailing_stop_pct"] == -15

    def test_value_targets(self, db_path):
        """가치주 타겟: -10% 손절, +15%/+30% 익절."""
        _seed_portfolio_nm(db_path)
        _seed_prices_nm(db_path)
        from nuri.trading.recommend.price_targets import calculate_targets
        result = calculate_targets("GOOGL", entry_price=270.0, stock_type="value", db_path=db_path)
        assert result["stock_type"] == "value"
        assert result["stop_loss"] == pytest.approx(270.0 * 0.90, rel=0.01)
        assert result["target_1"] == pytest.approx(270.0 * 1.15, rel=0.01)
        assert result["target_2"] == pytest.approx(270.0 * 1.30, rel=0.01)

    def test_swing_targets(self, db_path):
        """스윙 타겟: -7% 손절, +5%/+10% 익절."""
        _seed_prices_nm(db_path)
        from nuri.trading.recommend.price_targets import calculate_targets
        result = calculate_targets("NVDA", entry_price=168.0, stock_type="swing", db_path=db_path)
        assert result["stock_type"] == "swing"
        assert result["target_1"] == pytest.approx(168.0 * 1.05, rel=0.01)
        assert result["target_2"] == pytest.approx(168.0 * 1.10, rel=0.01)

    def test_analyst_target_included(self, db_path):
        """애널리스트 목표가가 있으면 포함."""
        _seed_prices_nm(db_path)
        _seed_estimates_nm(db_path)
        from nuri.trading.recommend.price_targets import calculate_targets
        result = calculate_targets("NVDA", entry_price=168.0, stock_type="growth", db_path=db_path)
        assert result["analyst_target"] == pytest.approx(273.61, rel=0.01)
        assert result["analyst_upside_pct"] is not None
        assert result["analyst_upside_pct"] > 0

    def test_no_price_returns_error(self, db_path):
        """가격 데이터 없으면 에러 반환."""
        from nuri.trading.recommend.price_targets import calculate_targets
        result = calculate_targets("NOPRICE", db_path=db_path)
        assert "error" in result

    def test_uses_current_price_when_no_entry(self, db_path):
        """entry_price 미지정 시 현재가 사용."""
        _seed_prices_nm(db_path)
        from nuri.trading.recommend.price_targets import calculate_targets
        result = calculate_targets("TSLA", stock_type="growth", db_path=db_path)
        assert result["entry_price"] == result["current_price"]


class TestPortfolioTargets:
    """From test_new_modules.py."""

    def test_all_holdings_have_targets(self, db_path):
        """모든 보유 종목에 대해 타겟 생성."""
        _seed_portfolio_nm(db_path)
        _seed_prices_nm(db_path)
        _seed_fundamentals_nm(db_path)
        from nuri.trading.recommend.price_targets import calculate_portfolio_targets
        targets = calculate_portfolio_targets(db_path=db_path)
        assert len(targets) > 0
        tickers = {t["ticker"] for t in targets if "error" not in t}
        assert "TSLA" in tickers
        assert "NVDA" in tickers

    def test_empty_portfolio(self, db_path):
        """빈 포트폴리오면 빈 리스트."""
        from nuri.trading.recommend.price_targets import calculate_portfolio_targets
        targets = calculate_portfolio_targets(db_path=db_path)
        assert targets == []


class TestFormatTargetTree:
    """From test_new_modules.py."""

    def test_usd_format(self):
        """USD 종목 포맷."""
        from nuri.trading.recommend.price_targets import format_target_tree
        target = {
            "ticker": "NVDA", "stock_type": "growth",
            "current_price": 168.0, "entry_price": 165.0,
            "stop_loss": 153.45, "stop_loss_pct": -7.0,
            "target_1": 198.0, "target_1_pct": 20.0, "target_1_sell_pct": 50,
            "target_2": 231.0, "target_2_pct": 40.0, "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": 273.61, "analyst_upside_pct": 63.4,
        }
        output = format_target_tree(target)
        assert "NVDA" in output
        assert "성장주" in output
        assert "$168.00" in output
        assert "손절가" in output
        assert "1차 익절" in output
        assert "50% 매도" in output

    def test_krw_format(self):
        """KRW 종목 포맷."""
        from nuri.trading.recommend.price_targets import format_target_tree
        target = {
            "ticker": "005930.KS", "stock_type": "growth",
            "current_price": 179700.0, "entry_price": 55000.0,
            "stop_loss": 55521.0, "stop_loss_pct": -7.0,
            "target_1": 71640.0, "target_1_pct": 20.0, "target_1_sell_pct": 50,
            "target_2": 83580.0, "target_2_pct": 40.0, "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": None, "analyst_upside_pct": None,
        }
        output = format_target_tree(target)
        assert "005930.KS" in output
        assert "₩" in output


class TestPriceTargets_R9:
    """From test_coverage_round9.py."""

    def test_calculate_targets(self, rich_db):
        from nuri.trading.recommend.price_targets import calculate_portfolio_targets
        results = calculate_portfolio_targets()
        assert isinstance(results, list)

    def test_check_take_profit(self, rich_db):
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        signals = check_take_profit_signals()
        assert isinstance(signals, list)

    def test_check_trailing_stop(self, rich_db):
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals
        signals = check_trailing_stop_signals()
        assert isinstance(signals, list)


class TestPriceTargets_R20:
    """From test_coverage_round20.py."""

    def test_calculate_targets_growth(self, rich_db_full, monkeypatch):
        """NVDA has PE=55 (>30), should be classified as growth."""
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)
        result = pt.calculate_targets("NVDA", entry_price=250.0, db_path=rich_db_full)
        assert "error" not in result
        assert result["stock_type"] == "growth"
        assert result["stop_loss_pct"] == -7
        assert result["target_1_pct"] == 20
        assert result["target_2_pct"] == 40
        assert result["stop_loss"] == round(250 * 0.93, 2)
        assert result["target_1"] == round(250 * 1.20, 2)
        assert result["analyst_target"] == 270.0

    def test_calculate_targets_value(self, rich_db_full, monkeypatch):
        """AAPL has PE=28 (<30), should be classified as value."""
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)
        result = pt.calculate_targets("AAPL", entry_price=200.0, db_path=rich_db_full)
        assert "error" not in result
        assert result["stock_type"] == "value"
        assert result["stop_loss_pct"] == -10
        assert result["target_1_pct"] == 15
        assert result["target_2_pct"] == 30

    def test_calculate_targets_no_price(self, rich_db_full, monkeypatch):
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)
        result = pt.calculate_targets("ZZZZ", db_path=rich_db_full)
        assert "error" in result

    def test_calculate_targets_uses_current_price_as_entry(self, rich_db_full, monkeypatch):
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)
        result = pt.calculate_targets("AAPL", db_path=rich_db_full)
        assert "error" not in result
        assert result["entry_price"] == result["current_price"]

    def test_classify_stock_type_manual_override(self, rich_db_full, monkeypatch):
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", {"AAPL": "swing"})
        assert pt.classify_stock_type("AAPL", db_path=rich_db_full) == "swing"

    def test_classify_stock_type_sector_growth(self, rich_db_full, monkeypatch):
        """Portfolio sector 'Semiconductor' should match GROWTH_SECTORS."""
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", {})
        with get_db(rich_db_full) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "QCOM", 10, 100.0, "USD", "Semiconductor"),
            )
        result = pt.classify_stock_type("QCOM", db_path=rich_db_full)
        assert result == "growth"


class TestPortfolioTargets_R20:
    """From test_coverage_round20.py."""

    def test_calculate_portfolio_targets(self, rich_db_full, monkeypatch):
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)
        targets = pt.calculate_portfolio_targets(db_path=rich_db_full)
        assert len(targets) >= 2
        tickers = [t["ticker"] for t in targets]
        assert "AAPL" in tickers
        assert "NVDA" in tickers


class TestTakeProfitSignals:
    """From test_coverage_round20.py."""

    def test_check_take_profit_signals_triggered(self, rich_db_full, monkeypatch):
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)
        signals = pt.check_take_profit_signals(db_path=rich_db_full)
        assert isinstance(signals, list)
        if signals:
            sig = signals[0]
            assert "level" in sig
            assert sig["level"] in ("target_1", "target_2")
            assert sig["sell_pct"] > 0

    def test_check_take_profit_no_holdings(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        result = check_take_profit_signals(db_path=path)
        assert result == []


class TestTrailingStopSignals:
    """From test_coverage_round20.py."""

    def test_check_trailing_stop_no_trigger(self, rich_db_full, monkeypatch):
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)
        signals = pt.check_trailing_stop_signals(db_path=rich_db_full)
        assert isinstance(signals, list)

    def test_check_trailing_stop_no_holdings(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals
        result = check_trailing_stop_signals(db_path=path)
        assert result == []


class TestPortfolioMDD:
    """From test_coverage_round20.py."""

    def test_check_portfolio_mdd_no_violation(self, rich_db_full, monkeypatch):
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)
        result = pt.check_portfolio_mdd(db_path=rich_db_full)
        assert result is None

    def test_check_portfolio_mdd_violation(self, tmp_path, monkeypatch):
        import nuri.trading.recommend.price_targets as pt
        monkeypatch.setattr(pt, "_stock_types_cache", None)

        path = tmp_path / "mdd.db"
        init_db(path)
        upsert_portfolio([
            {"account": "test", "ticker": "LOSS", "quantity": 100,
             "avg_price": 200.0, "currency": "USD", "sector": "Tech"},
        ], path)
        rows = [{"ticker": "LOSS", "date": "2025-01-01",
                 "open": 170, "high": 172, "low": 168,
                 "close": 170, "volume": 100000, "adj_close": 170}]
        upsert_prices(pd.DataFrame(rows), path)

        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        result = pt.check_portfolio_mdd(db_path=path)
        assert result is not None
        assert result["severity"] == "critical"
        assert result["pnl_pct"] < -10

    def test_check_portfolio_mdd_empty(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.trading.recommend.price_targets import check_portfolio_mdd
        result = check_portfolio_mdd(db_path=path)
        assert result is None


class TestFormatTargetTree_R20:
    """From test_coverage_round20.py."""

    def test_format_target_tree_growth(self):
        from nuri.trading.recommend.price_targets import format_target_tree
        target = {
            "ticker": "NVDA", "stock_type": "growth",
            "current_price": 250.0, "entry_price": 200.0,
            "stop_loss": 186.0, "stop_loss_pct": -7.0,
            "target_1": 240.0, "target_1_pct": 20.0, "target_1_sell_pct": 50,
            "target_2": 280.0, "target_2_pct": 40.0, "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": 270.0, "analyst_upside_pct": 35.0,
        }
        result = format_target_tree(target)
        assert "NVDA" in result
        assert "성장주" in result
        assert "손절가" in result
        assert "1차 익절" in result
        assert "애널리스트 목표가" in result

    def test_format_target_tree_error(self):
        from nuri.trading.recommend.price_targets import format_target_tree
        result = format_target_tree({"ticker": "BAD", "error": "no data"})
        assert "BAD" in result
        assert "no data" in result

    def test_format_target_tree_no_analyst(self):
        from nuri.trading.recommend.price_targets import format_target_tree
        target = {
            "ticker": "TEST", "stock_type": "value",
            "current_price": 100.0, "entry_price": 100.0,
            "stop_loss": 90.0, "stop_loss_pct": -10.0,
            "target_1": 115.0, "target_1_pct": 15.0, "target_1_sell_pct": 50,
            "target_2": 130.0, "target_2_pct": 30.0, "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": None, "analyst_upside_pct": None,
        }
        result = format_target_tree(target)
        assert "TEST" in result
        assert "가치주" in result
        assert "└──" in result

    def test_format_price_krw(self):
        from nuri.trading.recommend.price_targets import _format_price
        result = _format_price(70000, "005930.KS")
        assert "₩" in result

    def test_format_price_usd(self):
        from nuri.trading.recommend.price_targets import _format_price
        result = _format_price(150.50, "AAPL")
        assert "$" in result


class TestPriceTargets_R23:
    """From test_coverage_round23.py."""

    def test_classify_stock_type_growth_pe(self, db_path):
        """PE > 30 -> growth."""
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import classify_stock_type
        pt_mod._stock_types_cache = None
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO fundamentals (ticker, date, pe_ratio) VALUES (?, ?, ?)",
                         ("NEWCO", "2026-03-31", 50.0))
        result = classify_stock_type("NEWCO", db_path=db_path)
        assert result == "growth"

    def test_classify_stock_type_sector_growth(self, db_path):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import classify_stock_type
        pt_mod._stock_types_cache = None
        _seed_portfolio_r23(db_path, [("test", "SEMCO", 10, 100.0, "USD", "Semiconductor")])
        result = classify_stock_type("SEMCO", db_path=db_path)
        assert result == "growth"

    def test_classify_stock_type_value(self, db_path):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import classify_stock_type
        pt_mod._stock_types_cache = None
        result = classify_stock_type("UNKNOWN", db_path=db_path)
        assert result == "value"

    def test_calculate_targets_no_price(self, db_path):
        from nuri.trading.recommend.price_targets import calculate_targets
        result = calculate_targets("NOPRICE", db_path=db_path)
        assert "error" in result

    def test_calculate_targets_swing(self, db_path):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import calculate_targets
        pt_mod._stock_types_cache = None
        _seed_prices_r23(db_path, "SWING", 100.0)
        result = calculate_targets("SWING", entry_price=100.0, stock_type="swing", db_path=db_path)
        assert result["stock_type"] == "swing"
        assert result["trailing_stop_pct"] == -20

    def test_calculate_targets_value(self, db_path):
        from nuri.trading.recommend.price_targets import calculate_targets
        _seed_prices_r23(db_path, "VALUE", 100.0)
        result = calculate_targets("VALUE", entry_price=100.0, stock_type="value", db_path=db_path)
        assert result["stock_type"] == "value"
        assert result["stop_loss_pct"] == -10

    def test_calculate_targets_with_analyst(self, db_path):
        from nuri.trading.recommend.price_targets import calculate_targets
        _seed_prices_r23(db_path, "AAPL", 170.0)
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO estimates (ticker, date, target_mean) VALUES (?, ?, ?)",
                         ("AAPL", "2026-03-31", 220.0))
        result = calculate_targets("AAPL", db_path=db_path)
        assert result["analyst_target"] == 220.0
        assert result["analyst_upside_pct"] is not None

    def test_print_portfolio_targets_empty(self, capsys):
        from nuri.trading.recommend.price_targets import print_portfolio_targets
        print_portfolio_targets([])
        captured = capsys.readouterr()
        assert "종목 없음" in captured.out

    def test_print_portfolio_targets(self, capsys, db_path):
        from nuri.trading.recommend.price_targets import print_portfolio_targets
        targets = [
            {"ticker": "AAPL", "stock_type": "growth", "current_price": 170.0, "entry_price": 150.0,
             "stop_loss": 139.5, "stop_loss_pct": -7.0, "target_1": 180.0, "target_1_pct": 20.0,
             "target_1_sell_pct": 50, "target_2": 210.0, "target_2_pct": 40.0, "target_2_sell_pct": 25,
             "trailing_stop_pct": -15.0, "analyst_target": 220.0, "analyst_upside_pct": 29.4},
            {"ticker": "MSFT", "stock_type": "value", "current_price": 400.0, "entry_price": 380.0,
             "stop_loss": 342.0, "stop_loss_pct": -10.0, "target_1": 437.0, "target_1_pct": 15.0,
             "target_1_sell_pct": 50, "target_2": 494.0, "target_2_pct": 30.0, "target_2_sell_pct": 25,
             "trailing_stop_pct": -15.0, "analyst_target": None, "analyst_upside_pct": None},
        ]
        print_portfolio_targets(targets)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out
        assert "MSFT" in captured.out
        assert "포트폴리오 가격 목표" in captured.out

    def test_check_take_profit_target2(self, db_path):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        pt_mod._stock_types_cache = None
        _seed_portfolio_r23(db_path, [("test", "AAPL", 10, 100.0, "USD", "Technology")])
        _seed_prices_r23(db_path, "AAPL", 145.0)
        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) >= 1
        assert signals[0]["level"] == "target_2"

    def test_check_take_profit_target1(self, db_path):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        pt_mod._stock_types_cache = None
        _seed_portfolio_r23(db_path, [("test", "AAPL", 10, 100.0, "USD", "Technology")])
        _seed_prices_r23(db_path, "AAPL", 122.0)
        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) >= 1
        assert signals[0]["level"] == "target_1"

    def test_check_take_profit_no_entry(self, db_path):
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        _seed_portfolio_r23(db_path, [("test", "AAPL", 10, 0, "USD", "Technology")])
        _seed_prices_r23(db_path, "AAPL", 200.0)
        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) == 0

    def test_check_trailing_stop(self, db_path):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals
        pt_mod._stock_types_cache = None
        _seed_portfolio_r23(db_path, [("test", "AAPL", 10, 100.0, "USD", "Technology")])
        with get_db(db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         ("AAPL", "2026-03-01", 195, 200, 190, 195, 1000000))
            conn.execute("INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         ("AAPL", "2026-03-31", 162, 165, 158, 160, 1000000))
        signals = check_trailing_stop_signals(db_path=db_path)
        assert len(signals) >= 1
        assert signals[0]["status"] == "TRIGGERED"

    def test_check_trailing_stop_not_triggered(self, db_path):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals
        pt_mod._stock_types_cache = None
        _seed_portfolio_r23(db_path, [("test", "AAPL", 10, 100.0, "USD", "Technology")])
        _seed_prices_r23(db_path, "AAPL", 180.0, high=185.0)
        signals = check_trailing_stop_signals(db_path=db_path)
        assert len(signals) == 0

    def test_check_portfolio_mdd_no_violation(self, db_path):
        from nuri.trading.recommend.price_targets import check_portfolio_mdd
        _seed_portfolio_r23(db_path, [("test", "AAPL", 10, 150.0, "USD", "Technology")])
        _seed_prices_r23(db_path, "AAPL", 155.0)
        result = check_portfolio_mdd(db_path=db_path)
        assert result is None

    def test_check_portfolio_mdd_violation(self, db_path):
        from nuri.trading.recommend.price_targets import check_portfolio_mdd
        _seed_portfolio_r23(db_path, [("test", "AAPL", 100, 200.0, "USD", "Technology")])
        _seed_prices_r23(db_path, "AAPL", 170.0)
        result = check_portfolio_mdd(db_path=db_path)
        assert result is not None
        assert result["severity"] == "critical"

    def test_check_portfolio_mdd_with_krw(self, db_path):
        from nuri.trading.recommend.price_targets import check_portfolio_mdd
        _seed_portfolio_r23(db_path, [("test", "005930.KS", 10, 70000.0, "KRW", "Semiconductor")])
        _seed_prices_r23(db_path, "005930.KS", 72000.0, high=73000.0)
        _seed_macro_r23(db_path, "usd_krw", 1350.0)
        result = check_portfolio_mdd(db_path=db_path)
        assert result is None

    def test_check_portfolio_mdd_empty(self, db_path):
        from nuri.trading.recommend.price_targets import check_portfolio_mdd
        result = check_portfolio_mdd(db_path=db_path)
        assert result is None

    def test_format_target_tree_error(self):
        from nuri.trading.recommend.price_targets import format_target_tree
        result = format_target_tree({"ticker": "AAPL", "error": "no data"})
        assert "AAPL" in result
        assert "no data" in result

    def test_format_target_tree_no_analyst(self):
        from nuri.trading.recommend.price_targets import format_target_tree
        target = {
            "ticker": "AAPL", "stock_type": "growth", "current_price": 170.0, "entry_price": 150.0,
            "stop_loss": 139.5, "stop_loss_pct": -7.0, "target_1": 180.0, "target_1_pct": 20.0,
            "target_1_sell_pct": 50, "target_2": 210.0, "target_2_pct": 40.0, "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0, "analyst_target": None, "analyst_upside_pct": None,
        }
        result = format_target_tree(target)
        assert "└──" in result

    def test_format_price_krw(self):
        from nuri.trading.recommend.price_targets import _format_price
        assert "₩" in _format_price(70000, "005930.KS")
        assert "$" in _format_price(170.0, "AAPL")

    def test_calculate_portfolio_targets_empty(self, db_path):
        from nuri.trading.recommend.price_targets import calculate_portfolio_targets
        result = calculate_portfolio_targets(db_path=db_path)
        assert result == []

    def test_calculate_portfolio_targets(self, db_path):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import calculate_portfolio_targets
        pt_mod._stock_types_cache = None
        _seed_portfolio_r23(db_path, [("test", "AAPL", 10, 150.0, "USD", "Technology")])
        _seed_prices_r23(db_path, "AAPL", 170.0)
        targets = calculate_portfolio_targets(db_path=db_path)
        assert len(targets) >= 1
        assert targets[0]["ticker"] == "AAPL"

    def test_calculate_portfolio_targets_skip_no_price(self, db_path):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import calculate_portfolio_targets
        pt_mod._stock_types_cache = None
        _seed_portfolio_r23(db_path, [
            ("test", "AAPL", 10, 150.0, "USD", "Technology"),
            ("test", "NOPRICE", 5, 100.0, "USD", "Tech"),
        ])
        _seed_prices_r23(db_path, "AAPL", 170.0)
        targets = calculate_portfolio_targets(db_path=db_path)
        tickers = [t["ticker"] for t in targets]
        assert "AAPL" in tickers
        assert "NOPRICE" not in tickers


class TestPriceTargets_R27:
    """From test_coverage_round27.py."""

    def test_classify_stock_type_manual(self, monkeypatch):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import classify_stock_type
        monkeypatch.setattr(pt_mod, "_stock_types_cache", {"TSLA": "growth"})
        assert classify_stock_type("TSLA") == "growth"

    def test_classify_stock_type_high_pe(self, db_path, monkeypatch):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import classify_stock_type
        monkeypatch.setattr(pt_mod, "_stock_types_cache", {})
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO fundamentals (ticker, date, pe_ratio) VALUES (?,?,?)",
                         ("TEST", "2025-03-28", 50.0))
        assert classify_stock_type("TEST", db_path=db_path) == "growth"

    def test_classify_stock_type_value_default(self, db_path, monkeypatch):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import classify_stock_type
        monkeypatch.setattr(pt_mod, "_stock_types_cache", {})
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO fundamentals (ticker, date, pe_ratio) VALUES (?,?,?)",
                         ("TEST", "2025-03-28", 12.0))
        assert classify_stock_type("TEST", db_path=db_path) == "value"

    def test_calculate_targets_no_price(self, db_path):
        from nuri.trading.recommend.price_targets import calculate_targets
        result = calculate_targets("NOPRICE", db_path=db_path)
        assert "error" in result

    def test_calculate_targets_swing(self, db_path, monkeypatch):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import calculate_targets
        monkeypatch.setattr(pt_mod, "_stock_types_cache", {"TEST": "swing"})
        with get_db(db_path) as conn:
            dates = pd.bdate_range(end="2025-03-28", periods=5)
            for i, d in enumerate(dates):
                price = 100 + np.sin(i / 10) * 10
                conn.execute("INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                             ("TEST", d.strftime("%Y-%m-%d"), price - 1, price + 2, price - 2, price, 500000 + i * 10000))
        result = calculate_targets("TEST", stock_type="swing", db_path=db_path)
        assert result["stock_type"] == "swing"
        assert result["trailing_stop_pct"] == -20

    def test_format_target_tree_error(self):
        from nuri.trading.recommend.price_targets import format_target_tree
        result = format_target_tree({"ticker": "TEST", "error": "no data"})
        assert "TEST" in result
        assert "no data" in result

    def test_format_target_tree_kr_ticker(self):
        from nuri.trading.recommend.price_targets import format_target_tree
        target = {
            "ticker": "005930.KS", "stock_type": "value",
            "current_price": 70000, "entry_price": 68000,
            "stop_loss": 61200, "stop_loss_pct": -10.0,
            "target_1": 78200, "target_1_pct": 15.0, "target_1_sell_pct": 50,
            "target_2": 88400, "target_2_pct": 30.0, "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": None, "analyst_upside_pct": None,
        }
        result = format_target_tree(target)
        assert "₩" in result
        assert "└──" in result

    def test_format_target_tree_with_analyst(self):
        from nuri.trading.recommend.price_targets import format_target_tree
        target = {
            "ticker": "AAPL", "stock_type": "growth",
            "current_price": 200, "entry_price": 195,
            "stop_loss": 181.35, "stop_loss_pct": -7.0,
            "target_1": 234, "target_1_pct": 20.0, "target_1_sell_pct": 50,
            "target_2": 273, "target_2_pct": 40.0, "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": 250, "analyst_upside_pct": 28.2,
        }
        result = format_target_tree(target)
        assert "애널리스트" in result
        assert "$" in result

    def test_check_take_profit_signals(self, db_path, monkeypatch):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        monkeypatch.setattr(pt_mod, "_stock_types_cache", {"AAPL": "growth"})
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO portfolio (account, ticker, quantity, avg_price, sector, currency) VALUES (?,?,?,?,?,?)",
                         ("test", "AAPL", 10, 100.0, "Technology", "USD"))
            conn.execute("INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                         ("AAPL", "2025-03-28", 124, 126, 123, 125, 500000))
        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) >= 1
        assert signals[0]["level"] == "target_1"

    def test_check_trailing_stop_signals(self, db_path, monkeypatch):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals
        monkeypatch.setattr(pt_mod, "_stock_types_cache", {"AAPL": "growth"})
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO portfolio (account, ticker, quantity, avg_price, sector, currency) VALUES (?,?,?,?,?,?)",
                         ("test", "AAPL", 10, 100.0, "Technology", "USD"))
            conn.execute("INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                         ("AAPL", "2025-03-20", 195, 200, 190, 198, 500000))
            conn.execute("INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                         ("AAPL", "2025-03-28", 162, 165, 158, 160, 500000))
        signals = check_trailing_stop_signals(db_path=db_path)
        assert len(signals) >= 1

    def test_check_portfolio_mdd_no_violation(self, db_path):
        from nuri.trading.recommend.price_targets import check_portfolio_mdd
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO portfolio (account, ticker, quantity, avg_price, sector, currency) VALUES (?,?,?,?,?,?)",
                         ("test", "AAPL", 10, 100.0, "Technology", "USD"))
        with get_db(db_path) as conn:
            dates = pd.bdate_range(end="2025-03-28", periods=5)
            for i, d in enumerate(dates):
                conn.execute("INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                             ("AAPL", d.strftime("%Y-%m-%d"), 109, 112, 108, 110, 500000))
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)", ("usd_krw", "2025-03-28", 1400.0))
        result = check_portfolio_mdd(db_path=db_path)
        assert result is None

    def test_print_portfolio_targets_empty(self, capsys):
        from nuri.trading.recommend.price_targets import print_portfolio_targets
        print_portfolio_targets([])
        captured = capsys.readouterr()
        assert "가격 목표 대상 종목 없음" in captured.out


# ═══════════════════════════════════════════════════════════════════════════════
# CONFLICTS using Candidate — nuri.trading.engine.conflicts (uses recommend.candidates.Candidate)
# ═══════════════════════════════════════════════════════════════════════════════


class TestConflictsWithCandidate:
    """From test_engine.py / test_trading_engine_all.py — uses Candidate from recommend."""

    def test_direction_conflict_detected(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate

        candidates = [
            Candidate("TSLA", "bb_bounce", "2025-03-25", "BUY", 65, 0.59, 2.0, True, 380.0, ""),
            Candidate("TSLA", "macd_dead", "2025-03-24", "SELL", 55, 0.70, 1.4, True, 380.0, ""),
        ]
        conflicts = detect_conflicts(candidates)
        assert len(conflicts) >= 1
        tsla_conflict = [c for c in conflicts if c.ticker == "TSLA" and c.conflict_type == "direction_conflict"]
        assert len(tsla_conflict) == 1
        assert tsla_conflict[0].severity == "high"

    def test_no_conflict_single_direction(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate

        candidates = [
            Candidate("NVDA", "bb_bounce", "2025-03-25", "BUY", 65, 0.59, 2.0, True, 100.0, ""),
            Candidate("NVDA", "rsi_oversold", "2025-03-24", "BUY", 60, 0.53, 1.8, True, 100.0, ""),
        ]
        conflicts = detect_conflicts(candidates)
        direction = [c for c in conflicts if c.conflict_type == "direction_conflict"]
        assert len(direction) == 0

    def test_empty_candidates(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        assert detect_conflicts([]) == []


class TestConflictsStrengthMismatch:
    """From test_coverage_round16.py / test_trading_engine_all.py."""

    def test_strength_mismatch_detected(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate
        candidates = [
            Candidate("AAPL", "rsi_oversold", "2025-03-25", "BUY", 70, 0.60, 5.0, True, 170, ""),
            Candidate("AAPL", "gap_up", "2025-03-25", "BUY", 40, 0.40, 1.2, False, 170, ""),
        ]
        conflicts = detect_conflicts(candidates)
        strength = [c for c in conflicts if c.conflict_type == "strength_mismatch"]
        assert len(strength) == 1
        assert "강한 시그널" in strength[0].detail

    def test_no_strength_mismatch_when_similar(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate
        candidates = [
            Candidate("AAPL", "rsi_oversold", "2025-03-25", "BUY", 70, 0.60, 2.0, True, 170, ""),
            Candidate("AAPL", "bb_bounce", "2025-03-25", "BUY", 65, 0.55, 1.8, True, 170, ""),
        ]
        conflicts = detect_conflicts(candidates)
        strength = [c for c in conflicts if c.conflict_type == "strength_mismatch"]
        assert len(strength) == 0


class TestConflictsRegimeContradiction:
    """From test_coverage_round16.py / test_trading_engine_all.py."""

    def test_buy_in_bear_market(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate
        candidates = [
            Candidate("TSLA", "bb_bounce", "2025-03-25", "BUY", 55, 0.50, 1.5, False, 200, ""),
        ]
        mock_regime = MagicMock()
        mock_regime.trend = "bear"
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            conflicts = detect_conflicts(candidates)
        regime_c = [c for c in conflicts if c.conflict_type == "regime_contradiction"]
        assert len(regime_c) == 1
        assert "하락장" in regime_c[0].detail

    def test_sell_in_bull_market(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate
        candidates = [
            Candidate("TSLA", "macd_dead", "2025-03-25", "SELL", 55, 0.50, 1.5, False, 200, ""),
        ]
        mock_regime = MagicMock()
        mock_regime.trend = "bull"
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            conflicts = detect_conflicts(candidates)
        regime_c = [c for c in conflicts if c.conflict_type == "regime_contradiction"]
        assert len(regime_c) == 1
        assert "상승장" in regime_c[0].detail

    def test_regime_fit_buy_in_bear_skipped(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate
        candidates = [
            Candidate("TSLA", "bb_bounce", "2025-03-25", "BUY", 55, 0.50, 1.5, True, 200, ""),
        ]
        mock_regime = MagicMock()
        mock_regime.trend = "bear"
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            conflicts = detect_conflicts(candidates)
        regime_c = [c for c in conflicts if c.conflict_type == "regime_contradiction"]
        assert len(regime_c) == 0

    def test_classify_regime_exception_no_crash(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate
        candidates = [
            Candidate("TSLA", "bb_bounce", "2025-03-25", "BUY", 55, 0.50, 1.5, False, 200, ""),
        ]
        with patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("fail")):
            conflicts = detect_conflicts(candidates)
        regime_c = [c for c in conflicts if c.conflict_type == "regime_contradiction"]
        assert len(regime_c) == 0


class TestConflictsMediumSeverity:
    """From test_coverage_round16.py / test_trading_engine_all.py."""

    def test_medium_severity_direction_conflict(self):
        from nuri.trading.engine.conflicts import detect_conflicts
        from nuri.trading.recommend.candidates import Candidate
        candidates = [
            Candidate("NVDA", "rsi_oversold", "2025-03-25", "BUY", 60, 0.55, 2.0, True, 100, ""),
            Candidate("NVDA", "macd_dead", "2025-03-24", "SELL", 50, 0.45, 1.3, False, 100, ""),
        ]
        conflicts = detect_conflicts(candidates)
        dc = [c for c in conflicts if c.conflict_type == "direction_conflict"]
        assert len(dc) == 1
        assert dc[0].severity == "medium"
        assert "레짐 적합 시그널" in dc[0].recommendation
