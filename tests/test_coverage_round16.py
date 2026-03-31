"""Coverage round 16 — memory, monitor, mean_reversion, rebalance_advisor, performance, tracker, broker, conflicts."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    """Full DB with portfolio, prices (SPY + tickers), macro."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 170, "currency": "USD", "sector": "Technology"},
        {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 120, "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "TSLA", "quantity": 8, "avg_price": 250, "currency": "USD", "sector": "EV/AI"},
    ], path)

    dates = pd.bdate_range("2024-06-01", periods=300, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA", "TSLA", "VOO"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120, "TSLA": 200, "VOO": 440}[t]
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


# ═══════════════════════════════════════════════════════
# 1. Memory — _compute_stats, _find_latest_csv, print_memory_status
# ═══════════════════════════════════════════════════════


class TestMemoryComputeStats:
    """Cover _compute_stats with various return distributions."""

    def test_all_positive_returns(self):
        from nuri.trading.engine.memory import _compute_stats
        df = pd.DataFrame({"return_pct": [5.0, 10.0, 3.0]})
        stats = _compute_stats(df)
        assert stats["trades"] == 3
        assert stats["win_rate"] == 1.0
        assert stats["profit_factor"] == 99.99  # no losses -> inf capped

    def test_all_negative_returns(self):
        from nuri.trading.engine.memory import _compute_stats
        df = pd.DataFrame({"return_pct": [-5.0, -10.0, -3.0]})
        stats = _compute_stats(df)
        assert stats["win_rate"] == 0.0
        assert stats["avg_return"] < 0

    def test_mixed_returns(self):
        from nuri.trading.engine.memory import _compute_stats
        df = pd.DataFrame({"return_pct": [10.0, -5.0, 3.0, -2.0]})
        stats = _compute_stats(df)
        assert stats["trades"] == 4
        assert stats["win_rate"] == 0.5
        assert stats["profit_factor"] > 0


class TestMemoryFindCsv:
    """Cover _find_latest_csv for missing dirs and files."""

    def test_nonexistent_dir(self, monkeypatch):
        from nuri.trading.engine import memory as mem_mod
        monkeypatch.setattr(mem_mod, "REPORT_DIR", MagicMock(exists=MagicMock(return_value=False)))
        assert mem_mod._find_latest_csv("signal_results.csv") is None

    def test_dir_exists_no_csv(self, tmp_path, monkeypatch):
        from nuri.trading.engine import memory as mem_mod
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        (report_dir / "2025-01-01").mkdir()
        monkeypatch.setattr(mem_mod, "REPORT_DIR", report_dir)
        assert mem_mod._find_latest_csv("signal_results.csv") is None

    def test_dir_exists_with_csv(self, tmp_path, monkeypatch):
        from nuri.trading.engine import memory as mem_mod
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        day_dir = report_dir / "2025-03-20"
        day_dir.mkdir()
        csv_file = day_dir / "signal_results.csv"
        csv_file.write_text("signal_id,return_pct\nrsi_oversold,5.0")
        monkeypatch.setattr(mem_mod, "REPORT_DIR", report_dir)
        result = mem_mod._find_latest_csv("signal_results.csv")
        assert result is not None
        assert result.name == "signal_results.csv"


class TestMemoryPrintStatus:
    """Cover print_memory_status branches."""

    def test_empty_drifts(self, capsys):
        from nuri.trading.engine.memory import print_memory_status
        print_memory_status([])
        out = capsys.readouterr().out
        assert "학습 메모리 없음" in out

    def test_with_drifts(self, capsys):
        from nuri.trading.engine.memory import PerformanceDrift, print_memory_status
        drifts = [
            PerformanceDrift("rsi_oversold", None, 0.60, 0.30, -50.0, "critical", "승률 급락"),
            PerformanceDrift("macd_golden", None, 0.55, 0.65, 18.2, "improving", "승률 개선"),
            PerformanceDrift("bb_bounce", None, 0.50, 0.48, -4.0, "stable", "안정"),
        ]
        print_memory_status(drifts)
        out = capsys.readouterr().out
        assert "Signal" in out
        assert "rsi_oversold" in out
        assert "성과 하락 시그널 1개" in out  # only critical counted


class TestMemorySaveSnapshotEmptyCsv:
    """Cover save_snapshot when CSV found but empty."""

    def test_empty_csv(self, rich_db, tmp_path, monkeypatch):
        from nuri.trading.engine import memory as mem_mod
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        day_dir = report_dir / "2026-01-01"
        day_dir.mkdir()
        (day_dir / "signal_results.csv").write_text("signal_id,return_pct,entry_date\n")
        monkeypatch.setattr(mem_mod, "REPORT_DIR", report_dir)
        count = mem_mod.save_snapshot(db_path=rich_db)
        assert count == 0


class TestMemoryDetectDriftMultipleStatuses:
    """Cover all 4 drift statuses: critical, degrading, improving, stable."""

    def test_four_statuses(self, rich_db):
        from nuri.trading.engine.memory import detect_drift

        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(rich_db) as conn:
            # critical: 60% -> 30%  => -50% drift
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_critical", None, "all_time", 100, 0.60, 2.0, 3.5))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_critical", None, "recent_90d", 20, 0.30, 0.8, -1.0))
            # degrading: 60% -> 48%  => -20% drift
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_degrading", None, "all_time", 100, 0.60, 2.0, 3.0))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_degrading", None, "recent_90d", 20, 0.48, 1.2, 1.0))
            # improving: 50% -> 60%  => +20% drift
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_improving", None, "all_time", 100, 0.50, 1.5, 2.0))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_improving", None, "recent_90d", 20, 0.60, 2.5, 4.0))
            # stable: 55% -> 53%  => ~-3.6% drift
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_stable", None, "all_time", 100, 0.55, 1.7, 2.5))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_stable", None, "recent_90d", 20, 0.53, 1.6, 2.3))

        drifts = detect_drift(db_path=rich_db)
        statuses = {d.signal_id: d.status for d in drifts}
        assert statuses["sig_critical"] == "critical"
        assert statuses["sig_degrading"] == "degrading"
        assert statuses["sig_improving"] == "improving"
        assert statuses["sig_stable"] == "stable"
        # sorted by severity
        assert drifts[0].status == "critical"
        assert drifts[-1].status == "stable"


# ═══════════════════════════════════════════════════════
# 2. Monitor — daily_pnl_summary, detect_regime_transition
# ═══════════════════════════════════════════════════════


class TestMonitorDailyPnl:
    """Cover daily_pnl_summary with open positions."""

    def test_empty_positions(self, rich_db):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        with patch("nuri.trading.strategy.position.update_prices"):
            result = daily_pnl_summary(db_path=rich_db)
        assert result["total_positions"] == 0
        assert result["total_pnl"] == 0
        assert result["best"] is None
        assert result["worst"] is None

    def test_with_open_positions(self, rich_db):
        from nuri.trading.strategy.monitor import daily_pnl_summary
        # insert open positions
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, quantity, current_price, return_pct, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("core", "AAPL", "long", "2025-01-01", 170.0, 10, 200.0, 17.6, "open"))
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, quantity, current_price, return_pct, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("tactical", "NVDA", "short", "2025-01-01", 120.0, 5, 110.0, 8.3, "open"))
            conn.execute(
                "INSERT INTO positions (portfolio_type, ticker, direction, entry_date, entry_price, quantity, current_price, return_pct, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("core", "TSLA", "long", "2025-01-01", 250.0, 3, 230.0, -8.0, "open"))

        with patch("nuri.trading.strategy.position.update_prices"):
            result = daily_pnl_summary(db_path=rich_db)
        assert result["total_positions"] == 3
        assert result["winners"] == 2
        assert result["losers"] == 1
        assert result["best"]["ticker"] == "AAPL"
        assert result["worst"]["ticker"] == "TSLA"


class TestMonitorRegimeTransition:
    """Cover detect_regime_transition branches."""

    def test_classify_regime_fails(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        with patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("fail")):
            result = detect_regime_transition(db_path=rich_db)
        assert result is None

    def test_classify_returns_none(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=None):
            result = detect_regime_transition(db_path=rich_db)
        assert result is None

    def test_no_transition_same_regime(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        mock_regime = MagicMock()
        mock_regime.regime = "bull_low_vol"
        mock_regime.confidence = 0.85
        mock_regime.trend = "bull"
        # insert previous regime transition
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime) VALUES (?, ?, ?)",
                ("2025-03-01", "bear_high_vol", "bull_low_vol"))
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            result = detect_regime_transition(db_path=rich_db)
        assert result is None

    def test_transition_bull_to_bear(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        mock_regime = MagicMock()
        mock_regime.regime = "bear_high_vol"
        mock_regime.confidence = 0.80
        mock_regime.trend = "bear"
        # insert previous transition as bull
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime) VALUES (?, ?, ?)",
                ("2025-03-01", "sideways_low_vol", "bull_low_vol"))
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            result = detect_regime_transition(db_path=rich_db)
        assert result is not None
        assert result["urgency"] == "high"
        assert "BULL" in result["switch"] and "BEAR" in result["switch"]

    def test_transition_to_sideways(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        mock_regime = MagicMock()
        mock_regime.regime = "sideways_low_vol"
        mock_regime.confidence = 0.70
        mock_regime.trend = "sideways"
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime) VALUES (?, ?, ?)",
                ("2025-03-01", "unknown", "bull_low_vol"))
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            result = detect_regime_transition(db_path=rich_db)
        assert result is not None
        assert result["urgency"] == "medium"

    def test_first_regime_no_previous(self, rich_db):
        from nuri.trading.strategy.monitor import detect_regime_transition
        mock_regime = MagicMock()
        mock_regime.regime = "bull_low_vol"
        mock_regime.confidence = 0.90
        mock_regime.trend = "bull"
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            result = detect_regime_transition(db_path=rich_db)
        assert result is not None
        assert result["urgency"] == "low"
        assert "초기 레짐" in result["switch"]

    def test_volatility_change_transition(self, rich_db):
        """Same trend direction but different volatility -> low urgency."""
        from nuri.trading.strategy.monitor import detect_regime_transition
        mock_regime = MagicMock()
        mock_regime.regime = "bull_high_vol"
        mock_regime.confidence = 0.75
        mock_regime.trend = "bull"
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO regime_transitions (date, from_regime, to_regime) VALUES (?, ?, ?)",
                ("2025-03-01", "bear_high_vol", "bull_low_vol"))
        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            result = detect_regime_transition(db_path=rich_db)
        assert result is not None
        assert result["urgency"] == "low"
        assert "변동성 변화" in result["switch"]


# ═══════════════════════════════════════════════════════
# 3. Mean Reversion — scan + backtest
# ═══════════════════════════════════════════════════════


class TestMeanReversionScan:
    """Cover scan_mean_reversion code paths."""

    def _make_oversold_db(self, tmp_path, monkeypatch):
        """Create DB with oversold price pattern (drops below BB lower + RSI < 30)."""
        import nuri.core.db as db_mod
        path = tmp_path / "mr.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        upsert_portfolio([{"account": "t", "ticker": "DROP", "quantity": 1, "avg_price": 100, "currency": "USD", "sector": "Tech"}], path)

        dates = pd.bdate_range("2024-01-01", periods=60, freq="B")
        close_vals = list(np.linspace(100, 102, 40)) + list(np.linspace(102, 80, 20))
        rows = []
        for i, d in enumerate(dates):
            c = close_vals[i]
            rows.append({"ticker": "DROP", "date": d.strftime("%Y-%m-%d"),
                         "open": c, "high": c + 1, "low": c - 1, "close": c,
                         "volume": 1_000_000, "adj_close": c})
        upsert_prices(pd.DataFrame(rows), path)
        return path

    def test_scan_few_data_points(self, rich_db):
        """Tickers with < 30 data points are skipped."""
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        # rich_db has 300 data points per ticker, so no skip
        signals = scan_mean_reversion(db_path=rich_db)
        assert isinstance(signals, list)

    def test_scan_returns_sorted_by_zscore(self, tmp_path, monkeypatch):
        from nuri.trading.strategy.mean_reversion import scan_mean_reversion
        path = self._make_oversold_db(tmp_path, monkeypatch)
        signals = scan_mean_reversion(lookback=20, db_path=path)
        if len(signals) >= 2:
            assert signals[0].z_score <= signals[1].z_score


class TestMeanReversionBacktest:
    """Cover backtest_mean_reversion."""

    def test_no_trades(self, tmp_path, monkeypatch):
        """Backtest with flat prices -> no entry signals."""
        import nuri.core.db as db_mod
        path = tmp_path / "flat.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        upsert_portfolio([{"account": "t", "ticker": "FLAT", "quantity": 1, "avg_price": 100, "currency": "USD", "sector": "Tech"}], path)
        dates = pd.bdate_range("2024-01-01", periods=80, freq="B")
        rows = [{"ticker": "FLAT", "date": d.strftime("%Y-%m-%d"),
                 "open": 100, "high": 101, "low": 99, "close": 100,
                 "volume": 1_000_000, "adj_close": 100} for d in dates]
        upsert_prices(pd.DataFrame(rows), path)

        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion
        result = backtest_mean_reversion(db_path=path)
        assert result["total_trades"] == 0

    def test_backtest_with_rich_data(self, rich_db):
        from nuri.trading.strategy.mean_reversion import backtest_mean_reversion
        result = backtest_mean_reversion(db_path=rich_db)
        assert "total_trades" in result
        if result["total_trades"] > 0:
            assert "win_rate" in result
            assert "avg_hold_days" in result


# ═══════════════════════════════════════════════════════
# 4. Rebalance Advisor — _severity, print_rebalance_advisor
# ═══════════════════════════════════════════════════════


class TestRebalanceSeverity:
    """Cover all _severity branches."""

    def test_leverage_etf(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("leverage_etf", 0, 0) == "critical"

    def test_stop_loss_critical(self):
        from nuri.analysis.rebalance_advisor import _severity
        # current_value <= limit_value * 2 => critical (both negative)
        assert _severity("stop_loss_exceeded", -15, -7) == "critical"

    def test_stop_loss_high(self):
        from nuri.analysis.rebalance_advisor import _severity
        # current_value > limit_value * 2 (less negative) => high
        assert _severity("stop_loss_exceeded", -8, -7) == "high"

    def test_position_limit_high(self):
        from nuri.analysis.rebalance_advisor import _severity
        # excess > 10pp => high  (current_value is weight in %, limit is fraction)
        assert _severity("position_limit_exceeded", 30, 0.15) == "high"

    def test_position_limit_medium(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("position_limit_exceeded", 18, 0.15) == "medium"

    def test_sector_limit_high(self):
        from nuri.analysis.rebalance_advisor import _severity
        # excess = 50/100 - 0.35 = 0.15 > 0.10 => high
        assert _severity("sector_limit_exceeded", 50, 0.35) == "high"

    def test_sector_limit_medium(self):
        from nuri.analysis.rebalance_advisor import _severity
        # excess = 40/100 - 0.35 = 0.05 <= 0.10 => medium
        assert _severity("sector_limit_exceeded", 40, 0.35) == "medium"

    def test_unknown_type(self):
        from nuri.analysis.rebalance_advisor import _severity
        assert _severity("some_new_type", 0, 0) == "medium"


class TestRebalancePrint:
    """Cover print_rebalance_advisor output."""

    def test_no_actions(self, capsys):
        from nuri.analysis.rebalance_advisor import print_rebalance_advisor
        print_rebalance_advisor([])
        out = capsys.readouterr().out
        assert "위반 사항 없음" in out

    def test_with_actions(self, capsys):
        from nuri.analysis.rebalance_advisor import print_rebalance_advisor
        actions = [
            {"ticker": "TQQQ", "sell_shares": 100, "sell_value_usd": 5000, "reason": "레버리지 ETF",
             "action": "SELL_ALL", "severity": "critical", "cumulative_recovery_usd": 5000},
            {"ticker": "AAPL", "sell_shares": 5, "sell_value_usd": 1000, "reason": "비중 초과",
             "action": "REDUCE", "severity": "high", "cumulative_recovery_usd": 6000},
        ]
        print_rebalance_advisor(actions)
        out = capsys.readouterr().out
        assert "SELL TQQQ" in out
        assert "[!!]" in out  # critical marker
        assert "총 회수" in out


class TestRebalanceGetFactorScores:
    """Cover _get_factor_scores."""

    def test_empty(self, rich_db):
        from nuri.analysis.rebalance_advisor import _get_factor_scores
        scores = _get_factor_scores(db_path=rich_db)
        assert scores == {}  # no factors table data

    def test_with_data(self, rich_db):
        from nuri.analysis.rebalance_advisor import _get_factor_scores
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO factors (ticker, date, composite_score) VALUES (?, ?, ?)",
                ("AAPL", "2025-03-20", 0.85))
        scores = _get_factor_scores(db_path=rich_db)
        assert scores["AAPL"] == 0.85


class TestRebalanceGenerateReport:
    """Cover generate_advisor_report empty path."""

    def test_no_violations(self, rich_db):
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        with patch("nuri.analysis.rebalance_advisor.detect_violations", return_value=[]):
            report = generate_advisor_report(db_path=rich_db)
        assert report["total_violations"] == 0
        assert report["has_critical"] is False

    def test_with_violations(self, rich_db):
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        fake_violations = [
            {"ticker": "TQQQ", "violation_type": "leverage_etf", "priority": 1,
             "current_value": -5, "limit_value": 0, "severity": "critical",
             "action": "SELL_ALL", "sell_shares": 50, "sell_value_usd": 3000, "reason": "test"},
        ]
        with patch("nuri.analysis.rebalance_advisor.detect_violations", return_value=fake_violations):
            report = generate_advisor_report(db_path=rich_db)
        assert report["total_violations"] == 1
        assert report["has_critical"] is True
        assert report["violations_by_type"]["leverage_etf"] == 1


# ═══════════════════════════════════════════════════════
# 5. Performance — get_portfolio_returns, get_benchmark_returns, print_performance
# ═══════════════════════════════════════════════════════


class TestPerformanceReturns:
    """Cover performance analysis functions."""

    def test_empty_portfolio(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert returns.empty

    def test_portfolio_returns_with_data(self, rich_db):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns()
        assert not returns.empty
        assert returns.name == "Nuri-Quant Portfolio"

    def test_benchmark_returns(self, rich_db):
        from nuri.analysis.performance import get_benchmark_returns
        returns = get_benchmark_returns()
        assert not returns.empty
        assert returns.name == "VOO"

    def test_benchmark_returns_no_voo(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        path = tmp_path / "novoo.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        from nuri.analysis.performance import get_benchmark_returns
        returns = get_benchmark_returns()
        assert returns.empty


class TestPerformancePrint:
    """Cover print_performance output."""

    def test_empty_returns(self, capsys):
        from nuri.analysis.performance import print_performance
        print_performance(pd.Series(dtype=float), pd.Series(dtype=float))
        out = capsys.readouterr().out
        assert "성과 데이터가 없습니다" in out

    def test_with_returns(self, capsys, rich_db):
        from nuri.analysis.performance import get_benchmark_returns, get_portfolio_returns, print_performance
        port = get_portfolio_returns()
        bench = get_benchmark_returns()
        print_performance(port, bench)
        out = capsys.readouterr().out
        assert "Sharpe" in out
        assert "Alpha" in out


# ═══════════════════════════════════════════════════════
# 6. Tracker — save_recommendations, track_outcomes, get_tracking_report
# ═══════════════════════════════════════════════════════


class TestTrackerSaveRecommendations:
    """Cover save_recommendations with candidates and actions."""

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
        assert count == 1  # only regime_fit=True saved

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
        # candidate saved + action merged into existing record, count should be 1
        assert count == 1


class TestTrackerTrackOutcomes:
    """Cover track_outcomes 30d/60d/90d branches."""

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
        # Insert a low price at target date to simulate price drop
        target_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rec_date, "TSLA", "SELL", 60.0, "bear", "[]", 250.0))
            # Insert a lower price to ensure negative return
            conn.execute(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("TSLA", target_date, 200, 205, 195, 200, 1000000))

        updated = track_outcomes(db_path=rich_db)
        assert updated >= 1


class TestTrackerReport:
    """Cover get_tracking_report and print_tracking_report."""

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


# ═══════════════════════════════════════════════════════
# 7. Broker — Order, DryRunBroker, AlpacaBroker, get_broker
# ═══════════════════════════════════════════════════════


class TestBrokerOrder:
    """Cover Order dataclass __post_init__ and is_partial."""

    def test_filled_order_auto_qty(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="filled")
        assert order.filled_qty == 10
        assert order.unfilled_qty == 0.0

    def test_pending_order_auto_qty(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="submitted")
        assert order.filled_qty == 0.0
        assert order.unfilled_qty == 10

    def test_partial_fill_detection(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="partially_filled",
                      filled_qty=5, unfilled_qty=5)
        assert order.is_partial is True

    def test_not_partial_when_fully_filled(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="filled")
        assert order.is_partial is False

    def test_explicit_timestamp(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="dry_run", timestamp="2025-01-01T00:00:00")
        assert order.timestamp == "2025-01-01T00:00:00"


class TestDryRunBroker:
    """Cover DryRunBroker methods."""

    def test_submit_order(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        order = broker.submit_order("AAPL", "buy", 5, "market")
        assert order.status == "dry_run"
        assert order.broker == "dry_run"
        assert order.order_id.startswith("DRY-")

    def test_multiple_orders_increment_id(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        o1 = broker.submit_order("AAPL", "buy", 5)
        o2 = broker.submit_order("NVDA", "sell", 3)
        assert o1.order_id == "DRY-1"
        assert o2.order_id == "DRY-2"

    def test_get_positions(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        assert broker.get_positions() == []

    def test_get_account_value(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        assert broker.get_account_value() == 100_000.0

    def test_cancel_all(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        assert broker.cancel_all() == 0


class TestAlpacaBroker:
    """Cover AlpacaBroker initialization and error paths."""

    def test_init_without_keys(self):
        from nuri.trading.execution.broker import AlpacaBroker
        with pytest.raises(ValueError, match="ALPACA_API_KEY"):
            AlpacaBroker()

    def test_init_with_keys(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "test-key")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
        broker = AlpacaBroker()
        assert broker.api_key == "test-key"
        assert broker.secret_key == "test-secret"

    def test_submit_order_success(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        mock_response = {
            "id": "order-123", "status": "filled",
            "filled_qty": "10", "filled_avg_price": "175.50",
        }
        with patch.object(broker, "_request", return_value=mock_response):
            order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "filled"
        assert order.filled_price == 175.50
        assert order.filled_qty == 10.0

    def test_submit_order_partial_fill(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        mock_response = {
            "id": "order-456", "status": "filled",
            "filled_qty": "5", "filled_avg_price": "175.50",
        }
        with patch.object(broker, "_request", return_value=mock_response):
            order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "partially_filled"
        assert order.filled_qty == 5.0
        assert order.unfilled_qty == 5.0
        assert order.is_partial is True

    def test_submit_order_failure(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", side_effect=Exception("network error")):
            order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "rejected"

    def test_get_positions_success(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        mock_data = [
            {"symbol": "AAPL", "qty": "10", "avg_entry_price": "170",
             "current_price": "180", "unrealized_plpc": "0.0588"},
        ]
        with patch.object(broker, "_request", return_value=mock_data):
            positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0].ticker == "AAPL"
        assert positions[0].pnl_pct == pytest.approx(5.88)

    def test_get_positions_failure(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", side_effect=Exception("fail")):
            positions = broker.get_positions()
        assert positions == []

    def test_get_account_value_success(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", return_value={"portfolio_value": "250000.50"}):
            value = broker.get_account_value()
        assert value == 250000.50

    def test_get_account_value_failure(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", side_effect=Exception("fail")):
            value = broker.get_account_value()
        assert value == 0.0

    def test_cancel_all_success(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", return_value=[{"id": "1"}, {"id": "2"}]):
            count = broker.cancel_all()
        assert count == 2

    def test_cancel_all_failure(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", side_effect=Exception("fail")):
            count = broker.cancel_all()
        assert count == 0


class TestGetBroker:
    """Cover get_broker factory."""

    def test_dry_run(self):
        from nuri.trading.execution.broker import DryRunBroker, get_broker
        broker = get_broker(dry_run=True)
        assert isinstance(broker, DryRunBroker)

    def test_no_alpaca_keys_fallback(self, monkeypatch):
        from nuri.trading.execution.broker import DryRunBroker, get_broker
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
        broker = get_broker(dry_run=False)
        assert isinstance(broker, DryRunBroker)

    def test_with_alpaca_keys(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker, get_broker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = get_broker(dry_run=False)
        assert isinstance(broker, AlpacaBroker)


# ═══════════════════════════════════════════════════════
# 8. Conflicts — strength_mismatch, regime_contradiction, print
# ═══════════════════════════════════════════════════════


class TestConflictsStrengthMismatch:
    """Cover strength_mismatch detection."""

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
    """Cover regime_contradiction detection."""

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
        """Buy signal that is regime_fit in bear market should be skipped (already validated)."""
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
        """If classify_regime raises, no regime_contradiction detected but no crash."""
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
    """Cover direction conflict with medium severity (one side not regime_fit)."""

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


class TestConflictsPrint:
    """Cover print_conflicts output formatting."""

    def test_no_conflicts(self, capsys):
        from nuri.trading.engine.conflicts import print_conflicts
        print_conflicts([])
        out = capsys.readouterr().out
        assert "시그널 충돌 없음" in out

    def test_with_conflicts(self, capsys):
        from nuri.trading.engine.conflicts import SignalConflict, print_conflicts
        conflicts = [
            SignalConflict(
                ticker="TSLA", conflict_type="direction_conflict", severity="high",
                buy_signals=["bb_bounce"], sell_signals=["macd_dead"],
                detail="BUY와 SELL 동시 발생", recommendation="관망 권장"),
            SignalConflict(
                ticker="AAPL", conflict_type="strength_mismatch", severity="low",
                buy_signals=["rsi_oversold"], sell_signals=[],
                detail="강한/약한 시그널 공존", recommendation="강한 시그널 우선"),
        ]
        print_conflicts(conflicts)
        out = capsys.readouterr().out
        assert "Signal Conflicts (2건)" in out
        assert "[!!!]" in out  # high severity
        assert "TSLA" in out
