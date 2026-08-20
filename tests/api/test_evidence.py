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
