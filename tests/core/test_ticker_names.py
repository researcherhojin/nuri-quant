"""Tests for nuri.core.ticker_names — note-split canonical name extraction."""

from __future__ import annotations

import json
from unittest.mock import patch

from nuri.core import ticker_names


def _mock_meta(meta: dict) -> list[dict]:
    return [{"metadata": json.dumps(meta)}]


class TestGetTickerName:
    def setup_method(self) -> None:
        ticker_names.get_ticker_name.cache_clear()

    def test_us_ticker_returns_none(self) -> None:
        assert ticker_names.get_ticker_name("MSFT") is None
        assert ticker_names.get_ticker_name("NVDA") is None

    def test_kr_uses_explicit_name_field(self) -> None:
        with patch("nuri.core.db.query", return_value=_mock_meta({"name": "삼성전자"})):
            assert ticker_names.get_ticker_name("005930.KS") == "삼성전자"

    def test_kr_extracts_name_before_em_dash(self) -> None:
        """note 가 '<canonical> — <thesis>' 패턴 → 첫 dash 앞부분만."""
        with patch(
            "nuri.core.db.query",
            return_value=_mock_meta({"note": "KODEX 200 — 2026-04-28 broad market 분산"}),
        ):
            assert ticker_names.get_ticker_name("069500.KS") == "KODEX 200"

    def test_kr_handles_ascii_dash(self) -> None:
        with patch(
            "nuri.core.db.query",
            return_value=_mock_meta({"note": "TIGER 미국S&P500 - 2026-04-30"}),
        ):
            assert ticker_names.get_ticker_name("448290.KS") == "TIGER 미국S&P500"

    def test_kr_no_separator_truncates_to_24_chars(self) -> None:
        long = "ABCDEFGHIJKLMNOPQRSTUVWXYZ extra long narrative"
        with patch("nuri.core.db.query", return_value=_mock_meta({"note": long})):
            assert ticker_names.get_ticker_name("123456.KS") == long[:24]

    def test_kr_empty_metadata_falls_through(self) -> None:
        """metadata 가 비어있으면 pykrx fallback (mock 으로 None 반환).
        본 테스트는 1차 lookup 의 None-fall-through 경로만 검증."""
        with (
            patch("nuri.core.db.query", return_value=[]),
            patch("pykrx.stock.get_market_ticker_name", return_value=""),
        ):
            assert ticker_names.get_ticker_name("999999.KS") is None
