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
        data = resp.json()
        for key in ["trend", "vix", "fear_greed", "macro_score"]:
            assert key in data

    def test_market_context_with_vix_data(self, seeded_client):
        """VIX 데이터가 있으면 값 반환."""
        from nuri.core.db import get_db

        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO macro (indicator, date, value, source) VALUES ('vix','2026-04-10',19.2,'test')"
            )
            conn.execute(
                "INSERT OR REPLACE INTO macro (indicator, date, value, source) VALUES ('fear_greed','2026-04-10',37.7,'test')"
            )
        resp = seeded_client.get("/api/tickers/market-context")
        data = resp.json()
        assert data["vix"] == 19.2
        assert data["fear_greed"] == 37.7


class TestLatestPricesWithData:
    def test_prices_with_seeded_data(self, seeded_client):
        """가격 데이터가 있으면 price/prev 반환."""
        import pandas as pd

        from nuri.core.db import upsert_prices

        df = pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "date": "2026-04-09",
                    "open": 220,
                    "high": 222,
                    "low": 218,
                    "close": 219,
                    "volume": 1000,
                    "adj_close": 219,
                },
                {
                    "ticker": "AAPL",
                    "date": "2026-04-10",
                    "open": 219,
                    "high": 225,
                    "low": 219,
                    "close": 223,
                    "volume": 1200,
                    "adj_close": 223,
                },
            ]
        )
        upsert_prices(df)
        resp = seeded_client.get("/api/tickers/latest-prices?tickers=AAPL")
        data = resp.json()
        assert data["prices"]["AAPL"]["price"] == 223
        assert data["prices"]["AAPL"]["prev"] == 219


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


class TestSearchTickersBranchCoverage:
    """ticker.py 브랜치 커버 — universe.yaml 부재 / 비-dict 그룹 분기."""

    def test_universe_missing_skips_loading(self, client, monkeypatch):
        """universe.yaml 가 없으면 line 27 False → line 35 점프 (한글 매칭만 시도)."""
        from pathlib import Path as _P

        original_exists = _P.exists

        def fake_exists(self):
            # universe.yaml 만 False 로 가장. 다른 경로(예: 실제 fs lookup) 는 영향 없게.
            if self.name == "universe.yaml":
                return False
            return original_exists(self)

        monkeypatch.setattr(_P, "exists", fake_exists)
        resp = client.get("/api/tickers/search?q=AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        # universe.yaml 부재 → all_tickers 비어 ticker code 매칭 0
        # 한글 매칭 path 도 all_tickers 비어 0 → results=[]
        assert data["count"] == 0

    def test_universe_group_non_dict_skipped(self, client, monkeypatch, tmp_path):
        """universe.yaml 안에 list / 비-dict 그룹이 섞이면 line 31 False → 다음 그룹으로 진행."""
        import yaml as _yaml

        # 비-dict 값을 포함한 universe payload (실제 universe.yaml 와 같은 구조)
        fake_universe = {
            "us_growth": {"tickers": ["AAPL", "NVDA"]},  # dict + tickers (정상)
            "deprecated_legacy": ["OLD1", "OLD2"],  # list (비-dict, 31->30 트리거)
            "metadata_only": {"description": "no tickers key"},  # dict but no "tickers"
        }

        original_safe_load = _yaml.safe_load

        def fake_safe_load(stream):
            text = stream.read() if hasattr(stream, "read") else stream
            if "us_growth" in str(text) or "tickers" in str(text):
                return fake_universe
            return original_safe_load(text)

        monkeypatch.setattr(_yaml, "safe_load", fake_safe_load)
        resp = client.get("/api/tickers/search?q=AAPL")
        assert resp.status_code == 200
        # AAPL 은 us_growth 그룹에 있어 매칭 성공해야 함 (다른 비-dict 그룹은 skip)
        data = resp.json()
        tickers = [r["ticker"] for r in data.get("results", [])]
        assert "AAPL" in tickers
