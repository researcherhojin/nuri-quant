"""모든 launchd 설치 경로가 치환·원자 교체를 하는지, 그리고 레포가 bare-cp 설치를
지시하지 않는지 잠근다 (#992).

Gotcha-Test Pair:
#989/#990 이 배포 경로 하나를 고쳤다. 그런데 `/codex review` (gpt-5.4, 2026-08-03) 가
같은 클래스가 레포에 그대로 남아 있는 걸 찾았다 — 설치 경로 3곳이 최종 경로에 직접 쓰고
있었고(`Makefile` 2곳 + `install_crons.sh`), 추적 파일 8곳이 아직 bare `cp` 로 설치하라고
**지시**하고 있었다. 그중 2곳은 경로까지 틀렸다.

지시가 위험한 이유: #980 이후 repo plist 는 `/Users/USER/` 플레이스홀더를 담는다. 그대로
복사하면 launchd 가 exit 78(EX_CONFIG)로 죽고 stderr 에 **아무것도 안 남긴다**. 게다가
돌고 있던 job 은 launchd 가 캐시한 정의로 살아남아 다음 재시작까지 잠복한다. 사람이든
에이전트든 파일 안에 적힌 설치 명령을 그대로 따르므로, 문서가 곧 사고 경로다.

`tests/scripts/test_deploy_plist_placeholder.py` 는 **배포 경로만** 본다. 이 파일은
나머지 전부를 본다 — 인스턴스가 아니라 클래스를 잠그는 게 목적이다.
"""

from __future__ import annotations

import re
from pathlib import Path

LAUNCHD_DIR = Path("scripts/launchd")
MAKEFILE = Path("Makefile")
INSTALL_CRONS = LAUNCHD_DIR / "install_crons.sh"

PLACEHOLDER_SED = "/Users/USER"

# 레포에서 설치 지시가 실릴 수 있는 파일들 (주석·문서 포함)
_INSTRUCTION_FILES = [
    *sorted(LAUNCHD_DIR.glob("*.plist")),
    *sorted(Path("scripts").rglob("*.sh")),
    MAKEFILE,
]

# `cp <무언가> ~/Library/LaunchAgents/...` — 치환 없이 복사하라는 지시
_BARE_CP = re.compile(r"cp\s+\S*\.plist\s+.*Library/LaunchAgents")


def test_no_tracked_file_instructs_a_bare_cp_install():
    """레포 어디에도 bare `cp` 로 plist 를 설치하라는 지시가 없어야 한다.

    회귀 시나리오: 누가 편의로 `cp ... ~/Library/LaunchAgents/` 를 주석에 되살리면,
    그걸 따른 사람이 프로덕션 scheduler 를 exit 78 로 죽인다 (#988).
    """
    offenders = []
    for path in _INSTRUCTION_FILES:
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if _BARE_CP.search(line):
                offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert not offenders, (
        "bare cp 설치 지시가 남아 있다 — 그대로 따르면 /Users/USER 플레이스홀더가 설치돼 "
        "launchd exit 78:\n" + "\n".join(offenders)
    )


def test_plist_install_instructions_reference_the_launchd_dir():
    """plist 헤더의 설치 예시가 실제 경로(`scripts/launchd/`)를 가리켜야 한다.

    `scheduler` / `autopull` 두 헤더는 `scripts/<name>.plist` 라는 **없는 경로**를 적고
    있었다. 따라 하면 sed/cp 가 실패하고, 실패를 무시하면 다음 단계가 더 나쁘게 굴러간다.
    """
    offenders = []
    for path in sorted(LAUNCHD_DIR.glob("*.plist")):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for ref in re.findall(r"scripts/\S*\.plist", line):
                if not ref.startswith("scripts/launchd/"):
                    offenders.append(f"{path}:{lineno}: {ref}")
    assert not offenders, f"plist 설치 예시가 없는 경로를 가리킨다: {offenders}"


# 플레이스홀더를 치환하면서 **어딘가로 쓰는** 라인 (`sed "s|/Users/USER..." ... > dest`)
_SUBSTITUTING_WRITE = re.compile(r"s\|/Users/USER.*?>\s*(?P<dest>\S+)")


def _substituting_writes(path: Path) -> list[tuple[str, str]]:
    out = []
    for line in path.read_text().splitlines():
        m = _SUBSTITUTING_WRITE.search(line)
        if m:
            out.append((m.group("dest"), line))
    return out


def test_every_install_path_substitutes_and_swaps_atomically():
    """설치 경로는 전부 치환 결과를 temp 에 쓰고 `mv` 로 교체해야 한다.

    회귀 시나리오: 최종 경로에 직접 쓰면 셸이 sed 전에 목적지를 truncate 한다. 세 경로 다
    `launchctl unload` 뒤에 실행되므로, 실패하면 깨진(또는 빈) plist 를 load 하게 된다.

    배포 경로(`deploy_to_mini.sh`)는 `test_deploy_plist_placeholder.py` 가 셸을 실제로
    태워서 잠근다. 여기서는 나머지 경로를 텍스트로 잠근다 — 셸 실행이 launchctl 을
    건드리게 되어 테스트에서 돌릴 수 없기 때문이다.
    """
    checked = 0
    for path in (MAKEFILE, INSTALL_CRONS):
        assert path.exists(), f"{path} 가 없다 — 구조가 바뀌었다"
        for dest, line in _substituting_writes(path):
            checked += 1
            assert ".tmp" in dest, f"치환 결과를 최종 경로에 직접 쓴다 (truncate 위험): {path}: {line.strip()}"
            # 같은 라인이나 바로 뒤에서 mv 로 되돌려놔야 한다
            assert "mv " in line or "mv " in path.read_text(), f"{path} 에 temp → 최종 경로 원자 교체(mv)가 없다"
    assert checked >= 3, (
        f"치환 쓰기 라인이 {checked}개뿐 — Makefile 2곳 + install_crons.sh 를 못 찾았다. "
        "설치 경로가 사라졌거나 이 테스트의 패턴이 낡았다"
    )
