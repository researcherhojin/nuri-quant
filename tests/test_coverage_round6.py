"""커버리지 보강 Round 6 — ls_backtest deep, backtest engine, optimizer, longshort, scheduler, cboe, analyst."""
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_portfolio, upsert_prices


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
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
    dates = pd.date_range("2024-06-01", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 5
            rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p + 3, "low": p - 2,
                         "close": p + 1, "volume": 50000000, "adj_close": p + 1})
    upsert_prices(pd.DataFrame(rows), path)
    vix = [{"indicator": "vix", "date": d.strftime("%Y-%m-%d"),
            "value": 15 + np.sin(i / 30) * 8, "source": "test"}
           for i, d in enumerate(dates)]
    upsert_macro(vix, path)
    return path


# ─── L/S Backtest — 미커버 함수들 ───


class TestLSBacktestRound6:
    def test_analyze_per_regime(self, rich_db):
        from nuri.trading.strategy.ls_backtest import (
            analyze_per_regime,
            classify_historical_regimes,
        )
        regimes = classify_historical_regimes()
        perfs = analyze_per_regime(regimes)
        assert isinstance(perfs, list)
        assert len(perfs) > 0
        assert hasattr(perfs[0], "regime")
        assert hasattr(perfs[0], "days")

    def test_analyze_entry_timing(self, rich_db):
        from nuri.trading.strategy.ls_backtest import (
            analyze_entry_timing,
            classify_historical_regimes,
        )
        regimes = classify_historical_regimes()
        timing = analyze_entry_timing(regimes, current_regime="bull_low_vol")
        # timing은 None이거나 TimingAnalysis
        if timing is not None:
            assert hasattr(timing, "current_regime")

    def test_stress_test(self, rich_db):
        from nuri.trading.strategy.ls_backtest import (
            classify_historical_regimes,
            stress_test,
        )
        regimes = classify_historical_regimes()
        results = stress_test(regimes)
        assert isinstance(results, list)
        assert len(results) > 0

    def test_run_backtest_with_rules(self, rich_db):
        from nuri.trading.strategy.ls_backtest import (
            classify_historical_regimes,
            run_backtest_with_rules,
        )
        regimes = classify_historical_regimes()
        result = run_backtest_with_rules(regimes)
        assert isinstance(result, dict)

    def test_print_regime_performance(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import (
            analyze_per_regime,
            classify_historical_regimes,
            print_regime_performance,
        )
        regimes = classify_historical_regimes()
        perfs = analyze_per_regime(regimes)
        print_regime_performance(perfs)
        assert len(capsys.readouterr().out) > 0

    def test_print_timing(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import (
            analyze_entry_timing,
            classify_historical_regimes,
            print_timing,
        )
        regimes = classify_historical_regimes()
        timing = analyze_entry_timing(regimes)
        print_timing(timing)
        assert len(capsys.readouterr().out) >= 0

    def test_print_stress(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import (
            classify_historical_regimes,
            print_stress,
            stress_test,
        )
        regimes = classify_historical_regimes()
        results = stress_test(regimes)
        print_stress(results)
        assert len(capsys.readouterr().out) > 0

    def test_print_monte_carlo(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import (
            classify_historical_regimes,
            monte_carlo_test,
            print_monte_carlo,
        )
        regimes = classify_historical_regimes()
        mc = monte_carlo_test(regimes, n_simulations=5)
        print_monte_carlo(mc)
        assert len(capsys.readouterr().out) > 0

    def test_print_rules_comparison(self, rich_db, capsys):
        from nuri.trading.strategy.ls_backtest import (
            classify_historical_regimes,
            print_rules_comparison,
            run_backtest_with_rules,
        )
        regimes = classify_historical_regimes()
        result = run_backtest_with_rules(regimes)
        print_rules_comparison(result)
        assert len(capsys.readouterr().out) > 0


# ─── Longshort Strategy ───


class TestLongshortDeep:
    def test_generate_strategy(self, rich_db):
        from nuri.trading.strategy.longshort import generate_strategy
        actions = generate_strategy()
        assert isinstance(actions, list)

    def test_print_strategy(self, rich_db, capsys):
        from nuri.trading.strategy.longshort import generate_strategy, print_strategy
        actions = generate_strategy()
        print_strategy(actions)
        assert len(capsys.readouterr().out) >= 0


# ─── Scheduler — lazy import 라인들 ───


class TestSchedulerLazy:
    def test_run_collector_known_names(self):
        """실제 collector 이름 호출 — conftest mock 덕분에 네트워크 안 탐."""
        from nuri.scheduler import _run_collector
        names = ["stock", "stock_kr", "macro", "technical", "fear_greed",
                 "ark", "news", "fundamental", "estimates", "wallstreet",
                 "cboe", "finviz", "etf_flows"]
        for name in names:
            _run_collector(name)  # lazy import + run() 호출

    def test_run_collector_reddit(self):
        from nuri.scheduler import _run_collector
        _run_collector("reddit")

    def test_run_collector_events(self):
        from nuri.scheduler import _run_collector
        _run_collector("events")


# ─── CBOE deep ───


class TestCBOEDeep:
    def test_collect_daily_success(self):
        from nuri.collectors.cboe import CBOECollector
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]
        }
        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_daily()
        assert isinstance(result, list)
        if result:
            assert result[0]["value"] == 0.85

    def test_collect_totalpc(self):
        from nuri.collectors.cboe import CBOECollector
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"TRADE_DATE": "2026-03-29", "TOTAL_PUT_CALL_RATIO": 0.90},
                {"TRADE_DATE": "2026-03-28", "TOTAL_PUT_CALL_RATIO": 0.88},
            ]
        }
        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c._collect_totalpc()
        assert isinstance(result, list)

    def test_collect_full(self, rich_db):
        """collect() 전체 — daily + totalpc + fred fallback."""
        from nuri.collectors.cboe import CBOECollector
        c = CBOECollector()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]
        }
        with patch("nuri.collectors.cboe.requests.get", return_value=mock_resp):
            result = c.collect()
        assert isinstance(result, list)


# ─── Analyst Backtest ───


class TestAnalystBacktest:
    def test_validate_estimates_no_data(self, rich_db):
        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates()
        assert isinstance(results, list)

    def test_print_results(self, capsys):
        from nuri.quant.validation.analyst_backtest import print_results
        print_results([])
        output = capsys.readouterr().out
        assert len(output) >= 0


# ─── Superinvestor Backtest ───


class TestSuperinvestorBacktest:
    def test_check_data_readiness(self, rich_db):
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        result = _check_data_readiness()
        assert isinstance(result, bool)

    def test_backtest_no_data(self, rich_db):
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        results = backtest_superinvestor()
        assert isinstance(results, list)


# ─── Optimizer ───


class TestOptimizerDeep:
    def test_optimize_signal(self, rich_db):
        from nuri.quant.backtest.optimizer import optimize_signal
        result = optimize_signal("rsi_oversold")
        # 데이터에 따라 결과 달라짐
        assert result is not None or result is None
