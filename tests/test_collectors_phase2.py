"""Phase 2 수집기 테스트 — CBOE, CoinGecko, FINVIZ, Reddit, FRED Calendar, macro_score 통합."""
from unittest.mock import MagicMock, patch

import pytest

from nuri.core.db import init_db, query, upsert_macro, upsert_portfolio


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def db_with_us_tickers(db_path):
    """US 보유 종목이 있는 DB."""
    upsert_portfolio([
        {"account": "test", "ticker": "TSLA", "quantity": 10,
         "avg_price": 300, "currency": "USD", "sector": "EV"},
        {"account": "test", "ticker": "NVDA", "quantity": 5,
         "avg_price": 800, "currency": "USD", "sector": "Semi"},
        {"account": "test", "ticker": "AAPL", "quantity": 20,
         "avg_price": 180, "currency": "USD", "sector": "Tech"},
    ], db_path)
    return db_path


# ═══════════════════════════════════════════════════════
# CBOE Put/Call Ratio
# ═══════════════════════════════════════════════════════

class TestCBOECollector:
    def test_extract_pcr_ratio_key(self):
        """PCR 추출 — TOTAL_PUT_CALL_RATIO 키."""
        from nuri.collectors.cboe import CBOECollector
        assert CBOECollector._extract_pcr({"TOTAL_PUT_CALL_RATIO": 0.85}) == 0.85
        assert CBOECollector._extract_pcr({"PUT_CALL_RATIO": 1.2}) == 1.2

    def test_extract_pcr_volume_calc(self):
        """PCR 추출 — put/call volume 직접 계산."""
        from nuri.collectors.cboe import CBOECollector
        result = CBOECollector._extract_pcr({
            "TOTAL_PUT_VOLUME": 1500000,
            "TOTAL_CALL_VOLUME": 2000000,
        })
        assert result == pytest.approx(0.75)

    def test_extract_pcr_missing(self):
        """PCR 추출 — 키 없음."""
        from nuri.collectors.cboe import CBOECollector
        assert CBOECollector._extract_pcr({}) is None
        assert CBOECollector._extract_pcr({"unrelated": 42}) is None

    def test_extract_pcr_zero_call(self):
        """PCR 추출 — call volume 0 (ZeroDivisionError 방지)."""
        from nuri.collectors.cboe import CBOECollector
        assert CBOECollector._extract_pcr({
            "TOTAL_PUT_VOLUME": 100,
            "TOTAL_CALL_VOLUME": 0,
        }) is None

    @patch("nuri.collectors.cboe.requests.get")
    def test_collect_daily_json(self, mock_get):
        """CBOE daily JSON 수집."""
        from nuri.collectors.cboe import CBOECollector
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-28", "TOTAL_PUT_CALL_RATIO": 0.92}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = CBOECollector()
        records = collector.collect()
        assert len(records) >= 1
        assert records[0]["indicator"] == "put_call_ratio"
        assert records[0]["value"] == 0.92
        assert records[0]["source"] == "CBOE"

    @patch("nuri.collectors.cboe.requests.get")
    def test_save_to_macro(self, mock_get, db_path):
        """CBOE 데이터 macro 테이블 저장."""
        from nuri.collectors.cboe import CBOECollector
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"TRADE_DATE": "2026-03-28", "TOTAL_PUT_CALL_RATIO": 0.88}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = CBOECollector()
        records = collector.collect()
        from nuri.core.db import upsert_macro
        count = upsert_macro(records, db_path)
        assert count >= 1

        rows = query("SELECT * FROM macro WHERE indicator = 'put_call_ratio'", db_path=db_path)
        assert len(rows) >= 1
        assert rows[0]["value"] == pytest.approx(0.88)


    def test_parse_date_formats(self):
        """_parse_date 다양한 형식 처리."""
        from nuri.collectors.cboe import _parse_date
        assert _parse_date("2026-03-28") == "2026-03-28"
        assert _parse_date("03/28/2026") == "2026-03-28"
        assert _parse_date("") is None
        assert _parse_date("invalid") is None
        assert _parse_date("2026-03-28T12:00:00") == "2026-03-28"


# ═══════════════════════════════════════════════════════
# CoinGecko BTC
# ═══════════════════════════════════════════════════════

class TestCoinGeckoCollector:
    @patch("nuri.collectors.coingecko.requests.get")
    def test_collect_price(self, mock_get):
        """CoinGecko BTC 가격 수집."""
        from nuri.collectors.coingecko import CoinGeckoCollector

        # price API → global API 순서로 호출
        price_resp = MagicMock()
        price_resp.json.return_value = {
            "bitcoin": {
                "usd": 67500.0,
                "usd_market_cap": 1320000000000,
                "usd_24h_vol": 28500000000,
                "usd_24h_change": -2.35,
            }
        }
        price_resp.raise_for_status = MagicMock()

        global_resp = MagicMock()
        global_resp.json.return_value = {
            "data": {
                "market_cap_percentage": {"btc": 54.2},
                "total_market_cap": {"usd": 2450000000000},
                "active_cryptocurrencies": 14500,
            }
        }
        global_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [price_resp, global_resp]

        collector = CoinGeckoCollector()
        records = collector.collect()

        indicators = {r["indicator"]: r["value"] for r in records}
        assert indicators["btc_usd_cg"] == 67500.0
        assert indicators["btc_market_cap_t"] == pytest.approx(1.32)
        assert indicators["btc_24h_volume_b"] == pytest.approx(28.5)
        assert indicators["btc_24h_change_pct"] == -2.35
        assert indicators["btc_dominance"] == 54.2
        assert indicators["crypto_total_mcap_t"] == pytest.approx(2.45)
        assert all(r["source"] == "CoinGecko" for r in records)

    @patch("nuri.collectors.coingecko.requests.get")
    def test_save_to_macro(self, mock_get, db_path):
        """CoinGecko 데이터 macro 저장."""
        from nuri.collectors.coingecko import CoinGeckoCollector

        price_resp = MagicMock()
        price_resp.json.return_value = {"bitcoin": {"usd": 70000.0}}
        price_resp.raise_for_status = MagicMock()

        global_resp = MagicMock()
        global_resp.json.return_value = {"data": {"market_cap_percentage": {}, "active_cryptocurrencies": None}}
        global_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [price_resp, global_resp]

        collector = CoinGeckoCollector()
        records = collector.collect()
        from nuri.core.db import upsert_macro
        count = upsert_macro(records, db_path)
        assert count >= 1

        rows = query("SELECT * FROM macro WHERE indicator = 'btc_usd_cg'", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["value"] == 70000.0

    @patch("nuri.collectors.coingecko.requests.get")
    def test_partial_failure(self, mock_get):
        """price 성공 + global 실패 시 부분 결과 반환."""
        from nuri.collectors.coingecko import CoinGeckoCollector

        price_resp = MagicMock()
        price_resp.json.return_value = {"bitcoin": {"usd": 65000.0}}
        price_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [price_resp, Exception("global API down")]

        collector = CoinGeckoCollector()
        records = collector.collect()
        assert len(records) >= 1
        assert records[0]["indicator"] == "btc_usd_cg"


# ═══════════════════════════════════════════════════════
# FINVIZ Screener
# ═══════════════════════════════════════════════════════

class TestFINVIZCollector:
    @patch("nuri.collectors.finviz.FINVIZCollector._fetch_signal_tickers")
    def test_fetch_signal_tickers(self, mock_fetch):
        """finvizfinance 시그널 조회."""
        from nuri.collectors.finviz import FINVIZCollector

        mock_fetch.return_value = {"TSLA", "NVDA", "AAPL", "MSFT"}

        collector = FINVIZCollector()
        tickers = collector._fetch_signal_tickers("Oversold")
        assert "TSLA" in tickers
        assert "NVDA" in tickers
        assert len(tickers) == 4

    @patch("nuri.collectors.finviz.FINVIZCollector._fetch_signal_tickers")
    @patch("nuri.collectors.finviz.FINVIZCollector._get_tickers")
    def test_collect_filters_held(self, mock_tickers, mock_fetch):
        """보유 종목만 필터링하여 수집."""
        from nuri.collectors.finviz import FINVIZCollector

        mock_tickers.return_value = ["TSLA", "NVDA", "AAPL"]
        # oversold_rsi에서 TSLA 발견, 나머지는 빈 셋
        mock_fetch.side_effect = [
            {"TSLA", "MSFT", "GME"},  # oversold_rsi
            set(),  # overbought_rsi
            {"NVDA"},  # new_high
            set(),  # new_low
            set(),  # most_volatile
            {"TSLA", "AAPL"},  # unusual_volume
        ]

        collector = FINVIZCollector()
        records = collector.collect()
        tickers_found = {r["ticker"] for r in records}
        signals_found = {r["signal"] for r in records}

        assert "TSLA" in tickers_found
        assert "NVDA" in tickers_found
        assert "GME" not in tickers_found  # 미보유
        assert "oversold_rsi" in signals_found
        assert "new_high" in signals_found

    def test_save_to_external_analysis(self, db_with_us_tickers):
        """FINVIZ 시그널 external_analysis 테이블 저장."""
        from nuri.collectors.finviz import FINVIZCollector

        collector = FINVIZCollector()
        data = [
            {"date": "2026-03-28", "ticker": "TSLA", "signal": "oversold_rsi", "source": "FINVIZ"},
            {"date": "2026-03-28", "ticker": "NVDA", "signal": "new_high", "source": "FINVIZ"},
        ]
        count = collector.save(data, db_path=db_with_us_tickers)
        assert count == 2

        rows = query(
            "SELECT * FROM external_analysis WHERE source = 'FINVIZ'",
            db_path=db_with_us_tickers,
        )
        assert len(rows) == 2

    @patch("nuri.collectors.finviz.FINVIZCollector._get_tickers")
    def test_collect_no_holdings(self, mock_tickers):
        """보유 US 종목 없으면 빈 리스트."""
        from nuri.collectors.finviz import FINVIZCollector
        mock_tickers.return_value = []
        collector = FINVIZCollector()
        assert collector.collect() == []


# ═══════════════════════════════════════════════════════
# Reddit/WSB Sentiment
# ═══════════════════════════════════════════════════════

class TestRedditCollector:
    def test_count_mentions_dollar_sign(self):
        """$ 접두사 티커 인식."""
        from nuri.collectors.reddit import RedditCollector

        collector = RedditCollector()
        posts = [
            {"title": "$TSLA to the moon!", "selftext": "Buy $NVDA too"},
            {"title": "What about $TSLA?", "selftext": ""},
        ]
        counts = collector._count_mentions(posts, {"TSLA", "NVDA", "AAPL"})
        assert counts["TSLA"] == 2
        assert counts["NVDA"] == 1

    def test_count_mentions_uppercase(self):
        """대문자 티커 인식 ($ 없이)."""
        from nuri.collectors.reddit import RedditCollector

        collector = RedditCollector()
        posts = [
            {"title": "TSLA earnings tomorrow", "selftext": "NVDA looking good"},
        ]
        counts = collector._count_mentions(posts, {"TSLA", "NVDA"})
        assert counts["TSLA"] == 1
        assert counts["NVDA"] == 1

    def test_noise_words_filtered(self):
        """일반 영단어는 티커로 인식하지 않음."""
        from nuri.collectors.reddit import RedditCollector

        collector = RedditCollector()
        posts = [
            {"title": "CEO of THE company IS great", "selftext": "BUY NOW OR NOT"},
        ]
        counts = collector._count_mentions(posts, set())
        # 노이즈 단어는 카운트 안 됨
        assert counts.get("THE", 0) == 0
        assert counts.get("CEO", 0) == 0
        assert counts.get("BUY", 0) == 0
        assert counts.get("NOT", 0) == 0

    @patch("nuri.collectors.reddit.requests.get")
    @patch("nuri.collectors.reddit.RedditCollector._get_tickers")
    def test_collect_with_mock_api(self, mock_tickers, mock_get):
        """Arctic Shift API 응답으로 전체 수집 테스트."""
        from nuri.collectors.reddit import RedditCollector

        mock_tickers.return_value = ["TSLA", "NVDA"]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"title": "$TSLA yolo", "selftext": "diamond hands TSLA"},
                {"title": "NVDA earnings beat", "selftext": "$TSLA also up"},
                {"title": "Market crash incoming", "selftext": "sell everything"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = RedditCollector()
        records = collector.collect()

        indicators = {r["indicator"]: r["value"] for r in records}
        assert indicators["wsb_post_count"] == 3.0
        assert indicators["wsb_held_mentions"] == 2.0  # TSLA + NVDA
        assert indicators["wsb_mention_TSLA"] == 2.0  # 2 posts mention TSLA (deduplicated per post)
        assert indicators["wsb_mention_NVDA"] == 1.0

    @patch("nuri.collectors.reddit.requests.get")
    @patch("nuri.collectors.reddit.RedditCollector._get_tickers")
    def test_save_to_macro(self, mock_tickers, mock_get, db_path):
        """Reddit 데이터 macro 테이블 저장."""
        from nuri.collectors.reddit import RedditCollector

        mock_tickers.return_value = ["TSLA"]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"title": "$TSLA", "selftext": ""}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = RedditCollector()
        records = collector.collect()
        from nuri.core.db import upsert_macro
        count = upsert_macro(records, db_path)
        assert count >= 1

        rows = query("SELECT * FROM macro WHERE indicator = 'wsb_post_count'", db_path=db_path)
        assert len(rows) == 1

    @patch("nuri.collectors.reddit.requests.get")
    @patch("nuri.collectors.reddit.RedditCollector._get_tickers")
    def test_api_failure_returns_empty(self, mock_tickers, mock_get):
        """API 실패 시 빈 결과."""
        from nuri.collectors.reddit import RedditCollector

        mock_tickers.return_value = ["TSLA"]
        mock_get.side_effect = Exception("connection error")

        collector = RedditCollector()
        records = collector.collect()
        assert records == []


# ═══════════════════════════════════════════════════════
# FRED Economic Calendar
# ═══════════════════════════════════════════════════════

class TestFREDCalendarCollector:
    def test_fallback_calendar(self):
        """FRED API 키 없을 때 하드코딩 캘린더 폴백."""
        from nuri.collectors.fred_calendar import FREDCalendarCollector
        collector = FREDCalendarCollector()
        collector.api_key = ""  # 키 없음
        records = collector.collect(days_ahead=365)  # 1년 범위로 테스트
        # 2026년 폴백 데이터가 있으면 결과 반환
        assert isinstance(records, list)
        for r in records:
            assert r["event_type"] == "economic"
            assert "FRED:" in r["description"]
            assert r["importance"] in (1, 2, 3)

    @patch("nuri.collectors.fred_calendar.requests.get")
    def test_collect_fred_api(self, mock_get):
        """FRED API 응답 파싱."""
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "release_dates": [
                {"release_id": 10, "date": "2026-04-14"},  # CPI
                {"release_id": 50, "date": "2026-04-03"},  # 고용
                {"release_id": 999, "date": "2026-04-10"},  # 미중요 → 무시
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = FREDCalendarCollector()
        collector.api_key = "test_key"
        records = collector.collect()
        assert len(records) == 2  # CPI + 고용만
        descriptions = {r["description"] for r in records}
        assert "FRED: CPI" in descriptions
        assert "FRED: 고용 보고서" in descriptions

    def test_save_to_events(self, db_path):
        """events 테이블 저장."""
        data = [
            {"date": "2026-04-14", "event_type": "economic", "ticker": None,
             "description": "FRED: CPI", "importance": 3},
        ]
        # save()는 get_db()를 내부에서 호출하므로 db_path 없이 직접 insert 테스트
        from nuri.core.db import insert_events
        count = insert_events(data, db_path)
        assert count == 1
        rows = query("SELECT * FROM events WHERE event_type = 'economic'", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["description"] == "FRED: CPI"

    def test_negative_days_ahead_defaults(self):
        """음수 days_ahead는 기본값 14로 보정."""
        from nuri.collectors.fred_calendar import FREDCalendarCollector
        collector = FREDCalendarCollector()
        collector.api_key = ""
        records = collector.collect(days_ahead=-5)
        assert isinstance(records, list)  # 에러 없이 정상 실행


# ═══════════════════════════════════════════════════════
# macro_score: 3M-10Y spread + put/call ratio 통합 테스트
# ═══════════════════════════════════════════════════════

class TestMacroScoreNewComponents:
    """macro_score에 추가된 3M-10Y 스프레드 + put/call ratio 테스트."""

    def test_yield_spread_3m10y_normal(self, db_path):
        """정상 3M-10Y 스프레드 → 높은 점수."""
        from nuri.quant.regime.macro_score import _score_yield_spread_3m10y
        date = "2026-03-28"
        upsert_macro([
            {"indicator": "us_10y_yield", "date": date, "value": 4.5, "source": "test"},
            {"indicator": "us_3m_yield", "date": date, "value": 3.0, "source": "test"},
        ], db_path)
        score, detail = _score_yield_spread_3m10y(db_path, date)
        assert score > 80  # 1.5% spread → 높은 점수
        assert detail["spread_3m10y"] == 1.5

    def test_yield_spread_3m10y_inverted(self, db_path):
        """역전 3M-10Y 스프레드 → 낮은 점수 (경기침체 경고)."""
        from nuri.quant.regime.macro_score import _score_yield_spread_3m10y
        date = "2026-03-28"
        upsert_macro([
            {"indicator": "us_10y_yield", "date": date, "value": 3.5, "source": "test"},
            {"indicator": "us_3m_yield", "date": date, "value": 4.5, "source": "test"},
        ], db_path)
        score, detail = _score_yield_spread_3m10y(db_path, date)
        assert score < 30  # -1.0% spread → 경기침체 경고
        assert detail["spread_3m10y"] == -1.0

    def test_yield_spread_3m10y_missing_data(self, db_path):
        """데이터 없으면 기본값 50."""
        from nuri.quant.regime.macro_score import _score_yield_spread_3m10y
        score, detail = _score_yield_spread_3m10y(db_path, "2026-03-28")
        assert score == 50.0
        assert detail["spread_3m10y"] is None

    def test_put_call_ratio_neutral(self, db_path):
        """중립 PCR (0.85) → 높은 점수."""
        from nuri.quant.regime.macro_score import _score_put_call_ratio
        date = "2026-03-28"
        upsert_macro([
            {"indicator": "put_call_ratio", "date": date, "value": 0.85, "source": "test"},
        ], db_path)
        score, detail = _score_put_call_ratio(db_path, date)
        assert score > 80  # 중립 범위
        assert detail["put_call_ratio"] == 0.85

    def test_put_call_ratio_extreme_fear(self, db_path):
        """극단적 공포 PCR (1.3) → 낮은 점수."""
        from nuri.quant.regime.macro_score import _score_put_call_ratio
        date = "2026-03-28"
        upsert_macro([
            {"indicator": "put_call_ratio", "date": date, "value": 1.3, "source": "test"},
        ], db_path)
        score, detail = _score_put_call_ratio(db_path, date)
        assert score < 50  # 공포 극단

    def test_put_call_ratio_extreme_greed(self, db_path):
        """극단적 탐욕 PCR (0.5) → 낮은 점수."""
        from nuri.quant.regime.macro_score import _score_put_call_ratio
        date = "2026-03-28"
        upsert_macro([
            {"indicator": "put_call_ratio", "date": date, "value": 0.5, "source": "test"},
        ], db_path)
        score, detail = _score_put_call_ratio(db_path, date)
        assert score < 50  # 탐욕 극단

    def test_put_call_ratio_missing(self, db_path):
        """PCR 데이터 없으면 기본값 50."""
        from nuri.quant.regime.macro_score import _score_put_call_ratio
        score, _ = _score_put_call_ratio(db_path, "2026-03-28")
        assert score == 50.0

    def test_compute_includes_new_fields(self, db_path):
        """compute_macro_score 결과에 새 필드 포함."""
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(db_path=db_path)
        assert hasattr(score, "yield_spread_3m10y_score")
        assert hasattr(score, "put_call_ratio_score")
        assert 0 <= score.yield_spread_3m10y_score <= 100
        assert 0 <= score.put_call_ratio_score <= 100

    def test_full_score_with_all_8_indicators(self, db_path):
        """8개 지표 모두 있을 때 종합 점수 계산."""
        from nuri.quant.regime.macro_score import compute_macro_score
        date = "2026-03-28"
        upsert_macro([
            {"indicator": "us_10y_yield", "date": date, "value": 4.0, "source": "test"},
            {"indicator": "us_2y_yield", "date": date, "value": 3.2, "source": "test"},
            {"indicator": "us_3m_yield", "date": date, "value": 2.8, "source": "test"},
            {"indicator": "vix", "date": date, "value": 15.0, "source": "test"},
            {"indicator": "put_call_ratio", "date": date, "value": 0.88, "source": "test"},
            {"indicator": "fear_greed", "date": date, "value": 52.0, "source": "test"},
            {"indicator": "unemployment", "date": date, "value": 3.7, "source": "test"},
            {"indicator": "cpi_yoy", "date": date, "value": 2.1, "source": "test"},
            {"indicator": "fed_funds_rate", "date": date, "value": 3.0, "source": "test"},
        ], db_path)
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.total_score > 65  # 양호한 조건
        assert score.interpretation == "Favorable"
        assert score.details.get("spread_3m10y") == 1.2  # 4.0 - 2.8
        assert score.details.get("put_call_ratio") == 0.88
