"""offbox heartbeat 분기 잠금 — deploy key 배선 · CLI · `-m` 진입점.

git 은 `subprocess.run` 경계에서 대역을 쓰고 argv·env 를 단언한다 (실 push 동작은
`test_offbox_heartbeat.py` 의 로컬 bare remote 테스트 몫이다).
"""

from __future__ import annotations

import io
import runpy
import subprocess
import sys

import pytest

from nuri.alerts import offbox_heartbeat as ob

SHA = "abc123def456"


def _record_git(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, SHA + "\n" if "commit-tree" in argv else "", "")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


class TestDeployKey:
    def test_an_existing_deploy_key_pins_the_ssh_command_of_both_git_calls(self, monkeypatch, tmp_path):
        key = tmp_path / "nuri_heartbeat_deploy"
        key.write_text("placeholder")
        monkeypatch.setattr(ob, "DEPLOY_KEY", key)
        monkeypatch.setenv("NURI_ROLE", "production")
        calls = _record_git(monkeypatch)

        assert ob.send_heartbeat(remote_url="git@example.invalid:o/r.git") == SHA

        expected = f"ssh -4 -i {key} -o IdentitiesOnly=yes -o ConnectTimeout=10"
        assert [kwargs["env"]["GIT_SSH_COMMAND"] for _, kwargs in calls] == [expected, expected]
        assert calls[1][0] == [
            "git",
            "push",
            "--no-verify",
            "--force",
            "git@example.invalid:o/r.git",
            f"{SHA}:{ob.HEARTBEAT_REF}",
        ]

    def test_without_the_key_git_keeps_its_own_ssh_setup(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ob, "DEPLOY_KEY", tmp_path / "absent")
        monkeypatch.setenv("NURI_ROLE", "production")
        monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
        calls = _record_git(monkeypatch)

        assert ob.send_heartbeat() == SHA
        assert all("GIT_SSH_COMMAND" not in kwargs["env"] for _, kwargs in calls)
        assert calls[1][0][4] == ob.REMOTE_URL


class TestCli:
    def test_send_prints_the_sha_and_exits_0(self, monkeypatch, capsys):
        monkeypatch.setattr(ob, "send_heartbeat", lambda: SHA)

        assert ob.main(["send"]) == 0
        assert capsys.readouterr().out.strip() == f"pushed {SHA}"

    def test_a_skip_or_failure_exits_1_with_a_hint(self, monkeypatch, capsys):
        monkeypatch.setattr(ob, "send_heartbeat", lambda: None)

        assert ob.main(["send"]) == 1
        assert "NURI_ROLE" in capsys.readouterr().out

    def test_the_module_entry_point_on_a_dev_machine_exits_1_without_running_git(self, monkeypatch):
        """runpy 는 모듈을 다시 실행하므로 모듈 속성 patch 는 무효다 — 경계(subprocess)를 막고
        role 을 dev 로 둔다. 실 경로가 git 을 띄우면 대역이 테스트를 실패시킨다."""
        monkeypatch.delenv("NURI_ROLE", raising=False)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("dev 에서 git 을 띄웠다"))
        stdout = io.StringIO()
        monkeypatch.setattr(sys, "argv", ["offbox_heartbeat", "send"])
        monkeypatch.setattr(sys, "stdout", stdout)

        with pytest.raises(SystemExit) as exc:
            runpy.run_module("nuri.alerts.offbox_heartbeat", run_name="__main__")

        assert exc.value.code == 1
        assert "skip 또는 실패" in stdout.getvalue()
