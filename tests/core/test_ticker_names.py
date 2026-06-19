"""Tests for nuri.core.ticker_names — note-split canonical name extraction."""

from __future__ import annotations

import json
from unittest.mock import patch

from nuri.core import ticker_names


def _mock_meta(meta: dict) -> list[dict]:
    return [{"metadata": json.dumps(meta)}]


class TestIsKrTicker:
    """#764: 통화/지역 게이트는 KOSPI(.KS) + KOSDAQ(.KQ) 둘 다 KR 로 본다."""

    def test_kospi_ks_is_kr(self) -> None:
        assert ticker_names.is_kr_ticker("005930.KS") is True

    def test_kosdaq_kq_is_kr(self) -> None:
        assert ticker_names.is_kr_ticker("035720.KQ") is True

    def test_us_ticker_is_not_kr(self) -> None:
        assert ticker_names.is_kr_ticker("NVDA") is False


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

    def test_db_lookup_exception_falls_through_to_pykrx(self) -> None:
        """1차 DB query 가 raise → except 분기 후 pykrx 시도 (lines 44-45)."""

        def _boom_query(*a, **kw):
            raise RuntimeError("DB outage")

        with (
            patch("nuri.core.db.query", side_effect=_boom_query),
            patch("pykrx.stock.get_market_ticker_name", return_value="삼성전자"),
        ):
            assert ticker_names.get_ticker_name("100100.KS") == "삼성전자"

    def test_pykrx_exception_returns_none(self) -> None:
        """2차 pykrx 호출이 raise → except 분기 → None (lines 54-56)."""

        def _boom_pykrx(*a, **kw):
            raise RuntimeError("pykrx down")

        with (
            patch("nuri.core.db.query", return_value=[]),
            patch("pykrx.stock.get_market_ticker_name", side_effect=_boom_pykrx),
        ):
            assert ticker_names.get_ticker_name("100200.KS") is None

    def test_kr_local_map_resolves_network_free(self) -> None:
        """DB 미스 → 로컬 KOSPI200 맵에서 해석, pykrx 미호출 (#712 prod fix 핵심).

        맵 tier 가 제거되면 /tickers/search 가 요청당 수백 pykrx 호출로 회귀 →
        이 테스트가 FAIL. pykrx 를 raise 로 막아도 맵으로 이름이 나와야 network-free.
        """
        ticker_names._load_kr_name_map.cache_clear()

        def _boom_pykrx(*a, **kw):
            raise RuntimeError("network blocked")

        with (
            patch("nuri.core.db.query", return_value=[]),
            patch.object(ticker_names, "_load_kr_name_map", return_value={"005930.KS": "삼성전자"}),
            patch("pykrx.stock.get_market_ticker_name", side_effect=_boom_pykrx),
        ):
            assert ticker_names.get_ticker_name("005930.KS") == "삼성전자"

    def test_kr_not_in_map_falls_to_pykrx(self) -> None:
        """맵에 없는 종목은 pykrx fallback (맵외 ETF 등 — graceful)."""
        ticker_names._load_kr_name_map.cache_clear()
        with (
            patch("nuri.core.db.query", return_value=[]),
            patch.object(ticker_names, "_load_kr_name_map", return_value={}),
            patch("pykrx.stock.get_market_ticker_name", return_value="맵외종목"),
        ):
            assert ticker_names.get_ticker_name("999000.KS") == "맵외종목"
