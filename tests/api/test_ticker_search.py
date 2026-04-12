"""Tests for /api/tickers/* endpoints (#133)."""
import pytest

from nuri.core.db import get_db, init_db


class TestLatestPrices:
    def test_batch_prices(self, client):
        """여러 종목 가격 batch 조회."""
        resp = client.get("/api/tickers/latest-prices?tickers=AAPL,NVDA")
        assert resp.status_code == 200
        data = resp.json()
        assert "prices" in data
        assert "AAPL" in data["prices"]
        assert "NVDA" in data["prices"]

    def test_batch_prices_with_kr(self, client):
        """KR 종목 포함 batch 조회."""
        resp = client.get("/api/tickers/latest-prices?tickers=AAPL,005930.KS")
        assert resp.status_code == 200
        data = resp.json()
        assert "005930.KS" in data["prices"]

    def test_batch_prices_max_20(self, client):
        """20개 초과 시 잘림."""
        tickers = ",".join([f"T{i}" for i in range(25)])
        resp = client.get(f"/api/tickers/latest-prices?tickers={tickers}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["prices"]) <= 20

    def test_batch_prices_unknown_ticker(self, client):
        """미수집 종목은 price=null."""
        resp = client.get("/api/tickers/latest-prices?tickers=XYZNOTEXIST")
        assert resp.status_code == 200
        assert resp.json()["prices"]["XYZNOTEXIST"]["price"] is None


class TestMarketContext:
    def test_market_context_returns(self, client):
        """시장 현황 엔드포인트 기본 동작."""
        resp = client.get("/api/tickers/market-context")
        assert resp.status_code == 200
        data = resp.json()
        assert "trend" in data
        assert "vix" in data
        assert "fear_greed" in data
        assert "macro_score" in data

    def test_market_context_fields_nullable(self, client):
        """데이터 없을 때 null 반환 (에러 아님)."""
        resp = client.get("/api/tickers/market-context")
        assert resp.status_code == 200
        # 빈 DB에서는 null 가능 — 에러가 아닌 정상 응답
        data = resp.json()
        for key in ["trend", "vix", "fear_greed", "macro_score"]:
            assert key in data


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
