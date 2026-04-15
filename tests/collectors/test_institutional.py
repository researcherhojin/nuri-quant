"""Per-collector tests for institutional — KIS Open API path (#247).

KR path uses KIS `investor-trade-by-stock-daily` endpoint. pykrx removed.
"""

from unittest.mock import MagicMock, patch

import pytest

from nuri.core.db import init_db, query

# ──────────────────────────────────────────────────────────────
# Helpers / fixtures
# ──────────────────────────────────────────────────────────────


def _fake_kis_response(
    ticker_code: str = "005930",
    dates: list[str] | None = None,
    rt_cd: str = "0",
    msg1: str = "정상처리 되었습니다.",
):
    """Build a KIS-shaped JSON response (output2 = list of daily rows)."""
    dates = dates or ["20260414", "20260413", "20260410"]
    output2 = []
    for i, d in enumerate(dates):
        output2.append(
            {
                "stck_bsop_date": d,
                "frgn_ntby_qty": str(100_000 + i * 10),
                "orgn_ntby_qty": str(-50_000 - i * 5),
                "prsn_ntby_qty": str(-50_000 + i * 3),
                "frgn_ntby_tr_pbmn": str(20_000 + i),
                "orgn_ntby_tr_pbmn": str(-10_000 - i),
                "prsn_ntby_tr_pbmn": str(-10_000 + i),
            }
        )
    return {"rt_cd": rt_cd, "msg_cd": "MCA00000", "msg1": msg1, "output2": output2}


@pytest.fixture
def mock_kis_creds():
    """Valid KIS credentials object."""
    from nuri.collectors.kis_realtime import KISCredentials

    return KISCredentials(
        app_key="test_app_key",
        app_secret="test_app_secret",
        account="1234567",
        hts_id="test_hts",
        mode="prod",
    )


# ──────────────────────────────────────────────────────────────
# Pure parsing helpers (no network, no DB)
# ──────────────────────────────────────────────────────────────


class TestParseKisRow:
    def test_valid_row(self):
        from nuri.collectors.institutional import _parse_kis_row

        row = {
            "stck_bsop_date": "20260414",
            "frgn_ntby_qty": "465171",
            "orgn_ntby_qty": "-475614",
            "prsn_ntby_qty": "-1938572",
        }
        result = _parse_kis_row(row, "005930.KS")
        assert result == {
            "ticker": "005930.KS",
            "date": "2026-04-14",
            "market": "KR",
            "institution_net": -475614,
            "foreign_net": 465171,
            "individual_net": -1938572,
            "source": "kis_openapi",
        }

    def test_missing_date(self):
        from nuri.collectors.institutional import _parse_kis_row

        assert _parse_kis_row({"frgn_ntby_qty": "100"}, "005930.KS") is None
        assert _parse_kis_row({"stck_bsop_date": ""}, "005930.KS") is None
        assert _parse_kis_row({"stck_bsop_date": "invalid"}, "005930.KS") is None

    def test_missing_qty_fields(self):
        """Missing fields become None — graceful degradation."""
        from nuri.collectors.institutional import _parse_kis_row

        result = _parse_kis_row({"stck_bsop_date": "20260414"}, "005930.KS")
        assert result is not None
        assert result["foreign_net"] is None
        assert result["institution_net"] is None


class TestSafeInt:
    def test_valid(self):
        from nuri.collectors.institutional import _safe_int

        assert _safe_int("465171") == 465171
        assert _safe_int("-475614") == -475614
        assert _safe_int("1,000,000") == 1_000_000  # Korean-style comma

    def test_invalid(self):
        from nuri.collectors.institutional import _safe_int

        assert _safe_int(None) is None
        assert _safe_int("") is None
        assert _safe_int("abc") is None


# ──────────────────────────────────────────────────────────────
# _collect_kr_kis — credential / token failure paths (Surface §2.6)
# ──────────────────────────────────────────────────────────────


class TestCollectKrKisNoCreds:
    def test_returns_empty_and_surfaces_event(self, db_with_portfolio, monkeypatch):
        """No KIS creds → skip + step_blocked event, not silent empty."""
        from nuri.collectors.institutional import InstitutionalCollector

        with patch("nuri.collectors.kis_realtime.load_credentials", return_value=None):
            c = InstitutionalCollector()
            result = c._collect_kr_kis(["005930.KS"])
        assert result == []

        # Verify pipeline event emitted (Surface rung, not silent)
        events = query(
            "SELECT event_type, payload FROM pipeline_events "
            "WHERE event_type='step_blocked' AND payload LIKE '%kis_creds_missing%'",
            db_path=db_with_portfolio,
        )
        # At least one event emitted (events table may have other rows from db_with_portfolio)
        assert len(events) >= 1

    def test_invalid_creds(self, db_with_portfolio):
        """KIS creds object exists but empty → same as None."""
        from nuri.collectors.institutional import InstitutionalCollector
        from nuri.collectors.kis_realtime import KISCredentials

        empty_creds = KISCredentials(app_key="", app_secret="", account="", hts_id="", mode="prod")
        with patch("nuri.collectors.kis_realtime.load_credentials", return_value=empty_creds):
            c = InstitutionalCollector()
            assert c._collect_kr_kis(["005930.KS"]) == []


class TestCollectKrKisTokenFail:
    def test_token_failure(self, db_with_portfolio, mock_kis_creds):
        """Token None → skip + step_failed event."""
        from nuri.collectors.institutional import InstitutionalCollector

        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value=None),
        ):
            c = InstitutionalCollector()
            assert c._collect_kr_kis(["005930.KS"]) == []

        events = query(
            "SELECT payload FROM pipeline_events WHERE event_type='step_failed' AND payload LIKE '%kis_token_failed%'",
            db_path=db_with_portfolio,
        )
        assert len(events) >= 1


# ──────────────────────────────────────────────────────────────
# _collect_kr_kis — success path (mocked KIS API)
# ──────────────────────────────────────────────────────────────


class TestCollectKrKisSuccess:
    def test_single_ticker_parses_30_rows(self, db_with_portfolio, mock_kis_creds):
        """Mock KIS response → all rows parsed into records."""
        from nuri.collectors.institutional import InstitutionalCollector

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = _fake_kis_response(
            dates=["20260414", "20260413", "20260410", "20260409"],
        )

        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="fake_token"),
            patch("requests.get", return_value=fake_resp),
            patch("time.sleep"),
        ):  # no real delay in tests
            c = InstitutionalCollector()
            result = c._collect_kr_kis(["005930.KS"])

        assert len(result) == 4
        assert result[0]["ticker"] == "005930.KS"
        assert result[0]["date"] == "2026-04-14"
        assert result[0]["source"] == "kis_openapi"
        assert result[0]["foreign_net"] == 100_000
        assert result[0]["institution_net"] == -50_000

    def test_multiple_tickers(self, db_with_portfolio, mock_kis_creds):
        from nuri.collectors.institutional import InstitutionalCollector

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = _fake_kis_response(dates=["20260414"])

        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", return_value=fake_resp),
            patch("time.sleep"),
        ):
            result = InstitutionalCollector()._collect_kr_kis(["005930.KS", "000660.KS"])

        assert len(result) == 2
        assert {r["ticker"] for r in result} == {"005930.KS", "000660.KS"}


class TestCollectKrKisFailureModes:
    def test_http_error_skips_ticker(self, db_with_portfolio, mock_kis_creds):
        """HTTP 500 → skip ticker, no exception propagation."""
        from nuri.collectors.institutional import InstitutionalCollector

        fake_resp = MagicMock()
        fake_resp.status_code = 500

        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", return_value=fake_resp),
            patch("time.sleep"),
        ):
            result = InstitutionalCollector()._collect_kr_kis(["005930.KS"])

        assert result == []

    def test_rt_cd_nonzero(self, db_with_portfolio, mock_kis_creds):
        """rt_cd=2 (TIME LIMIT) → skip ticker, no records."""
        from nuri.collectors.institutional import InstitutionalCollector

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "rt_cd": "2",
            "msg_cd": "OPSQ2001",
            "msg1": "TIME LIMIT 00:00 ~ 15:40",
            "output2": [],
        }

        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", return_value=fake_resp),
            patch("time.sleep"),
        ):
            result = InstitutionalCollector()._collect_kr_kis(["005930.KS"])

        assert result == []

    def test_rate_limit_retry_then_success(self, db_with_portfolio, mock_kis_creds):
        """First response rate-limited → sleep → retry succeeds → records parsed.

        Covers rate_limit retry branch (institutional.py L151-156) — close
        Codecov gap from PR #316.
        """
        from nuri.collectors.institutional import InstitutionalCollector

        rate_limited = MagicMock()
        rate_limited.status_code = 200
        rate_limited.json.return_value = {
            "rt_cd": "1",
            "msg_cd": "EGW00201",
            "msg1": "초당 거래건수를 초과하였습니다.",
            "output2": [],
        }
        success = MagicMock()
        success.status_code = 200
        success.json.return_value = _fake_kis_response(dates=["20260414"])

        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", side_effect=[rate_limited, success]),
            patch("time.sleep"),
        ):
            result = InstitutionalCollector()._collect_kr_kis(["005930.KS"])

        # Second call's output2 parsed → 1 record
        assert len(result) == 1
        assert result[0]["date"] == "2026-04-14"
        assert result[0]["source"] == "kis_openapi"

    def test_network_exception_skips_ticker(self, db_with_portfolio, mock_kis_creds):
        """requests.get raises → ticker skipped, loop continues."""
        from nuri.collectors.institutional import InstitutionalCollector

        def _raise(*_a, **_kw):
            raise ConnectionError("network down")

        with (
            patch("nuri.collectors.kis_realtime.load_credentials", return_value=mock_kis_creds),
            patch("nuri.collectors.kis_realtime.get_access_token", return_value="tok"),
            patch("requests.get", side_effect=_raise),
            patch("time.sleep"),
        ):
            result = InstitutionalCollector()._collect_kr_kis(["005930.KS", "000660.KS"])

        assert result == []


# ──────────────────────────────────────────────────────────────
# UPSERT — B1 lesson (PR #311)
# ──────────────────────────────────────────────────────────────


class TestUpsertOnConflict:
    def test_duplicate_date_ticker_updates_not_duplicates(self, db_path):
        """Same (ticker, date, market) twice → 1 row, updated values."""
        # monkeypatch DB_PATH
        import nuri.core.db as db_mod
        from nuri.collectors.institutional import _upsert_institutional

        original = db_mod.DB_PATH
        db_mod.DB_PATH = db_path
        try:
            rec_v1 = {
                "ticker": "005930.KS",
                "date": "2026-04-14",
                "market": "KR",
                "institution_net": 100,
                "foreign_net": 200,
                "individual_net": 300,
                "source": "kis_openapi",
            }
            assert _upsert_institutional([rec_v1]) == 1

            rec_v2 = {**rec_v1, "institution_net": 999, "foreign_net": 999, "individual_net": 999}
            assert _upsert_institutional([rec_v2]) == 1

            rows = query(
                "SELECT * FROM institutional_flows WHERE ticker='005930.KS' AND date='2026-04-14'", db_path=db_path
            )
            assert len(rows) == 1
            assert rows[0]["institution_net"] == 999
            assert rows[0]["foreign_net"] == 999
        finally:
            db_mod.DB_PATH = original


# ──────────────────────────────────────────────────────────────
# US path (finnhub) — unchanged from pre-#247
# ──────────────────────────────────────────────────────────────


class TestCollectUs:
    def test_finnhub_success(self, monkeypatch, db_with_portfolio):
        from nuri.collectors.institutional import InstitutionalCollector

        monkeypatch.setenv("FINNHUB_API_KEY", "test_key")
        mock_client = MagicMock()
        mock_client.ownership.return_value = {"ownership": [{"data": "test"}]}
        mock_finnhub = MagicMock()
        mock_finnhub.Client.return_value = mock_client
        import sys

        monkeypatch.setitem(sys.modules, "finnhub", mock_finnhub)

        c = InstitutionalCollector()
        monkeypatch.setattr(
            c, "_get_tickers", lambda market=None, source="portfolio": ["AAPL"] if market == "us" else []
        )
        # Patch KIS to return empty (avoid KR work interfering)
        with patch.object(c, "_collect_kr_kis", return_value=[]):
            result = c.collect()
        assert any(r["market"] == "US" for r in result)

    def test_finnhub_import_error(self, monkeypatch, db_with_portfolio):
        import sys

        from nuri.collectors.institutional import InstitutionalCollector

        monkeypatch.delitem(sys.modules, "finnhub", raising=False)
        original_import = __import__

        def _mock_import(name, *args, **kwargs):
            if name == "finnhub":
                raise ImportError("no finnhub")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _mock_import)
        assert InstitutionalCollector()._collect_us(["AAPL"], "key") == []

    def test_finnhub_ticker_error(self, monkeypatch, db_with_portfolio):
        import sys

        from nuri.collectors.institutional import InstitutionalCollector

        mock_client = MagicMock()
        mock_client.ownership.side_effect = Exception("API error")
        mock_finnhub = MagicMock()
        mock_finnhub.Client.return_value = mock_client
        monkeypatch.setitem(sys.modules, "finnhub", mock_finnhub)
        assert InstitutionalCollector()._collect_us(["AAPL"], "key") == []


# ──────────────────────────────────────────────────────────────
# Save + collector smoke
# ──────────────────────────────────────────────────────────────


class TestSaveAndBasics:
    def test_save_empty(self, db_path):
        from nuri.collectors.institutional import InstitutionalCollector

        assert InstitutionalCollector().save([]) == 0

    def test_save_records(self, db_path):
        import nuri.core.db as db_mod
        from nuri.collectors.institutional import InstitutionalCollector

        original = db_mod.DB_PATH
        db_mod.DB_PATH = db_path
        try:
            count = InstitutionalCollector().save(
                [
                    {
                        "ticker": "005930.KS",
                        "date": "2026-04-14",
                        "market": "KR",
                        "institution_net": 1_000_000,
                        "foreign_net": 500_000,
                        "individual_net": -1_500_000,
                        "source": "kis_openapi",
                    }
                ]
            )
            assert count == 1
        finally:
            db_mod.DB_PATH = original

    def test_collector_name(self):
        from nuri.collectors.institutional import InstitutionalCollector

        assert InstitutionalCollector().name == "institutional"


class TestCollectNoUSTickets:
    """Unrelated — kept from legacy test file."""

    def test_no_us_tickers(self, monkeypatch, tmp_path):
        import nuri.core.db as db_mod
        from nuri.collectors.reddit import RedditCollector

        path = tmp_path / "empty.db"
        init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        assert RedditCollector().collect() == []
