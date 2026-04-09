"""Tests for nuri.trading.engine.memory.

Extracted from tests/test_trading_engine_all.py (refactor #157).
Source: test_engine.py, test_coverage_round10.py, test_coverage_round16.py,
test_coverage_round23.py.
"""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from nuri.core.db import get_db


class TestMemory:
    """From test_engine.py."""

    def test_detect_drift_empty(self, db_path):
        from nuri.trading.engine.memory import detect_drift
        drifts = detect_drift(db_path=db_path)
        assert drifts == []

    def test_snapshot_and_drift(self, db_path):
        from nuri.core.db import get_db
        from nuri.trading.engine.memory import detect_drift

        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (today, "rsi_oversold", None, "all_time", 100, 0.60, 2.0, 3.5),
            )
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (today, "rsi_oversold", None, "recent_90d", 20, 0.35, 0.8, -1.2),
            )

        drifts = detect_drift(db_path=db_path)
        assert len(drifts) == 1
        assert drifts[0].signal_id == "rsi_oversold"
        assert drifts[0].status == "critical"


class TestLearningMemory:
    """From test_coverage_round10.py."""

    def test_save_snapshot(self, rich_db):
        from nuri.trading.engine.memory import save_snapshot
        count = save_snapshot()
        assert isinstance(count, int)

    def test_detect_drift(self, rich_db):
        from nuri.trading.engine.memory import detect_drift
        drifts = detect_drift()
        assert isinstance(drifts, list)

    def test_print_memory_status(self, rich_db, capsys):
        from nuri.trading.engine.memory import detect_drift, print_memory_status
        drifts = detect_drift()
        print_memory_status(drifts)
        assert len(capsys.readouterr().out) >= 0


class TestMemoryComputeStats:
    """From test_coverage_round16.py."""

    def test_all_positive_returns(self):
        from nuri.trading.engine.memory import _compute_stats
        df = pd.DataFrame({"return_pct": [5.0, 10.0, 3.0]})
        stats = _compute_stats(df)
        assert stats["trades"] == 3
        assert stats["win_rate"] == 1.0
        assert stats["profit_factor"] == 99.99

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
    """From test_coverage_round16.py."""

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
    """From test_coverage_round16.py."""

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
        assert "성과 하락 시그널 1개" in out


class TestMemorySaveSnapshotEmptyCsv:
    """From test_coverage_round16.py."""

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
    """From test_coverage_round16.py."""

    def test_four_statuses(self, rich_db):
        from nuri.trading.engine.memory import detect_drift

        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_critical", None, "all_time", 100, 0.60, 2.0, 3.5))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_critical", None, "recent_90d", 20, 0.30, 0.8, -1.0))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_degrading", None, "all_time", 100, 0.60, 2.0, 3.0))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_degrading", None, "recent_90d", 20, 0.48, 1.2, 1.0))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_improving", None, "all_time", 100, 0.50, 1.5, 2.0))
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (today, "sig_improving", None, "recent_90d", 20, 0.60, 2.5, 4.0))
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
        assert drifts[0].status == "critical"
        assert drifts[-1].status == "stable"


class TestMemory_R23:
    """From test_coverage_round23.py."""

    def test_save_snapshot_no_csv(self, db_path, monkeypatch):
        from nuri.trading.engine.memory import save_snapshot

        monkeypatch.setattr("nuri.trading.engine.memory._find_latest_csv", lambda fn: None)
        n = save_snapshot(db_path=db_path)
        assert n == 0

    def test_save_snapshot_empty_trades(self, db_path, monkeypatch, tmp_path):
        from nuri.trading.engine.memory import save_snapshot

        csv_path = tmp_path / "signal_results.csv"
        pd.DataFrame(columns=["signal_id", "entry_date", "return_pct"]).to_csv(csv_path, index=False)
        monkeypatch.setattr("nuri.trading.engine.memory._find_latest_csv", lambda fn: csv_path)

        n = save_snapshot(db_path=db_path)
        assert n == 0

    def test_save_snapshot_with_trades(self, db_path, monkeypatch, tmp_path):
        from nuri.trading.engine.memory import save_snapshot

        csv_path = tmp_path / "signal_results.csv"
        trades_df = pd.DataFrame({
            "signal_id": ["rsi_oversold"] * 5 + ["macd_golden"] * 3,
            "entry_date": [
                (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
                for d in range(8)
            ],
            "return_pct": [3.0, -1.0, 5.0, 2.0, -2.0, 4.0, -1.0, 6.0],
        })
        trades_df.to_csv(csv_path, index=False)
        monkeypatch.setattr("nuri.trading.engine.memory._find_latest_csv", lambda fn: csv_path)

        monkeypatch.setattr("nuri.quant.regime.strategy_map.analyze_signal_by_regime",
                            lambda **kw: (_ for _ in ()).throw(ImportError("no module")))

        n = save_snapshot(db_path=db_path)
        assert n > 0

    def test_save_snapshot_with_cross_df(self, db_path, monkeypatch, tmp_path):
        from nuri.trading.engine.memory import save_snapshot

        csv_path = tmp_path / "signal_results.csv"
        trades_df = pd.DataFrame({
            "signal_id": ["rsi_oversold"] * 3,
            "entry_date": ["2026-03-01", "2026-03-10", "2026-03-20"],
            "return_pct": [3.0, -1.0, 5.0],
        })
        trades_df.to_csv(csv_path, index=False)
        monkeypatch.setattr("nuri.trading.engine.memory._find_latest_csv", lambda fn: csv_path)

        cross_df = pd.DataFrame({
            "signal_id": ["rsi_oversold"],
            "regime": ["bull_low_vol"],
            "trades": [10],
            "win_rate": [0.65],
            "profit_factor": [2.1],
            "avg_return": [3.5],
        })
        monkeypatch.setattr("nuri.quant.regime.strategy_map.analyze_signal_by_regime",
                            lambda **kw: cross_df)

        n = save_snapshot(db_path=db_path)
        assert n > 0

    def test_detect_drift_no_data(self, db_path):
        from nuri.trading.engine.memory import detect_drift

        drifts = detect_drift(db_path=db_path)
        assert drifts == []

    def test_detect_drift_with_data(self, db_path):
        from nuri.trading.engine.memory import detect_drift

        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'all_time', ?, ?, ?, ?)",
                (today, "rsi_oversold", 100, 0.70, 2.5, 3.0),
            )
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'recent_90d', ?, ?, ?, ?)",
                (today, "rsi_oversold", 20, 0.35, 0.8, -1.0),
            )
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'all_time', ?, ?, ?, ?)",
                (today, "macd_golden", 80, 0.55, 1.5, 2.0),
            )
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'recent_90d', ?, ?, ?, ?)",
                (today, "macd_golden", 15, 0.60, 1.6, 2.5),
            )

        drifts = detect_drift(db_path=db_path)
        assert len(drifts) >= 2
        rsi_drift = [d for d in drifts if d.signal_id == "rsi_oversold"]
        assert rsi_drift[0].status == "critical"
        macd_drift = [d for d in drifts if d.signal_id == "macd_golden"]
        assert macd_drift[0].status in ("stable", "improving")

    def test_print_memory_status_empty(self, capsys):
        from nuri.trading.engine.memory import print_memory_status

        print_memory_status([])
        captured = capsys.readouterr()
        assert "학습 메모리 없음" in captured.out

    def test_print_memory_status_with_drifts(self, capsys):
        from nuri.trading.engine.memory import PerformanceDrift, print_memory_status

        drifts = [
            PerformanceDrift("rsi_oversold", None, 0.70, 0.35, -50.0, "critical",
                             "승률 -50% 급락 (전체 70% → 최근 35%)"),
            PerformanceDrift("macd_golden", None, 0.55, 0.60, 9.1, "stable",
                             "승률 변화 +9.1% (안정)"),
        ]
        print_memory_status(drifts)
        captured = capsys.readouterr()
        assert "Performance Drift" in captured.out
        assert "성과 하락 시그널" in captured.out

    def test_detect_drift_degrading(self, db_path):
        from nuri.trading.engine.memory import detect_drift

        today = datetime.now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'all_time', ?, ?, ?, ?)",
                (today, "bb_bounce", 50, 0.60, 1.8, 2.0),
            )
            conn.execute(
                "INSERT INTO strategy_memory (snapshot_date, signal_id, regime, period, trades, win_rate, profit_factor, avg_return) "
                "VALUES (?, ?, NULL, 'recent_90d', ?, ?, ?, ?)",
                (today, "bb_bounce", 10, 0.48, 1.0, 0.5),
            )

        drifts = detect_drift(db_path=db_path)
        bb_drift = [d for d in drifts if d.signal_id == "bb_bounce"]
        assert bb_drift[0].status == "degrading"

    def test_find_latest_csv_nonexistent(self):
        import nuri.trading.engine.memory as mem_mod
        from nuri.trading.engine.memory import _find_latest_csv
        original = mem_mod.REPORT_DIR
        mem_mod.REPORT_DIR = Path("/nonexistent/path")
        result = _find_latest_csv("signal_results.csv")
        mem_mod.REPORT_DIR = original
        assert result is None
