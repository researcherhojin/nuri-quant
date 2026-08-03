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

import re
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
