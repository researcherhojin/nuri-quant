"""커버리지 보강 Round 2 — analysis/trading/api 모듈."""
from unittest.mock import patch

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
    # 가격 데이터
    dates = pd.date_range("2026-01-01", periods=100, freq="B")
    rows = []
    for t in ["AAPL", "NVDA"]:
        base = 190 if t == "AAPL" else 130
        for i, d in enumerate(dates):
            p = base + i * 0.5
            rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p+2, "low": p-1,
                         "close": p+1, "volume": 1000000, "adj_close": p+1})
    upsert_prices(pd.DataFrame(rows), path)
    return path


# ─── Sentiment (pure function) ───


class TestSentiment:
    def test_compute_positive(self):
        from nuri.analysis.sentiment import compute_sentiment
        score = compute_sentiment("Strong growth beats expectations with record revenue")
        assert score > 0

    def test_compute_negative(self):
        from nuri.analysis.sentiment import compute_sentiment
        score = compute_sentiment("Company faces lawsuit and massive debt crisis")
        assert score < 0

    def test_compute_neutral(self):
        from nuri.analysis.sentiment import compute_sentiment
        # 키워드 사전에 없는 단어만 사용
        score = compute_sentiment("xyz abc 123")
        assert score == 0.0

    def test_compute_empty(self):
        from nuri.analysis.sentiment import compute_sentiment
        assert compute_sentiment("") == 0.0


# ─── Scheduler ───


class TestScheduler:
    def test_schedules_structure(self):
        from nuri.scheduler import SCHEDULES
        assert len(SCHEDULES) >= 17
        for s in SCHEDULES:
            assert "name" in s
            assert "func" in s
            assert "cron" in s

    def test_run_collector_unknown(self):
        """존재하지 않는 collector → 에러 로그만, 예외 없음."""
        from nuri.scheduler import _run_collector
        # 존재하지 않는 collector 이름 → 로그만 남기고 반환
        _run_collector("nonexistent_collector_xyz")

    def test_write_heartbeat(self, tmp_path, monkeypatch):
        from nuri.scheduler import _write_heartbeat
        hb_path = tmp_path / ".scheduler_heartbeat"
        monkeypatch.setattr("nuri.scheduler.HEARTBEAT_PATH", hb_path)
        _write_heartbeat()
        assert hb_path.exists()
        content = hb_path.read_text()
        assert len(content) > 0


# ─── Correlation ───


class TestCorrelation:
    def test_analyze_with_data(self, db_path):
        from nuri.analysis.correlation import analyze_correlation
        corr, warnings = analyze_correlation(min_days=10)
        assert isinstance(corr, pd.DataFrame)
        assert isinstance(warnings, list)
        # 2종목이므로 2x2 행렬
        assert corr.shape == (2, 2)

    def test_print_correlation(self, capsys):
        from nuri.analysis.correlation import print_correlation
        corr = pd.DataFrame({"AAPL": [1.0, 0.9], "NVDA": [0.9, 1.0]},
                             index=["AAPL", "NVDA"])
        warnings = [{"ticker_a": "AAPL", "ticker_b": "NVDA", "correlation": 0.9}]
        print_correlation(corr, warnings)
        output = capsys.readouterr().out
        assert "AAPL" in output


# ─── Sector ───


class TestSector:
    def test_analyze_sector(self, db_path):
        from nuri.analysis.sector import analyze_sector
        with patch("nuri.analysis.sector.get_exchange_rate", return_value=1400.0):
            sector_df, region_df, warnings = analyze_sector()
        assert isinstance(sector_df, pd.DataFrame)
        assert isinstance(region_df, pd.DataFrame)
        assert isinstance(warnings, list)


# ─── Performance ───


class TestPerformance:
    def test_get_portfolio_returns(self, db_path):
        from nuri.analysis.performance import get_portfolio_returns
        returns = get_portfolio_returns(days=30)
        assert isinstance(returns, pd.Series)

    def test_get_benchmark_returns(self, db_path):
        """VOO가 없으면 빈 Series."""
        from nuri.analysis.performance import get_benchmark_returns
        result = get_benchmark_returns()
        assert isinstance(result, pd.Series)


# ─── Evidence API ───


class TestEvidenceAPI:
    def test_find_latest_report_dir(self, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod
        from nuri.api.routes.evidence import _find_latest_report_dir
        # evidence 하위 디렉토리까지 생성
        evidence_dir = tmp_path / "reports" / "2026-03-31" / "evidence"
        evidence_dir.mkdir(parents=True)
        monkeypatch.setattr(ev_mod, "REPORT_DIR", tmp_path / "reports")
        result = _find_latest_report_dir()
        assert result is not None
        assert "2026-03-31" in str(result)

    def test_find_no_reports(self, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod
        from nuri.api.routes.evidence import _find_latest_report_dir
        empty_dir = tmp_path / "empty_reports"
        empty_dir.mkdir()
        monkeypatch.setattr(ev_mod, "REPORT_DIR", empty_dir)
        assert _find_latest_report_dir() is None

    def test_evidence_list_endpoint(self, tmp_path, monkeypatch):
        """GET /api/evidence — 리포트 없을 때."""
        from fastapi.testclient import TestClient

        import nuri.api.routes.evidence as ev_mod
        import nuri.core.db as db_mod
        from nuri.core.db import init_db

        db = tmp_path / "t.db"
        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)
        monkeypatch.setattr(ev_mod, "REPORT_DIR", tmp_path / "no_reports")

        import nuri.core.portfolio_sync as sync_mod
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "p.yaml")

        from nuri.api.main import app
        client = TestClient(app)
        r = client.get("/api/evidence")
        assert r.status_code == 200

    def test_evidence_chart_not_found(self, tmp_path, monkeypatch):
        """GET /api/evidence/{chart_id} — 파일 없으면 404."""
        from fastapi.testclient import TestClient

        import nuri.api.routes.evidence as ev_mod
        import nuri.core.db as db_mod
        from nuri.core.db import init_db

        db = tmp_path / "t.db"
        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)
        monkeypatch.setattr(ev_mod, "REPORT_DIR", tmp_path / "no_reports")

        import nuri.core.portfolio_sync as sync_mod
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "p.yaml")

        from nuri.api.main import app
        client = TestClient(app)
        r = client.get("/api/evidence/regime")
        assert r.status_code == 404


# ─── Dashboard internals ───


class TestDashboardInternals:
    def test_get_allocation(self):
        from nuri.api.routes.dashboard import _get_allocation
        result = _get_allocation("bull_low_vol")
        assert "long" in result
        assert "short" in result
        assert "cash" in result

    def test_get_allocation_unknown(self):
        from nuri.api.routes.dashboard import _get_allocation
        result = _get_allocation("unknown_regime")
        # 기본값 반환
        assert "long" in result


# ─── Position ───


class TestPosition:
    def test_certify_position_no_data(self, db_path):
        """데이터 없을 때 certification 결과."""
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("AAPL", "long", "bull_low_vol", "growth")
        # certification 객체 반환
        assert hasattr(cert, "certified")
        assert hasattr(cert, "regime_aligned")

    def test_open_position_rejected(self, db_path):
        """certification 실패 시 False 반환."""
        from nuri.trading.strategy.position import open_position
        # agent consensus 없으면 rejected
        result = open_position("FAKE", "long", 100.0, 10, "growth", "bull_low_vol")
        assert result is False

    def test_get_positions_summary_empty(self, db_path):
        """빈 DB에서 summary."""
        from nuri.trading.strategy.position import get_positions_summary
        summary = get_positions_summary()
        assert isinstance(summary, dict)
        assert summary.get("total_open", 0) == 0

    def test_close_position_nonexistent(self, db_path):
        """존재하지 않는 position 닫기."""
        from nuri.trading.strategy.position import close_position
        # 에러 없이 처리
        close_position(99999, 100.0, "test")
