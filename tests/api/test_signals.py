"""Tests for signals — split from test_api_all.py."""

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


class TestSignals:
    def test_candidates_empty(self, client):
        r = client.get("/api/candidates")
        assert r.status_code == 200
        data = r.json()
        assert "candidates" in data
        assert "count" in data

    def test_candidates_query_param(self, client):
        r = client.get("/api/candidates?days=10")
        assert r.status_code == 200

    def test_candidates_invalid_days(self, client):
        r = client.get("/api/candidates?days=100")
        assert r.status_code == 422

    def test_scorecard_no_data(self, client):
        r = client.get("/api/scorecard")
        assert r.status_code == 200
        data = r.json()
        assert "error" in data or "scorecard" in data

    def test_cross_analysis(self, client):
        r = client.get("/api/cross-analysis")
        assert r.status_code == 200

    def test_scorecard_no_report_dir(self, client, monkeypatch, tmp_path):
        """report dir 없을 때 error 반환 (line 32)."""
        from pathlib import Path as RealPath

        # Patch `Path` in pathlib so that lookups inside the route
        # return a path under tmp_path which has no data/reports folder.
        nonexistent = tmp_path / "no_reports_here"

        def fake_path(arg):
            # arg = __file__ → return wrapper whose .parent.parent... → nonexistent
            class _W:
                @property
                def parent(self):
                    return self

                def __truediv__(self, other):
                    return nonexistent / other

            return _W()

        monkeypatch.setattr("pathlib.Path", fake_path)
        r = client.get("/api/scorecard")
        assert r.status_code == 200
        assert r.json() == {"error": "report 디렉토리 없음"}

    def test_scorecard_with_csv(self, client, monkeypatch, tmp_path):
        """report dir + csv 존재 시 scorecard records 반환 (lines 34-45)."""
        report_root = tmp_path / "reports"
        sub = report_root / "2026-05-04"
        sub.mkdir(parents=True)
        csv = sub / "signal_scorecard.csv"
        csv.write_text("ticker,score\n,75.0\nAAPL,80.0\n")

        def fake_path(arg):
            class _W:
                @property
                def parent(self):
                    return self

                def __truediv__(self, other):
                    if other == "data":
                        return _Mid()
                    return tmp_path / other

            class _Mid:
                def __truediv__(self, other):
                    if other == "reports":
                        return report_root
                    return tmp_path / other

            return _W()

        monkeypatch.setattr("pathlib.Path", fake_path)
        r = client.get("/api/scorecard")
        assert r.status_code == 200
        data = r.json()
        assert "scorecard" in data
        assert data["date"] == "2026-05-04"

    def test_scorecard_dir_exists_but_no_csv(self, client, monkeypatch, tmp_path):
        """dir 존재 but csv 없음 → 'csv 없음' 메시지 (line 47)."""
        report_root = tmp_path / "reports"
        sub = report_root / "2026-05-04"
        sub.mkdir(parents=True)
        # No CSV file

        def fake_path(arg):
            class _W:
                @property
                def parent(self):
                    return self

                def __truediv__(self, other):
                    if other == "data":
                        return _Mid()
                    return tmp_path / other

            class _Mid:
                def __truediv__(self, other):
                    if other == "reports":
                        return report_root
                    return tmp_path / other

            return _W()

        monkeypatch.setattr("pathlib.Path", fake_path)
        r = client.get("/api/scorecard")
        assert r.status_code == 200
        data = r.json()
        assert "error" in data
        assert "scorecard.csv" in data["error"]

    def test_cross_analysis_empty(self, client, monkeypatch):
        """analyze_signal_by_regime 가 빈 df → error (line 56)."""
        monkeypatch.setattr(
            "nuri.quant.regime.strategy_map.analyze_signal_by_regime",
            lambda: pd.DataFrame(),
        )
        r = client.get("/api/cross-analysis")
        assert r.status_code == 200
        assert "error" in r.json()

    def test_cross_analysis_with_data(self, client, monkeypatch):
        """analyze_signal_by_regime 가 dataframe → data records (line 57)."""
        monkeypatch.setattr(
            "nuri.quant.regime.strategy_map.analyze_signal_by_regime",
            lambda: pd.DataFrame([{"signal": "rsi", "regime": "bull", "win_rate": 0.6}]),
        )
        r = client.get("/api/cross-analysis")
        assert r.status_code == 200
        assert "data" in r.json()
