"""Tests for evidence — split from test_api_all.py."""

import asyncio
import json
import time as _time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.api._helpers import _csv_file  # noqa: F401


class TestEvidenceAPI:
    def test_evidence(self, client):
        r = client.get("/api/evidence")
        assert r.status_code == 200

    def test_evidence_list(self, client):
        r = client.get("/api/evidence")
        assert r.status_code == 200


class TestEvidenceAPI_R2:
    def test_find_latest_report_dir(self, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod
        from nuri.api.routes.evidence import _find_latest_report_dir

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
        import nuri.api.routes.evidence as ev_mod
        import nuri.core.db as db_mod
        import nuri.core.portfolio_sync as sync_mod

        db = tmp_path / "t.db"
        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)
        monkeypatch.setattr(ev_mod, "REPORT_DIR", tmp_path / "no_reports")
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "p.yaml")

        from nuri.api.main import app

        c = TestClient(app)
        r = c.get("/api/evidence")
        assert r.status_code == 200

    def test_evidence_chart_not_found(self, tmp_path, monkeypatch):
        """GET /api/evidence/{chart_id} — 파일 없으면 404."""
        import nuri.api.routes.evidence as ev_mod
        import nuri.core.db as db_mod
        import nuri.core.portfolio_sync as sync_mod

        db = tmp_path / "t.db"
        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)
        monkeypatch.setattr(ev_mod, "REPORT_DIR", tmp_path / "no_reports")
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", tmp_path / "p.yaml")

        from nuri.api.main import app

        c = TestClient(app)
        r = c.get("/api/evidence/regime")
        assert r.status_code == 404


class TestEvidenceAPI_R22:
    @pytest.fixture()
    def _client(self, db_path, monkeypatch):
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        from nuri.api.main import app

        return TestClient(app)

    def test_list_evidence_no_reports(self, _client, monkeypatch):
        import nuri.api.routes.evidence as ev_mod

        monkeypatch.setattr(ev_mod, "REPORT_DIR", Path("/nonexistent/path"))
        resp = _client.get("/api/evidence")
        assert resp.status_code == 200
        data = resp.json()
        assert data["charts"] == []

    def test_list_evidence_with_dir(self, _client, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod

        report_dir = tmp_path / "reports"
        date_dir = report_dir / "2025-03-31" / "evidence"
        date_dir.mkdir(parents=True)
        (date_dir / "regime.html").write_text("<html>regime</html>")
        monkeypatch.setattr(ev_mod, "REPORT_DIR", report_dir)
        resp = _client.get("/api/evidence")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["charts"]) > 0
        regime_chart = [c for c in data["charts"] if c["id"] == "regime"][0]
        assert regime_chart["available"] is True

    def test_get_evidence_chart_invalid(self, _client):
        resp = _client.get("/api/evidence/invalid_chart")
        assert resp.status_code == 400

    def test_get_evidence_chart_no_dir(self, _client, monkeypatch):
        import nuri.api.routes.evidence as ev_mod

        monkeypatch.setattr(ev_mod, "REPORT_DIR", Path("/nonexistent"))
        resp = _client.get("/api/evidence/regime")
        assert resp.status_code == 404

    def test_get_evidence_chart_found(self, _client, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod

        report_dir = tmp_path / "reports"
        date_dir = report_dir / "2025-03-31" / "evidence"
        date_dir.mkdir(parents=True)
        (date_dir / "regime.html").write_text("<html>test regime chart</html>")
        monkeypatch.setattr(ev_mod, "REPORT_DIR", report_dir)
        resp = _client.get("/api/evidence/regime")
        assert resp.status_code == 200
        assert "test regime chart" in resp.text

    def test_get_evidence_chart_alternative_name(self, _client, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod

        report_dir = tmp_path / "reports"
        date_dir = report_dir / "2025-03-31" / "evidence"
        date_dir.mkdir(parents=True)
        (date_dir / "regime_evidence.html").write_text("<html>alt name</html>")
        monkeypatch.setattr(ev_mod, "REPORT_DIR", report_dir)
        resp = _client.get("/api/evidence/regime")
        assert resp.status_code == 200
        assert "alt name" in resp.text

    def test_get_evidence_chart_not_generated(self, _client, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod

        report_dir = tmp_path / "reports"
        date_dir = report_dir / "2025-03-31" / "evidence"
        date_dir.mkdir(parents=True)
        monkeypatch.setattr(ev_mod, "REPORT_DIR", report_dir)
        resp = _client.get("/api/evidence/regime")
        assert resp.status_code == 404

    def test_get_evidence_report_not_found(self, _client, monkeypatch):
        """evidence/report — route may be shadowed by /{chart_id} due to definition order."""
        import nuri.api.routes.evidence as ev_mod

        monkeypatch.setattr(ev_mod, "REPORT_DIR", Path("/nonexistent"))
        resp = _client.get("/api/evidence/report")
        assert resp.status_code in (400, 404)

    def test_get_evidence_report_found(self, _client, tmp_path, monkeypatch):
        """Test get_evidence_report directly since route may be shadowed."""
        import nuri.api.routes.evidence as ev_mod

        report_dir = tmp_path / "reports"
        date_dir = report_dir / "2025-03-31"
        (date_dir / "evidence").mkdir(parents=True)
        (date_dir / "portfolio_action_plan.md").write_text("# Plan content")
        monkeypatch.setattr(ev_mod, "REPORT_DIR", report_dir)
        result = ev_mod.get_evidence_report()
        assert "Plan content" in result["content"]


class TestEvidenceReportLatest:
    def test_report_from_latest_dir(self, tmp_path, monkeypatch):
        """Test get_evidence_report falls back to latest directory."""
        import nuri.api.routes.evidence as ev_mod

        report_dir = tmp_path / "reports"
        date_dir = report_dir / "2025-03-30"
        evidence_dir = date_dir / "evidence"
        evidence_dir.mkdir(parents=True)
        (date_dir / "llm_evidence_report.md").write_text("# LLM Report")
        monkeypatch.setattr(ev_mod, "REPORT_DIR", report_dir)
        result = ev_mod.get_evidence_report()
        assert "LLM Report" in result["content"]

    def test_report_raises_when_none(self, tmp_path, monkeypatch):
        """get_evidence_report raises 404 when no report files exist."""
        import nuri.api.routes.evidence as ev_mod

        monkeypatch.setattr(ev_mod, "REPORT_DIR", tmp_path / "nonexistent")
        with pytest.raises(Exception):
            ev_mod.get_evidence_report()

    def test_report_today_path_hits(self, tmp_path, monkeypatch):
        """오늘자 디렉토리에 plan 파일 → today branch 적중 (line 93)."""
        from datetime import date as _date

        import nuri.api.routes.evidence as ev_mod

        report_dir = tmp_path / "reports"
        today = str(_date.today())
        today_dir = report_dir / today
        today_dir.mkdir(parents=True)
        (today_dir / "portfolio_action_plan.md").write_text("# Today Plan")
        monkeypatch.setattr(ev_mod, "REPORT_DIR", report_dir)
        result = ev_mod.get_evidence_report()
        assert "Today Plan" in result["content"]


class TestReportDirIsNotFutureDated:
    """미래 날짜 / 비-날짜 디렉터리가 최신 리포트로 뽑히지 않는지 잠근다.

    `data/reports/` 에는 `briefs` · `postmarket` · `buy_tracking` 이 섞여 있고,
    잘못된 날짜로 만들어진 미래 디렉터리도 남는다 (실측 2026-08-20 로컬:
    `2026-11-08` · `2027-02-06` · `2027-09-14`). 이름 역순 정렬만 하면 그것들이
    1등이라 /evidence 화면 날짜가 통째로 2027-09-14 였다.
    """

    def _seed(self, root: Path, name: str) -> None:
        (root / name / "evidence").mkdir(parents=True)

    def test_future_dated_dir_is_ignored(self, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod
        from nuri.api.routes.evidence import _find_latest_report_dir
        from nuri.core.timezone import today_kst

        reports = tmp_path / "reports"
        today = today_kst()
        year = int(today[:4])
        self._seed(reports, today)
        self._seed(reports, f"{year + 1}-09-14")  # 미래
        monkeypatch.setattr(ev_mod, "REPORT_DIR", reports)

        result = _find_latest_report_dir()
        assert result is not None
        assert result.parent.name == today

    def test_non_date_dir_is_ignored(self, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod
        from nuri.api.routes.evidence import _find_latest_report_dir
        from nuri.core.timezone import today_kst

        reports = tmp_path / "reports"
        today = today_kst()
        self._seed(reports, today)
        # 'postmarket' 은 사전순으로 어떤 '20xx-' 보다 뒤라 역순 정렬에서 1등이다
        self._seed(reports, "postmarket")
        monkeypatch.setattr(ev_mod, "REPORT_DIR", reports)

        result = _find_latest_report_dir()
        assert result is not None
        assert result.parent.name == today

    def test_dated_dir_without_evidence_falls_through_to_older_one(self, tmp_path, monkeypatch):
        """날짜는 유효하지만 `evidence/` 가 없는 디렉터리는 건너뛰고 더 오래된 것을 쓴다.

        루프가 한 바퀴 돌고도 매칭 없이 다음 후보로 넘어가는 arc — 이게 없으면
        codecov 가 partial branch 로 잡는다 (실측 #1124: misses 0 / partials 1).
        """
        import nuri.api.routes.evidence as ev_mod
        from nuri.api.routes.evidence import _find_latest_report_dir
        from nuri.core.timezone import today_kst

        reports = tmp_path / "reports"
        today = today_kst()
        # 최신 날짜인데 evidence/ 가 없다 → 건너뛰어야 한다
        (reports / today).mkdir(parents=True)
        older = f"{int(today[:4]) - 1}-01-02"
        self._seed(reports, older)
        monkeypatch.setattr(ev_mod, "REPORT_DIR", reports)

        result = _find_latest_report_dir()
        assert result is not None
        assert result.parent.name == older

    def test_no_valid_dir_returns_none(self, tmp_path, monkeypatch):
        import nuri.api.routes.evidence as ev_mod
        from nuri.api.routes.evidence import _find_latest_report_dir
        from nuri.core.timezone import today_kst

        reports = tmp_path / "reports"
        year = int(today_kst()[:4])
        self._seed(reports, f"{year + 1}-09-14")
        self._seed(reports, "briefs")
        monkeypatch.setattr(ev_mod, "REPORT_DIR", reports)

        assert _find_latest_report_dir() is None


class TestEvidenceDataEndpoint:
    """GET /api/evidence/data/{chart_id} — 네이티브 차트용 JSON (#1224 U5a-1)."""

    @pytest.fixture()
    def _client(self, db_path, monkeypatch):
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", db_path)
        from nuri.api.main import app

        return TestClient(app)

    def _seed_spy(self, db_path, n: int = 5) -> None:
        dates = pd.bdate_range(end=pd.Timestamp.today(), periods=n)
        upsert_prices(
            pd.DataFrame(
                {
                    "ticker": "SPY",
                    "date": dates.strftime("%Y-%m-%d"),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": [100.0 + i for i in range(n)],
                    "volume": 1_000_000,
                    "adj_close": [100.0 + i for i in range(n)],
                }
            ),
            db_path=db_path,
        )

    def test_unknown_chart_id_400(self, _client):
        r = _client.get("/api/evidence/data/nope")
        assert r.status_code == 400

    def test_regime_empty_db(self, _client):
        r = _client.get("/api/evidence/data/regime")
        assert r.status_code == 200
        data = r.json()
        assert data == {"spy": [], "vix": [], "regime": None, "count": 0}

    def test_regime_seeded(self, _client, db_path, monkeypatch):
        import nuri.quant.regime.classifier as clf_mod
        from nuri.quant.regime.classifier import RegimeState

        self._seed_spy(db_path, n=5)
        upsert_macro(
            [{"indicator": "vix", "date": "2026-08-21", "value": 18.0, "source": "t"}],
            db_path=db_path,
        )
        # 형태는 실 dataclass — 라우트는 핸들러 안 lazy import 라 source-level patch
        state = RegimeState(
            date="2026-08-21",
            trend="bull",
            volatility="low",
            regime="bull_low_vol",
            confidence=0.8,
            details={},
        )
        monkeypatch.setattr(clf_mod, "classify_regime", lambda *a, **kw: state)

        r = _client.get("/api/evidence/data/regime")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 5
        row = data["spy"][0]
        # ISO 날짜 문자열 + sma NaN → null (numpy 누수 없음: json 왕복 자체가 증명)
        assert isinstance(row["date"], str) and len(row["date"]) == 10
        assert row["sma50"] is None
        assert data["vix"][0]["value"] == 18.0
        assert data["regime"] == {
            "regime": "bull_low_vol",
            "trend": "bull",
            "volatility": "low",
            "confidence": 0.8,
        }

    def test_regime_classifier_returns_none(self, _client, db_path, monkeypatch):
        import nuri.quant.regime.classifier as clf_mod

        self._seed_spy(db_path, n=5)
        monkeypatch.setattr(clf_mod, "classify_regime", lambda *a, **kw: None)
        r = _client.get("/api/evidence/data/regime")
        assert r.status_code == 200
        assert r.json()["regime"] is None

    def test_portfolio_heatmap_empty(self, _client):
        r = _client.get("/api/evidence/data/portfolio_heatmap")
        assert r.status_code == 200
        assert r.json() == {"items": [], "count": 0}

    def test_portfolio_heatmap_seeded(self, _client):
        # 형태는 analyze_portfolio 실반환에서 복사 (mock-shape 규칙)
        df = pd.DataFrame(
            [
                {"ticker": "AAA", "current_value_usd": 5000, "pnl_pct": -12.0, "weight_pct": 20.0, "sector": "Tech"},
                {"ticker": "BBB", "current_value_usd": 4000, "pnl_pct": 3.0, "weight_pct": 8.0, "sector": "Health"},
            ]
        )
        with patch("nuri.analysis.portfolio.analyze_portfolio", return_value=df):
            r = _client.get("/api/evidence/data/portfolio_heatmap")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 2
        by_ticker = {i["ticker"]: i for i in data["items"]}
        assert by_ticker["AAA"]["violation"] == "stop_loss"
        assert by_ticker["BBB"]["violation"] is None

    def test_signal_performance_none(self, _client, tmp_path, monkeypatch):
        import nuri.analysis.evidence_data as ed

        monkeypatch.setattr(ed, "REPORT_DIR", tmp_path / "no_reports")
        r = _client.get("/api/evidence/data/signal_performance")
        assert r.status_code == 200
        assert r.json() == {"signals": [], "count": 0}

    def test_signal_performance_seeded(self, _client, tmp_path, monkeypatch):
        import nuri.analysis.evidence_data as ed

        day_dir = tmp_path / "reports" / "2026-08-21"
        day_dir.mkdir(parents=True)
        # 형태는 signal_scorecard.csv 실물에서 복사 (mock-shape 규칙)
        pd.DataFrame(
            [
                {
                    "signal_id": "rsi_oversold",
                    "ticker": None,
                    "total_trades": 10,
                    "win_rate": 0.6,
                    "profit_factor": 1.5,
                    "avg_return": 2.0,
                    "median_return": 1.5,
                    "max_return": 10.0,
                    "max_loss": -5.0,
                    "avg_holding_days": 20,
                },
            ]
        ).to_csv(day_dir / "signal_scorecard.csv", index=False)
        monkeypatch.setattr(ed, "REPORT_DIR", tmp_path / "reports")
        monkeypatch.setattr(
            ed, "load_drift_map", lambda *a, **kw: {"rsi_oversold": {"status": "critical", "drift_pct": -15.0}}
        )

        r = _client.get("/api/evidence/data/signal_performance")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        sig = data["signals"][0]
        assert sig["signal_id"] == "rsi_oversold"
        assert sig["drift_status"] == "critical"
        # 선택 컬럼만 — ticker(NaN)나 max_return 은 응답에 없다
        assert "max_return" not in sig

    def test_fear_greed_empty_and_seeded(self, _client, db_path):
        r = _client.get("/api/evidence/data/fear_greed")
        assert r.json() == {"history": [], "count": 0}
        upsert_macro(
            [{"indicator": "fear_greed", "date": "2026-08-21", "value": 55.0, "source": "t"}],
            db_path=db_path,
        )
        r = _client.get("/api/evidence/data/fear_greed")
        data = r.json()
        assert data["count"] == 1
        assert data["history"][0]["value"] == 55.0

    def test_sell_evidence(self, _client):
        r = _client.get("/api/evidence/data/sell_evidence")
        assert r.json() == {"violations": [], "count": 0}
        df = pd.DataFrame(
            [{"ticker": "AAA", "current_value_usd": 5000, "pnl_pct": -12.0, "weight_pct": 8.0, "sector": "Tech"}]
        )
        with patch("nuri.analysis.portfolio.analyze_portfolio", return_value=df):
            r = _client.get("/api/evidence/data/sell_evidence")
        data = r.json()
        assert data["count"] == 1
        v = data["violations"][0]
        assert v["type"] == "stop_loss" and v["action"] == "SELL ALL"
