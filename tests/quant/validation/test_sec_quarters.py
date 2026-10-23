"""SEC capture and as-of quarterly evidence regression tests."""

import hashlib
import json
from datetime import datetime, timezone

import httpx
import pytest

from nuri.collectors import sec_research
from nuri.core import db
from nuri.quant.validation import sec_quarters

ACCESSION = "0000000001-26-000001"
AS_OF = "2026-10-23T00:00:00+00:00"


@pytest.fixture
def captured(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("research accessed a database")

    monkeypatch.setattr(db, "get_connection", forbidden)
    monkeypatch.setattr(sec_research, "kst_now", lambda: datetime(2026, 10, 22, tzinfo=timezone.utc))
    facts = {
        "cik": 1,
        "taxonomy": "us-gaap",
        "tag": "EarningsPerShareDiluted",
        "units": {
            "USD/shares": [
                {"start": "2026-07-01", "end": "2026-09-30", "accn": ACCESSION, "form": "10-Q", "val": 2.0},
                {"start": "2025-07-01", "end": "2025-09-30", "accn": ACCESSION, "form": "10-Q", "val": 1.0},
                {"start": "2026-01-01", "end": "2026-09-30", "accn": ACCESSION, "form": "10-Q", "val": 9.0},
            ]
        },
    }
    submissions = {
        "cik": "0000000001",
        "filings": {
            "recent": {
                "accessionNumber": [ACCESSION],
                "acceptanceDateTime": ["2026-10-21T20:00:00Z"],
                "reportDate": ["2026-09-30"],
                "form": ["10-Q"],
            }
        },
    }
    client_class = httpx.Client
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=facts if "companyconcept" in str(request.url) else submissions)

    monkeypatch.setattr(
        sec_research.httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(transport), **kw)
    )
    path, complete = sec_research.capture("1", "Test research contact", tmp_path)
    assert complete
    assert len(requests) == 2
    assert all(r.headers["User-Agent"] == "Test research contact" for r in requests)
    return path


def change(path, source, mutate):
    manifest = json.loads(path.read_text())
    entry = next(s for s in manifest["sources"] if s["name"] == source)
    target = path.parent / entry["file"]
    data = json.loads(target.read_text())
    mutate(data)
    body = json.dumps(data).encode()
    target.write_bytes(body)
    entry["sha256"] = hashlib.sha256(body).hexdigest()
    path.write_text(json.dumps(manifest))


def run(path, **kwargs):
    return sec_quarters.audit(path, ACCESSION, "2026-07-01", "2026-09-30", kwargs.get("as_of", AS_OF))


def test_exact_quarters_exclude_ytd_and_never_approve_signal(captured):
    result = run(captured)
    assert result["evidence_linked"]
    assert [p["eps"] for p in result["periods"]] == [2.0, 1.0]
    assert result["available_at"] == "2026-10-22T00:00:00+00:00"
    assert result["research_eligible"] is False


def test_repeated_capture_preserves_previous(captured):
    before = {p.name: p.read_bytes() for p in captured.parent.iterdir()}
    second, complete = sec_research.capture("1", "Test contact", captured.parent.parent)
    assert complete and second != captured
    assert before == {p.name: p.read_bytes() for p in captured.parent.iterdir()}
    assert "Test contact" not in second.read_text()


@pytest.mark.parametrize("as_of", ["2026-10-21T23:00:00Z", "2026-10-21T19:00:00Z", "2026-10-23"])
def test_backdated_or_naive_cutoff_is_rejected(captured, as_of):
    result = run(captured, as_of=as_of)
    assert not result["evidence_linked"] and result["periods"] == []


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("acceptanceDateTime", "2026-10-24T00:00:00Z", "FILING_AFTER_AS_OF"),
        ("form", "10-Q/A", "NOT_ORIGINAL_QUARTERLY_REPORT"),
        ("reportDate", "2026-06-30", "NOT_ORIGINAL_QUARTERLY_REPORT"),
        ("accessionNumber", "another", "ACCESSION_NOT_UNIQUE_OR_MISSING"),
    ],
)
def test_filing_identity_and_availability(captured, field, value, reason):
    change(captured, "submissions", lambda d: d["filings"]["recent"][field].__setitem__(0, value))
    result = run(captured)
    assert reason in result["reasons"] and not result["evidence_linked"]


@pytest.mark.parametrize("mode", ["missing_prior", "other_accession", "conflicting", "bool", "nan"])
def test_missing_conflicting_or_invalid_quarter_not_filled(captured, mode):
    def mutate(data):
        rows = data["units"]["USD/shares"]
        if mode == "missing_prior":
            rows.pop(1)
        elif mode == "other_accession":
            rows[1]["accn"] = "later-amendment"
        elif mode == "conflicting":
            rows.append({**rows[0], "val": 4.0})
        else:
            rows[0]["val"] = True if mode == "bool" else float("nan")

    change(captured, "facts", mutate)
    result = run(captured)
    assert not result["evidence_linked"] and result["periods"] == []


def test_duplicate_equal_values_are_not_independent_events(captured):
    change(captured, "facts", lambda d: d["units"]["USD/shares"].append(dict(d["units"]["USD/shares"][0])))
    result = run(captured)
    assert result["evidence_linked"] and len(result["periods"]) == 2
    assert result["periods"][0]["source_rows"] == 2


@pytest.mark.parametrize(
    "source,field,value,reason",
    [
        ("facts", "cik", 2, "CIK_MISMATCH"),
        ("submissions", "cik", "2", "CIK_MISMATCH"),
        ("facts", "tag", "EarningsPerShareBasic", "EPS_TAG_MISMATCH"),
    ],
)
def test_wrong_company_or_basis_is_rejected(captured, source, field, value, reason):
    change(captured, source, lambda d: d.__setitem__(field, value))
    assert reason in run(captured)["reasons"]


def test_corrupted_payload_is_not_used(captured):
    with (captured.parent / "facts.json").open("a") as handle:
        handle.write(" ")
    assert "SOURCE_HASH_MISMATCH" in run(captured)["reasons"]


@pytest.mark.parametrize("start,end", [("2026-01-01", "2026-09-30"), ("2026-07-05", "2026-10-03")])
def test_ytd_and_week_based_quarters_need_separate_support(captured, start, end):
    assert not sec_quarters.audit(captured, ACCESSION, start, end, AS_OF)["evidence_linked"]


@pytest.mark.parametrize("failure", ["http", "network", "json"])
def test_failed_requests_are_archived_and_not_approved(tmp_path, monkeypatch, failure):
    client_class = httpx.Client

    def transport(request):
        if failure == "network":
            raise httpx.ConnectError("private details", request=request)
        return httpx.Response(503 if failure == "http" else 200, content=b"not JSON")

    monkeypatch.setattr(
        sec_research.httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(transport), **kw)
    )
    path, complete = sec_research.capture("1", "Test contact", tmp_path)
    assert not complete
    assert "private details" not in path.read_text()
    assert all(s["status"] == "failed" for s in json.loads(path.read_text())["sources"])
    assert not run(path)["evidence_linked"]


def test_cli_runs_audit_and_returns_failure_for_backdated_capture(captured, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        [
            "audit",
            "--manifest",
            str(captured),
            "--accession",
            ACCESSION,
            "--start",
            "2026-07-01",
            "--end",
            "2026-09-30",
            "--as-of",
            "2020-01-01T00:00:00Z",
        ],
    )
    assert sec_quarters.main() == 2
    assert "CAPTURE_AFTER_AS_OF" in json.loads(capsys.readouterr().out)["reasons"]


@pytest.mark.parametrize("cik", ["0", "-1", "10000000000", "not-a-cik"])
def test_capture_cli_rejects_invalid_cik_before_io(tmp_path, monkeypatch, cik):
    import runpy

    def forbidden(**kwargs):
        pytest.fail("invalid CLI input opened an HTTP client")

    monkeypatch.setattr(sec_research.httpx, "Client", forbidden)
    monkeypatch.setattr("sys.argv", ["capture", "--cik", cik, "--identity", "Test contact", "--output", str(tmp_path)])
    with pytest.raises(ValueError, match="positive SEC CIK"):
        runpy.run_path(sec_research.__file__, run_name="__main__")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("identity", ["", "   ", "Test\ncontact", "Test\rcontact"])
def test_capture_cli_rejects_invalid_identity_before_io(tmp_path, monkeypatch, identity):
    import runpy

    def forbidden(**kwargs):
        pytest.fail("invalid CLI identity opened an HTTP client")

    monkeypatch.setattr(sec_research.httpx, "Client", forbidden)
    monkeypatch.setattr("sys.argv", ["capture", "--cik", "1", "--identity", identity, "--output", str(tmp_path)])
    with pytest.raises(ValueError, match="single-line SEC user agent"):
        runpy.run_path(sec_research.__file__, run_name="__main__")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("object_payload", [True, False])
def test_capture_cli_archives_object_validation_and_exit_status(tmp_path, monkeypatch, capsys, object_payload):
    import runpy
    from pathlib import Path

    requests = []
    client_class = httpx.Client

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={} if object_payload else [])

    monkeypatch.setattr(
        sec_research.httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(transport), **kw)
    )
    monkeypatch.setattr("sys.argv", ["capture", "--cik", "1", "--identity", "Test contact", "--output", str(tmp_path)])
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(sec_research.__file__, run_name="__main__")
    assert exited.value.code == (0 if object_payload else 2)
    summary = json.loads(capsys.readouterr().out)
    assert summary["capture_complete"] is object_payload
    assert summary["research_eligible"] is False
    assert len(requests) == 2
    manifest = json.loads(Path(summary["manifest"]).read_text())
    assert all(source["error_type"] == (None if object_payload else "ValueError") for source in manifest["sources"])


@pytest.mark.parametrize("corruption", ["schema", "experiment", "cik", "sources", "path", "url", "interval"])
def test_manifest_contract_failures_clear_evidence(captured, corruption):
    manifest = json.loads(captured.read_text())
    if corruption == "schema":
        manifest["schema_version"] = 2
    elif corruption == "experiment":
        manifest["experiment_id"] = "another-experiment"
    elif corruption == "cik":
        manifest["cik"] = "0"
    elif corruption == "sources":
        manifest["sources"].pop()
    elif corruption == "path":
        manifest["sources"][0]["file"] = "../facts.json"
    elif corruption == "url":
        manifest["sources"][0]["url"] = "https://example.invalid/facts.json"
    else:
        manifest["sources"][0]["request_started_at_utc"] = "2026-10-23T00:00:00Z"
    captured.write_text(json.dumps(manifest))
    result = run(captured)
    reason = "INVALID_CAPTURE_INTERVAL" if corruption == "interval" else "MISSING_OR_INVALID_EVIDENCE"
    assert reason in result["reasons"]
    assert result["periods"] == []
    assert not result["evidence_linked"] and not result["research_eligible"]


def test_unaligned_submission_arrays_do_not_join_by_wrong_index(captured):
    change(captured, "submissions", lambda d: d["filings"]["recent"]["reportDate"].clear())
    result = run(captured)
    assert result["reasons"] == ["MISSING_OR_INVALID_EVIDENCE"]
    assert not result["evidence_linked"] and result["periods"] == []


def test_audit_module_cli_links_evidence_but_never_grants_eligibility(captured, monkeypatch, capsys):
    import runpy

    monkeypatch.setattr(
        "sys.argv",
        [
            "audit",
            "--manifest",
            str(captured),
            "--accession",
            ACCESSION,
            "--start",
            "2026-07-01",
            "--end",
            "2026-09-30",
            "--as-of",
            AS_OF,
        ],
    )
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(sec_quarters.__file__, run_name="__main__")
    assert exited.value.code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["evidence_linked"] and not result["research_eligible"]
    assert [period["eps"] for period in result["periods"]] == [2.0, 1.0]
