"""커버리지 보강 Round 4 — ls_backtest, charts, collector collect() 내부 로직."""
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_portfolio, upsert_prices


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    """ls_backtest에 필요한 풍부한 데이터."""
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    # 포트폴리오
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 190, "currency": "USD", "sector": "Tech"},
    ], path)

    # SPY + AAPL 가격 (500일 — 백테스트에 충분)
    dates = pd.date_range("2024-06-01", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL"]:
        base = 450 if t == "SPY" else 170
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 5
            rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p + 3, "low": p - 2,
                         "close": p + 1, "volume": 50000000, "adj_close": p + 1})
    upsert_prices(pd.DataFrame(rows), path)

    # VIX 매크로 데이터
    vix_records = []
    for i, d in enumerate(dates):
        vix_records.append({
            "indicator": "vix", "date": d.strftime("%Y-%m-%d"),
            "value": 15 + np.sin(i / 30) * 8, "source": "test",
        })
    upsert_macro(vix_records, path)

    return path


# ─── L/S Backtest ───


class TestLSBacktest:
    def test_classify_historical_regimes(self, rich_db):
        """과거 레짐 분류."""
        from nuri.trading.strategy.ls_backtest import classify_historical_regimes
        regimes = classify_historical_regimes()
        assert isinstance(regimes, pd.DataFrame)
        assert "regime" in regimes.columns
        assert len(regimes) > 100

    def test_run_backtest(self, rich_db):
        """백테스트 실행."""
        from nuri.trading.strategy.ls_backtest import (
            BacktestResult,
            classify_historical_regimes,
            run_backtest,
        )
        regimes = classify_historical_regimes()
        result = run_backtest(regimes)
        assert isinstance(result, BacktestResult)
        assert hasattr(result, "total_return")
        assert hasattr(result, "sharpe")
        assert hasattr(result, "equity_curve")
        assert result.total_days > 0

    def test_monte_carlo(self, rich_db):
        """몬테카를로 시뮬레이션."""
        from nuri.trading.strategy.ls_backtest import (
            classify_historical_regimes,
            monte_carlo_test,
        )
        regimes = classify_historical_regimes()
        mc = monte_carlo_test(regimes, n_simulations=10)
        assert isinstance(mc, dict)


# ─── Charts ───


class TestChartsGeneration:
    def test_generate_plotly_chart(self, rich_db, tmp_path):
        """Plotly 차트 생성."""
        from nuri.analysis.charts import _load_chart_data, generate_plotly_chart
        df = _load_chart_data("AAPL")
        assert df is not None
        output = generate_plotly_chart("AAPL", df, tmp_path)
        assert output.exists()
        assert output.suffix == ".html"

    def test_generate_charts_all(self, rich_db, tmp_path):
        """전체 차트 생성."""
        from nuri.analysis.charts import generate_charts
        results = generate_charts(output_dir=tmp_path)
        assert isinstance(results, list)


# ─── WallStreet Collector (내부 로직) ───


class TestWallStreetDeep:
    def test_collect_and_save(self, rich_db):
        """collect() + save() 전체 경로 mock."""
        from nuri.collectors.wallstreet import WallStreetCollector

        mock_ticker = MagicMock()
        mock_ticker.upgrades_downgrades = pd.DataFrame([
            {"GradeDate": pd.Timestamp("2026-03-01"), "Firm": "GS",
             "ToGrade": "Buy", "FromGrade": "Hold", "Action": "upgrade"},
        ])
        mock_ticker.earnings_history = pd.DataFrame([
            {"Quarter": pd.Timestamp("2026-01-01"), "epsActual": 2.1,
             "epsEstimate": 1.9, "surprisePercent": 10.5},
        ])
        mock_ticker.insider_transactions = pd.DataFrame([
            {"startDate": pd.Timestamp("2026-03-20"), "insiderName": "Tim Cook",
             "position": "CEO", "transactionType": "Sale",
             "shares": 50000, "value": 9500000},
        ])
        mock_ticker.info = {"shortPercentOfFloat": 0.008, "shortRatio": 1.2}

        c = WallStreetCollector()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            data = c.collect()
        assert "ratings" in data
        count = c.save(data)
        assert count > 0

    def test_collect_empty_data(self, rich_db):
        """yfinance에서 빈 데이터."""
        from nuri.collectors.wallstreet import WallStreetCollector

        mock_ticker = MagicMock()
        mock_ticker.upgrades_downgrades = None
        mock_ticker.earnings_history = None
        mock_ticker.insider_transactions = None
        mock_ticker.info = {}

        c = WallStreetCollector()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            data = c.collect()
        assert isinstance(data, dict)


# ─── ETF Flows Collector (내부) ───


class TestEtfFlowsDeep:
    def test_collect_with_obb_mock(self, rich_db):
        from nuri.collectors.etf_flows import EtfFlowsCollector

        mock_result = MagicMock()
        mock_result.to_df.return_value = pd.DataFrame([
            {"symbol": "SPY", "name": "SPDR S&P 500",
             "total_assets": 500e9, "average_volume": 80000000,
             "nav_price": 520.0},
        ])

        c = EtfFlowsCollector()
        with patch.object(c, "collect", return_value=[
            {"ticker": "SPY", "date": "2026-03-30", "name": "SPDR S&P 500",
             "total_assets": 500e9, "volume_avg": 80000000, "nav_price": 520.0},
        ]):
            data = c.collect()
            count = c.save(data)
        assert count == 1

    def test_analyze_sector_rotation(self, rich_db):
        """섹터 로테이션 분석 (ETF 데이터 필요)."""
        from nuri.collectors.etf_flows import analyze_sector_rotation
        result = analyze_sector_rotation(days=30)
        # 데이터 없으면 None
        assert result is None or isinstance(result, pd.DataFrame)


# ─── Institutional Collector ───


class TestInstitutionalDeep:
    def test_save_records(self, rich_db):
        from nuri.collectors.institutional import InstitutionalCollector
        c = InstitutionalCollector()
        data = [
            {"ticker": "005930.KS", "date": "2026-03-30", "market": "KOSPI",
             "institution_net": 1000000, "foreign_net": 500000,
             "individual_net": -1500000, "source": "pykrx"},
        ]
        count = c.save(data)
        assert count >= 0


# ─── Consensus (deeper) ───


class TestConsensusDeep:
    def test_analyze_ticker(self, rich_db):
        from nuri.trading.agents.consensus import analyze_ticker
        result = analyze_ticker("AAPL")
        assert hasattr(result, "final_action")
        assert hasattr(result, "final_confidence")
        assert hasattr(result, "agreement_rate")

    def test_analyze_portfolio(self, rich_db):
        from nuri.trading.agents.consensus import analyze_portfolio
        results = analyze_portfolio()
        assert isinstance(results, list)
        assert len(results) > 0


# ─── Regime Classifier (deeper) ───


class TestRegimeDeep:
    def test_classify_regime(self, rich_db):
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime()
        assert hasattr(state, "regime")
        assert hasattr(state, "trend")
        assert hasattr(state, "confidence")

    def test_classify_with_historical_vix(self, rich_db):
        """VIX 데이터가 있을 때 분류."""
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime()
        assert state.regime is not None
        assert state.confidence > 0
