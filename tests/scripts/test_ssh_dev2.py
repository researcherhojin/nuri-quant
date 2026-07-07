"""Tests for scripts/deploy/ssh_dev2.sh — ssh -4 + dscacheutil IPv4 fallback helper (#827).

Network-free: PATH 앞에 stub ssh/dscacheutil 을 주입해 분기 검증.
(a) 외근망 IPv6 no-route → -4 강제, (b) .local 해석 실패 → dscacheutil IP fallback.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

HELPER = Path(__file__).parent.parent.parent / "scripts" / "deploy" / "ssh_dev2.sh"

HOST = "devtwo.local"
DEST = f"deploy@{HOST}"
FAKE_IP = "192.168.0.99"

# dscacheutil -q host 실제 출력 형식 재현
DSCACHEUTIL_OK = f"name: {HOST}\\nip_address: {FAKE_IP}"


def _make_stub(bin_dir: Path, name: str, body: str) -> None:
    """호출 인자를 로그에 남기는 실행 가능 stub 생성."""
    path = bin_dir / name
    path.write_text(f"#!/usr/bin/env bash\n{body}\n")
    path.chmod(0o755)


def _run(bin_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(HELPER), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _setup(tmp_path: Path, ssh_body: str, dscacheutil_body: str = "exit 0") -> tuple[Path, Path]:
    log = tmp_path / "calls.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_stub(bin_dir, "ssh", f'echo "ssh $*" >> "{log}"\n{ssh_body}')
    _make_stub(bin_dir, "dscacheutil", f'echo "dscacheutil $*" >> "{log}"\n{dscacheutil_body}')
    return bin_dir, log


def test_first_attempt_success_forces_ipv4_no_fallback(tmp_path):
    """정상 연결: ssh -4 1회 호출, fallback 없음."""
    bin_dir, log = _setup(tmp_path, "exit 0")
    r = _run(bin_dir, DEST, "echo ok")
    assert r.returncode == 0
    assert log.read_text().splitlines() == [f"ssh -4 {DEST} echo ok"]


def test_exit_255_falls_back_to_dscacheutil_ip(tmp_path):
    """연결 실패 (255): dscacheutil IPv4 로 destination 치환 + HostKeyAlias 재시도."""
    ssh_body = f'case "$*" in *{FAKE_IP}*) exit 0;; *) exit 255;; esac'
    bin_dir, log = _setup(tmp_path, ssh_body, f'printf "{DSCACHEUTIL_OK}\\n"')
    r = _run(bin_dir, DEST, "echo ok")
    assert r.returncode == 0
    calls = log.read_text().splitlines()
    assert calls == [
        f"ssh -4 {DEST} echo ok",
        f"dscacheutil -q host -a name {HOST}",
        f"ssh -4 -o HostKeyAlias={HOST} deploy@{FAKE_IP} echo ok",
    ]
    assert f"{HOST} → {FAKE_IP}" in r.stderr


def test_fallback_preserves_leading_options(tmp_path):
    """옵션 (-o k=v) 뒤의 destination 만 IP 로 치환 — 옵션/원격명령은 그대로."""
    ssh_body = f'case "$*" in *{FAKE_IP}*) exit 0;; *) exit 255;; esac'
    bin_dir, log = _setup(tmp_path, ssh_body, f'printf "{DSCACHEUTIL_OK}\\n"')
    r = _run(bin_dir, "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", DEST, "echo ok")
    assert r.returncode == 0
    assert log.read_text().splitlines()[-1] == (
        f"ssh -4 -o HostKeyAlias={HOST} -o BatchMode=yes -o ConnectTimeout=5 deploy@{FAKE_IP} echo ok"
    )


def test_scp_style_double_dash_destination(tmp_path):
    """scp -S 호출 형태 (-l user ... -- host cmd): '--' 다음 인자가 destination."""
    ssh_body = f'case "$*" in *{FAKE_IP}*) exit 0;; *) exit 255;; esac'
    bin_dir, log = _setup(tmp_path, ssh_body, f'printf "{DSCACHEUTIL_OK}\\n"')
    r = _run(bin_dir, "-x", "-oForwardAgent=no", "-l", "deploy", "--", HOST, "scp", "-t", "/tmp/x")
    assert r.returncode == 0
    assert log.read_text().splitlines()[-1] == (
        f"ssh -4 -o HostKeyAlias={HOST} -x -oForwardAgent=no -l deploy -- {FAKE_IP} scp -t /tmp/x"
    )


def test_remote_command_failure_no_retry(tmp_path):
    """원격 명령 실패 (exit 1): 연결층 실패가 아니므로 재시도 없이 그대로 전파."""
    bin_dir, log = _setup(tmp_path, "exit 1")
    r = _run(bin_dir, DEST, "false")
    assert r.returncode == 1
    assert len(log.read_text().splitlines()) == 1  # ssh 1회만 — dscacheutil 미호출


def test_dscacheutil_no_ip_exits_255(tmp_path):
    """dscacheutil 도 해석 실패: fallback 불가 메시지 + 원래 exit 255 유지."""
    bin_dir, log = _setup(tmp_path, "exit 255", "exit 0")
    r = _run(bin_dir, DEST, "echo ok")
    assert r.returncode == 255
    assert "fallback 불가" in r.stderr
    calls = log.read_text().splitlines()
    assert calls[0] == f"ssh -4 {DEST} echo ok"
    assert calls[1].startswith("dscacheutil ")
    assert len(calls) == 2  # ssh 재시도 없음


def test_ipv4_literal_destination_skips_fallback(tmp_path):
    """destination 이 이미 IPv4 literal: dscacheutil fallback 무의미 — 즉시 255."""
    bin_dir, log = _setup(tmp_path, "exit 255")
    r = _run(bin_dir, f"deploy@{FAKE_IP}", "echo ok")
    assert r.returncode == 255
    assert len(log.read_text().splitlines()) == 1  # dscacheutil 미호출


def test_no_destination_usage_error(tmp_path):
    """destination 없이 옵션만: usage 에러 (exit 2)."""
    bin_dir, _ = _setup(tmp_path, "exit 0")
    r = _run(bin_dir, "-o", "BatchMode=yes")
    assert r.returncode == 2
    assert "usage:" in r.stderr
