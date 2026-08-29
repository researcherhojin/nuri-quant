"""기계 밖 감시의 송신 절반 — dead-man heartbeat push (#1191 옵션 C).

## 왜 이 모양인가

42h 침묵 사고(#1191)의 축은 "감시자가 감시 대상과 같은 기계" 였다. mini 위의
어떤 장치도(watchdog 포함) 로그인 세션과 함께 죽고, FileVault ON 이라 LaunchDaemon
이관(B)은 pre-boot 잠금 앞에서 무효다. 그래서 **탐지를 기계 밖으로** 뺀다:

- **송신(이 모듈, mini)**: 스케줄러 job 이 10분마다 빈-트리 커밋을
  `refs/nuri/heartbeat-mini` (커스텀 ref — 브랜치 아님) 로 push. 로그인 세션 소멸·머신 다운·네트워크
  단절·스케줄러 사망 **전부가 "침묵" 으로 수렴**한다 — 송신자가 죽는 것이 곧
  신호라서, 송신자를 살리려는 어떤 장치도 필요 없다 (dead-man 패턴).
- **감시(기계 밖)**: `.github/workflows/heartbeat-watch.yml` 이 ref 의 커밋 시각
  staleness 를 검사해 임계 초과 시 `#ops` webhook 으로 알린다.

## 설계 결정

- **스케줄러 job 이지 launchd 가 아니다** — autopull + deploy 만으로 배포되고,
  스케줄러 사망도 침묵에 포함시키는 게 목적에 맞다 (스케줄러 생존 중의 개별
  고장은 on-box watchdog 담당 — 반경이 다르다).
- **`is_production()` 게이트** — `NURI_ROLE` 은 mini 의 launchd plist 에만 있다
  (.env 는 sync 로 양쪽에 복사되므로 판별자가 될 수 없다 — DEV2_HOST 교훈).
  MBP 에서 스케줄러를 돌려도 heartbeat 가 mini 의 침묵을 가리지 않는다.
- **전용 deploy key** — mini 의 origin 은 https(익명 fetch 전용)고 gh 토큰도
  없다. repo 한정 write key(`~/.ssh/nuri_heartbeat_deploy`)만 쓰며, main 은
  branch protection 이 지킨다. 키 부재/만료도 침묵 → 감시자가 잡는다.
- **빈-트리 + 무부모 커밋을 force-push** — 브랜치가 커밋 1개로 고정되어 히스토리가
  자라지 않는다 (10분 간격 = 연 5만 커밋을 체인으로 쌓지 않기 위해).
- **push 실패는 조용히 실패해도 안전하다** — 실패 = 침묵 = 알림. 여기서 재시도나
  경보를 쌓으면 감시자와 역할이 겹치고, #894 계열(관측이 본 작업을 게이트)로 간다.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from nuri.alerts.alpha_report import is_production

logger = logging.getLogger(__name__)

#: git 의 잘 알려진 빈 트리 오브젝트 — 어떤 레포에도 존재한다.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# refs/heads 밖의 커스텀 네임스페이스 — GitHub 브랜치 목록·"recent pushes" 배너·
# PR 프롬프트 어디에도 안 잡힌다 (2026-08-30, 배너가 매 10분 되살아나는 문제로 이전).
# 브랜치 시절 이름: refs/heads/ops/heartbeat-mini.
HEARTBEAT_REF = "refs/nuri/heartbeat-mini"

#: mini 의 origin 은 https(익명 fetch 전용)라 push 대상은 ssh URL 을 명시한다.
REMOTE_URL = "git@github.com:researcherhojin/nuri-quant.git"

#: repo 한정 write deploy key (mini 에만 존재, 2026-08-29 등록 id 161664449).
DEPLOY_KEY = Path.home() / ".ssh" / "nuri_heartbeat_deploy"

#: 커밋 ident — 실 이메일을 쓰지 않는다 (author 익명화 방침).
_IDENT_ENV = {
    "GIT_AUTHOR_NAME": "nuri-heartbeat",
    "GIT_AUTHOR_EMAIL": "heartbeat@localhost",
    "GIT_COMMITTER_NAME": "nuri-heartbeat",
    "GIT_COMMITTER_EMAIL": "heartbeat@localhost",
}


def send_heartbeat(repo_root: Path | None = None, remote_url: str | None = None) -> str | None:
    """빈-트리 커밋을 만들어 heartbeat ref 로 force-push. 성공 시 sha, 실패/skip 시 None.

    커밋의 committer 시각 자체가 heartbeat 페이로드다 — 메시지는 사람이 브랜치를
    봤을 때의 안내일 뿐, 감시자는 시각만 읽는다.
    """
    if not is_production():
        logger.debug("[offbox_heartbeat] NURI_ROLE != production — skip (dev 은 침묵이 정상)")
        return None

    import os

    cwd = str(repo_root) if repo_root else None
    env = {**os.environ, **_IDENT_ENV}
    if DEPLOY_KEY.exists():
        env["GIT_SSH_COMMAND"] = f"ssh -4 -i {DEPLOY_KEY} -o IdentitiesOnly=yes -o ConnectTimeout=10"

    try:
        sha = subprocess.run(
            ["git", "commit-tree", EMPTY_TREE, "-m", "offbox heartbeat — 감시자는 커밋 시각만 읽는다 (#1191)"],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout.strip()
        subprocess.run(
            # --no-verify: pre-push 게이트는 코드 push 용이다 — 빈 트리 ref 갱신에
            # 드리프트/린트 검사를 돌릴 이유가 없고, 게이트 red 가 heartbeat 를
            # 죽이면 가짜 침묵 알림이 된다.
            ["git", "push", "--no-verify", "--force", remote_url or REMOTE_URL, f"{sha}:{HEARTBEAT_REF}"],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        logger.info(f"[offbox_heartbeat] pushed {sha[:8]} → {HEARTBEAT_REF}")
        return sha
    except subprocess.SubprocessError as e:
        # 실패 = 침묵 = 기계 밖 감시자가 알린다. 여기서는 로그만 남긴다 (독트린은
        # 모듈 독스트링 마지막 항목).
        detail = getattr(e, "stderr", "") or str(e)
        logger.error(f"[offbox_heartbeat] push 실패 (감시자가 침묵으로 탐지): {detail.strip()[:200]}")
        return None


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m nuri.alerts.offbox_heartbeat send` — 배포 후 수동 검증용."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["send"])
    parser.parse_args(argv)

    sha = send_heartbeat()
    if sha:
        print(f"pushed {sha}")
        return 0
    print("skip 또는 실패 — NURI_ROLE/로그 확인 (침묵은 감시자가 잡는다)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
