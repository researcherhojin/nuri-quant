"""Tests for nuri.api.routes.coverage — #272 Phase 4 UX backend.

Exposes `compute_all_data_coverage()` results via REST so the Dashboard
widget can render PASS/FAIL status + KR "n/a (US-only)" labels.
"""

from __future__ import annotations

import yaml


class TestCoverageEndpoint:
    def test_returns_200_and_shape(self, client, tmp_path, monkeypatch):
        """GET /api/coverage returns {pass, fail, exit_code, checks[]}."""
        # Write temp universe.yaml so compute_all_data_coverage has something
        cfg = tmp_path / "config"
        cfg.mkdir(exist_ok=True)
        (cfg / "universe.yaml").write_text(
            yaml.safe_dump(
                {
                    "us_core": {"tickers": ["AAPL", "MSFT"]},
                    "kr_kospi200": {"tickers": ["005930.KS"]},
                }
            )
        )
        monkeypatch.chdir(tmp_path)

        r = client.get("/api/coverage")
        assert r.status_code == 200
        data = r.json()
        assert set(data.keys()) >= {"pass", "fail", "exit_code", "checks"}
        assert isinstance(data["checks"], list)
        assert len(data["checks"]) == 5  # 5 data tables per Spec §2.2

    def test_each_check_has_us_only_flag(self, client, tmp_path, monkeypatch):
        """Each check exposes `us_only: bool` so frontend renders KR label."""
        cfg = tmp_path / "config"
        cfg.mkdir(exist_ok=True)
        (cfg / "universe.yaml").write_text(
            yaml.safe_dump(
                {
                    "us_core": {"tickers": ["AAPL"]},
                    "kr_kospi200": {"tickers": ["005930.KS"]},
                }
            )
        )
        monkeypatch.chdir(tmp_path)

        data = client.get("/api/coverage").json()
        for c in data["checks"]:
            assert "us_only" in c
            assert isinstance(c["us_only"], bool)
            # name format "data.<table>"
            assert c["name"].startswith("data.")

    def test_us_only_flag_matches_table_set(self, client, tmp_path, monkeypatch):
        """analyst_ratings/insider_trades/superinvestors/estimates/earnings_surprises
        → us_only=True; prices/fundamentals → False."""
        cfg = tmp_path / "config"
        cfg.mkdir(exist_ok=True)
        (cfg / "universe.yaml").write_text(
            yaml.safe_dump(
                {
                    "us_core": {"tickers": ["AAPL"]},
                    "kr_kospi200": {"tickers": ["005930.KS"]},
                }
            )
        )
        monkeypatch.chdir(tmp_path)

        data = client.get("/api/coverage").json()
        flags = {c["name"]: c["us_only"] for c in data["checks"]}

        assert flags["data.prices"] is False
        assert flags["data.fundamentals"] is False
        assert flags["data.analyst_ratings"] is True
        assert flags["data.insider_trades"] is True
        assert flags["data.superinvestors"] is True

    def test_check_fields_include_status_and_detail(self, client, tmp_path, monkeypatch):
        """Each check has actual/threshold/status/detail for UI rendering."""
        cfg = tmp_path / "config"
        cfg.mkdir(exist_ok=True)
        (cfg / "universe.yaml").write_text(
            yaml.safe_dump(
                {
                    "us_core": {"tickers": ["AAPL"]},
                    "kr_kospi200": {"tickers": ["005930.KS"]},
                }
            )
        )
        monkeypatch.chdir(tmp_path)

        data = client.get("/api/coverage").json()
        c0 = data["checks"][0]
        assert set(c0.keys()) >= {"name", "actual", "threshold", "status", "detail", "us_only"}
        assert c0["status"] in ("PASS", "FAIL")
        assert 0.0 <= c0["actual"] <= 1.0
        assert 0.0 < c0["threshold"] <= 1.0

    def test_error_path_returns_json(self, client, tmp_path, monkeypatch):
        """Missing universe.yaml → still 200 with error key, never 500.

        The endpoint catches exceptions and returns a JSON body (CodeQL
        py/stack-trace-exposure invariant)."""
        # No universe.yaml in cwd
        monkeypatch.chdir(tmp_path)

        r = client.get("/api/coverage")
        assert r.status_code == 200
        # Either computed with empty universe (FAIL all) OR error JSON —
        # either way it's a valid dict, no 500
        data = r.json()
        assert isinstance(data, dict)
