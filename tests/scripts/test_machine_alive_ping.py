"""머신 LaunchDaemon 의 외부 dead-man ping (#1848) — 스크립트를 실제로 돌려 본다.

git 과 curl 은 PATH 앞의 가짜로 바꾸고 argv 를 기록한다 (tests/CLAUDE.md "워크플로 스텝은
실행하고, 스텁은 argv 를 단언한다"). 잠그는 것:

- ping 은 `cd` 와 git 보다 먼저, push 와 무관하게 나간다 — push 가 깨지거나 REPO 가 옛 경로를
  가리켜도 머신은 살아 있고, 그 비트가 멎으면 감시자는 "머신 꺼짐" 으로 오분류한다 (#1443 이
  막으려던 바로 그 오인). 체크아웃이 통째로 사라지는 경우는 데몬 자체가 못 뜨므로 여기서
  다루지 않는다 — 스크립트 머리말의 한계 항목.
- URL 은 출력에 나오지 않는다 — `bash -x` 트레이스까지. URL 을 아는 사람은 누구나 침묵을
  가릴 수 있다.
- 파일이 없거나 비어 있으면 curl 을 부르지 않고 미설정이라고 말한다.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ops" / "machine_alive.sh"
# 실제 check 가 아니다 — 출력에 새는지 보려고 일부러 눈에 띄는 값을 쓴다.
URL = "https://hc-ping.example/" + "machine-test-uuid"

FAKE_GIT = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG/git.argv"
if [ "$1" = "commit-tree" ]; then
    [ "${FAKE_GIT_RC:-0}" = 0 ] || exit "$FAKE_GIT_RC"
    echo deadbeefcafe0000
fi
exit 0
"""

FAKE_CURL = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG/curl.argv"
exit "${FAKE_CURL_RC:-0}"
"""


@pytest.fixture()
def sandbox(tmp_path):
    home, repo, log, fakebin = (tmp_path / d for d in ("home", "repo", "log", "bin"))
    for d in (home, repo, log, fakebin):
        d.mkdir()
    for name, body in (("git", FAKE_GIT), ("curl", FAKE_CURL)):
        exe = fakebin / name
        exe.write_text(body)
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    env = {"PATH": f"{fakebin}:/usr/bin:/bin", "HOME": str(home), "NURI_REPO": str(repo), "FAKE_LOG": str(log)}
    return env, home, log


def _write_url_file(home: Path, content: str) -> None:
    path = home / ".config" / "nuri-quant" / "deadman-machine.url"
    path.parent.mkdir(parents=True)
    path.write_text(content)


def _run(env: dict[str, str], *bash_args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", *bash_args, str(SCRIPT)], env={**env, **extra}, capture_output=True, text=True, timeout=30
    )


def _argv(log: Path, name: str) -> list[str]:
    path = log / f"{name}.argv"
    return path.read_text().splitlines() if path.exists() else []


def test_the_url_is_pinged_with_bounded_timeouts_and_never_printed(sandbox):
    env, home, log = sandbox
    _write_url_file(home, URL + "\n")

    r = _run(env)

    assert r.returncode == 0, r.stderr
    [curl] = _argv(log, "curl")
    assert curl.endswith(URL) and "-sf" in curl and "--connect-timeout 5" in curl and "-m 10" in curl, curl
    assert URL not in r.stdout + r.stderr
    assert "dead-man ping ok" in r.stdout
    assert any(a.startswith("push ") for a in _argv(log, "git")), "ping 이 push 를 대신하면 안 된다"


def test_a_failed_ping_still_pushes_and_reports_only_the_exit_code(sandbox):
    env, home, log = sandbox
    _write_url_file(home, URL)

    r = _run(env, FAKE_CURL_RC="6")

    assert r.returncode == 0, r.stderr
    assert "dead-man ping failed (curl exit 6)" in r.stdout
    assert URL not in r.stdout + r.stderr
    assert any(a.startswith("push ") for a in _argv(log, "git"))


def test_the_ping_goes_out_even_when_git_fails(sandbox):
    """git 이 깨져도 머신은 살아 있다 — ping 이 git 뒤에 있으면 그 비트도 같이 멎는다."""
    env, home, log = sandbox
    _write_url_file(home, URL)

    r = _run(env, FAKE_GIT_RC="1")

    assert r.returncode != 0
    assert len(_argv(log, "curl")) == 1


@pytest.mark.parametrize("content", [None, "\n"], ids=["missing", "empty"])
def test_without_a_url_curl_is_never_called(sandbox, content):
    env, home, log = sandbox
    if content is not None:
        _write_url_file(home, content)

    r = _run(env)

    assert r.returncode == 0, r.stderr
    assert _argv(log, "curl") == []
    assert "dead-man ping not configured" in r.stdout
    assert any(a.startswith("push ") for a in _argv(log, "git"))


def test_the_ping_goes_out_even_when_the_repo_path_is_stale(sandbox):
    """체크아웃이 옮겨져 REPO 가 옛 경로를 가리키면 `cd` 가 실패한다 — ping 이 그 뒤에 있으면
    살아 있는 머신의 check 가 같이 멎는다 (MBP 체크아웃도 실제로 옮겨진 적이 있다, 2026-10-06)."""
    env, home, log = sandbox
    _write_url_file(home, URL)

    r = _run(env, NURI_REPO=str(home / "no-such-repo"))

    assert r.returncode != 0
    assert len(_argv(log, "curl")) == 1
    assert _argv(log, "git") == []


def test_bash_tracing_does_not_print_the_url(sandbox):
    """`-s` 는 curl 의 진단만 끈다 — `bash -x` 로 디버깅하면 대입과 curl 줄이 URL 째 찍힌다."""
    env, home, log = sandbox
    _write_url_file(home, URL)

    r = _run(env, "-x")

    assert r.returncode == 0, r.stderr
    assert len(_argv(log, "curl")) == 1
    assert URL not in r.stdout + r.stderr
    assert "commit-tree" in r.stderr, "블록 뒤에서 트레이스를 되돌리지 않았다"
