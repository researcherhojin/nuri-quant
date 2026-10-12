"""offbox heartbeat 분기 잠금 — deploy key 배선 · CLI · `-m` 진입점 · dead-man ping (#1848).

git 은 `subprocess.run` 경계에서 대역을 쓰고 argv·env 를 단언한다 (실 push 동작은
`test_offbox_heartbeat.py` 의 로컬 bare remote 테스트 몫이다).
"""

from __future__ import annotations

import io
import logging
import runpy
import subprocess
import sys

import pytest
import requests

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


# 실제 check 가 아니다 — 비밀이 테스트 로그에 새는지 보려고 일부러 눈에 띄는 값을 쓴다.
URL = "https://hc-ping.example/" + "scheduler-test-uuid"


def _forbid_http(monkeypatch):
    """요청이 나가면 테스트를 실패시킨다 — conftest 는 yfinance 만 막는다."""
    monkeypatch.setattr(ob.requests, "get", lambda *a, **k: pytest.fail("ping 이 나갔다"))


def _record_http(monkeypatch, status=200):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        resp = requests.Response()
        resp.status_code = status
        resp.url = url
        return resp

    monkeypatch.setattr(ob.requests, "get", get)
    return calls


class TestDeadmanPing:
    """외부 dead-man ping (#1848) — role 게이트 · mini 전용 파일 · URL 비노출."""

    def test_a_dev_machine_never_pings_even_with_the_file(self, monkeypatch, tmp_path):
        """MBP 의 ping 이 죽은 mini 를 가리면 dead-man 이 무의미해진다."""
        monkeypatch.delenv("NURI_ROLE", raising=False)
        url_file = tmp_path / "deadman-scheduler.url"
        url_file.write_text(URL + "\n")
        _forbid_http(monkeypatch)

        assert ob.ping_deadman(url_file) is False

    @pytest.mark.parametrize("content", [None, "", "  \n"], ids=["missing", "empty", "blank"])
    def test_without_a_url_nothing_is_sent_and_the_gap_is_logged(self, monkeypatch, tmp_path, caplog, content):
        monkeypatch.setenv("NURI_ROLE", "production")
        url_file = tmp_path / "deadman-scheduler.url"
        if content is not None:
            url_file.write_text(content)
        _forbid_http(monkeypatch)

        with caplog.at_level(logging.INFO, logger=ob.__name__):
            assert ob.ping_deadman(url_file) is False
        assert "미설정" in caplog.text

    def test_production_pings_the_url_in_the_file_with_bounded_timeouts(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setenv("NURI_ROLE", "production")
        url_file = tmp_path / "deadman-scheduler.url"
        url_file.write_text(f"  {URL}\n")
        calls = _record_http(monkeypatch)

        with caplog.at_level(logging.DEBUG, logger=ob.__name__):
            assert ob.ping_deadman(url_file) is True
        assert calls == [(URL, {"timeout": (5, 10)})]
        assert URL not in caplog.text

    def test_an_http_error_is_logged_by_type_and_status_without_the_url(self, monkeypatch, tmp_path, caplog):
        """raise_for_status 의 문구는 "... for url: <URL>" 이다 — 그대로 남기면 비밀이 샌다."""
        monkeypatch.setenv("NURI_ROLE", "production")
        url_file = tmp_path / "deadman-scheduler.url"
        url_file.write_text(URL)
        _record_http(monkeypatch, status=404)

        with caplog.at_level(logging.DEBUG, logger=ob.__name__):
            assert ob.ping_deadman(url_file) is False
        assert "HTTPError 404" in caplog.text
        assert URL not in caplog.text

    def test_a_connection_error_is_logged_without_the_url(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setenv("NURI_ROLE", "production")
        url_file = tmp_path / "deadman-scheduler.url"
        url_file.write_text(URL)

        def get(url, **kwargs):
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}")

        monkeypatch.setattr(ob.requests, "get", get)

        with caplog.at_level(logging.DEBUG, logger=ob.__name__):
            assert ob.ping_deadman(url_file) is False
        assert "ConnectionError" in caplog.text
        assert URL not in caplog.text

    def test_the_default_file_lives_in_the_user_config_dir(self):
        assert ob.PING_URL_FILE.parts[-3:] == (".config", "nuri-quant", "deadman-scheduler.url")


class TestPingCli:
    def test_ping_prints_ok_and_exits_0(self, monkeypatch, capsys):
        monkeypatch.setattr(ob, "ping_deadman", lambda: True)

        assert ob.main(["ping"]) == 0
        assert capsys.readouterr().out.strip() == "dead-man ping ok"

    def test_a_skipped_or_failed_ping_exits_1_with_a_hint(self, monkeypatch, capsys):
        monkeypatch.setattr(ob, "ping_deadman", lambda: False)

        assert ob.main(["ping"]) == 1
        assert "NURI_ROLE" in capsys.readouterr().out
