#!/usr/bin/env bash
# 닫힌 PR 의 refs/pull/N/merge 캐시를 지운다 — cache-cleanup.yml 의 정기 청소 (#1812).
#
# PR 이 닫힐 때 도는 즉시 삭제는 GITHUB_TOKEN 이 머지한 PR(dependabot auto-merge)에서 아예
# 시작되지 않는다 — 원인은 main_ci_catchup.sh 머리말. 2026-10-12 실측: 그렇게 남은 4개 PR 의
# 캐시 4.8GB 가 repo 한도 10GB 의 절반을 넘게 물고 있었다 (8.2GB → 정리 후 3.4GB).
# PR ref 만 본다 — main 의 세대 교체분은 GitHub 의 7일 미사용 축출이 처리한다.
# Test: tests/scripts/test_sweep_closed_pr_caches.py
set -euo pipefail

REPO="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

REFS=$(gh api --paginate "repos/${REPO}/actions/caches?per_page=100" --jq '.actions_caches[].ref' \
    | grep -E '^refs/pull/[0-9]+/merge$' | sort -u || true)

DELETED=0
for REF in $REFS; do
    N="${REF#refs/pull/}"
    N="${N%/merge}"
    STATE=$(gh api "repos/${REPO}/pulls/${N}" --jq '.state')
    if [ "$STATE" = "closed" ]; then
        gh cache delete --all --ref "$REF" -R "$REPO" --succeed-on-no-caches
        printf 'deleted caches for %s (PR #%s is closed)\n' "$REF" "$N"
        DELETED=$((DELETED + 1))
    fi
done
printf 'swept %s closed-PR ref(s)\n' "$DELETED"
