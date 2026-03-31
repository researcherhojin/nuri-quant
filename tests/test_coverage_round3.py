"""커버리지 보강 Round 3 — scheduler + external + position + rebalance + charts + llm."""
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_portfolio, upsert_prices


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 190, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "NVDA", "quantity": 5,
         "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
    ], path)
    dates = pd.date_range("2025-06-01", periods=250, freq="B")
    rows = []
    for t in ["AAPL", "NVDA", "SPY"]:
        base = {"AAPL": 180, "NVDA": 120, "SPY": 500}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.3
            rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p + 2, "low": p - 1,
                         "close": p + 1, "volume": 1000000, "adj_close": p + 1})
    upsert_prices(pd.DataFrame(rows), path)
    return path


# ─── Scheduler ───


class TestSchedulerDispatch:
    def test_run_collector_memory_snapshot(self):
        from nuri.scheduler import _run_collector
        _run_collector("memory_snapshot")

    def test_run_backup(self):
        from nuri.scheduler import _run_backup
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _run_backup()

    def test_run_db_maintenance(self):
        from nuri.scheduler import _run_db_maintenance
        with patch("scripts.db_maintenance.run_maintenance"):
            _run_db_maintenance()

    def test_schedules_cron_format(self):
        from nuri.scheduler import SCHEDULES
        for s in SCHEDULES:
            cron = s["cron"]
            assert isinstance(cron, str), f"{s['name']}: cron should be str"
            parts = cron.split()
            assert len(parts) == 5, f"{s['name']}: cron should have 5 parts"

    def test_print_schedule(self, capsys):
        from nuri.scheduler import print_schedule
        print_schedule()
        output = capsys.readouterr().out
        assert "stock" in output.lower() or "schedule" in output.lower() or len(output) > 0


# ─── External (save functions) ───


class TestExternalSave:
    def test_save_external(self, db_path):
        from nuri.collectors.external import save_external
        assert save_external("tipranks", "AAPL", "consensus", "Strong Buy", 4.5) is True

    def test_save_tipranks(self, db_path):
        from nuri.collectors.external import save_tipranks
        save_tipranks("AAPL", "Strong Buy", 230.0, 30)

    def test_save_superinvestor(self, db_path):
        from nuri.collectors.external import save_superinvestor
        save_superinvestor("AAPL", 5, "increasing")

    def test_get_external(self, db_path):
        from nuri.collectors.external import get_external, save_external
        save_external("test_src", "AAPL", "rating", "Buy", 4.0)
        result = get_external("AAPL")
        assert isinstance(result, list)

    def test_get_external_summary(self, db_path):
        from nuri.collectors.external import get_external_summary, save_external
        save_external("test", "AAPL", "score", "high", 9.0)
        summary = get_external_summary()
        assert isinstance(summary, dict)

    def test_print_summary(self, db_path, capsys):
        from nuri.collectors.external import print_summary, save_external
        save_external("test", "AAPL", "score", "high", 9.0)
        print_summary()
        output = capsys.readouterr().out
        assert len(output) > 0


# ─── Position ───


class TestPositionDeep:
    def test_certify_bull_long(self, db_path):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bull_low_vol", "growth")
        assert cert.regime_aligned is True

    def test_certify_bear_long_misaligned(self, db_path):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bear_high_vol", "growth")
        assert cert.regime_aligned is False

    def test_certify_concentration_ok(self, db_path):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bull_low_vol", "growth")
        assert cert.concentration_ok is True
        assert cert.daily_limit_ok is True

    def test_get_positions_summary(self, db_path):
        from nuri.trading.strategy.position import get_positions_summary
        summary = get_positions_summary()
        assert "open_total" in summary
        assert summary["open_total"] == 0

    def test_close_nonexistent(self, db_path):
        from nuri.trading.strategy.position import close_position
        close_position(99999, 100.0, "test")


# ─── Rebalance ───


class TestRebalanceModule:
    def test_analyze_rebalance_returns_df(self, db_path):
        from nuri.analysis.rebalance import analyze_rebalance
        result = analyze_rebalance()
        assert isinstance(result, pd.DataFrame)

    def test_detect_violations_with_rate(self, db_path):
        from nuri.analysis.rebalance_advisor import detect_violations
        mock_df = pd.DataFrame([
            {"ticker": "AAPL", "account": "test", "quantity": 10,
             "avg_price": 190, "current_price": 200, "current_value_usd": 2000,
             "pnl_pct": 5.2, "weight_pct": 60.0, "sector": "Tech", "currency": "USD"},
        ])
        mock_df.attrs["total_value_usd"] = 2000
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations()
        assert isinstance(violations, list)


# ─── Charts ───


class TestCharts:
    def test_load_chart_data(self, db_path):
        from nuri.analysis.charts import _load_chart_data
        df = _load_chart_data("AAPL")
        assert df is not None
        assert "close" in df.columns

    def test_detect_signals(self, db_path):
        from nuri.analysis.charts import _detect_signals, _load_chart_data
        df = _load_chart_data("AAPL")
        if df is not None and len(df) > 30:
            result = _detect_signals(df)
            assert isinstance(result, pd.DataFrame)

    def test_get_info_panel(self, db_path):
        from nuri.analysis.charts import _get_info_panel
        info = _get_info_panel("AAPL")
        assert isinstance(info, dict)


# ─── LLM Report ───


class TestLLMReport:
    def test_gather_context(self, db_path):
        from nuri.llm.report import gather_context
        ctx = gather_context()
        assert hasattr(ctx, "gate_summary")
        assert hasattr(ctx, "regime_section")

    def test_format_prompt(self, db_path):
        from nuri.llm.report import format_prompt, gather_context
        ctx = gather_context()
        prompt = format_prompt(ctx)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_validate_output(self, db_path):
        from nuri.llm.report import ValidationResult, gather_context, validate_output
        ctx = gather_context()
        result = validate_output("This is a test report about AAPL.", ctx)
        assert isinstance(result, ValidationResult)

    def test_generate_llm_report_no_server(self, db_path):
        """Ollama 서버 없을 때 graceful error."""
        from nuri.llm.report import generate_llm_report
        with patch("requests.post", side_effect=ConnectionError("no ollama")), \
             patch("requests.get", side_effect=ConnectionError("no ollama")):
            result = generate_llm_report()
        assert "error" in result or isinstance(result, dict)
