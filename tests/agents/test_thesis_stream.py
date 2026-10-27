"""#1965: 실제 자식 프로세스의 스트림·실패·취소를 검증하며 비공개 필드는 내보내지 않는다."""

import asyncio
import json
import sys

import pytest

from nuri.agents.discord import thesis_stream as stream
from nuri.llm.thesis_events import PREFIX

FINAL = {"event": "result", "rating": "Hold", "outcome": "verdict", "run_hash": "a" * 64}


def producer(monkeypatch, tmp_path, script, timeout: float = 5):
    original = asyncio.create_subprocess_exec
    calls = []

    async def spawn(*args, **kw):
        calls.append(args)
        return await original(sys.executable, "-u", "-c", script, **kw)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(
        stream, "load_config", lambda: {"archive_dir": str(tmp_path), "interactive": {"timeout_s": timeout}}
    )
    return calls


def payload(value):
    return "print(" + repr(PREFIX + json.dumps(value)) + ", flush=True)\n"


def test_real_child_stream_only_forwards_public_events(monkeypatch, tmp_path):
    stage = {"event": "stage", "stage": "manager", "status": "ok"}
    script = (
        'print("PRIVATE RAW LOG", flush=True)\n'
        + payload(stage | {"secret": "PRIVATE"})
        + payload(FINAL | {"holdings": "PRIVATE"})
    )
    calls = producer(monkeypatch, tmp_path, script)
    events = []

    async def collect(value):
        events.append(value)

    rc, result = asyncio.run(stream.run("thesis-remote", "TEST", collect))
    assert rc == 0 and result == FINAL and events == [stage]
    assert calls == [("make", "thesis-remote", "ticker=TEST")]
    assert "PRIVATE RAW LOG" in next((tmp_path / "interactive").glob("*.log")).read_text()


@pytest.mark.parametrize(
    ("script", "expected"),
    [("print('PRIVATE'); raise SystemExit(2)", "run_failed"), ("print('PRIVATE')", "stream_failed")],
)
def test_child_failure_never_returns_raw_text(monkeypatch, tmp_path, script, expected):
    producer(monkeypatch, tmp_path, script)

    async def collect(value):
        pytest.fail("unexpected stage")

    rc, result = asyncio.run(stream.run("thesis-remote", "TEST", collect))
    assert rc != 0 and result == {"event": "error", "code": expected}


def test_timeout_terminates_the_child_group(monkeypatch, tmp_path):
    producer(monkeypatch, tmp_path, "import time; time.sleep(60)", timeout=0.05)

    async def collect(value):
        pytest.fail("unexpected stage")

    rc, result = asyncio.run(stream.run("thesis-remote", "TEST", collect))
    assert rc == 124 and result["code"] == "timeout"


def test_invalid_stream_events_are_ignored(monkeypatch, tmp_path):
    producer(
        monkeypatch,
        tmp_path,
        'print("'
        + PREFIX
        + 'bad json", flush=True)\n'
        + payload({"event": "stage", "stage": "PRIVATE", "status": "ok"})
        + payload(FINAL),
    )

    async def collect(value):
        pytest.fail("invalid event was forwarded")

    assert asyncio.run(stream.run("thesis-remote", "TEST", collect)) == (0, FINAL)


@pytest.mark.parametrize(("target", "ticker"), [("arbitrary", "TEST"), ("thesis-remote", "A;B")])
def test_invalid_invocations_are_refused(target, ticker):
    async def collect(value):
        pass

    with pytest.raises(ValueError):
        asyncio.run(stream.run(target, ticker, collect))


@pytest.mark.integration
def test_stream_survives_a_real_five_minute_delay(monkeypatch, tmp_path):
    script = (
        payload({"event": "stage", "stage": "manager", "status": "started"})
        + "import time; time.sleep(301)\n"
        + payload(FINAL)
    )
    producer(monkeypatch, tmp_path, script, timeout=330)
    events = []

    async def collect(value):
        events.append(value)

    assert asyncio.run(stream.run("thesis-remote", "TEST", collect)) == (0, FINAL)
    assert len(events) == 1


def test_a_disappeared_child_is_safe_during_timeout_cleanup(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    proc = MagicMock()
    proc.returncode = None
    proc.wait = AsyncMock(return_value=0)

    async def blocked():
        await asyncio.sleep(60)

    proc.stdout.readline = blocked
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    monkeypatch.setattr(
        stream, "load_config", lambda: {"archive_dir": str(tmp_path), "interactive": {"timeout_s": 0.01}}
    )

    def disappeared(*a):
        raise ProcessLookupError

    monkeypatch.setattr(stream.os, "killpg", disappeared)

    async def collect(value):
        pytest.fail("unexpected stage")

    assert asyncio.run(stream.run("thesis-remote", "TEST", collect))[0] == 124
    proc.wait.assert_awaited_once()
