#!/usr/bin/env bash
# scripts/ops/machine_alive.sh — "머신은 살아 있다" 비트 (#1443).
#
# ## 왜 heartbeat 와 별도인가
#
# `refs/nuri/heartbeat-mini` (`nuri/alerts/offbox_heartbeat.py`) 는 **스케줄러가**
# 보낸다. dead-man 구조라 스케줄러·로그인 세션·머신·네트워크 중 무엇이 죽어도 전부
# "침묵" 한 가지로 수렴한다. 탐지에는 그게 옳지만 **분류에는 정보가 없다.**
#
# 2026-09-06 (#1443) 이 그 대가를 치렀다: mini 가 15:33 에 multi-user 로 부팅했는데
# 콘솔 로그인이 21:54 까지 없어서 gui LaunchAgent 7 개가 전부 미로드였다. 6 시간 21 분.
# 기계 밖 감시가 2.9 시간 뒤에 알렸지만, 알림이 "머신 꺼짐" 과 "머신은 켜졌는데
# 에이전트 미로드" 를 구분하지 못해 **의도적 종료로 오인**됐다. 두 상태는 조치가
# 정반대다 — 전자는 무해할 수 있고, 후자는 지금 손을 대야 한다.
#
# 그래서 신호를 둘로 나눈다. 이 스크립트는 **시스템 도메인 LaunchDaemon** 으로 돌아
# 로그인과 무관하게 `refs/nuri/machine-mini` 를 갱신한다:
#
#   machine 신선 + heartbeat 낡음  → 에이전트 미로드 / 스케줄러 사망 (긴급)
#   둘 다 낡음                     → 머신 꺼짐 또는 네트워크 단절
#
# ## FileVault 에 대한 정정
#
# "FileVault ON 이라 LaunchDaemon 이관은 무효" 라고 오래 적혀 있었으나 #1443 이
# 반증했다. FileVault 가 막는 것은 **전원 꺼진 상태의 무인 부팅**(pre-boot 물리 해제)
# 이지, 부팅 이후 시스템 도메인 데몬의 실행이 아니다. 이번 창(15:33~21:54)에
# LaunchDaemon 이었다면 정상 동작했다.
#
# ## 왜 파이썬이 아니라 셸인가
#
# 이 비트는 앱이 어떻게 깨지든 살아 있어야 한다. venv · DB · nuri import · 설정 로딩
# 어느 것에도 기대지 않는다 — 의존성이 늘수록 "머신은 살아 있다" 가 "앱이 살아 있다"
# 로 미끄러지고, 그러면 두 신호를 나눈 의미가 없어진다. git 과 deploy key 뿐이다.
#
# ## 설치
#
#   sudo bash scripts/launchd/install_daemons.sh        # 시스템 도메인
#
# gui LaunchAgent 로 설치하면 **아무 의미가 없다** — 그게 바로 못 잡는 실패 형태다.
# `scripts/launchd/install_crons.sh` 는 `-maxdepth 1` 로 이 디렉터리를 안 본다.
set -euo pipefail

REPO="${NURI_REPO:-$HOME/workspace/nuri-quant}"
REMOTE="git@github.com:researcherhojin/nuri-quant.git"
REF="refs/nuri/machine-mini"
# git 의 잘 알려진 빈 트리 — 어떤 레포에도 존재한다. 무부모 커밋을 force-push 하므로
# 히스토리가 자라지 않는다 (offbox_heartbeat 와 같은 이유).
EMPTY_TREE="4b825dc642cb6eb9a060e54bf8d69288fbee4904"
DEPLOY_KEY="${NURI_HEARTBEAT_KEY:-$HOME/.ssh/nuri_heartbeat_deploy}"

cd "$REPO"

export GIT_AUTHOR_NAME="nuri-machine" GIT_AUTHOR_EMAIL="machine@localhost"
export GIT_COMMITTER_NAME="nuri-machine" GIT_COMMITTER_EMAIL="machine@localhost"
export GIT_TERMINAL_PROMPT=0
[ -f "$DEPLOY_KEY" ] && export GIT_SSH_COMMAND="ssh -4 -i $DEPLOY_KEY -o IdentitiesOnly=yes -o ConnectTimeout=10"

sha=$(git commit-tree "$EMPTY_TREE" -m "machine alive — 감시자는 커밋 시각만 읽는다 (#1443)")
# --no-verify: pre-push 게이트는 코드 push 용이다. 빈 트리 ref 갱신을 린트로 막으면
# 살아 있는 머신이 죽은 것으로 보고된다 (가짜 긴급 알림).
git push --no-verify --force "$REMOTE" "$sha:$REF"
echo "machine-alive: pushed ${sha:0:8} → $REF"
