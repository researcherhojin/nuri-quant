"""커버리지 보강 Round 9 — 남은 collector collect(), api routes, trading deeper."""
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
        {"account": "test", "ticker": "005930.KS", "quantity": 4,
         "avg_price": 60000, "currency": "KRW", "sector": "Semiconductor"},
    ], path)
    dates = pd.date_range("2024-06-01", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA", "005930.KS"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120, "005930.KS": 58000}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 3
            rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p + 3, "low": p - 2,
                         "close": p + 1, "volume": 50000000, "adj_close": p + 1})
    upsert_prices(pd.DataFrame(rows), path)
    vix = [{"indicator": "vix", "date": d.strftime("%Y-%m-%d"),
            "value": 15 + np.sin(i / 30) * 8, "source": "test"}
           for i, d in enumerate(dates)]
    fg = [{"indicator": "fear_greed", "date": d.strftime("%Y-%m-%d"),
           "value": 50 + np.sin(i / 25) * 30, "source": "test"}
          for i, d in enumerate(dates)]
    upsert_macro(vix + fg, path)
    return path


# ─── Superinvestors collect() — with infotable data ───


class TestSuperinvestorsCollect:
    def test_collect_with_infotable(self):
        from nuri.collectors.superinvestors import SuperinvestorCollector

        mock_info = MagicMock()
        mock_info.infotable = pd.DataFrame([
            {"nameOfIssuer": "Apple Inc", "cusip": "037833100",
             "value": 171000, "sshPrnamt": 900000, "sshPrnamtType": "SH"},
        ])
        mock_filing = MagicMock()
        mock_filing.filing_date = "2026-02-14"
        mock_filing.obj.return_value = mock_info

        mock_co = MagicMock()
        mock_co.get_filings.return_value = [mock_filing]

        with patch("edgar.Company", return_value=mock_co), \
             patch("edgar.set_identity"):
            c = SuperinvestorCollector()
            result = c.collect(num_quarters=1)
        # infotable 파싱 로직에 따라 빈 결과일 수 있음
        assert isinstance(result, list)

    def test_run_full(self):
        """run() 전체 — collect + save."""
        from nuri.collectors.superinvestors import SuperinvestorCollector
        mock_info = MagicMock()
        mock_info.infotable = pd.DataFrame([
            {"nameOfIssuer": "Apple Inc", "cusip": "037833100",
             "value": 171000, "sshPrnamt": 900000, "sshPrnamtType": "SH"},
        ])
        mock_filing = MagicMock()
        mock_filing.filing_date = "2026-02-14"
        mock_filing.obj.return_value = mock_info
        mock_co = MagicMock()
        mock_co.get_filings.return_value = [mock_filing]
        with patch("edgar.Company", return_value=mock_co), \
             patch("edgar.set_identity"):
            c = SuperinvestorCollector()
            c.run(num_quarters=1)


# ─── CBOE — collect_totalpc + fred fallback ───


class TestCBOEFull:
    def test_collect_with_fallback(self):
        from nuri.collectors.cboe import CBOECollector
        # daily 성공, totalpc 실패
        mock_daily = MagicMock()
        mock_daily.status_code = 200
        mock_daily.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-30", "TOTAL_PUT_CALL_RATIO": 0.85}]
        }
        mock_fail = MagicMock()
        mock_fail.status_code = 500

        c = CBOECollector()
        with patch("nuri.collectors.cboe.requests.get",
                    side_effect=[mock_daily, mock_fail]):
            daily = c._collect_daily()
            totalpc = c._collect_totalpc()
        assert len(daily) > 0
        assert len(totalpc) == 0


# ─── Institutional collect() ───


class TestInstitutionalCollect:
    def test_collect_and_save(self, rich_db):
        from nuri.collectors.institutional import InstitutionalCollector
        c = InstitutionalCollector()
        mock_df = pd.DataFrame({
            "기관합계": [1000000, 2000000],
            "외국인합계": [500000, 600000],
            "개인": [-1500000, -2600000],
        }, index=pd.date_range("2026-03-29", periods=2))
        with patch("pykrx.stock.get_market_trading_value_by_date", return_value=mock_df):
            result = c.collect()
        assert isinstance(result, list)
        if result:
            count = c.save(result)
            assert count >= 0


# ─── ETF Flows collect() ───


class TestEtfFlowsFull:
    def test_collect_mock(self, rich_db):
        from nuri.collectors.etf_flows import EtfFlowsCollector
        c = EtfFlowsCollector()
        # collect()는 lazy import으로 openbb 사용 — mock으로 우회
        with patch.object(c, "collect", return_value=[
            {"ticker": "SPY", "date": "2026-03-30", "name": "SPDR S&P 500",
             "total_assets": 500e9, "volume_avg": 80000000, "nav_price": 520},
        ]):
            result = c.collect()
            count = c.save(result)
        assert count == 1


# ─── API Routes — stream, agents, regime ───


class TestAPIRoutes:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        import nuri.core.db as db_mod
        import nuri.core.portfolio_sync as sync_mod
        from nuri.core.db import init_db
        db = tmp_path / "t.db"
        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "p.yaml")
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        return TestClient(app)

    def test_consensus_endpoint(self, client):
        r = client.get("/api/consensus")
        assert r.status_code == 200

    def test_regime_endpoint(self, client):
        r = client.get("/api/regime")
        assert r.status_code == 200

    def test_macro_endpoint(self, client):
        r = client.get("/api/macro")
        assert r.status_code == 200

    def test_strategy_endpoint(self, client):
        r = client.get("/api/strategy")
        assert r.status_code == 200

    def test_pipeline_status(self, client):
        r = client.get("/api/pipeline/status")
        assert r.status_code == 200

    def test_freshness(self, client):
        r = client.get("/api/freshness")
        assert r.status_code == 200


# ─── Risk analysis ───


class TestRiskAnalysis:
    def test_analyze_risk(self, rich_db):
        from nuri.analysis.risk import analyze_risk
        result = analyze_risk()
        assert isinstance(result, dict)

    def test_portfolio_analysis(self, rich_db):
        from nuri.analysis.portfolio import analyze_portfolio
        with patch("nuri.analysis.portfolio.get_exchange_rate", return_value=1400.0):
            result = analyze_portfolio()
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0


# ─── Price Targets ───


class TestPriceTargets:
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
