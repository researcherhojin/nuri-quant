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

    def test_truncation_risk_event_emits_exactly_once_per_ticker(self, db_with_portfolio, mock_kis_creds):
        """Codex review P2: truncation_risk surfaces ONCE per ticker, not on every
        continued page (depth 8/9/10). Doc contract: '한 번 surface, 계속 진행'."""
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        # 10 pages all returning tr_cont=M (will hit max_depth — covers depths 8, 9, 10).
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
        # Exactly one — not 3 (one per page from depth 8 onward).
        assert len(events) == 1

    def test_continuation_request_carries_tr_cont_N(self, db_with_portfolio, mock_kis_creds):
        """Codex review test gap: assert second paginated request actually sends
        tr_cont='N' (continuation flag per official sample)."""
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        page_1 = _resp(_fake_invest_opinion_response(rows=[_default_rows()[0]]), tr_cont="M")
        page_2 = _resp(_fake_invest_opinion_response(rows=[_default_rows()[1]]), tr_cont="")
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", side_effect=[page_1, page_2]) as mock_get,
            patch("time.sleep"),
        ):
            KISAnalystOpinionCollector().collect(tickers=["005930.KS"])

        # First request sends empty tr_cont; second sends "N".
        first_headers = mock_get.call_args_list[0].kwargs["headers"]
        second_headers = mock_get.call_args_list[1].kwargs["headers"]
        assert first_headers["tr_cont"] == ""
        assert second_headers["tr_cont"] == "N"


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


class TestFailureClassification:
    """Codex Round 1 review P1: HTTP non-200 / rt_cd != 0 must increment
    `failed` counter, not `empty`. Telemetry honesty about run health."""

    def test_http_500_increments_failed_not_empty(self, db_with_portfolio, mock_kis_creds):
        import json as _json

        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        err = _resp({}, status=500)
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", return_value=err),
            patch("time.sleep"),
        ):
            KISAnalystOpinionCollector().collect(tickers=["005930.KS"])

        events = query(
            "SELECT payload FROM pipeline_events WHERE event_type='kis_analyst_opinion_run'",
            db_path=db_with_portfolio,
        )
        assert len(events) == 1
        payload = _json.loads(events[0]["payload"])
        assert payload["failed"] == 1
        assert payload["empty"] == 0
        assert payload["covered"] == 0

    def test_rt_cd_nonzero_increments_failed_not_empty(self, db_with_portfolio, mock_kis_creds):
        """rt_cd != "0" (KIS application-level error) → failed, not empty."""
        import json as _json

        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        err_body = {"rt_cd": "1", "msg_cd": "EHTC0001", "msg1": "권한 오류", "output": []}
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", return_value=_resp(err_body)),
            patch("time.sleep"),
        ):
            KISAnalystOpinionCollector().collect(tickers=["005930.KS"])

        events = query(
            "SELECT payload FROM pipeline_events WHERE event_type='kis_analyst_opinion_run'",
            db_path=db_with_portfolio,
        )
        payload = _json.loads(events[0]["payload"])
        assert payload["failed"] == 1
        assert payload["empty"] == 0


class TestMalformedRowResilience:
    """Codex Round 1 review P1: a single malformed row (None / non-string fields)
    must not abort the per-ticker loop."""

    def test_none_in_fields_does_not_crash(self, db_with_portfolio, mock_kis_creds):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        rows = [
            {  # First row malformed — None everywhere.
                "stck_bsop_date": None,
                "invt_opnn": None,
                "rgbf_invt_opnn": None,
                "mbcr_name": None,
                "hts_goal_prc": None,
            },
            {  # Second row valid — must still be parsed.
                "stck_bsop_date": "20260421",
                "invt_opnn": "매수",
                "invt_opnn_cls_code": "2",
                "rgbf_invt_opnn": "보유",
                "mbcr_name": "Test Securities A",
                "hts_goal_prc": "300000",
            },
        ]
        fake = _resp(_fake_invest_opinion_response(rows=rows))
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", return_value=fake),
            patch("time.sleep"),
        ):
            result = KISAnalystOpinionCollector().collect(tickers=["005930.KS"])
        # Malformed row dropped, valid row kept — no crash.
        assert len(result) == 1
        assert result[0]["firm"] == "Test Securities A"

    def test_non_string_field_types(self):
        """Numeric or other non-string types must coerce gracefully."""
        from nuri.collectors.kis_analyst_opinion import _parse_kis_row

        row = {
            "stck_bsop_date": 20260421,  # int instead of str
            "invt_opnn": 0,  # falsy non-str
            "rgbf_invt_opnn": "매수",
            "mbcr_name": 12345,  # int broker code-style
            "hts_goal_prc": "150000",
        }
        rec = _parse_kis_row(row, "005930.KS")
        assert rec is not None
        assert rec["date"] == "2026-04-21"  # int coerced
        assert rec["firm"] == "12345"  # int coerced to string
        # invt_opnn=0 (falsy) → empty after coercion → curr_text=None →
        # action falls to init since prev couldn't compare meaningfully.
        assert rec["action"] == "init"


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


class TestSmallBranches:
    """Codecov gap-fillers for short edge-case branches missed by main suite."""

    def test_format_yyyymmdd_non_eight_digit_passthrough(self):
        from nuri.collectors.kis_analyst_opinion import _format_yyyymmdd

        # Non-8-digit / non-numeric strings pass through unchanged.
        assert _format_yyyymmdd("2026-04-21") == "2026-04-21"
        assert _format_yyyymmdd("xxx") == "xxx"
        assert _format_yyyymmdd("") == ""

    def test_parse_kis_row_non_dict_input(self):
        from nuri.collectors.kis_analyst_opinion import _parse_kis_row

        # Non-dict input → defensive None return (covers isinstance guard).
        assert _parse_kis_row("not a dict", "005930.KS") is None  # type: ignore[arg-type]
        assert _parse_kis_row(None, "005930.KS") is None  # type: ignore[arg-type]

    def test_upsert_empty_records_returns_zero(self, db_with_portfolio):
        from nuri.collectors.kis_analyst_opinion import _upsert_analyst_ratings

        # Early return path when records list is empty.
        assert _upsert_analyst_ratings([], db_path=db_with_portfolio) == 0

    def test_collect_no_tickers_returns_empty(self, db_with_portfolio):
        """No KR tickers in universe → early return without load_credentials."""
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        c = KISAnalystOpinionCollector()
        with (
            patch.object(c, "_get_tickers", return_value=[]),
            patch("nuri.collectors.kis_realtime.load_credentials") as mock_load,
        ):
            # collect() called with no tickers kwarg → falls back to _get_tickers,
            # which we mocked to []. No load_credentials call expected.
            result = c.collect()
        assert result == []
        assert mock_load.call_count == 0

    def test_post_retry_http_failure_classified_failed(self, db_with_portfolio, mock_kis_creds):
        """Rate-limited then post-retry HTTP non-200 → failed (not empty)."""
        import json as _json

        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        rate_limited = _resp({"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "거래건수 초과", "output": []})
        retry_fail = _resp({}, status=503)
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", side_effect=[rate_limited, retry_fail]),
            patch("time.sleep"),
        ):
            KISAnalystOpinionCollector().collect(tickers=["005930.KS"])

        events = query(
            "SELECT payload FROM pipeline_events WHERE event_type='kis_analyst_opinion_run'",
            db_path=db_with_portfolio,
        )
        payload = _json.loads(events[0]["payload"])
        assert payload["failed"] == 1
        assert payload["empty"] == 0

    def test_output_dict_wrapped_to_list(self, db_with_portfolio, mock_kis_creds):
        """KIS sometimes returns output as a single dict instead of list — collector wraps it."""
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        # Single row as bare dict (not wrapped in list).
        body = {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "정상",
            "output": _default_rows()[0],  # dict, not list
        }
        fake = _resp(body)
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", return_value=fake),
            patch("time.sleep"),
        ):
            result = KISAnalystOpinionCollector().collect(tickers=["005930.KS"])
        assert len(result) == 1
        assert result[0]["firm"] == "Test Securities A"

    def test_save_method_upserts(self, db_with_portfolio):
        """Cover KISAnalystOpinionCollector.save() — small wrapper around _upsert_analyst_ratings."""
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        records = [
            {
                "ticker": "005930.KS",
                "date": "2026-04-21",
                "firm": "Test Securities A",
                "to_grade": "매수",
                "from_grade": None,
                "action": "init",
                "target_price": 300000.0,
            }
        ]
        c = KISAnalystOpinionCollector()
        # save() reaches _upsert_analyst_ratings using default DB_PATH (patched
        # by db_with_portfolio fixture's monkeypatch).
        n = c.save(records)
        assert n == 1


class TestDefensiveGuards:
    """Cover the try/except: pass guards around emit_event so those defensive
    blocks are exercised at least once. Pipeline-event persistence failure
    must never propagate up and abort the collector run."""

    def test_no_creds_emit_event_raise_swallowed(self, db_with_portfolio, monkeypatch):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        def _emit_raise(*a, **kw):
            raise RuntimeError("emit failed")

        monkeypatch.setattr("nuri.collectors.kis_realtime.load_credentials", lambda mode="prod": None)
        monkeypatch.setattr("nuri.collectors.kis_analyst_opinion.emit_event", _emit_raise)
        # Should still return [] without raising.
        result = KISAnalystOpinionCollector().collect(tickers=["005930.KS"])
        assert result == []

    def test_token_fail_emit_event_raise_swallowed(self, db_with_portfolio, mock_kis_creds, monkeypatch):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        def _emit_raise(*a, **kw):
            raise RuntimeError("emit failed")

        monkeypatch.setattr("nuri.collectors.kis_realtime.load_credentials", lambda mode="prod": mock_kis_creds)
        monkeypatch.setattr("nuri.collectors.kis_realtime.get_access_token", lambda creds: None)
        monkeypatch.setattr("nuri.collectors.kis_analyst_opinion.emit_event", _emit_raise)
        result = KISAnalystOpinionCollector().collect(tickers=["005930.KS"])
        assert result == []

    def test_run_summary_emit_event_raise_swallowed(self, db_with_portfolio, mock_kis_creds, monkeypatch):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        fake = _resp(_fake_invest_opinion_response())
        monkeypatch.setattr("nuri.collectors.kis_realtime.load_credentials", lambda mode="prod": mock_kis_creds)
        monkeypatch.setattr("nuri.collectors.kis_realtime.get_access_token", lambda creds: "tok")
        monkeypatch.setattr(
            "nuri.collectors.kis_analyst_opinion.emit_event",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("emit failed")),
        )
        with patch("requests.get", return_value=fake), patch("time.sleep"):
            # Even if emit_event raises, the collector returns parsed results.
            result = KISAnalystOpinionCollector().collect(tickers=["005930.KS"])
        assert len(result) == 2

    def test_truncation_emit_event_raise_swallowed(self, db_with_portfolio, mock_kis_creds, monkeypatch):
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        pages = [_resp(_fake_invest_opinion_response(rows=[_default_rows()[0]]), tr_cont="M") for _ in range(10)]
        monkeypatch.setattr("nuri.collectors.kis_realtime.load_credentials", lambda mode="prod": mock_kis_creds)
        monkeypatch.setattr("nuri.collectors.kis_realtime.get_access_token", lambda creds: "tok")
        monkeypatch.setattr(
            "nuri.collectors.kis_analyst_opinion.emit_event",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("emit failed")),
        )
        with patch("requests.get", side_effect=pages), patch("time.sleep"):
            # Truncation risk emit raises but collector continues.
            result = KISAnalystOpinionCollector().collect(tickers=["005930.KS"])
        assert len(result) == 10  # 10 pages * 1 row

    def test_safe_str_object_with_failing_str_method(self):
        """_safe_str returns '' when str(obj) itself raises (defensive)."""
        from nuri.collectors.kis_analyst_opinion import _safe_str

        class Boom:
            def __str__(self):
                raise RuntimeError("str() crash")

        # Triggers `try: str(raw) except: return ''` path.
        assert _safe_str(Boom()) == ""

    def test_per_row_parse_exception_skipped(self, db_with_portfolio, mock_kis_creds, monkeypatch):
        """Per-row try/except in collect() catches anything _parse_kis_row leaks."""
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        fake = _resp(_fake_invest_opinion_response())  # 2 rows
        monkeypatch.setattr("nuri.collectors.kis_realtime.load_credentials", lambda mode="prod": mock_kis_creds)
        monkeypatch.setattr("nuri.collectors.kis_realtime.get_access_token", lambda creds: "tok")

        # Patch _parse_kis_row to raise — collect() must skip the row, not crash.
        def _parse_raise(row, ticker):
            raise RuntimeError("parse boom")

        monkeypatch.setattr("nuri.collectors.kis_analyst_opinion._parse_kis_row", _parse_raise)
        with patch("requests.get", return_value=fake), patch("time.sleep"):
            result = KISAnalystOpinionCollector().collect(tickers=["005930.KS"])
        assert result == []  # All rows skipped, no crash.


class TestMainEntry:
    """Cover the `if __name__ == "__main__"` argparse block."""

    def test_main_with_ticker_argument(self, db_with_portfolio, mock_kis_creds, monkeypatch):
        import runpy
        import sys

        fake = _resp(_fake_invest_opinion_response())

        monkeypatch.setattr(sys, "argv", ["nuri.collectors.kis_analyst_opinion", "--ticker", "005930.KS"])
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", return_value=fake),
            patch("time.sleep"),
        ):
            sys.modules.pop("nuri.collectors.kis_analyst_opinion", None)
            runpy.run_module("nuri.collectors.kis_analyst_opinion", run_name="__main__")


class TestTqdmImportFallback:
    """`from tqdm import tqdm` ImportError → iterator = tickers (lines 269-270).

    sys.modules['tqdm'] = None 으로 설정하면 후속 `from tqdm import` 가 ImportError.
    """

    def test_no_tqdm_uses_plain_iterator(self, db_with_portfolio, mock_kis_creds, monkeypatch):
        import sys

        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        # tqdm 캐시 제거 후 None 등록 → from tqdm import tqdm → ImportError
        monkeypatch.delitem(sys.modules, "tqdm", raising=False)
        monkeypatch.delitem(sys.modules, "tqdm.std", raising=False)
        monkeypatch.setitem(sys.modules, "tqdm", None)

        fake = _resp(_fake_invest_opinion_response())
        c = KISAnalystOpinionCollector()
        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", return_value=fake),
            patch("time.sleep"),
        ):
            # 호출만 정상 통과 — except ImportError 분기로 iterator=tickers
            results = c.collect(tickers=["005930.KS"])
            assert isinstance(results, list)
