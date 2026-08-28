#!/usr/bin/env bash
# 로컬과 원격의 git HEAD 가 **같은 커밋인지** 판정한다 (#1277).
#
# 사용법:
#   verify_head_sync.sh <ssh_cmd> <remote_host> <remote_path>
#   (로컬 저장소는 현재 작업 디렉터리)
#
# 출력 (stdout 4줄):
#   1: 로컬 전체 SHA
#   2: 원격 전체 SHA
#   3: 로컬 표시용 라벨  ("<축약> <제목>")
#   4: 원격 표시용 라벨
# 종료 코드:
#   0 = 일치
#   1 = **불일치** (양쪽 SHA 를 정상적으로 받았고 서로 다름)
#   2 = **판정 불가** (SSH 실패 · git 실패 · 응답이 SHA 형태가 아님)
#
# 1 과 2 를 나누는 것이 이 스크립트의 두 번째 계약이다 (codex 리뷰 P1). 둘을 뭉뚱그리면
# **"검사 실패" 가 "검사 결과 불일치" 로 둔갑**한다 — 이 레포가 이미 겪은 형태다
# (#910/#911: rc=127 이 실패와 구분되지 않아 pre-push 테스트가 3.5개월 no-op).
# 호출자는 2 를 경고가 아니라 **중단**으로 다뤄야 한다: 마지막 안전 게이트가 돌지 않았는데
# "deploy 완료" 를 찍으면 게이트가 없는 것과 같다.
#
# ⚠️ **비교는 전체 SHA 로만 한다.** 이전에는 `git log -1 --oneline` 문자열을 비교했는데,
# 그 축약 SHA 길이는 **저장소마다 다르다** — git 의 auto-abbrev 가 오브젝트 수에서
# 파생되기 때문이다. 2026-08-29 실측: 같은 커밋 `eab0614…` 가 MBP 에서는 8자,
# Mac mini 에서는 7자로 찍혀 **완벽히 동기화된 배포마다 "HEAD 불일치" 경고**가 났다
# (두 번의 배포에서 모두 재현). 커밋 제목까지 비교면에 들어가 있어 공백·개행이 섞이면
# 오탐 축이 하나 더 생긴다.
#
# 거짓 경고는 단순 노이즈가 아니다 — 배포 검증은 상주 데몬이 구코드를 들고 도는 사고
# (#1024, 7일 잠복)를 잡는 마지막 관문인데, 매번 뜨는 경고는 **진짜 불일치가 났을 때
# 그 한 줄을 무시하게** 만든다. 이 레포가 반복해서 배운 false-red 형태다.
#
# 표시용 라벨은 사람이 읽으라고 따로 낸다 — 축약은 표시에만 쓰고 판정에는 안 쓴다.
# `-e` 는 일부러 안 켠다 — 실패를 스스로 분류해 rc 2 로 내보내야 하는데, `-e` 는
# 하위 명령의 rc 를 그대로 흘려 1(불일치)과 구분할 수 없게 만든다.
set -uo pipefail

SSH_CMD="${1:?ssh 커맨드 경로가 필요하다}"
REMOTE="${2:?원격 호스트가 필요하다}"
REMOTE_PATH="${3:?원격 저장소 경로가 필요하다}"

undetermined() { echo "verify_head_sync: $1" >&2; exit 2; }
is_sha() { case "$1" in [0-9a-f]*) [ "${#1}" -eq 40 ] ;; *) false ;; esac; }

# 원격은 SSH 왕복 1회로 둘 다 받는다 (판정용 SHA + 표시용 라벨).
# `%x20` 은 공백 — `--format` 안에서 공백을 그대로 쓰면 인용이 지저분해진다.
# shellcheck disable=SC2029  # 원격에서 확장되어야 하는 의도된 문자열
if ! REMOTE_OUT=$("${SSH_CMD}" "${REMOTE}" "cd ${REMOTE_PATH} && git rev-parse HEAD && git log -1 --format=%h%x20%s"); then
    undetermined "원격 HEAD 조회 실패 (ssh 또는 git) — 판정 불가"
fi

REMOTE_SHA=$(printf '%s\n' "${REMOTE_OUT}" | sed -n 1p)
REMOTE_LABEL=$(printf '%s\n' "${REMOTE_OUT}" | sed -n 2p)

if ! LOCAL_SHA=$(git rev-parse HEAD 2>/dev/null); then
    undetermined "로컬 HEAD 조회 실패 — 판정 불가"
fi
LOCAL_LABEL=$(git log -1 --format=%h%x20%s 2>/dev/null || echo "(라벨 없음)")

# 형태 검증 — 빈 응답이나 쓰레기를 **불일치로 흘리지 않는다**. SSH 가 rc 0 으로 배너만
# 뱉는 경우가 있고, 그걸 SHA 로 믿으면 "불일치" 라는 **틀린 이유**를 보고하게 된다.
is_sha "${LOCAL_SHA}" || undetermined "로컬 SHA 형태 아님: '${LOCAL_SHA}'"
is_sha "${REMOTE_SHA}" || undetermined "원격 SHA 형태 아님: '${REMOTE_SHA}'"

printf '%s\n%s\n%s\n%s\n' "${LOCAL_SHA}" "${REMOTE_SHA}" "${LOCAL_LABEL}" "${REMOTE_LABEL}"

[ "${LOCAL_SHA}" = "${REMOTE_SHA}" ]
