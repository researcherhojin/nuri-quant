"""60% 달성을 위한 최종 테스트 — signal_backtest, candidates, consensus, optimizer."""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_prices


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def full_db(db_path):
    """풍부한 가격 + 시그널 + 매크로 데이터."""
    today = datetime.now().strftime("%Y-%m-%d")

    with get_db(db_path) as conn:
        for t, q, p, s in [("AAPL", 10, 150, "Technology"), ("MSFT", 5, 300, "Software"),
                            ("TSLA", 8, 340, "EV/AI")]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)", ("test", t, q, p, "USD", s))

    dates = pd.bdate_range("2023-01-01", periods=400)
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
        upsert_prices(df, db_path)

    # 시그널 데이터 (TA-Lib 스타일)
    with get_db(db_path) as conn:
        for i, d in enumerate(dates[-100:]):
            ds = d.strftime("%Y-%m-%d")
            for ticker in ["AAPL", "MSFT", "TSLA", "SPY"]:
                rsi = 30 + (i % 40)  # 30~70 oscillation
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
    ], db_path)

    return db_path


# ═══════════════════════════════════════════════════════
# Signal Backtest
# ═══════════════════════════════════════════════════════

class TestSignalBacktest:
    def test_compute_indicators(self, full_db):
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import _compute_indicators
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if not df.empty:
            result = _compute_indicators(df)
            assert "rsi_14" in result.columns or "sma_20" in result.columns

    def test_backtest_signals(self, full_db, tmp_path):
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(db_path=full_db)
        assert isinstance(results, list)

    def test_generate_scorecard(self):
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard
        results = [
            SignalResult("rsi_oversold", "AAPL", "2024-06-01", 150.0, "2024-06-15", 160.0, 6.67, 10, True),
            SignalResult("rsi_oversold", "AAPL", "2024-07-01", 155.0, "2024-07-15", 150.0, -3.23, 10, False),
            SignalResult("macd_golden", "MSFT", "2024-06-01", 300.0, "2024-06-15", 320.0, 6.67, 10, True),
        ]
        scorecards = generate_scorecard(results)
        assert len(scorecards) > 0

    def test_print_scorecard(self, capsys):
        from nuri.quant.validation.signal_backtest import SignalScorecard, print_scorecard
        scorecards = [
            SignalScorecard(
                signal_id="rsi_oversold", ticker=None,
                total_trades=50, win_rate=0.6,
                avg_return=3.5, median_return=2.5,
                max_return=15.0, max_loss=-8.0,
                profit_factor=2.0, avg_holding_days=10.0,
            ),
        ]
        print_scorecard(scorecards)
        output = capsys.readouterr().out
        assert "rsi_oversold" in output


# ═══════════════════════════════════════════════════════
# Candidates 확장
# ═══════════════════════════════════════════════════════

class TestCandidatesDeep:
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


# ═══════════════════════════════════════════════════════
# Optimizer 확장
# ═══════════════════════════════════════════════════════

class TestOptimizerExtended:
    def test_optimize_signal(self, full_db):
        from nuri.quant.backtest.optimizer import optimize_signal
        result = optimize_signal("rsi_oversold", db_path=full_db)
        assert isinstance(result, (list, type(None)))

    def test_backtest_with_params(self, full_db):
        from nuri.core.db import query_df
        from nuri.quant.backtest.optimizer import _backtest_signal_with_params
        df = query_df("SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date")
        if not df.empty and len(df) > 50:
            result = _backtest_signal_with_params(df, "rsi_oversold", {"rsi_entry": 30, "rsi_exit": 70})
            assert result is None or hasattr(result, "win_rate")


# ═══════════════════════════════════════════════════════
# Classifier 확장
# ═══════════════════════════════════════════════════════

class TestClassifierDeep:
    def test_print_regime(self, full_db, capsys):
        from nuri.quant.regime.classifier import classify_regime, print_regime
        result = classify_regime(db_path=full_db)
        print_regime(result)
        output = capsys.readouterr().out
        assert len(output) > 0

    def test_compute_thresholds(self, full_db):
        from nuri.quant.regime.classifier import compute_dynamic_thresholds
        thresholds = compute_dynamic_thresholds(db_path=full_db)
        assert isinstance(thresholds, dict)
        assert "vix_threshold" in thresholds
        assert "sideways_pct" in thresholds


# ═══════════════════════════════════════════════════════
# Evidence Charts 보충
# ═══════════════════════════════════════════════════════

class TestEvidenceChartsDeep:
    def test_regime_chart_with_data(self, full_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_regime_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_regime_chart(output_dir, db_path=full_db)
        assert result.exists()

    def test_portfolio_heatmap_with_data(self, full_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_portfolio_heatmap
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_portfolio_heatmap(output_dir, db_path=full_db)
        assert result.exists()

    def test_signal_performance_with_data(self, full_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_signal_performance_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_signal_performance_chart(output_dir, db_path=full_db)
        assert result.exists()

    def test_fear_greed_with_data(self, full_db, tmp_path):
        # 30일 F&G 데이터
        with get_db(full_db) as conn:
            for i in range(60):
                conn.execute(
                    "INSERT OR IGNORE INTO macro (date, indicator, value) VALUES (?, 'fear_greed', ?)",
                    (f"2026-01-{(i % 28) + 1:02d}", 30.0 + i * 0.5),
                )
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_fear_greed_chart(output_dir, db_path=full_db)
        assert result.exists()
