#!/usr/bin/env bash
# scripts/deploy/thesis_remote.sh — Discord /thesis 를 상대 머신(MBP)에서 실행한다.
#
# 왜: thesis 는 로컬 모델만 쓴다 (`llm_consult --local-only`, loopback 전용). 그 모델(Strata,
# Metal GGUF 77GB)은 RAM 32GB 인 Mac mini 에 올라가지 않는다. 그래서 mini 의 봇은 ticker 만
# MBP 로 보내고, 맥락 조회와 모델 호출은 전부 MBP 안(loopback)에서 일어난다. mini 가 받는 건
# `make thesis` 의 출력 텍스트뿐이다.
#
# 데이터: MBP 의 dev DB 는 며칠씩 낡는다 (2026-10-26 실측: 4일). mini 가 매시간 push 하는
# 최신 `data/replicas/*.db` 를 NURI_DB_PATH 로 쓴다. 복제본이 없으면 dev DB 로 돌리되 경고한다.
#
# 호출: make thesis-remote ticker=<TICKER>   (Discord /thesis 가 부른다)
# 환경: DEV2_HOST / DEV2_PATH — ~/.zshrc 에만 둔다. .env 는 sync_dev.sh 가 머신 사이로 복사하므로
#       머신별 값을 두지 않는다 (state_replicator.sh 와 같은 규칙). 봇 프로세스는 .env 만 읽으므로
#       비어 있으면 여기서 ~/.zshrc 를 읽는다.
# 종료: 원격 `make thesis` 의 exit code 를 그대로 돌려준다. 입력 오류·설정 누락은 2.

set -euo pipefail

TICKER="${1:-}"
# 원격 셸 문자열로 들어가므로 여기서 형태를 고정한다 (봇도 검사하지만 이 스크립트 단독 호출도 있다)
if [[ ! "$TICKER" =~ ^[A-Z]{1,6}$ ]]; then
    echo "usage: thesis_remote.sh <TICKER>  (A-Z, 1-6 chars)" >&2
    exit 2
fi

if [[ -z "${DEV2_HOST:-}" ]]; then
    # shellcheck disable=SC2016  # 작은따옴표 안 변수는 zsh 쪽에서 풀린다
    eval "$(zsh -c 'source ~/.zshrc >/dev/null 2>&1; printf "DEV2_HOST=%q\nDEV2_PATH=%q\n" "${DEV2_HOST:-}" "${DEV2_PATH:-}"')"
fi
if [[ -z "${DEV2_HOST:-}" ]]; then
    echo "DEV2_HOST not set — export it in ~/.zshrc (not .env)" >&2
    exit 2
fi

REMOTE_REPO="${DEV2_PATH:-~/workspace/nuri-quant}"
REMOTE_REPO="${REMOTE_REPO#\~/}"  # ssh 는 홈에서 시작한다 — `\~` escape 이유는 state_replicator.sh (#947)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_CMD="cd $(printf '%q' "$REMOTE_REPO") && export PATH=/opt/homebrew/bin:\$PATH"
REMOTE_CMD+=" && R=\$(ls -t data/replicas/*.db 2>/dev/null | head -n 1)"
REMOTE_CMD+="; if [ -n \"\$R\" ]; then export NURI_DB_PATH=\"\$PWD/\$R\"; else echo 'warn: no replica — using the dev DB' >&2; fi"
REMOTE_CMD+="; make thesis ticker=$TICKER"

exec bash "$SCRIPT_DIR/ssh_dev2.sh" -o BatchMode=yes -o ConnectTimeout=10 "$DEV2_HOST" "$REMOTE_CMD"
