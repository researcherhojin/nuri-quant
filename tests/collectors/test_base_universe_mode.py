"""Tests for BaseCollector._get_tickers(source=...) — #272 Phase 2b.

Verify:
- backwards compat: default source='portfolio' unchanged behavior
- new modes: 'universe' loads yaml, 'all' unions both
- market filter works for all sources
- invalid source raises ValueError
- _load_universe_tickers handles missing file / missing keys gracefully
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from nuri.collectors.base import BaseCollector, _load_universe_tickers


class StubCollector(BaseCollector):
    def __init__(self):
        super().__init__("stub")

    def collect(self, **kwargs):
        pass

    def save(self, data):
        return 0


@pytest.fixture
def universe_yaml(tmp_path, monkeypatch):
    """temp universe.yaml 생성 + PATH override."""
    path = tmp_path / "universe.yaml"
    data = {
        "us_core": {"description": "core", "tickers": ["AAPL", "MSFT"]},
        "us_sp500_extended": {"description": "ext", "tickers": ["GOOGL", "AMD"]},
        "kr_kospi200": {"description": "kr", "tickers": ["005930.KS", "000660.KS"]},
    }
    path.write_text(yaml.safe_dump(data))

    # _load_universe_tickers uses Path("config/universe.yaml") — 상대 경로라 cwd 변경 필요
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "pathlib.Path.exists",
        lambda self: (
            str(self) == "config/universe.yaml" or Path.exists.__wrapped__(self)
            if hasattr(Path.exists, "__wrapped__")
            else False
        ),
    )
    return path


class TestLoadUniverseTickers:
    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # no config/universe.yaml here
        assert _load_universe_tickers() == []

    def test_loads_all_three_sections(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "universe.yaml").write_text(
            yaml.safe_dump(
                {
                    "us_core": {"tickers": ["AAPL", "MSFT"]},
                    "us_sp500_extended": {"tickers": ["GOOGL"]},
                    "kr_kospi200": {"tickers": ["005930.KS"]},
                }
            )
        )
        monkeypatch.chdir(tmp_path)
        result = _load_universe_tickers()
        assert set(result) == {"AAPL", "MSFT", "GOOGL", "005930.KS"}

    def test_missing_section_handled(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "universe.yaml").write_text(
            yaml.safe_dump(
                {
                    "us_core": {"tickers": ["AAPL"]},
                    # no us_sp500_extended or kr_kospi200
                }
            )
        )
        monkeypatch.chdir(tmp_path)
        assert _load_universe_tickers() == ["AAPL"]

    def test_empty_yaml(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "universe.yaml").write_text("")
        monkeypatch.chdir(tmp_path)
        assert _load_universe_tickers() == []

    def test_dedup_sorted(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "universe.yaml").write_text(
            yaml.safe_dump(
                {
                    "us_core": {"tickers": ["AAPL", "MSFT"]},
                    "us_sp500_extended": {"tickers": ["MSFT", "AAPL"]},  # overlap
                }
            )
        )
        monkeypatch.chdir(tmp_path)
        result = _load_universe_tickers()
        assert result == ["AAPL", "MSFT"]  # dedup'd + sorted


class TestGetTickersSourceParam:
    def test_portfolio_default_unchanged(self):
        """기존 동작 (backwards compat)."""
        with patch("nuri.core.db.get_tickers", return_value=["NVDA", "TSLA"]):
            s = StubCollector()
            assert s._get_tickers() == ["NVDA", "TSLA"]  # default = portfolio

    def test_universe_source(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "universe.yaml").write_text(
            yaml.safe_dump(
                {
                    "us_core": {"tickers": ["AAPL", "MSFT"]},
                }
            )
        )
        monkeypatch.chdir(tmp_path)
        with patch("nuri.core.db.get_tickers", return_value=["NVDA"]):
            s = StubCollector()
            assert s._get_tickers(source="universe") == ["AAPL", "MSFT"]

    def test_all_source_unions(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "universe.yaml").write_text(
            yaml.safe_dump(
                {
                    "us_core": {"tickers": ["AAPL", "MSFT"]},
                }
            )
        )
        monkeypatch.chdir(tmp_path)
        with patch("nuri.core.db.get_tickers", return_value=["NVDA", "AAPL"]):  # AAPL overlap
            s = StubCollector()
            result = s._get_tickers(source="all")
            assert set(result) == {"AAPL", "MSFT", "NVDA"}  # dedup'd

    def test_market_filter_with_universe(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "universe.yaml").write_text(
            yaml.safe_dump(
                {
                    "us_core": {"tickers": ["AAPL"]},
                    "kr_kospi200": {"tickers": ["005930.KS"]},
                }
            )
        )
        monkeypatch.chdir(tmp_path)
        with patch("nuri.core.db.get_tickers", return_value=[]):
            s = StubCollector()
            assert s._get_tickers(market="us", source="universe") == ["AAPL"]
            assert s._get_tickers(market="kr", source="universe") == ["005930.KS"]

    def test_invalid_source_raises(self):
        with patch("nuri.core.db.get_tickers", return_value=[]):
            s = StubCollector()
            with pytest.raises(ValueError, match="Unknown source"):
                s._get_tickers(source="invalid")

    def test_source_none_raises(self):
        """None 도 invalid — 명시적 string만 허용."""
        with patch("nuri.core.db.get_tickers", return_value=[]):
            s = StubCollector()
            with pytest.raises(ValueError):
                s._get_tickers(source=None)  # type: ignore
