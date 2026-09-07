"""머신 생존 비트가 **로그인 게이트 밖**에 있는지 (#1443).

2026-09-06: mini 가 15:33 에 multi-user 로 부팅했으나 콘솔 로그인이 21:54 여서 nuri
gui LaunchAgent 7 개가 6 시간 21 분 미로드였다. 감시용 watchdog 도 같은 목록이라 같이
죽었고, 유일하게 작동한 기계 밖 감시는 "머신 꺼짐" 과 "에이전트 미로드" 를 구분하지
못해 **의도적 종료로 오인**됐다. 조치가 정반대인 두 상태다.

여기서 잠그는 것은 두 가지다:

1. 시스템 도메인 plist 가 gui installer 에 **딸려 들어가지 않는다.** 그게 일어나면
   로그인 게이트를 벗어나려고 만든 데몬이 정확히 그 게이트 뒤에 놓인다 — 조용히,
   설치가 성공한 것처럼.
2. 감시자가 두 신호를 조합해 상태를 **분류**한다.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

#: launchd 는 macOS 서브시스템이라 `launchctl`·`plutil` 이 Linux 러너에 없다. 이 파일의
#: **실행형** 테스트만 Darwin 으로 게이트한다 — 분류·문구·ref 잠금은 플랫폼 무관이라
#: CI 에서 계속 돈다. 실행형을 구조 검사로 바꾸지 않는 이유는 이 세션에서 구조 게이트가
#: 네 번 샜기 때문이고, 대상(launchd plist)이 도는 곳은 어차피 mini 와 이 개발기뿐이다.
darwin_only = pytest.mark.skipif(sys.platform != "darwin", reason="launchd 는 macOS 전용 — plutil/launchctl 부재")

REPO = Path(__file__).resolve().parents[1]
SYSTEM_PLIST = REPO / "scripts/launchd/system/com.nuri-quant.machine-alive.plist"
CRONS_INSTALLER = REPO / "scripts/launchd/install_crons.sh"
DAEMONS_INSTALLER = REPO / "scripts/launchd/install_daemons.sh"
WATCH_WORKFLOW = REPO / ".github/workflows/heartbeat-watch.yml"


class TestSystemDomainIsNotSweptIntoTheAgentInstaller:
    """구조가 아니라 **동작**으로 잠근다 — installer 를 dry-run 으로 실행해 목록을 본다."""

    @darwin_only
    def test_the_agent_installer_does_not_list_the_system_daemon(self):
        r = subprocess.run(
            ["bash", str(CRONS_INSTALLER), "--dry"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
        )
        # stderr 를 단언 메시지에 싣는다 — 첫 판은 stdout 만 봐서 CI 가 "비었다" 만 말하고
        # **왜** 비었는지는 감췄다. 실패한 게이트는 이유를 보여줘야 고칠 수 있다.
        out = r.stdout
        ctx = f"\n[rc={r.returncode}] stderr: {r.stderr.strip()[:400]}"
        assert "machine-alive" not in out, (
            "gui installer 가 시스템 도메인 plist 를 집었다 — 그대로 설치하면 로그인 게이트를 "
            "벗어나려는 데몬이 그 게이트 뒤에 놓인다. `find -maxdepth 1` 을 확인할 것." + ctx
        )
        # 카나리아: dry-run 이 애초에 아무것도 안 세면 위 단언은 공허하다 (#910).
        assert "scheduler" in out, "installer dry-run 이 비었다 — 검사가 0 개를 통과시키고 있다" + ctx

    def test_the_daemon_installer_does_list_it(self):
        # 이쪽은 게이트하지 않는다 — Linux CI 에서 실제로 통과했다. 필요 이상으로 막으면
        # 그만큼 CI 가 검사하지 않는 표면이 늘어난다.
        out = subprocess.run(
            ["bash", str(DAEMONS_INSTALLER), "--dry"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
        assert "machine-alive" in out
        assert "/Library/LaunchDaemons" in out


class TestTheDaemonPlistWouldActuallyLoad:
    @darwin_only
    def test_plist_parses_and_targets_the_system_domain(self):
        # plutil 은 macOS 기본 — 문법 오류를 grep 이 아니라 파서로 잡는다.
        rc = subprocess.run(["plutil", "-lint", str(SYSTEM_PLIST)], capture_output=True, text=True, timeout=30)
        assert rc.returncode == 0, rc.stdout + rc.stderr

    @darwin_only
    def test_it_runs_as_a_real_user_not_root(self):
        """`UserName` 이 없으면 root 로 돌고 `$HOME` 이 root 홈이라 deploy key 를 못 찾는다.

        그러면 push 가 조용히 실패하고, 침묵이 곧 "머신 죽음" 으로 보고돼 **분류가 거꾸로**
        된다 — 머신은 멀쩡한데 꺼진 것으로 읽힌다.

        문자열이 아니라 **파싱한 값**을 본다: 첫 판은 원문에 `/var/root` 가 없는지만 봐서,
        그 경로를 *설명하는 주석* 에 걸려 오탐했다 (산문과 설정을 못 가르는 검사).
        """
        import json

        parsed = json.loads(
            subprocess.run(
                ["plutil", "-convert", "json", "-o", "-", str(SYSTEM_PLIST)],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            ).stdout
        )
        assert parsed.get("UserName") not in (None, "root")
        assert parsed["EnvironmentVariables"]["HOME"].startswith("/Users/")


class TestTheWatcherClassifiesInsteadOfJustReportingSilence:
    """세 상태가 **서로 다른 조치**를 말해야 한다 — 그게 오인을 만든 지점이다."""

    def test_it_reads_both_refs(self):
        """이름을 **동치**로 본다 — substring 은 rename 을 통과시킨다.

        `…-mini` 는 `…-mini-v2` 의 부분 문자열이라, 송신 쪽만 rename 해도 검사가 초록이고
        감시자는 영원히 "ref 없음" 침묵 알림만 낸다 (`test_offbox_heartbeat.py` 가 같은
        이유로 substring 을 기각한다). 머신 ref 의 정본은 셸 스크립트 상수다.
        """
        watched = set(re.findall(r"ref_age_min ([A-Za-z0-9/_.-]+)", WATCH_WORKFLOW.read_text()))
        m = re.search(r'^REF="([^"]+)"', (REPO / "scripts/ops/machine_alive.sh").read_text(), re.M)
        assert m, "machine_alive.sh 에서 REF 상수를 못 찾았다"
        machine_ref = m.group(1).removeprefix("refs/")
        assert machine_ref in watched, f"감시자가 보는 ref {watched!r} 에 송신 ref {machine_ref!r} 가 없다"
        assert len(watched) == 2, f"2-ref 분류가 아니다: {watched!r}"

    def test_each_branch_names_a_different_action(self):
        text = WATCH_WORKFLOW.read_text()
        actions = re.findall(r'action="([^"]+)"', text)
        assert len(actions) == 3, f"3 상태 분기가 아니다: {len(actions)}"
        assert len(set(actions)) == 3, "분기가 같은 조치를 말한다 — 분류의 의미가 없다"

    def test_the_machine_up_branch_does_not_ask_to_check_power(self):
        """머신 비트가 신선한데 '전원 확인' 을 시키면 정확히 그 오인을 되풀이한다.

        지시 **문구**를 본다. 첫 판은 "전원" 이라는 낱말만 찾아서, 이 분기가 일부러 적은
        "전원/네트워크 문제가 아니다" 라는 **부정문**에 걸려 오탐했다.
        """
        text = WATCH_WORKFLOW.read_text()
        up_branch = text.split('if [ "$mach_age" -le "$THRESHOLD_MIN" ]; then', 1)[1].split("elif", 1)[0]
        assert "전원·네트워크 확인" not in up_branch, "머신이 살아 있는 분기가 전원 확인을 지시한다"
        assert "launchctl" in up_branch, "미로드 진단 명령이 없다"
        # 나머지 두 분기는 반대로 전원 확인을 지시해야 한다 — 대조로 잠근다
        rest = text.split('if [ "$mach_age" -le "$THRESHOLD_MIN" ]; then', 1)[1].split("elif", 1)[1]
        assert "전원·네트워크 확인" in rest


class TestTheDisprovenFileVaultClaimIsGone:
    """반증된 전제가 남아 있으면 다음 세션이 다시 그 근거로 대책을 접는다 (#1443).

    "FileVault ON 이라 LaunchDaemon 이관은 무효" 가 `offbox_heartbeat.py` 독스트링에
    있었고, 그 문장 때문에 옳은 대책이 오래 배제됐다. FileVault 가 막는 것은 전원 꺼진
    상태의 무인 부팅이지 부팅 이후 데몬 실행이 아니다.
    """

    def test_the_module_no_longer_calls_the_migration_void(self):
        text = (REPO / "nuri/alerts/offbox_heartbeat.py").read_text()
        assert "pre-boot 잠금 앞에서 무효" not in text
        assert "#1443" in text, "정정이 근거 이슈를 인용하지 않으면 다시 뒤집힌다"
