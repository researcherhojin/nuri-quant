#!/usr/bin/env bash
# main 의 캐시 중 같은 계열의 더 새 캐시로 대체된 것을 지운다 — cache-cleanup.yml 의 정기 청소 (#1901).
#
# "main 의 세대 교체분은 GitHub 의 7일 미사용 축출이 처리한다" 는 전제가 2026-10-22 에 깨졌다:
# 10GB 한도 중 8.1GB 가 찼고, 그중 ~5.3GB 가 7일 창 안의 대체된 main 캐시였다 — 이전 uv.lock
# 해시의 venv/uv-tool/uv-local-llm(~2.4GB), 이전 node/trivy, 그리고 main 커밋마다 하나씩 쌓이는
# CodeQL overlay base DB 50개(~2.9GB). 한도를 넘으면 GitHub 은 LRU 로 축출하므로 다음은 살아있는 캐시다.
#
# 계열 = 키에서 끝의 해시(lock 해시 · 커밋 sha) 또는 날짜를 뗀 것. 계열마다 가장 최근에 만든
# 1개를 남긴다(CodeQL overlay 는 PR 분석의 base 로 쓰일 수 있어 5개). 끝이 그런 꼴이 아닌 키
# (talib-0.4.0-…-v5 같은 고정 키)는 계열에 자기 하나뿐이라 지워지지 않는다. main 외 ref 는 조회도
# 하지 않는다 — PR ref 는 sweep_closed_pr_caches.sh 가 맡는다.
# Test: tests/scripts/test_prune_superseded_main_caches.py
set -euo pipefail

REPO="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

# 목록 조회가 실패하면 set -e 로 여기서 멈춘다 — 빈 목록으로 오인해 지나가지 않는다.
LIST=$(gh api --paginate "repos/${REPO}/actions/caches?per_page=100&ref=refs/heads/main" \
    --jq '.actions_caches[] | [.id, .key, .created_at] | @tsv')

STALE=$(printf '%s\n' "$LIST" | awk -F'\t' 'NF == 3' \
    | while IFS=$'\t' read -r ID KEY CREATED; do
        FAMILY=$(printf '%s' "$KEY" | sed -E 's/-([0-9a-f]{7,}|[0-9]{4}-[0-9]{2}-[0-9]{2})$//')
        printf '%s\t%s\t%s\n' "$FAMILY" "$CREATED" "$ID"
    done \
    | sort -t$'\t' -k1,1 -k2,2r \
    | awk -F'\t' '{ keep = ($1 ~ /^codeql-overlay-/) ? 5 : 1; if (++seen[$1] > keep) print $3 }')

DELETED=0
for ID in $STALE; do
    gh api -X DELETE "repos/${REPO}/actions/caches/${ID}"
    DELETED=$((DELETED + 1))
done
printf 'pruned %s superseded main cache(s)\n' "$DELETED"
