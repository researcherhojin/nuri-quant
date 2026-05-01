"""Tests for scripts/check_universe_coverage.py — #272 Phase 2c + #288 KR label.

Smoke tests for the stdout output format. The script is a diagnostic
quick-check (not a gate), so we verify:
1. Runs without crashing on empty / populated DB
2. US-only tables display "n/a (US-only)" per #288
3. Non-US-only tables display real KR match percentage
4. Footer includes the KR explanation note
"""

from __future__ import annotations

import pytest
import yaml


@pytest.fixture
def universe_cwd(tmp_path, monkeypatch):
    """Temp universe.yaml + cwd."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "universe.yaml").write_text(
        yaml.safe_dump(
            {
                "us_core": {"tickers": ["AAPL", "MSFT"]},
                "kr_kospi200": {"tickers": ["005930.KS", "000660.KS"]},
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def populated_db(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    from nuri.core.db import get_db, init_db

    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr(db_mod, "DB_PATH", db)

    with get_db(db) as conn:
        # prices: US + KR (not US_ONLY)
        for t in ["AAPL", "MSFT", "005930.KS", "000660.KS"]:
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close) "
                "VALUES (?, ?, 1, 2, 0.5, 1.5, 1000, 1.5)",
                (t, "2026-04-14"),
            )
        # analyst_ratings: US only (US_ONLY_TABLES member)
        for t in ["AAPL", "MSFT"]:
            conn.execute(
                "INSERT INTO analyst_ratings (ticker, date, firm, action, to_grade) VALUES (?, ?, 'Firm', 'up', 'Buy')",
                (t, "2026-04-14"),
            )
    return db


class TestOutputFormat:
    def test_runs_on_empty_db(self, universe_cwd, tmp_path, monkeypatch, capsys):
        """Empty DB: script should run to completion and print zero-counts."""
        import nuri.core.db as db_mod
        from nuri.core.db import init_db

        db = tmp_path / "empty.db"
        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)

        from scripts.verify.check_universe_coverage import main

        main()
        out = capsys.readouterr().out
        assert "Universe Coverage 확인" in out
        assert "US=2" in out and "KR=2" in out

    def _coverage_section_lines(self, out: str) -> list[str]:
        """Extract only lines from the [2/2] Universe coverage section.

        The script has two sections: [1/2] raw counts and [2/2] coverage %.
        Tests for the #288 KR label apply to [2/2] only.
        """
        lines = out.splitlines()
        try:
            start = next(i for i, ln in enumerate(lines) if "[2/2]" in ln)
        except StopIteration:
            return []
        return lines[start:]

    def test_us_only_tables_show_na_label(self, universe_cwd, populated_db, capsys):
        """#288: analyst_ratings KR column = 'n/a (US-only)' in coverage section."""
        from scripts.verify.check_universe_coverage import main

        main()
        out = capsys.readouterr().out
        section = self._coverage_section_lines(out)

        analyst_line = next((ln for ln in section if "analyst_ratings" in ln), None)
        assert analyst_line is not None
        assert "n/a (US-only)" in analyst_line
        # Explicit: no KR percentage like "0/2 (0%)" for US-only tables
        assert "0/2" not in analyst_line

    def test_non_us_only_tables_show_real_kr_percentage(self, universe_cwd, populated_db, capsys):
        """prices: KR column shows X/2 (Y%) in coverage section."""
        from scripts.verify.check_universe_coverage import main

        main()
        out = capsys.readouterr().out
        section = self._coverage_section_lines(out)

        prices_line = next((ln for ln in section if ln.strip().startswith("prices")), None)
        assert prices_line is not None
        assert "n/a (US-only)" not in prices_line
        # Real KR match: 2/2 (100%)
        assert "2/2" in prices_line

    def test_footer_explains_us_only_label(self, universe_cwd, populated_db, capsys):
        """Footer teaches the reader what 'n/a (US-only)' means — a docs invariant."""
        from scripts.verify.check_universe_coverage import main

        main()
        out = capsys.readouterr().out
        assert "소스 한계" in out or "소스(yfinance .KS / SEC EDGAR)" in out

    def test_missing_universe_yaml_does_not_crash(self, tmp_path, monkeypatch, capsys):
        """Script prints error and returns instead of exception when yaml missing."""
        monkeypatch.chdir(tmp_path)
        import nuri.core.db as db_mod
        from nuri.core.db import init_db

        db = tmp_path / "x.db"
        init_db(db)
        monkeypatch.setattr(db_mod, "DB_PATH", db)

        from scripts.verify.check_universe_coverage import main

        main()  # should not raise
        out = capsys.readouterr().out
        assert "config/universe.yaml 없음" in out
