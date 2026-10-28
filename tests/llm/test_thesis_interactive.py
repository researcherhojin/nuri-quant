"""#1965: 단계 이벤트에는 허용 필드만 있으며 인터랙티브 실행은 원장을 쓰지 않는다."""

import json
from typing import Any

import pytest

from nuri.llm import local_client as lc
from nuri.llm import thesis_arm as arm
from nuri.llm import thesis_interactive as cli
from nuri.llm.thesis_events import PREFIX, STAGES, public_event
from tests.llm.test_thesis_arm import CFG, FakeGenerate, packets  # noqa: F401


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"event": "unknown"},
        {"event": "stage", "stage": "SECRET", "status": "ok"},
        {"event": "stage", "stage": "manager", "status": "SECRET"},
        {"event": "error", "code": "SECRET"},
        {"event": "result", "rating": "Buy", "outcome": "failed", "run_hash": "a" * 64},
        {"event": "result", "rating": "Hold", "outcome": "verdict", "run_hash": "SECRET"},
    ],
)
def test_unknown_values_are_never_public(value):
    assert public_event(value) is None


@pytest.mark.parametrize(
    "value",
    [
        {"event": "stage", "stage": "manager", "status": "ok"},
        {"event": "error", "code": "run_failed"},
        {"event": "result", "rating": "Hold", "outcome": "verdict", "run_hash": "a" * 64},
    ],
)
def test_extra_fields_are_removed(value):
    assert public_event(value | {"holdings": "PRIVATE", "error": "PRIVATE", "rendered": "PRIVATE"}) == value


def test_progress_preserves_the_result_and_stage_order(monkeypatch, packets):
    monkeypatch.setattr(lc, "generate", FakeGenerate())
    plain = arm.run_arm_b("T0", packets, cfg=dict(CFG))
    events = []
    live = arm.run_arm_b("T0", packets, cfg=dict(CFG), progress=events.append)
    assert live["run_hash"] == plain["run_hash"]
    assert [(e["stage"], e["status"]) for e in events] == [(s, state) for s in STAGES for state in ("started", "ok")]
    assert all(public_event(e) == e for e in events)


def test_absent_stages_are_reported_without_a_model_call(monkeypatch, packets):
    packets["ticker"]["items"] = []
    packets["market"]["items"] = []
    monkeypatch.setattr(lc, "generate", lambda *a, **kw: pytest.fail("no evidence"))
    events = []
    run = arm.run_arm_b("T0", packets, cfg=dict(CFG), progress=events.append)
    assert run["rating"] == "REVIEW"
    assert [e["status"] for e in events] == [state for _ in STAGES for state in ("started", "absent")]


def test_cli_only_emits_allowlisted_events(monkeypatch, packets, tmp_path, capsys):
    cfg: dict[str, Any] = dict(CFG, archive_dir=str(tmp_path), expected={"version": "0.40.11", "digest": "test"})
    monkeypatch.setattr(lc, "load_config", lambda: cfg)
    fake = FakeGenerate()

    def generate(prompt, **kwargs):
        assert kwargs["cfg"]["expected"]["version"] == "0.40.12"
        return fake(prompt, **kwargs)

    monkeypatch.setattr(lc, "generate", generate)
    monkeypatch.setattr(cli.tc, "build_packets", lambda ticker, db_path=None: packets)
    monkeypatch.setattr(arm.ledger, "record_run", lambda *a, **kw: pytest.fail("interactive ledger write"))
    assert cli.main(["--ticker", "TEST"]) == 0
    events = [json.loads(line[len(PREFIX) :]) for line in capsys.readouterr().out.splitlines()]
    assert len(events) == 15 and events[-1]["event"] == "result"
    assert all(public_event(e) == e for e in events)
    assert len(list((tmp_path / "runs").glob("*.json"))) == 1
    assert cfg["expected"]["version"] == "0.40.11"


def test_error_text_is_archived_and_never_emitted(monkeypatch, packets, tmp_path, capsys):
    monkeypatch.setattr(
        lc,
        "load_config",
        lambda: dict(CFG, archive_dir=str(tmp_path), expected={"version": "0.40.11", "digest": "test"}),
    )
    monkeypatch.setattr(cli.tc, "build_packets", lambda ticker, db_path=None: packets)

    def fail(*a, **kw):
        raise RuntimeError("PRIVATE ERROR")

    monkeypatch.setattr(arm, "run_arm_b", fail)
    assert cli.main(["--ticker", "TEST"]) == 1
    out = capsys.readouterr().out
    assert "PRIVATE" not in out and '"code": "run_failed"' in out
    assert "PRIVATE ERROR" in next((tmp_path / "interactive").glob("*.log")).read_text()


@pytest.mark.parametrize("outcome,expected,rc", [("review_model", "review", 0), ("transport:Timeout", "failed", 1)])
def test_review_and_failure_remain_distinct(monkeypatch, packets, tmp_path, capsys, outcome, expected, rc):
    monkeypatch.setattr(
        lc,
        "load_config",
        lambda: dict(CFG, archive_dir=str(tmp_path), expected={"version": "0.40.11", "digest": "test"}),
    )
    monkeypatch.setattr(cli.tc, "build_packets", lambda ticker, db_path=None: packets)
    monkeypatch.setattr(
        arm,
        "run_arm_b",
        lambda *a, **kw: {"ticker": "TEST", "run_hash": "a" * 64, "rating": "REVIEW", "outcome": outcome},
    )
    assert cli.main(["--ticker", "TEST"]) == rc
    event = json.loads(capsys.readouterr().out.strip()[len(PREFIX) :])
    assert event["outcome"] == expected


def test_cli_rejects_invalid_ticker():
    with pytest.raises(SystemExit) as error:
        cli.main(["--ticker", "A;B"])
    assert error.value.code == 2


@pytest.mark.parametrize(
    ("event", "field", "value"),
    [
        ("stage", "stage", []),
        ("stage", "status", None),
        ("error", "code", []),
        ("result", "rating", None),
        ("result", "rating", "unknown"),
        ("result", "outcome", []),
        ("result", "outcome", "unknown"),
        ("result", "run_hash", None),
        ("result", "rating", "REVIEW"),
    ],
)
def test_event_fields_have_strict_types_and_values(event, field, value):
    data = {
        "event": event,
        "stage": "manager",
        "status": "ok",
        "code": "timeout",
        "rating": "Hold",
        "outcome": "verdict",
        "run_hash": "a" * 64,
    }
    data[field] = value
    assert public_event(data) is None


def test_a_review_result_is_public_without_free_text():
    value = {"event": "result", "rating": "REVIEW", "outcome": "review", "run_hash": "a" * 64}
    assert public_event(value) == value


def test_emit_drops_unknown_events(capsys):
    cli.emit({"event": "unknown", "secret": "PRIVATE"})
    assert capsys.readouterr().out == ""


def test_main_guard_rejects_invalid_input_without_external_calls(monkeypatch):
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["interactive", "--ticker", "invalid!"])
    with pytest.raises(SystemExit) as error:
        runpy.run_module("nuri.llm.thesis_interactive", run_name="__main__")
    assert error.value.code == 2


def test_failed_stage_progress_has_only_a_generic_status(monkeypatch, packets):
    import requests

    fake = FakeGenerate({"analyst:market": [requests.Timeout("PRIVATE")]})
    monkeypatch.setattr(lc, "generate", fake)
    events = []
    run = arm.run_arm_b("T0", packets, cfg=dict(CFG), progress=events.append)
    assert run["outcome"].startswith("transport:")
    assert events[-1] == {"event": "stage", "stage": "analyst:market", "status": "failed"}
    assert "PRIVATE" not in json.dumps(events)


def test_interactive_pin_preserves_scored_runtime_and_digest(monkeypatch, tmp_path):
    from copy import deepcopy

    from nuri.llm import thesis_freeze

    scored = lc.load_config()
    original = deepcopy(scored)
    hashes = thesis_freeze.current_hashes(scored)
    interactive = cli.interactive_config(scored)
    assert interactive["expected"]["version"] == "0.40.12"
    assert interactive["expected"]["digest"] == scored["expected"]["digest"]
    assert interactive["base_url"] == scored["base_url"]
    assert scored == original
    assert thesis_freeze.current_hashes(scored) == hashes
    assert thesis_freeze.check() == []
    rt = lc.Runtime("0.40.12", scored["expected"]["digest"], "os", "build", {}, "host")
    lc.check_runtime(rt, interactive)
    with pytest.raises(lc.LocalModelError, match="runtime_mismatch"):
        lc.check_runtime(rt, scored)
    from dataclasses import replace

    rt = replace(rt, digest="wrong")
    with pytest.raises(lc.LocalModelError, match="runtime_mismatch"):
        lc.check_runtime(rt, interactive)


@pytest.mark.parametrize("text", ["{}", "version: latest", "version: 12", "[]", "version: 0.40.12\nmodel: other"])
def test_interactive_pin_rejects_invalid_or_extra_overrides(tmp_path, text):
    path = tmp_path / "runtime.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="explicit version"):
        cli.interactive_config(lc.load_config(), path)
