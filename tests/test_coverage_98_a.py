"""Coverage push: API signals + collector __main__ blocks.

Target: ~93 uncovered lines → covered.
Key: patch at SOURCE level for runpy — nuri.collectors.base.BaseCollector.run,
nuri.core.db.query, etc.  NOT at the module level being re-run.
"""
import runpy
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_portfolio


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def db_with_portfolio(db_path):
    upsert_portfolio(
        [
            {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190,
             "currency": "USD", "sector": "Tech"},
            {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130,
             "currency": "USD", "sector": "Semiconductor"},
        ],
        db_path,
    )
    return db_path


# ═══════════════════════════════════════════════════════════
# API routes/signals.py — lines 25-43, 53
# ═══════════════════════════════════════════════════════════


class TestScorecardAPI:
    """Cover get_scorecard() all branches."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from nuri.api.main import app
        return TestClient(app)

    def test_scorecard_with_inf_values(self, client, tmp_path, monkeypatch):
        """CSV with inf/NaN → JSON 직렬화 성공 (bug fix 검증)."""
        import nuri.api.routes.signals as sig_mod

        # __file__을 tmp_path 기반으로 패치 → report_dir이 tmp_path/data/reports로 해석
        fake_file = tmp_path / "nuri" / "api" / "routes" / "signals.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.touch()
        monkeypatch.setattr(sig_mod, "__file__", str(fake_file))

        report_dir = tmp_path / "data" / "reports"
        day_dir = report_dir / "2026-04-01"
        day_dir.mkdir(parents=True)
        csv = day_dir / "signal_scorecard.csv"
        csv.write_text("ticker,win_rate,profit_factor\n,0.65,inf\nAAPL,0.5,1.2\n")

        r = client.get("/api/scorecard")
        assert r.status_code == 200
        data = r.json()
        assert "scorecard" in data
        # inf → None
        assert data["scorecard"][0]["profit_factor"] is None

    def test_scorecard_no_report_dir(self, client, tmp_path, monkeypatch):
        """report 디렉토리 없으면 에러."""
        import nuri.api.routes.signals as sig_mod
        fake_file = tmp_path / "nuri" / "api" / "routes" / "signals.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.touch()
        monkeypatch.setattr(sig_mod, "__file__", str(fake_file))
        # data/reports 디렉토리 안 만듦
        r = client.get("/api/scorecard")
        assert r.status_code == 200
        assert "error" in r.json()

    def test_scorecard_no_csv(self, client, tmp_path, monkeypatch):
        """디렉토리 있지만 CSV 없음."""
        import nuri.api.routes.signals as sig_mod
        fake_file = tmp_path / "nuri" / "api" / "routes" / "signals.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.touch()
        monkeypatch.setattr(sig_mod, "__file__", str(fake_file))
        report_dir = tmp_path / "data" / "reports" / "2026-01-01"
        report_dir.mkdir(parents=True)
        # CSV 없음
        r = client.get("/api/scorecard")
        assert r.status_code == 200
        assert "error" in r.json()

    def test_cross_analysis_empty(self, client, monkeypatch):
        monkeypatch.setattr(
            "nuri.quant.regime.strategy_map.analyze_signal_by_regime",
            MagicMock(return_value=pd.DataFrame()),
        )
        r = client.get("/api/cross-analysis")
        assert r.status_code == 200
        assert "error" in r.json()

    def test_cross_analysis_with_data(self, client, monkeypatch):
        mock_df = pd.DataFrame([{"signal": "rsi_oversold", "regime": "bull_low_vol", "win_rate": 0.7}])
        monkeypatch.setattr(
            "nuri.quant.regime.strategy_map.analyze_signal_by_regime",
            MagicMock(return_value=mock_df),
        )
        r = client.get("/api/cross-analysis")
        assert r.status_code == 200
        assert "data" in r.json()


# ═══════════════════════════════════════════════════════════
# collectors/estimates.py — lines 102-134 (__main__ block)
# ═══════════════════════════════════════════════════════════


class TestEstimatesMain:
    def test_main_with_rows(self, monkeypatch, db_with_portfolio, capsys):
        """__main__ block — rows 있을 때 전체 출력."""
        rows = [
            {"ticker": "AAPL", "recommendation": "Buy", "target_mean": 250.0,
             "target_median": 245.0, "current_price": 200.0, "num_analysts": 30},
            {"ticker": "NVDA", "recommendation": None, "target_mean": None,
             "target_median": None, "current_price": None, "num_analysts": None},
        ]
        monkeypatch.setattr(sys, "argv", ["estimates"])

        with patch("nuri.collectors.base.BaseCollector.run", return_value=3), \
             patch("nuri.core.db.query", return_value=rows):
            runpy.run_module("nuri.collectors.estimates", run_name="__main__")

        out = capsys.readouterr().out
        assert "애널리스트 컨센서스" in out
        assert "AAPL" in out
        assert "N/A" in out  # NVDA의 None 값들

    def test_main_no_rows(self, monkeypatch, db_with_portfolio, capsys):
        monkeypatch.setattr(sys, "argv", ["estimates"])

        with patch("nuri.collectors.base.BaseCollector.run", return_value=0), \
             patch("nuri.core.db.query", return_value=[]):
            runpy.run_module("nuri.collectors.estimates", run_name="__main__")

        out = capsys.readouterr().out
        assert "애널리스트 컨센서스" not in out


# ═══════════════════════════════════════════════════════════
# collectors/external.py — lines 181-213 (__main__ block)
# ═══════════════════════════════════════════════════════════


class TestExternalMain:
    def test_main_save_tipranks(self, monkeypatch, db_with_portfolio, capsys):
        monkeypatch.setattr(sys, "argv", [
            "external", "--save-tipranks", "NVDA", "Strong Buy", "273.61", "38",
        ])
        with patch("nuri.collectors.external.save_tipranks"):
            runpy.run_module("nuri.collectors.external", run_name="__main__")
        out = capsys.readouterr().out
        assert "TipRanks 저장" in out

    def test_main_save_superinvestor(self, monkeypatch, db_with_portfolio, capsys):
        monkeypatch.setattr(sys, "argv", [
            "external", "--save-superinvestor", "NVDA", "14", "buying",
        ])
        with patch("nuri.collectors.external.save_superinvestor"):
            runpy.run_module("nuri.collectors.external", run_name="__main__")
        out = capsys.readouterr().out
        assert "Dataroma 저장" in out

    def test_main_show(self, monkeypatch, db_with_portfolio):
        monkeypatch.setattr(sys, "argv", ["external", "--show", "NVDA"])
        with patch("nuri.collectors.external.print_ticker_external"):
            runpy.run_module("nuri.collectors.external", run_name="__main__")

    def test_main_summary(self, monkeypatch, db_with_portfolio):
        monkeypatch.setattr(sys, "argv", ["external", "--summary"])
        with patch("nuri.collectors.external.print_summary"):
            runpy.run_module("nuri.collectors.external", run_name="__main__")

    def test_main_default_no_data(self, monkeypatch, db_with_portfolio, capsys):
        monkeypatch.setattr(sys, "argv", ["external"])
        with patch("nuri.collectors.external.get_external_summary",
                    return_value={"total_records": 0}):
            runpy.run_module("nuri.collectors.external", run_name="__main__")
        out = capsys.readouterr().out
        assert "외부 데이터 없음" in out

    def test_main_default_with_data(self, monkeypatch, db_with_portfolio):
        monkeypatch.setattr(sys, "argv", ["external"])
        with patch("nuri.collectors.external.get_external_summary",
                    return_value={"total_records": 5}), \
             patch("nuri.collectors.external.print_summary"):
            runpy.run_module("nuri.collectors.external", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# collectors/fundamental.py — lines 117-140 (__main__ block)
# ═══════════════════════════════════════════════════════════


class TestFundamentalMain:
    def test_main_with_rows(self, monkeypatch, db_with_portfolio, capsys):
        rows = [
            {"ticker": "AAPL", "pe_ratio": 28.5, "forward_pe": 25.0,
             "roe": 0.15, "revenue_growth": 0.08, "debt_to_equity": 1.2},
            {"ticker": "NVDA", "pe_ratio": None, "forward_pe": None,
             "roe": None, "revenue_growth": None, "debt_to_equity": None},
        ]
        monkeypatch.setattr(sys, "argv", ["fundamental"])

        with patch("nuri.collectors.base.BaseCollector.run", return_value=2), \
             patch("nuri.core.db.query", return_value=rows):
            runpy.run_module("nuri.collectors.fundamental", run_name="__main__")

        out = capsys.readouterr().out
        assert "펀더멘탈 수집 완료" in out
        assert "N/A" in out


# ═══════════════════════════════════════════════════════════
# collectors/stock.py — lines 83-89, 111, 133, 137-148
# ═══════════════════════════════════════════════════════════


class TestStockCollectorCoverage:
    def test_yfinance_fallback_multiindex(self, monkeypatch, db_with_portfolio):
        """OpenBB 실패 → yfinance MultiIndex 컬럼 폴백."""
        from nuri.collectors.stock import StockCollector

        collector = StockCollector()

        # OpenBB 실패
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(
            obb=MagicMock(equity=MagicMock(price=MagicMock(
                historical=MagicMock(side_effect=Exception("OpenBB down")),
            ))),
        ))

        # yfinance 성공 — MultiIndex 컬럼
        raw = pd.DataFrame(
            {"Close": [195.0], "Open": [190.0], "High": [196.0],
             "Low": [189.0], "Volume": [50000000]},
            index=pd.DatetimeIndex(["2025-01-15"], name="Date"),
        )

        import yfinance
        monkeypatch.setattr(yfinance, "download", MagicMock(return_value=raw))

        result = collector._collect_ticker("AAPL", "2025-01-01", "2025-01-31")
        assert result is not None
        assert not result.empty

    def test_yfinance_fallback_also_fails(self, monkeypatch, db_with_portfolio):
        """OpenBB + yfinance 모두 실패 → None."""
        from nuri.collectors.stock import StockCollector

        collector = StockCollector()
        monkeypatch.setitem(sys.modules, "openbb", MagicMock(
            obb=MagicMock(equity=MagicMock(price=MagicMock(
                historical=MagicMock(side_effect=Exception("OpenBB down")),
            ))),
        ))
        import yfinance
        monkeypatch.setattr(yfinance, "download", MagicMock(side_effect=Exception("yfinance down")))

        result = collector._collect_ticker("AAPL", "2025-01-01", "2025-01-31")
        assert result is None

    def test_standardize_missing_columns(self, db_with_portfolio):
        """_standardize: 누락 컬럼 → None으로 채움 (line 111)."""
        from nuri.collectors.stock import StockCollector
        df = pd.DataFrame({"date": ["2025-01-15"], "close": [195.0]})
        result = StockCollector()._standardize(df, "AAPL")
        assert "adj_close" in result.columns
        assert result["open"].iloc[0] is None or pd.isna(result["open"].iloc[0])

    def test_save_empty(self, db_with_portfolio):
        """save: 빈 DataFrame → 0 (line 133)."""
        from nuri.collectors.stock import StockCollector
        assert StockCollector().save(pd.DataFrame()) == 0

    def test_main_block(self, monkeypatch, db_with_portfolio):
        """__main__ block (lines 137-148)."""
        monkeypatch.setattr(sys, "argv", ["stock", "--period", "1mo"])
        with patch("nuri.collectors.base.BaseCollector.run", return_value=5):
            runpy.run_module("nuri.collectors.stock", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# collectors/stock_kr.py — lines 92-103 (__main__ block)
# ═══════════════════════════════════════════════════════════


class TestStockKRMain:
    def test_main_block(self, monkeypatch, db_with_portfolio):
        monkeypatch.setattr(sys, "argv", ["stock_kr", "--days", "30"])
        with patch("nuri.collectors.base.BaseCollector.run", return_value=3):
            runpy.run_module("nuri.collectors.stock_kr", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# collectors/wallstreet.py — lines 187-195 (__main__ block)
# ═══════════════════════════════════════════════════════════


class TestWallstreetMain:
    def test_main_block(self, monkeypatch, db_with_portfolio, capsys):
        monkeypatch.setattr(sys, "argv", ["wallstreet"])
        rows = [{"c": 10}]
        with patch("nuri.collectors.base.BaseCollector.run", return_value=10), \
             patch("nuri.core.db.query", return_value=rows):
            runpy.run_module("nuri.collectors.wallstreet", run_name="__main__")
        out = capsys.readouterr().out
        assert "10건" in out


# ═══════════════════════════════════════════════════════════
# Simple collector __main__ blocks (just logging + collector.run())
# ═══════════════════════════════════════════════════════════


class TestSimpleCollectorMains:
    @pytest.mark.parametrize("module", [
        "nuri.collectors.ark",
        "nuri.collectors.cboe",
        "nuri.collectors.coingecko",
        "nuri.collectors.fear_greed",
        "nuri.collectors.finviz",
        "nuri.collectors.fred_calendar",
        "nuri.collectors.macro",
        "nuri.collectors.news",
        "nuri.collectors.reddit",
        "nuri.collectors.technical",
        "nuri.collectors.events",
    ])
    def test_main_block(self, monkeypatch, db_with_portfolio, module):
        monkeypatch.setattr(sys, "argv", [module.split(".")[-1]])
        with patch("nuri.collectors.base.BaseCollector.run", return_value=1):
            runpy.run_module(module, run_name="__main__")


# ═══════════════════════════════════════════════════════════
# collectors/filings.py — lines 144-158 (__main__ block)
# ═══════════════════════════════════════════════════════════


class TestFilingsMain:
    def test_main_with_ticker(self, monkeypatch, db_with_portfolio):
        monkeypatch.setattr(sys, "argv", ["filings", "--ticker", "AAPL"])
        with patch("nuri.collectors.filings.parse_10k",
                   return_value={"ticker": "AAPL", "filing_date": "2025-01-01", "form": "10-K"}), \
             patch("nuri.collectors.filings.print_filings"):
            runpy.run_module("nuri.collectors.filings", run_name="__main__")

    def test_main_with_ticker_no_result(self, monkeypatch, db_with_portfolio, capsys):
        monkeypatch.setattr(sys, "argv", ["filings", "--ticker", "AAPL"])
        # parse_10k는 같은 모듈에서 정의 → 내부 의존성 (edgar) 을 mock
        mock_company = MagicMock()
        mock_company.return_value.get_filings.return_value = []
        with patch("edgar.Company", mock_company), \
             patch("edgar.set_identity"):
            runpy.run_module("nuri.collectors.filings", run_name="__main__")
        out = capsys.readouterr().out
        assert "10-K 없음" in out

    def test_main_all_tickers(self, monkeypatch, db_with_portfolio):
        monkeypatch.setattr(sys, "argv", ["filings"])
        with patch("nuri.collectors.filings.collect_filings", return_value=[]), \
             patch("nuri.collectors.filings.print_filings"):
            runpy.run_module("nuri.collectors.filings", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# collectors/institutional.py — lines 148-159 (__main__ block)
# ═══════════════════════════════════════════════════════════


class TestInstitutionalMain:
    def test_main_with_count(self, monkeypatch, db_with_portfolio, capsys):
        monkeypatch.setattr(sys, "argv", ["institutional"])
        with patch("nuri.collectors.base.BaseCollector.run", return_value=5):
            runpy.run_module("nuri.collectors.institutional", run_name="__main__")
        out = capsys.readouterr().out
        assert "수집 완료: 5건" in out

    def test_main_zero_count(self, monkeypatch, db_with_portfolio, capsys):
        monkeypatch.setattr(sys, "argv", ["institutional"])
        with patch("nuri.collectors.base.BaseCollector.run", return_value=0):
            runpy.run_module("nuri.collectors.institutional", run_name="__main__")
        out = capsys.readouterr().out
        assert "수집 완료: 0건" in out
        assert "pykrx" in out


# ═══════════════════════════════════════════════════════════
# collectors/etf_flows.py — lines 189-196 (__main__ block)
# ═══════════════════════════════════════════════════════════


class TestEtfFlowsMain:
    def test_main_block(self, monkeypatch, db_with_portfolio):
        monkeypatch.setattr(sys, "argv", ["etf_flows"])
        with patch("nuri.collectors.base.BaseCollector.run", return_value=5), \
             patch("nuri.collectors.etf_flows.analyze_sector_rotation", return_value={}), \
             patch("nuri.collectors.etf_flows.print_sector_rotation"):
            runpy.run_module("nuri.collectors.etf_flows", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# collectors/superinvestors.py — lines 279-286 (__main__)
# ═══════════════════════════════════════════════════════════


class TestSuperinvestorsMain:
    def test_main_block(self, monkeypatch, db_with_portfolio):
        monkeypatch.setattr(sys, "argv", ["superinvestors"])
        with patch("nuri.collectors.base.BaseCollector.run", return_value=10), \
             patch("nuri.collectors.superinvestors.print_summary"):
            runpy.run_module("nuri.collectors.superinvestors", run_name="__main__")


# ═══════════════════════════════════════════════════════════
# alerts/discord_bot.py — lines 97-108 (__main__ block)
# ═══════════════════════════════════════════════════════════


class TestDiscordBotMain:
    def test_main_webhook(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["discord_bot", "--webhook", "--message", "test"])
        with patch("nuri.alerts.discord_bot.send_webhook_text", return_value=True):
            runpy.run_module("nuri.alerts.discord_bot", run_name="__main__")

    def test_main_no_args(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["discord_bot"])
        runpy.run_module("nuri.alerts.discord_bot", run_name="__main__")
        out = capsys.readouterr().out
        assert "사용법" in out


# ═══════════════════════════════════════════════════════════
# alerts/daily_report.py — lines 128-132 (__main__ block)
# ═══════════════════════════════════════════════════════════


class TestDailyReportMain:
    def test_main_block(self, monkeypatch, db_with_portfolio):
        """main() 직접 호출 — runpy는 CI에서 모듈 캐시 문제로 불안정."""
        from nuri.alerts.daily_report import main

        with patch("nuri.alerts.daily_report.generate_report", return_value={}), \
             patch("nuri.alerts.daily_report.send_discord", return_value=True):
            main()


# ═══════════════════════════════════════════════════════════
# api/main.py — lines 143-147 (__main__ block)
# ═══════════════════════════════════════════════════════════


class TestAPIMain:
    def test_main_block(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["main"])
        with patch("uvicorn.run") as mock_run:
            runpy.run_module("nuri.api.main", run_name="__main__")
        mock_run.assert_called_once()
