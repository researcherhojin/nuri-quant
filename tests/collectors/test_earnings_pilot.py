"""R01 capture integrity, failure reporting and operational isolation."""

import hashlib
import json
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from nuri.collectors import earnings_pilot as pilot
from nuri.core import db


@pytest.fixture(autouse=True)
def forbid_database_access(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("pilot opened a database")

    monkeypatch.setattr(db, "get_connection", forbidden)


def payload(avg: float | bool | None = 1.5):
    return {
        "quoteSummary": {
            "result": [
                {
                    "earningsTrend": {
                        "trend": [{"period": "0q", "endDate": "2026-12-31", "earningsEstimate": {"avg": {"raw": avg}}}]
                    },
                    "calendarEvents": {"earnings": {"earningsDate": [1234567890]}},
                }
            ],
            "error": None,
        }
    }


def test_captures_are_immutable_and_timestamps_are_not_publication(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, "_fetch_payload", lambda ticker: payload())
    monkeypatch.setattr(pilot, "kst_now", lambda: datetime(2026, 10, 22, tzinfo=timezone.utc))
    collector = pilot.EarningsPilotCollector(["TESTAA"], tmp_path)
    assert collector.run() == 1
    first = collector.last_artifact
    assert first is not None
    before = first.read_bytes()
    monkeypatch.setattr(pilot, "_fetch_payload", lambda ticker: payload(2.5))
    assert collector.run() == 1
    assert collector.last_artifact != first
    assert first.read_bytes() == before
    saved = json.loads(before)
    row = saved["observations"][0]
    assert row["payload_sha256"] == hashlib.sha256(pilot._encode(row["payload"])).hexdigest()
    assert row["response_observed_at_utc"] == "2026-10-22T00:00:00+00:00"
    assert row["published_at_utc"] is None
    assert row["preannouncement_verified"] is False
    assert saved["r01_launch_ready"] is False
    with pytest.raises(FileExistsError):
        collector.save(saved)


@pytest.mark.parametrize("value", [{}, {"quoteSummary": {"result": []}}, payload(None), payload(True)])
def test_empty_or_invalid_estimates_are_not_success(tmp_path, monkeypatch, value):
    monkeypatch.setattr(pilot, "_fetch_payload", lambda ticker: value)
    collector = pilot.EarningsPilotCollector(["TESTAA"], tmp_path)
    assert collector.run() == 0
    assert collector.last_artifact is not None
    saved = json.loads(collector.last_artifact.read_bytes())
    assert saved["observations"][0]["status"] == "no_usable_estimate"


def test_failure_is_archived_without_alerts_or_db(tmp_path, monkeypatch):
    def fail(ticker):
        raise TimeoutError("sensitive query details")

    def forbidden(*args, **kwargs):
        pytest.fail("operational side effect")

    monkeypatch.setattr(pilot, "_fetch_payload", fail)
    monkeypatch.setattr(pilot.BaseCollector, "_send_failure_alert", forbidden)
    monkeypatch.setattr(pilot.BaseCollector, "_get_tickers", forbidden)
    collector = pilot.EarningsPilotCollector(["TESTAA"], tmp_path)
    assert collector.run() == 0
    assert collector.last_artifact is not None
    saved = collector.last_artifact.read_text()
    row = json.loads(saved)["observations"][0]
    assert row["status"] == "request_failed"
    assert row["error_type"] == "TimeoutError"
    assert "sensitive query details" not in saved


def test_provider_error_body_is_not_ordinary_missing_data(tmp_path, monkeypatch):
    response = {"quoteSummary": {"result": None, "error": {"code": "Unauthorized"}}}
    monkeypatch.setattr(pilot, "_fetch_payload", lambda ticker: response)
    collector = pilot.EarningsPilotCollector(["TESTAA"], tmp_path)
    assert collector.run() == 0
    assert collector.last_artifact is not None
    row = json.loads(collector.last_artifact.read_text())["observations"][0]
    assert row["status"] == "provider_error"
    assert row["error_type"] == "ProviderResponseError"
    assert row["payload"] == response


@pytest.mark.parametrize("tickers", [[], ["../escape"], ["testaa"]])
def test_explicit_symbols_required(tmp_path, tickers):
    with pytest.raises(ValueError):
        pilot.EarningsPilotCollector(tickers, tmp_path)


def test_adapter_requests_original_fields_with_timeout(monkeypatch):
    calls = []

    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return payload()

    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(Ticker=lambda ticker: SimpleNamespace(_data=SimpleNamespace(get_raw_json=fetch))),
    )
    result = pilot._fetch_payload("TESTAA")
    assert result == payload()
    assert calls == [
        (
            "https://query2.finance.yahoo.com/v10/finance/quoteSummary/TESTAA",
            {"params": {"modules": pilot.MODULES, "formatted": "false"}, "timeout": 20},
        )
    ]


@pytest.mark.parametrize(("response", "exit_code"), [(payload(), 0), ({}, 2)])
def test_cli_reports_transport_success_separately_from_readiness(tmp_path, monkeypatch, capsys, response, exit_code):
    monkeypatch.setattr(sys, "argv", ["pilot", "--tickers", "TESTAA", "--output", str(tmp_path)])
    monkeypatch.setattr(pilot, "_fetch_payload", lambda ticker: response)
    assert pilot.main() == exit_code
    summary = json.loads(capsys.readouterr().out)
    assert summary["r01_launch_ready"] is False
    assert summary["requested_symbols"] == 1


def test_estimate_rejects_error_even_when_estimate_is_present():
    response = payload()
    response["quoteSummary"]["error"] = {"code": "Unauthorized"}
    assert pilot._has_estimate(response) is False


def test_module_entrypoint_uses_explicit_symbols_and_archives(tmp_path, monkeypatch, capsys):
    import runpy

    calls = []

    def ticker(symbol):
        calls.append(symbol)
        return SimpleNamespace(_data=SimpleNamespace(get_raw_json=lambda *args, **kwargs: payload()))

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=ticker))
    monkeypatch.setattr(sys, "argv", ["pilot", "--tickers", "TESTAA", "--output", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("nuri.collectors.earnings_pilot", run_name="__main__")
    assert exc.value.code == 0
    assert calls == ["TESTAA"]
    result = json.loads(capsys.readouterr().out)
    assert result["estimates_observed"] == 1
    assert result["r01_launch_ready"] is False
    assert len(list(tmp_path.glob("capture-*.json"))) == 1
