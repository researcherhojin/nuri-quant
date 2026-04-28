"""Tests for nuri.collectors.kis_analyst_opinion (#418).

KIS Open API REST endpoint `invest-opinion` (tr_id FHKST663300C0).
All HTTP mocked — no live KIS calls. Test-fixture broker names are
synthetic ("Test Securities A/B/...") to stay clear of the privacy
scanner's BROKER_NAMES_KO patterns.
"""

from unittest.mock import MagicMock, patch

import pytest

from nuri.core.db import query

# ──────────────────────────────────────────────────────────────
# Helpers / fixtures
# ──────────────────────────────────────────────────────────────


def _fake_invest_opinion_response(
    rows: list[dict] | None = None,
    rt_cd: str = "0",
    msg1: str = "정상처리 되었습니다.",
):
    """Build a KIS-shaped invest_opinion response (output = list of opinion rows)."""
    output = rows if rows is not None else _default_rows()
    return {"rt_cd": rt_cd, "msg_cd": "MCA00000", "msg1": msg1, "output": output}


def _default_rows():
    return [
        {
            "stck_bsop_date": "20260421",
            "invt_opnn": "매수",
            "invt_opnn_cls_code": "2",
            "rgbf_invt_opnn": "보유",
            "rgbf_invt_opnn_cls_code": "3",
            "mbcr_name": "Test Securities A",
            "hts_goal_prc": "300000",
            "stck_prdy_clpr": "210000",
        },
        {
            "stck_bsop_date": "20260415",
            "invt_opnn": "보유",
            "invt_opnn_cls_code": "3",
            "rgbf_invt_opnn": "매수",
            "rgbf_invt_opnn_cls_code": "2",
            "mbcr_name": "Test Securities B",
            "hts_goal_prc": "250000",
            "stck_prdy_clpr": "210000",
        },
    ]


@pytest.fixture
def mock_kis_creds():
    from nuri.collectors.kis_realtime import KISCredentials

    return KISCredentials(
        app_key="test_app_key",
        app_secret="test_app_secret",
        account="1234567",
        hts_id="test_hts",
        mode="prod",
    )


def _resp(body, status=200, tr_cont=""):
    fake = MagicMock()
    fake.status_code = status
    fake.json.return_value = body
    fake.headers = {"tr_cont": tr_cont}
    return fake


# ──────────────────────────────────────────────────────────────
# Pure helpers (no HTTP, no DB)
# ──────────────────────────────────────────────────────────────


class TestNormalizeOpinion:
    def test_buy_variants(self):
        from nuri.collectors.kis_analyst_opinion import _normalize_opinion

        assert _normalize_opinion("매수") == "buy"
        assert _normalize_opinion("BUY") == "buy"
        assert _normalize_opinion("Buy") == "buy"
        assert _normalize_opinion("Outperform") == "buy"
        assert _normalize_opinion("Trading BUY") == "buy"

    def test_hold_variants(self):
        from nuri.collectors.kis_analyst_opinion import _normalize_opinion

        assert _normalize_opinion("보유") == "hold"
        assert _normalize_opinion("Hold") == "hold"
        assert _normalize_opinion("Neutral") == "hold"

    def test_sell_variants(self):
        from nuri.collectors.kis_analyst_opinion import _normalize_opinion

        assert _normalize_opinion("매도") == "sell"
        assert _normalize_opinion("Sell") == "sell"
        assert _normalize_opinion("Underperform") == "sell"

    def test_empty_or_unknown_returns_none(self):
        from nuri.collectors.kis_analyst_opinion import _normalize_opinion

        assert _normalize_opinion("") is None
        assert _normalize_opinion(None) is None
        assert _normalize_opinion("Some weird new label") is None


class TestActionDerivation:
    def test_init_when_no_prev(self):
        from nuri.collectors.kis_analyst_opinion import _derive_action

        assert _derive_action("매수", None) == "init"
        assert _derive_action("매수", "") == "init"

    def test_maintain_when_same_bucket(self):
        from nuri.collectors.kis_analyst_opinion import _derive_action

        # Different surface text but same canonical bucket.
        assert _derive_action("매수", "BUY") == "main"
        assert _derive_action("Hold", "Neutral") == "main"
        assert _derive_action("BUY", "Outperform") == "main"

    def test_upgrade(self):
        from nuri.collectors.kis_analyst_opinion import _derive_action

        assert _derive_action("매수", "보유") == "up"
        assert _derive_action("Buy", "Sell") == "up"
        assert _derive_action("Hold", "Sell") == "up"

    def test_downgrade(self):
        from nuri.collectors.kis_analyst_opinion import _derive_action

        assert _derive_action("보유", "매수") == "down"
        assert _derive_action("Sell", "Buy") == "down"

    def test_unknown_curr_treated_as_init(self):
        """If current text doesn't normalize cleanly, surface as init rather
        than guessing a direction."""
        from nuri.collectors.kis_analyst_opinion import _derive_action

        assert _derive_action("Some weird label", "매수") == "init"


class TestParseTargetPrice:
    def test_valid_string(self):
        from nuri.collectors.kis_analyst_opinion import _parse_target_price

        assert _parse_target_price("300000") == 300000.0

    def test_zero_or_empty_returns_none(self):
        from nuri.collectors.kis_analyst_opinion import _parse_target_price

        assert _parse_target_price("0") is None
        assert _parse_target_price("") is None
        assert _parse_target_price(None) is None

    def test_non_numeric_returns_none(self):
        from nuri.collectors.kis_analyst_opinion import _parse_target_price

        assert _parse_target_price("abc") is None


class TestParseKisRow:
    def test_full_row(self):
        from nuri.collectors.kis_analyst_opinion import _parse_kis_row

        row = _default_rows()[0]
        rec = _parse_kis_row(row, "005930.KS")
        assert rec is not None
        assert rec == {
            "ticker": "005930.KS",
            "date": "2026-04-21",
            "firm": "Test Securities A",
            "to_grade": "매수",
            "from_grade": "보유",
            "action": "up",  # 보유→매수 = upgrade
            "target_price": 300000.0,
        }

    def test_empty_mbcr_falls_back_to_KIS_UNKNOWN(self):
        """Codex Round 1 critical: NULL firm breaks UNIQUE(ticker, date, firm) UPSERT."""
        from nuri.collectors.kis_analyst_opinion import _parse_kis_row

        row = dict(_default_rows()[0], mbcr_name="")
        rec = _parse_kis_row(row, "005930.KS")
        assert rec is not None
        assert rec["firm"] == "KIS_UNKNOWN"

    def test_empty_date_returns_none(self):
        from nuri.collectors.kis_analyst_opinion import _parse_kis_row

        row = dict(_default_rows()[0], stck_bsop_date="")
        assert _parse_kis_row(row, "005930.KS") is None


# ──────────────────────────────────────────────────────────────
# Failure modes (Surface §2.6)
# ──────────────────────────────────────────────────────────────


class TestNoCredsSurface:
    def test_returns_empty_and_emits_step_blocked(self, db_with_portfolio, monkeypatch):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        monkeypatch.setattr(
            "nuri.collectors.kis_realtime.load_credentials",
            lambda mode="prod": None,
        )
        c = KISAnalystOpinionCollector()
        result = c.collect(tickers=["005930.KS"])
        assert result == []

        events = query(
            "SELECT payload FROM pipeline_events WHERE event_type='step_blocked' AND payload LIKE '%kis_creds_missing%'",
            db_path=db_with_portfolio,
        )
        assert len(events) >= 1


class TestTokenFailSurface:
    def test_returns_empty_and_emits_step_failed(self, db_with_portfolio, mock_kis_creds):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value=None),
        ):
            result = KISAnalystOpinionCollector().collect(tickers=["005930.KS"])
        assert result == []

        events = query(
            "SELECT payload FROM pipeline_events WHERE event_type='step_failed' AND payload LIKE '%kis_token_failed%'",
            db_path=db_with_portfolio,
        )
        assert len(events) >= 1


# ──────────────────────────────────────────────────────────────
# Happy paths + run summary event
# ──────────────────────────────────────────────────────────────


class TestCollectHappyPath:
    def test_single_ticker_parses_rows(self, db_with_portfolio, mock_kis_creds):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        fake = _resp(_fake_invest_opinion_response())
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", return_value=fake),
            patch("time.sleep"),
        ):
            result = KISAnalystOpinionCollector().collect(tickers=["005930.KS"])
        assert len(result) == 2
        assert result[0]["ticker"] == "005930.KS"
        assert result[0]["date"] == "2026-04-21"
        assert result[0]["firm"] == "Test Securities A"
        assert result[1]["firm"] == "Test Securities B"

    def test_empty_payload_counts_as_empty_not_failed(self, db_with_portfolio, mock_kis_creds):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        fake = _resp(_fake_invest_opinion_response(rows=[]))
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", return_value=fake),
            patch("time.sleep"),
        ):
            result = KISAnalystOpinionCollector().collect(tickers=["005930.KS"])
        assert result == []

        events = query(
            "SELECT payload FROM pipeline_events WHERE event_type='kis_analyst_opinion_run'",
            db_path=db_with_portfolio,
        )
        assert len(events) == 1
        # empty=1, covered=0, failed=0 expected.
        import json as _json

        payload = _json.loads(events[0]["payload"])
        assert payload["empty"] == 1
        assert payload["covered"] == 0
        assert payload["failed"] == 0
        assert payload["rows"] == 0


class TestPagination:
    def test_tr_cont_M_recurses(self, db_with_portfolio, mock_kis_creds):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        page_1 = _resp(
            _fake_invest_opinion_response(rows=[_default_rows()[0]]),
            tr_cont="M",
        )
        page_2 = _resp(
            _fake_invest_opinion_response(rows=[_default_rows()[1]]),
            tr_cont="",
        )
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", side_effect=[page_1, page_2]),
            patch("time.sleep"),
        ):
            result = KISAnalystOpinionCollector().collect(tickers=["005930.KS"])
        assert len(result) == 2

    def test_truncation_risk_event_at_high_depth(self, db_with_portfolio, mock_kis_creds):
        """8+ pages → kis_analyst_opinion_truncation_risk surface."""
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        # 10 pages all returning tr_cont=M (will hit max_depth)
        pages = [_resp(_fake_invest_opinion_response(rows=[_default_rows()[0]]), tr_cont="M") for _ in range(10)]
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", side_effect=pages),
            patch("time.sleep"),
        ):
            KISAnalystOpinionCollector().collect(tickers=["005930.KS"])

        events = query(
            "SELECT payload FROM pipeline_events WHERE event_type='kis_analyst_opinion_truncation_risk'",
            db_path=db_with_portfolio,
        )
        assert len(events) >= 1


# ──────────────────────────────────────────────────────────────
# Per-ticker failure handling (no raise)
# ──────────────────────────────────────────────────────────────


class TestPerTickerErrorSkip:
    def test_one_ticker_http_500_others_continue(self, db_with_portfolio, mock_kis_creds):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        ok = _resp(_fake_invest_opinion_response())
        err = _resp({}, status=500)
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", side_effect=[ok, err, ok]),
            patch("time.sleep"),
        ):
            result = KISAnalystOpinionCollector().collect(tickers=["005930.KS", "000660.KS", "035420.KS"])
        # Two tickers succeed (2 rows each), middle one HTTP-500 returns nothing.
        assert len(result) == 4
        tickers = {r["ticker"] for r in result}
        assert tickers == {"005930.KS", "035420.KS"}

    def test_request_exception_skips_ticker_no_raise(self, db_with_portfolio, mock_kis_creds):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        def _raise(*a, **kw):
            raise ConnectionError("boom")

        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", side_effect=_raise),
            patch("time.sleep"),
        ):
            # Should not raise.
            result = KISAnalystOpinionCollector().collect(tickers=["005930.KS"])
        assert result == []


class TestRateLimitRetry:
    def test_first_attempt_rate_limited_then_success(self, db_with_portfolio, mock_kis_creds):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        rate_limited_body = {"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "거래건수 초과", "output": []}
        rate_limited = _resp(rate_limited_body)
        success = _resp(_fake_invest_opinion_response())
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", side_effect=[rate_limited, success]),
            patch("time.sleep"),
        ):
            result = KISAnalystOpinionCollector().collect(tickers=["005930.KS"])
        assert len(result) == 2


# ──────────────────────────────────────────────────────────────
# UPSERT idempotence (codex Biggest Risk)
# ──────────────────────────────────────────────────────────────


class TestUpsertIdempotent:
    def test_same_payload_inserted_twice_does_not_duplicate(self, db_with_portfolio):
        from nuri.collectors.kis_analyst_opinion import _upsert_analyst_ratings

        record = {
            "ticker": "005930.KS",
            "date": "2026-04-21",
            "firm": "Test Securities A",
            "to_grade": "매수",
            "from_grade": "보유",
            "action": "up",
            "target_price": 300000.0,
        }
        first = _upsert_analyst_ratings([record], db_path=db_with_portfolio)
        second = _upsert_analyst_ratings([record], db_path=db_with_portfolio)
        assert first == 1
        assert second == 0  # IGNORE on dup → cursor.rowcount=0

        rows = query(
            "SELECT COUNT(*) AS n FROM analyst_ratings WHERE ticker='005930.KS' AND firm='Test Securities A'",
            db_path=db_with_portfolio,
        )
        assert rows[0]["n"] == 1

    def test_empty_firm_stable_fallback_does_not_duplicate(self, db_with_portfolio):
        """KIS_UNKNOWN sentinel must dedupe consistently — codex Round 1."""
        from nuri.collectors.kis_analyst_opinion import _upsert_analyst_ratings

        rec = {
            "ticker": "005930.KS",
            "date": "2026-04-21",
            "firm": "KIS_UNKNOWN",
            "to_grade": "매수",
            "from_grade": None,
            "action": "init",
            "target_price": None,
        }
        _upsert_analyst_ratings([rec], db_path=db_with_portfolio)
        _upsert_analyst_ratings([rec], db_path=db_with_portfolio)
        rows = query(
            "SELECT COUNT(*) AS n FROM analyst_ratings WHERE firm='KIS_UNKNOWN'",
            db_path=db_with_portfolio,
        )
        assert rows[0]["n"] == 1


# ──────────────────────────────────────────────────────────────
# Request param sanity (verify FID + ticker stripping match KIS spec)
# ──────────────────────────────────────────────────────────────


class TestRequestParams:
    def test_ticker_suffix_stripped_and_fid_correct(self, db_with_portfolio, mock_kis_creds):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        fake = _resp(_fake_invest_opinion_response())
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", return_value=fake) as mock_get,
            patch("time.sleep"),
        ):
            KISAnalystOpinionCollector().collect(tickers=["005930.KS"])

        # First request — verify params.
        call = mock_get.call_args_list[0]
        params = call.kwargs["params"]
        assert params["FID_COND_MRKT_DIV_CODE"] == "J"
        assert params["FID_COND_SCR_DIV_CODE"] == "16633"
        assert params["FID_INPUT_ISCD"] == "005930"  # .KS suffix stripped
        # Date format YYYYMMDD, 8 digits.
        assert len(params["FID_INPUT_DATE_1"]) == 8
        assert len(params["FID_INPUT_DATE_2"]) == 8
        # Headers carry tr_id.
        headers = call.kwargs["headers"]
        assert headers["tr_id"] == "FHKST663300C0"

    def test_kq_suffix_also_stripped(self, db_with_portfolio, mock_kis_creds):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        fake = _resp(_fake_invest_opinion_response(rows=[]))
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", return_value=fake) as mock_get,
            patch("time.sleep"),
        ):
            KISAnalystOpinionCollector().collect(tickers=["123456.KQ"])

        params = mock_get.call_args_list[0].kwargs["params"]
        assert params["FID_INPUT_ISCD"] == "123456"
