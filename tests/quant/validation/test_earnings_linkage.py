"""Timing and period checks must not grant accounting equivalence."""

import hashlib
import json
import runpy
import sys

import pytest

from nuri.quant.validation import earnings_linkage
from nuri.quant.validation.earnings_linkage import audit_link


@pytest.fixture
def evidence():
    source = b"Published: 2026-10-21 16:08 EDT"
    payload = {
        "quoteSummary": {
            "result": [
                {
                    "earningsTrend": {
                        "trend": [{"period": "0q", "endDate": "2026-09-30", "earningsEstimate": {"avg": {"raw": 1.0}}}]
                    }
                }
            ],
            "error": None,
        }
    }
    observation = {
        "ticker": "TESTAA",
        "status": "estimate_observed",
        "payload": payload,
        "payload_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "request_started_at_utc": "2026-10-21T19:00:00+00:00",
        "response_observed_at_utc": "2026-10-21T19:01:00+00:00",
    }
    release = {
        "ticker": "TESTAA",
        "source_url": "https://example.com/release",
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "fiscal_period_end": "2026-09-30",
        "publication_kind": "issuer_release",
        "publication_excerpt": source.decode(),
        "published_at_utc": "2026-10-21T16:08:00-04:00",
    }
    return observation, release, source


def test_good_timing_does_not_prove_accounting_basis(evidence):
    result = audit_link(*evidence)
    assert result["timing_and_period_verified"] is True
    assert result["accounting_basis_status"] == "unverified"
    assert result["research_eligible"] is False


@pytest.mark.parametrize("observed", ["2026-10-21T20:08:00+00:00", "2026-10-22T11:39:00+00:00"])
def test_equal_or_later_capture_is_not_preannouncement(evidence, observed):
    observation, release, source = evidence
    observation["response_observed_at_utc"] = observed
    assert "NOT_PREANNOUNCEMENT" in audit_link(observation, release, source)["timing_reasons"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("fiscal_period_end", "2026-12-31", "PERIOD_NOT_UNIQUELY_MATCHED"),
        ("publication_kind", "earnings_call", "ACTUAL_RELEASE_TIME_UNVERIFIED"),
        ("publication_kind", "scheduled", "ACTUAL_RELEASE_TIME_UNVERIFIED"),
        ("publication_kind", "sec_filing", "ACTUAL_RELEASE_TIME_UNVERIFIED"),
        ("published_at_utc", "2026-10-21", "MISSING_OR_INVALID_EVIDENCE"),
        ("published_at_utc", None, "MISSING_OR_INVALID_EVIDENCE"),
        ("publication_excerpt", "not in source", "PUBLICATION_EXCERPT_UNVERIFIED"),
        ("publication_excerpt", " ", "PUBLICATION_EXCERPT_UNVERIFIED"),
        ("publication_excerpt", None, "PUBLICATION_EXCERPT_UNVERIFIED"),
        ("source_url", "", "SOURCE_URL_MISSING"),
        ("source_url", "http://example.com/release", "SOURCE_URL_MISSING"),
        ("ticker", "TESTBB", "ISSUER_MISMATCH"),
    ],
)
def test_invalid_release_is_held(evidence, field, value, reason):
    observation, release, source = evidence
    release[field] = value
    result = audit_link(observation, release, source)
    assert reason in result["timing_reasons"]
    assert result["timing_and_period_verified"] is False


@pytest.mark.parametrize("tampered", ["payload", "source"])
def test_payload_and_source_tampering_is_detected(evidence, tampered):
    observation, release, source = evidence
    if tampered == "payload":
        observation["payload"]["changed"] = True
    else:
        source += b" changed"
    result = audit_link(observation, release, source)
    expected = "CAPTURE_HASH_MISMATCH" if tampered == "payload" else "SOURCE_HASH_MISMATCH"
    assert result["timing_reasons"] == [expected]
    assert result["timing_and_period_verified"] is False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("status", "no_usable_estimate", "NO_USABLE_ESTIMATE"),
        ("status", "request_failed", "NO_USABLE_ESTIMATE"),
        ("request_started_at_utc", "2026-10-21T19:02:00Z", "INVALID_CAPTURE_INTERVAL"),
        ("response_observed_at_utc", "2026-10-21T19:01:00", "MISSING_OR_INVALID_EVIDENCE"),
    ],
)
def test_invalid_observation_is_held(evidence, field, value, reason):
    observation, release, source = evidence
    observation[field] = value
    result = audit_link(observation, release, source)
    assert result["timing_reasons"] == [reason]
    assert result["timing_and_period_verified"] is False
    assert result["research_eligible"] is False


@pytest.mark.parametrize("defect", ["provider_error", "missing", "boolean", "string", "duplicate", "past_period"])
def test_matching_payload_needs_a_unique_usable_estimate(evidence, defect):
    observation, release, source = evidence
    summary = observation["payload"]["quoteSummary"]
    rows = summary["result"][0]["earningsTrend"]["trend"]
    if defect == "provider_error":
        summary["error"] = {"code": "Unauthorized"}
        expected = "PROVIDER_ERROR"
    elif defect in {"duplicate", "past_period"}:
        if defect == "duplicate":
            rows.append(dict(rows[0]))
        else:
            rows[0]["period"] = "-1q"
        expected = "PERIOD_NOT_UNIQUELY_MATCHED"
    else:
        rows[0]["earningsEstimate"]["avg"] = {"raw": {"missing": None, "boolean": True, "string": "1.0"}[defect]}
        expected = "MATCHED_ESTIMATE_MISSING"
    # 해시도 갱신해 각 의미 검증이 독립적으로 실패하는지 확인한다.
    observation["payload_sha256"] = hashlib.sha256(
        json.dumps(observation["payload"], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    result = audit_link(observation, release, source)
    assert result["timing_reasons"] == [expected]
    assert result["timing_and_period_verified"] is False
    assert result["research_eligible"] is False


@pytest.fixture
def cli_files(evidence, tmp_path, monkeypatch):
    observation, release, source = evidence
    capture_path = tmp_path / "capture.json"
    release_path = tmp_path / "release.json"
    source_path = tmp_path / "source.txt"
    capture_path.write_text(json.dumps({"observations": [observation]}))
    release_path.write_text(json.dumps(release))
    source_path.write_bytes(source)
    monkeypatch.setattr(
        sys,
        "argv",
        ["linkage", "--capture", str(capture_path), "--release", str(release_path), "--source", str(source_path)],
    )
    return capture_path, release_path, source_path


def test_module_cli_reports_evidence_without_granting_eligibility(cli_files, capsys):
    before = [path.read_bytes() for path in cli_files]
    runpy.run_path(earnings_linkage.__file__, run_name="__main__")
    result = json.loads(capsys.readouterr().out)
    assert result["timing_and_period_verified"] is True
    assert result["research_eligible"] is False
    assert [path.read_bytes() for path in cli_files] == before


@pytest.mark.parametrize("case", ["missing", "duplicate"])
def test_cli_refuses_nonunique_issuer_observations(cli_files, case, capsys):
    path = cli_files[0]
    capture = json.loads(path.read_text())
    rows = capture["observations"]
    if case == "missing":
        rows[0]["ticker"] = "TESTBB"
    else:
        rows.append(dict(rows[0]))
    path.write_text(json.dumps(capture))
    with pytest.raises(SystemExit) as exc:
        earnings_linkage.main()
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "Expected exactly one capture observation for issuer" in output.err
