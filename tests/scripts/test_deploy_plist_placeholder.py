"""배포가 plist 의 `/Users/USER/` 플레이스홀더를 실제 홈으로 치환하는지 검증.

Gotcha-Test Pair:
#980(privacy)이 repo 의 launchd plist 에서 실제 홈 경로를 지우고 `/Users/USER/`
플레이스홀더로 바꿨다. 그 자체는 옳다 — public repo 에 홈 경로가 남으면 안 된다.
그런데 `deploy_to_mini.sh` 의 plist 재설치만 평범한 `cp` 였다. 치환 전에는 repo 에
실제 경로가 박혀 있어서 cp 로도 우연히 동작했고, #980 이후로는 **존재하지 않는 경로를
가리키는 plist** 를 프로덕션에 설치하게 됐다.

이 고장은 조용하다. launchd 는 exit 78(EX_CONFIG)로 죽고 `scheduler.err` 에 아무것도
남기지 않는다 — 로그만 보면 정상 종료와 구분이 안 된다. 게다가 **이미 돌고 있는 job 은
launchd 가 캐시한 정의로 계속 살아 있어서**, 배포가 unload/load 를 도는 다음 번까지
잠복한다. 2026-08-03 실측: 의존성 범프 배포가 scheduler 를 내렸고, 그때서야 #980 이
심어둔 고장이 드러났다.

다른 설치 경로(Makefile `agent-launchd-install` / `discord-bot-install`)는 처음부터
같은 sed 치환을 했다. 배포 경로만 빠져 있었다.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

LAUNCHD_DIR = Path("scripts/launchd")
DEPLOY_SCRIPT = Path("scripts/deploy/deploy_to_mini.sh")

PLACEHOLDER = "/Users/USER/"


def test_repo_plists_use_placeholder_not_real_home():
    """repo plist 는 실제 홈 경로를 담지 않는다 (#980 privacy).

    이 테스트가 이 파일에 있는 이유: 아래 치환 테스트의 **전제**다. 언젠가 plist 가
    실제 경로로 되돌아가면 치환은 무의미해지고 privacy 도 깨진다.
    """
    offenders = []
    for path in sorted(LAUNCHD_DIR.glob("*.plist")):
        text = path.read_text()
        # `/Users/<something>/` 중 플레이스홀더가 아닌 것
        for match in re.findall(r"/Users/[^/\s<]+/", text):
            if match != PLACEHOLDER:
                offenders.append(f"{path.name}: {match}")
    assert not offenders, f"plist 에 실제 홈 경로 노출: {offenders}"


def test_deploy_substitutes_placeholder_when_installing_plist():
    """배포는 plist 를 그대로 cp 하지 않고 `$HOME` 으로 치환해 설치한다.

    회귀 시나리오: 이 sed 를 `cp` 로 되돌리면 프로덕션 scheduler 가 exit 78 로 죽는다.
    """
    text = DEPLOY_SCRIPT.read_text()

    install_lines = [line for line in text.splitlines() if "PLIST_REMOTE" in line and "scripts/launchd" in line]
    assert install_lines, "plist 설치 라인을 못 찾음 — 스크립트 구조가 바뀌었다"

    for line in install_lines:
        assert PLACEHOLDER in line and "sed" in line, f"plist 를 치환 없이 설치한다 (cp 회귀?): {line.strip()}"
        assert "$HOME/" in line, f"치환 대상이 $HOME 이 아니다: {line.strip()}"


# ── 두 셸 경계를 실제로 태우는 테스트 (#990) ────────────────────────────────
#
# 위 두 테스트는 스크립트 **본문 텍스트**를 본다. `sed`→`cp` 회귀는 확실히 잡지만
# (mutation 실측), `$HOME` 이 **어느 셸에서** 확장되는지는 검사하지 못한다 — 로컬에서
# 확장되게 잘못 이스케이프해도 통과한다. `/codex review` (gpt-5.4, 2026-08-03) 가
# 지적한 갭이다.
#
# 그래서 아래는 grep 이 아니라 **셸을 두 번 실행**한다: 로컬 셸이 원격 명령 문자열을
# 조립하게 하고(SSH 를 stub 으로 갈아끼워 실행 대신 문자열을 뱉게 한다), 그 문자열을
# 원격 홈을 흉내낸 두 번째 셸이 실행한다. `tests/test_hook_guard_execution.py` 가
# 훅을 grep 하지 않고 셸로 실행해 exit code 를 보는 것과 같은 방식이다.


def _script_var(name: str) -> str:
    """스크립트에서 변수 정의 한 줄을 그대로 뽑는다 (테스트가 값을 재선언하지 않도록)."""
    for line in DEPLOY_SCRIPT.read_text().splitlines():
        if line.startswith(f"{name}="):
            return line
    raise AssertionError(f"{name} 정의를 못 찾음 — 스크립트 구조가 바뀌었다")


def _install_line() -> str:
    for line in DEPLOY_SCRIPT.read_text().splitlines():
        if "PLIST_REMOTE" in line and "scripts/launchd" in line:
            return line
    raise AssertionError("plist 설치 라인을 못 찾음 — 스크립트 구조가 바뀌었다")


PLIST_NAME = "com.nuri-quant.scheduler.plist"


def _emit_remote_command(tmp_path: Path, repo: Path) -> str:
    """**로컬** 셸에 설치 라인을 실행시켜, 원격으로 보낼 명령 문자열을 얻는다."""
    # SSH stub: 원격 명령($2)을 실행하지 않고 stdout 으로 뱉는다.
    ssh_stub = tmp_path / "ssh_stub.sh"
    ssh_stub.write_text('#!/bin/sh\nprintf "%s" "$2"\n')
    ssh_stub.chmod(0o755)

    script = "\n".join(
        [
            f'SSH="{ssh_stub}"',
            "REMOTE=dummy-host",
            f'REMOTE_PATH="{repo}"',
            f'PLIST_NAME="{PLIST_NAME}"',
            _script_var("PLIST_REMOTE"),
            _install_line(),
        ]
    )
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    return done.stdout


def test_home_expands_on_the_remote_shell_not_the_local_one(tmp_path):
    """`$HOME` 은 로컬이 아니라 **원격** 셸에서 확장돼야 한다.

    회귀 시나리오: `\\$HOME` 의 이스케이프를 빠뜨리면 로컬 홈이 박힌 plist 가 설치된다.
    개발 머신과 mini 의 홈이 우연히 같으면 한동안 안 터지고, 달라지는 순간 exit 78.
    """
    repo = tmp_path / "repo"
    (repo / "scripts" / "launchd").mkdir(parents=True)
    (repo / "scripts" / "launchd" / PLIST_NAME).write_text(
        f"<string>{PLACEHOLDER}workspace/nuri-quant/.venv/bin/python</string>\n"
    )

    emitted = _emit_remote_command(tmp_path, repo)

    # 조립 단계에서 확장되면 안 된다 — 원격 셸이 볼 문자열에 리터럴로 남아야 한다.
    assert "$HOME/Library/LaunchAgents/" in emitted, f"로컬 셸이 $HOME 을 미리 확장했다 (이스케이프 누락?): {emitted}"

    # 2단계: 원격 셸이 실행한다. HOME 을 갈아끼워 로컬과 구분한다.
    remote_home = tmp_path / "remote_home"
    (remote_home / "Library" / "LaunchAgents").mkdir(parents=True)
    subprocess.run(
        ["bash", "-c", emitted],
        env={**os.environ, "HOME": str(remote_home)},
        check=True,
    )

    installed = remote_home / "Library" / "LaunchAgents" / PLIST_NAME
    assert installed.exists(), f"원격 홈에 설치되지 않았다: {sorted(tmp_path.rglob('*.plist'))}"
    body = installed.read_text()
    assert PLACEHOLDER not in body, f"플레이스홀더가 그대로 남았다: {body}"
    assert str(remote_home) in body, f"원격 홈으로 치환되지 않았다: {body}"


def test_install_leaves_existing_plist_intact_when_source_is_missing(tmp_path):
    """sed 가 실패하면 **기존 plist 가 그대로** 남아야 한다 (#990).

    회귀 시나리오: temp+mv 를 `> ${PLIST_REMOTE}` 직접 쓰기로 되돌리면, 셸이 sed 실행
    전에 목적지를 truncate 해 빈 파일이 남는다. 하필 unload 와 load **사이**라
    launchd 가 그 빈 파일을 읽는다.
    """
    repo = tmp_path / "repo"
    (repo / "scripts" / "launchd").mkdir(parents=True)
    # 소스 plist 를 **일부러 만들지 않는다** → sed 가 실패한다.

    emitted = _emit_remote_command(tmp_path, repo)

    remote_home = tmp_path / "remote_home"
    (remote_home / "Library" / "LaunchAgents").mkdir(parents=True)
    installed = remote_home / "Library" / "LaunchAgents" / PLIST_NAME
    sentinel = "<string>기존에 잘 돌던 정의</string>\n"
    installed.write_text(sentinel)

    done = subprocess.run(
        ["bash", "-c", emitted],
        env={**os.environ, "HOME": str(remote_home)},
        capture_output=True,
        text=True,
    )

    assert done.returncode != 0, "소스가 없는데 설치가 성공했다고 보고했다"
    assert installed.read_text() == sentinel, (
        "설치 실패가 기존 plist 를 파괴했다 — unload/load 창에서 launchd 가 이걸 읽는다"
    )
