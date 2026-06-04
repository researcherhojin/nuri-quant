"""Tests for price_targets — split from test_trading_recommend_all.py."""

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
from tests.trading.recommend._helpers import (  # noqa: F401
    _seed_estimates_nm,
    _seed_fundamentals_nm,
    _seed_macro_r23,
    _seed_portfolio_nm,
    _seed_portfolio_r23,
    _seed_prices_nm,
    _seed_prices_r23,
    _seed_recommendation,
)


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
            "ticker": "NVDA",
            "stock_type": "growth",
            "current_price": 168.0,
            "entry_price": 165.0,
            "stop_loss": 153.45,
            "stop_loss_pct": -7.0,
            "target_1": 198.0,
            "target_1_pct": 20.0,
            "target_1_sell_pct": 50,
            "target_2": 231.0,
            "target_2_pct": 40.0,
            "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": 273.61,
            "analyst_upside_pct": 63.4,
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
            "ticker": "005930.KS",
            "stock_type": "growth",
            "current_price": 179700.0,
            "entry_price": 55000.0,
            "stop_loss": 55521.0,
            "stop_loss_pct": -7.0,
            "target_1": 71640.0,
            "target_1_pct": 20.0,
            "target_1_sell_pct": 50,
            "target_2": 83580.0,
            "target_2_pct": 40.0,
            "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": None,
            "analyst_upside_pct": None,
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
        upsert_portfolio(
            [
                {
                    "account": "test",
                    "ticker": "LOSS",
                    "quantity": 100,
                    "avg_price": 200.0,
                    "currency": "USD",
                    "sector": "Tech",
                },
            ],
            path,
        )
        rows = [
            {
                "ticker": "LOSS",
                "date": "2025-01-01",
                "open": 170,
                "high": 172,
                "low": 168,
                "close": 170,
                "volume": 100000,
                "adj_close": 170,
            }
        ]
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
            "ticker": "NVDA",
            "stock_type": "growth",
            "current_price": 250.0,
            "entry_price": 200.0,
            "stop_loss": 186.0,
            "stop_loss_pct": -7.0,
            "target_1": 240.0,
            "target_1_pct": 20.0,
            "target_1_sell_pct": 50,
            "target_2": 280.0,
            "target_2_pct": 40.0,
            "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": 270.0,
            "analyst_upside_pct": 35.0,
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
            "ticker": "TEST",
            "stock_type": "value",
            "current_price": 100.0,
            "entry_price": 100.0,
            "stop_loss": 90.0,
            "stop_loss_pct": -10.0,
            "target_1": 115.0,
            "target_1_pct": 15.0,
            "target_1_sell_pct": 50,
            "target_2": 130.0,
            "target_2_pct": 30.0,
            "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": None,
            "analyst_upside_pct": None,
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
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio) VALUES (?, ?, ?)", ("NEWCO", "2026-03-31", 50.0)
            )
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
            conn.execute(
                "INSERT INTO estimates (ticker, date, target_mean) VALUES (?, ?, ?)", ("AAPL", "2026-03-31", 220.0)
            )
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
            {
                "ticker": "AAPL",
                "stock_type": "growth",
                "current_price": 170.0,
                "entry_price": 150.0,
                "stop_loss": 139.5,
                "stop_loss_pct": -7.0,
                "target_1": 180.0,
                "target_1_pct": 20.0,
                "target_1_sell_pct": 50,
                "target_2": 210.0,
                "target_2_pct": 40.0,
                "target_2_sell_pct": 25,
                "trailing_stop_pct": -15.0,
                "analyst_target": 220.0,
                "analyst_upside_pct": 29.4,
            },
            {
                "ticker": "MSFT",
                "stock_type": "value",
                "current_price": 400.0,
                "entry_price": 380.0,
                "stop_loss": 342.0,
                "stop_loss_pct": -10.0,
                "target_1": 437.0,
                "target_1_pct": 15.0,
                "target_1_sell_pct": 50,
                "target_2": 494.0,
                "target_2_pct": 30.0,
                "target_2_sell_pct": 25,
                "trailing_stop_pct": -15.0,
                "analyst_target": None,
                "analyst_upside_pct": None,
            },
        ]
        print_portfolio_targets(targets)
        captured = capsys.readouterr()
        assert "AAPL" in captured.out
        assert "MSFT" in captured.out
        assert "포트폴리오 가격 목표" in captured.out

    def test_check_take_profit_target2(self, db_path, monkeypatch):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_take_profit_signals

        pt_mod._stock_types_cache = None
        # leader off -> 고정 ladder 경로 검증 (성장주여도 target_2 발화)
        monkeypatch.setattr(pt_mod, "TAKE_PROFIT_LEADER", {"enabled": False, "trail_ma": 50})
        _seed_portfolio_r23(db_path, [("test", "AAPL", 10, 100.0, "USD", "Technology")])
        _seed_prices_r23(db_path, "AAPL", 145.0)
        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) >= 1
        assert signals[0]["level"] == "target_2"

    def test_check_take_profit_target1(self, db_path):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_take_profit_signals

        pt_mod._stock_types_cache = None
        # 가치주(Technology=비성장) +17% -> 비리더 -> 고정 TP1(+15%) 유지
        _seed_portfolio_r23(db_path, [("test", "AAPL", 10, 100.0, "USD", "Technology")])
        _seed_prices_r23(db_path, "AAPL", 117.0)
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
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-03-01", 195, 200, 190, 195, 1000000),
            )
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-03-31", 162, 165, 158, 160, 1000000),
            )
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
            "ticker": "AAPL",
            "stock_type": "growth",
            "current_price": 170.0,
            "entry_price": 150.0,
            "stop_loss": 139.5,
            "stop_loss_pct": -7.0,
            "target_1": 180.0,
            "target_1_pct": 20.0,
            "target_1_sell_pct": 50,
            "target_2": 210.0,
            "target_2_pct": 40.0,
            "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": None,
            "analyst_upside_pct": None,
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
        _seed_portfolio_r23(
            db_path,
            [
                ("test", "AAPL", 10, 150.0, "USD", "Technology"),
                ("test", "NOPRICE", 5, 100.0, "USD", "Tech"),
            ],
        )
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
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio) VALUES (?,?,?)", ("TEST", "2025-03-28", 50.0)
            )
        assert classify_stock_type("TEST", db_path=db_path) == "growth"

    def test_classify_stock_type_value_default(self, db_path, monkeypatch):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import classify_stock_type

        monkeypatch.setattr(pt_mod, "_stock_types_cache", {})
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio) VALUES (?,?,?)", ("TEST", "2025-03-28", 12.0)
            )
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
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                    ("TEST", d.strftime("%Y-%m-%d"), price - 1, price + 2, price - 2, price, 500000 + i * 10000),
                )
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
            "ticker": "005930.KS",
            "stock_type": "value",
            "current_price": 70000,
            "entry_price": 68000,
            "stop_loss": 61200,
            "stop_loss_pct": -10.0,
            "target_1": 78200,
            "target_1_pct": 15.0,
            "target_1_sell_pct": 50,
            "target_2": 88400,
            "target_2_pct": 30.0,
            "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": None,
            "analyst_upside_pct": None,
        }
        result = format_target_tree(target)
        assert "₩" in result
        assert "└──" in result

    def test_format_target_tree_with_analyst(self):
        from nuri.trading.recommend.price_targets import format_target_tree

        target = {
            "ticker": "AAPL",
            "stock_type": "growth",
            "current_price": 200,
            "entry_price": 195,
            "stop_loss": 181.35,
            "stop_loss_pct": -7.0,
            "target_1": 234,
            "target_1_pct": 20.0,
            "target_1_sell_pct": 50,
            "target_2": 273,
            "target_2_pct": 40.0,
            "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": 250,
            "analyst_upside_pct": 28.2,
        }
        result = format_target_tree(target)
        assert "애널리스트" in result
        assert "$" in result

    def test_check_take_profit_signals(self, db_path, monkeypatch):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_take_profit_signals

        monkeypatch.setattr(pt_mod, "_stock_types_cache", {"AAPL": "growth"})
        # 성장주 강제 -> leader off 해야 고정 TP1 검증 (on이면 리더로 skip)
        monkeypatch.setattr(pt_mod, "TAKE_PROFIT_LEADER", {"enabled": False, "trail_ma": 50})
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector, currency) VALUES (?,?,?,?,?,?)",
                ("test", "AAPL", 10, 100.0, "Technology", "USD"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                ("AAPL", "2025-03-28", 124, 126, 123, 125, 500000),
            )
        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) >= 1
        assert signals[0]["level"] == "target_1"

    def test_check_trailing_stop_signals(self, db_path, monkeypatch):
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals

        monkeypatch.setattr(pt_mod, "_stock_types_cache", {"AAPL": "growth"})
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector, currency) VALUES (?,?,?,?,?,?)",
                ("test", "AAPL", 10, 100.0, "Technology", "USD"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                ("AAPL", "2025-03-20", 195, 200, 190, 198, 500000),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                ("AAPL", "2025-03-28", 162, 165, 158, 160, 500000),
            )
        signals = check_trailing_stop_signals(db_path=db_path)
        assert len(signals) >= 1

    def test_trailing_stop_hwm_since_entry_not_all_time(self, db_path, monkeypatch):
        """Gotcha-Test: 트레일링 HWM 은 진입 이후(first_buy_date) 최고가만 집계해야 한다.

        진입 전 역대 최고가가 HWM 으로 잡히면 트레일링 스톱이 거짓 발동한다.
        price_targets.py HWM 쿼리에서 `date >= entry_anchor` 필터를 제거(revert)하면
        HWM=300(진입 전 꼭지) → -38% → 거짓 발동 → 이 테스트가 실패한다.
        """
        import nuri.trading.recommend.price_targets as pt_mod
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals

        monkeypatch.setattr(pt_mod, "_stock_types_cache", {"ZETA": "growth"})
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector, currency, first_buy_date) "
                "VALUES (?,?,?,?,?,?,?)",
                ("test", "ZETA", 10, 190.0, "Technology", "USD", "2025-03-01"),
            )
            # 진입 전(2025-03-01 이전) 역대 최고가 = 300 (트랩: 날짜 필터 없으면 HWM 으로 잡힘)
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                ("ZETA", "2025-01-01", 290, 300, 285, 295, 500000),
            )
            # 진입 이후 실제 고점 = 200
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                ("ZETA", "2025-03-05", 195, 200, 192, 198, 500000),
            )
            # 현재가 184 → 진입후 HWM(200) 대비 -8% → 트레일 -15% 미달, 발동 안 함
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                ("ZETA", "2025-03-28", 186, 188, 183, 184, 500000),
            )
        signals = check_trailing_stop_signals(db_path=db_path)
        assert signals == []

    def test_check_portfolio_mdd_no_violation(self, db_path):
        from nuri.trading.recommend.price_targets import check_portfolio_mdd

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector, currency) VALUES (?,?,?,?,?,?)",
                ("test", "AAPL", 10, 100.0, "Technology", "USD"),
            )
        with get_db(db_path) as conn:
            dates = pd.bdate_range(end="2025-03-28", periods=5)
            for i, d in enumerate(dates):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                    ("AAPL", d.strftime("%Y-%m-%d"), 109, 112, 108, 110, 500000),
                )
        with get_db(db_path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES (?,?,?)", ("usd_krw", "2025-03-28", 1400.0))
        result = check_portfolio_mdd(db_path=db_path)
        assert result is None

    def test_print_portfolio_targets_empty(self, capsys):
        from nuri.trading.recommend.price_targets import print_portfolio_targets

        print_portfolio_targets([])
        captured = capsys.readouterr()
        assert "가격 목표 대상 종목 없음" in captured.out
