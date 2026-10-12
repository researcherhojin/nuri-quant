#!/usr/bin/env bash
# main HEAD 에 main-ci-cd 런이 하나도 없으면 workflow_dispatch 로 띄운다 (#1812).
#
# GITHUB_TOKEN 이 한 머지 — dependabot-auto-merge.yml 이 켠 auto-merge — 는 어떤 워크플로도
# 시작하지 않는다. GitHub 문서: "events triggered by the GITHUB_TOKEN will not create a new
# workflow run", 예외는 workflow_dispatch · repository_dispatch
# (https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).
# 2026-10-12 실측: github-actions[bot] 이 머지한 6건(#1801–#1803 · #1792–#1794)의 머지 커밋에
# main CI 가 0회였다. autopull 의 CI 게이트(#1809)는 그런 커밋을 "no-run" 으로 계속 보류한다.
#
# main-ci-catchup.yml 이 매시간 부른다. 하는 일은 하나뿐이다:
#   - HEAD 커밋이 CATCHUP_MIN_AGE_SECONDS(기본 600)보다 새로우면 손대지 않는다 — 사람이 머지한
#     커밋의 push 런이 아직 안 생겼을 수 있고, push 런과 dispatch 런은 같은 concurrency 그룹
#     (ci-refs/heads/main)이라 서로를 취소한다.
#   - HEAD 에 main-ci-cd 런이 하나라도 있으면(이벤트 · 상태 무관) 손대지 않는다 — 빨간 런을 다시
#     돌리지 않는다. 그건 사람이 판단한다.
#   - 그 밖에만 main 에 dispatch 한다.
# Test: tests/scripts/test_main_ci_catchup.py
set -euo pipefail

REPO="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
MIN_AGE="${CATCHUP_MIN_AGE_SECONDS:-600}"
NOW="${CATCHUP_NOW:-$(date -u +%s)}"

head_info() {
    gh api "repos/${REPO}/commits/main" --jq '"\(.sha) \(.commit.committer.date | fromdateiso8601)"'
}

HEAD_INFO=$(head_info)
SHA="${HEAD_INFO%% *}"
COMMITTED="${HEAD_INFO##* }"
# 응답 형식을 확인하고 나서 판단한다 — if 조건 안의 비교 오류는 set -e 로 멈추지 않아서, 숫자가 아닌
# 값이 그대로 "런 없음" 쪽으로 떨어졌다 (#1812 리뷰).
[[ "$SHA" =~ ^[0-9a-f]{40}$ && "$COMMITTED" =~ ^[0-9]+$ ]] \
    || { printf 'unexpected HEAD answer: %q\n' "$HEAD_INFO" >&2; exit 1; }
AGE=$((NOW - COMMITTED))

if [ "$AGE" -lt "$MIN_AGE" ]; then
    printf 'main %s is %ss old (< %ss) — its push run may still be starting; nothing to do\n' "${SHA:0:8}" "$AGE" "$MIN_AGE"
    exit 0
fi

RUNS=$(gh api "repos/${REPO}/actions/workflows/main-ci-cd.yml/runs?head_sha=${SHA}&branch=main&per_page=1" --jq '.total_count')
[[ "$RUNS" =~ ^[0-9]+$ ]] || { printf 'unexpected run count: %q\n' "$RUNS" >&2; exit 1; }
if [ "$RUNS" -ne 0 ]; then
    printf 'main %s already has %s main-ci-cd run(s); nothing to do\n' "${SHA:0:8}" "$RUNS"
    exit 0
fi

# dispatch 는 SHA 가 아니라 움직이는 main ref 에 걸린다. 확인한 뒤 새 커밋이 들어왔으면 손대지
# 않는다 — 그 커밋은 자기 push 런(사람 머지)이나 다음 catch-up 이 맡는다. 그래도 남는 짧은 창에서
# 겹치면, main-ci-cd 의 concurrency 그룹이 이벤트별이라 dispatch 런이 push 런을 취소하지 않는다.
NOW_SHA=$(head_info)
NOW_SHA="${NOW_SHA%% *}"
if [ "$NOW_SHA" != "$SHA" ]; then
    printf 'main moved from %s to %s after the check; leaving it to that commit\n' "${SHA:0:8}" "${NOW_SHA:0:8}"
    exit 0
fi

gh workflow run main-ci-cd.yml --ref main -R "$REPO"
printf 'main %s had no main-ci-cd run (merged by GITHUB_TOKEN?) — dispatched one\n' "${SHA:0:8}"
