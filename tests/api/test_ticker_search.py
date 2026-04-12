"""Tests for GET /api/tickers/search endpoint (#133)."""
import pytest


class TestTickerSearch:
    def test_search_us_ticker_match(self, client):
        """US ticker code가 universe에 있으면 결과 반환."""
        resp = client.get("/api/tickers/search?q=NVDA")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        assert any(r["ticker"] == "NVDA" for r in data["results"])

    def test_search_partial_match(self, client):
        """부분 매칭 — "TSL"로 TSLA 검색."""
        resp = client.get("/api/tickers/search?q=TSL")
        assert resp.status_code == 200
        data = resp.json()
        assert any("TSL" in r["ticker"] for r in data["results"])

    def test_search_korean_name(self, client):
        """한국어 이름으로 검색 — "삼성" → 005930.KS."""
        resp = client.get("/api/tickers/search?q=삼성")
        assert resp.status_code == 200
        data = resp.json()
        tickers = [r["ticker"] for r in data["results"]]
        assert "005930.KS" in tickers

    def test_search_no_results(self, client):
        """존재하지 않는 ticker 검색 시 빈 결과."""
        resp = client.get("/api/tickers/search?q=XYZZZZNONE")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["results"] == []

    def test_search_max_8_results(self, client):
        """결과가 8개를 초과하지 않음."""
        # "0"은 많은 KR ticker code에 매칭
        resp = client.get("/api/tickers/search?q=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] <= 8

    def test_search_empty_query_rejected(self, client):
        """빈 쿼리는 422 에러."""
        resp = client.get("/api/tickers/search?q=")
        assert resp.status_code == 422

    def test_search_result_has_price_fields(self, client):
        """결과에 price와 date 필드가 포함됨."""
        resp = client.get("/api/tickers/search?q=AAPL")
        data = resp.json()
        if data["count"] > 0:
            r = data["results"][0]
            assert "price" in r
            assert "date" in r
            assert "ticker" in r
            assert "name" in r
