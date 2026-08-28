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
# 종료 코드: 0 = 일치, 1 = 불일치
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
set -euo pipefail

SSH_CMD="${1:?ssh 커맨드 경로가 필요하다}"
REMOTE="${2:?원격 호스트가 필요하다}"
REMOTE_PATH="${3:?원격 저장소 경로가 필요하다}"

# 원격은 SSH 왕복 1회로 둘 다 받는다 (판정용 SHA + 표시용 라벨).
# `%x20` 은 공백 — `--format` 안에서 공백을 그대로 쓰면 인용이 지저분해진다.
# shellcheck disable=SC2029  # 원격에서 확장되어야 하는 의도된 문자열
REMOTE_OUT=$("${SSH_CMD}" "${REMOTE}" "cd ${REMOTE_PATH} && git rev-parse HEAD && git log -1 --format=%h%x20%s")

REMOTE_SHA=$(printf '%s\n' "${REMOTE_OUT}" | sed -n 1p)
REMOTE_LABEL=$(printf '%s\n' "${REMOTE_OUT}" | sed -n 2p)
LOCAL_SHA=$(git rev-parse HEAD)
LOCAL_LABEL=$(git log -1 --format=%h%x20%s)

printf '%s\n%s\n%s\n%s\n' "${LOCAL_SHA}" "${REMOTE_SHA}" "${LOCAL_LABEL}" "${REMOTE_LABEL}"

[ "${LOCAL_SHA}" = "${REMOTE_SHA}" ]
