#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# Nuri-Quant Doc Count Sync
# 문서의 수치 claim 을 코드 실측으로 동기화.
# Covers: collectors, endpoints, backend/frontend test files, e2e specs, pytest count.
# Pair: scripts/verify_doc_counts.sh (read-only CI gate).
# ═══════════════════════════════════════════════════════
# All live_* functions are dispatched indirectly via $("$live_fn") in
# update_claim — shellcheck 0.10 cannot trace dynamic dispatch, so disable
# the false-positive "never invoked / unreachable" warnings file-wide.
# shellcheck disable=SC2317,SC2329
set -euo pipefail

# shellcheck source=scripts/_common.sh
# (sourced via $(dirname "$0")/../_common.sh — moved to subdir)
source "$(dirname "$0")/../_common.sh"

# Cross-platform sed -i
sedi() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "$@"
    else
        sed -i "$@"
    fi
}

# ─── 실측 count (verify_doc_counts.sh 와 동일) ──────────
live_collectors()   { find nuri/collectors -maxdepth 1 -name "*.py" \
    ! -name "__init__.py" ! -name "base.py" -type f | wc -l | tr -d ' '; }

live_agents()       { find nuri/trading/agents -maxdepth 1 -name "*.py" \
    ! -name "__init__.py" ! -name "base.py" \
    ! -name "consensus.py" ! -name "learning_memory.py" -type f | wc -l | tr -d ' '; }

live_endpoints()    { grep -rhE '@router\.(get|post|put|delete|patch)' \
    nuri/api/routes/ | wc -l | tr -d ' '; }

live_test_files_be() { find tests -name "test_*.py" -type f | wc -l | tr -d ' '; }

live_test_files_fe() { find frontend \( -name "*.test.ts" -o -name "*.test.tsx" \) \
    ! -path '*/node_modules/*' 2>/dev/null | wc -l | tr -d ' '; }

live_e2e_specs()    { find frontend/e2e -name "*.spec.ts" \
    ! -path '*/node_modules/*' 2>/dev/null | wc -l | tr -d ' '; }

# 2026-04-29: regime + DB-table counts (mirrors verify_doc_counts.sh additions).
live_regimes()      { .venv/bin/python -c \
    "from nuri.quant.regime.classifier import ALL_REGIMES; print(len(ALL_REGIMES))" 2>/dev/null; }

live_db_tables()    { .venv/bin/python -c "
import tempfile, sqlite3
from pathlib import Path
from nuri.core.db import init_db
with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as _f:
    _p = _f.name
init_db(Path(_p))
print(sqlite3.connect(_p).execute(\"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'\").fetchone()[0])
" 2>/dev/null; }

# verify_doc_counts.sh 와 동일 정의 — 두 스크립트의 claim 목록이 갈라지면
# 게이트가 잡은 drift 를 이 스크립트가 못 고치는 상태가 된다 (#916 의 본질).
# tests/verify/test_doc_claim_parity.py 가 두 목록의 포함관계를 잠근다.
live_migrations()     { grep -cE '^        [0-9]+,$' nuri/core/db_migrations.py || true; }
live_scheduler_jobs() { grep -cE '"cron":' nuri/scheduler.py || true; }
live_rules_lines()    { wc -l < config/rules.yaml | tr -d ' '; }

live_tests_be() {
    $PYTHON -m pytest tests/ --collect-only -q 2>/dev/null \
        | grep -oE '[0-9]+/[0-9]+ tests collected' \
        | head -1 | awk -F'/' '{print $2}' | awk '{print $1}'
}

CHANGED=0
FAILED=0

# update_claim <live_fn> <file> <context_pattern>
# context_pattern must uniquely match the phrase; target number is the LAST
# [0-9]+ in the match (same semantics as verify_doc_counts.sh).
update_claim() {
    local live_fn="$1" file="$2" pattern="$3"
    local expected current new_match
    expected=$("$live_fn")
    if [ -z "$expected" ]; then
        warn "$live_fn returned empty — $file skipped"
        FAILED=$((FAILED + 1))
        return
    fi
    if [ ! -f "$file" ]; then
        warn "$file not found — skipped"
        return
    fi
    # `|| true` 없으면 set -e 가 여기서 스크립트를 죽여, 바로 아래 warn 분기가
    # 영영 실행되지 않는다 (#916). 그 상태로 이 스크립트는 배너만 찍고 exit 1 했다.
    current=$(grep -oE "$pattern" "$file" | head -1 || true)
    if [ -z "$current" ]; then
        warn "$file: pattern not found — $pattern"
        FAILED=$((FAILED + 1))
        return
    fi
    # Swap the LAST integer in the match with expected
    new_match=$(echo "$current" | sed -E "s/([^0-9])[0-9]+([^0-9]*)$/\1$expected\2/")
    # Fallback: if the number was at the very start of the match (rare)
    if [ "$new_match" = "$current" ]; then
        new_match=$(echo "$current" | sed -E "s/^[0-9]+/$expected/")
    fi
    if [ "$current" = "$new_match" ]; then
        info "$file: already in sync ($expected)"
        return
    fi
    # Escape sed delimiter and metacharacters for safe substitution
    local esc_old esc_new
    # BRE escape: metachars are . * ^ $ [ ] \ (NOT ( ) which are literal in BRE)
    esc_old=$(printf '%s' "$current" | sed -e 's/[][\.\*\^\$\\/]/\\&/g')
    esc_new=$(printf '%s' "$new_match" | sed -e 's/[\/&\\]/\\&/g')
    sedi "s/$esc_old/$esc_new/" "$file"
    pass "$file: $current → $new_match"
    CHANGED=$((CHANGED + 1))
}

banner "Doc Count Sync"

# Collectors (3 sites) — CLAUDE.md 가 .claude/rules/ 로 분할되며 이사함 (#916)
update_claim live_collectors     .claude/rules/architecture.md '[0-9]+ collector modules'
update_claim live_collectors     nuri/collectors/CLAUDE.md     '[0-9]+ Data Collectors'
update_claim live_collectors     README.md                     '[0-9]+ collectors \(BaseCollector'

# Endpoints (4 sites)
update_claim live_endpoints      .claude/rules/architecture.md '\([0-9]+ endpoints, routes/'
update_claim live_endpoints      docs/ARCHITECTURE.md          '## API \([0-9]+ endpoints\)'
update_claim live_endpoints      docs/ARCHITECTURE.md          '— [0-9]+ REST endpoints'
update_claim live_endpoints      nuri/api/CLAUDE.md            'read surface \([0-9]+ endpoints\)'

# Backend test files (2 sites)
update_claim live_test_files_be  docs/ARCHITECTURE.md          'backend tests across [0-9]+ files'
update_claim live_test_files_be  docs/STRATEGY.md              'Backend tests.*tests, [0-9]+ files'
update_claim live_test_files_be  README.md                     'collected across [0-9]+ files'

# Frontend test files (2 sites)
update_claim live_test_files_fe  docs/ARCHITECTURE.md          'frontend vitest \([0-9]+ files\)'
update_claim live_test_files_fe  docs/STRATEGY.md              'Frontend tests.*tests, [0-9]+ files'

# E2E specs (1 site)
update_claim live_e2e_specs      docs/ARCHITECTURE.md          'Playwright E2E \([0-9]+ spec files\)'

update_claim live_regimes        README.md                     '· [0-9]+ regimes'
update_claim live_db_tables      README.md                     'SQLite WAL · [0-9]+ tables'

# grep/wc 기반 — verify 가 하드 게이트하는데 sync 에는 없어서, 이 셋이 drift 하면
# 게이트가 빨간불인 채 고칠 방법이 없었다 (#916).
update_claim live_migrations     README.md                     '[0-9]+ forward-only migrations'
# ARCHITECTURE 도 같은 수치를 적는데 등록이 안 돼 있었다 — 2026-07-30 실측 46 vs 실제 49.
update_claim live_migrations     docs/ARCHITECTURE.md          '\([0-9]+ migrations as of'
update_claim live_scheduler_jobs docs/ARCHITECTURE.md          '[0-9]+ cron jobs in'
# README 아키텍처 다이어그램도 같은 수치를 적는데 등록이 안 돼 있었다 — 2026-08-03 실측
# 48 vs 실제 49 (data_sanity 추가분). ARCHITECTURE 만 보던 것과 같은 누락 패턴.
update_claim live_scheduler_jobs README.md                     '[0-9]+ cron jobs · in-process'
update_claim live_rules_lines    config/CLAUDE.md              '\| [0-9]+ \| Investment rules'

# Pytest collect count — runs pytest which is slow; do last so failures above
# don't waste the call. Updates any "[0-9,]+ backend tests" / "[0-9,]+ tests,"
# phrase where the number has a thousands-comma format.
#
# NOTE (codex P3, 2026-04-17): README line "(2,993 backend + 917 frontend +
# 39 e2e)" only has the backend number auto-synced. Frontend "917 tests" and
# e2e "39 tests" are TEST counts (not file counts), so syncing them would
# require running `npm exec vitest` + `npx playwright test --list` — both
# slow and requiring a full npm install. Left unmanaged: if those change,
# update README manually for now. File counts (60 / 6) are still covered.
TESTS_BE=$(live_tests_be || echo "")
if [ -n "$TESTS_BE" ]; then
    # Portable thousands separator — `printf "%'d"` depends on LC_NUMERIC
    # which is often unset on Ubuntu CI (→ would yield "2993" and produce
    # spurious Mac↔Linux diffs). Use sed-based grouping (BSD/GNU compatible).
    # Pattern anchors at (,|$) so re-invocation via `ta` stops once every
    # triplet is grouped. Separate -e flags required (BSD sed rejects `;`
    # between label/branch commands).
    TESTS_DISPLAY=$(echo "$TESTS_BE" \
        | sed -E -e ':a' -e 's/([0-9])([0-9]{3})(,|$)/\1,\2\3/' -e 'ta')

    update_comma_number() {
        local file="$1" pattern="$2"
        [ ! -f "$file" ] && return
        local current new
        current=$(grep -oE "$pattern" "$file" | head -1 || true)   # set -e 가드 (#916)
        [ -z "$current" ] && return
        new=$(echo "$current" | sed -E "s/[0-9,]+/$TESTS_DISPLAY/")
        if [ "$current" = "$new" ]; then
            info "$file: tests count already $TESTS_DISPLAY"
            return
        fi
        local esc_old esc_new
        esc_old=$(printf '%s' "$current" | sed -e 's/[][\.\*\^\$\\/]/\\&/g')
        esc_new=$(printf '%s' "$new" | sed -e 's/[\/&\\]/\\&/g')
        sedi "s/$esc_old/$esc_new/" "$file"
        pass "$file: $current → $new"
        CHANGED=$((CHANGED + 1))
    }

    # 패턴은 두 조건을 동시에 만족해야 한다: (a) 대상 행을 고유하게 집을 것,
    # (b) 매치 문자열의 **첫** 숫자 런이 바꿀 숫자일 것 — sed 가 첫 런을 치환한다.
    #   · 옛 '[0-9,]+ tests, [0-9]+ files \|' 은 (b)는 만족하나 (a) 실패:
    #     바로 아래 Frontend 행에도 매치해 head -1 이 그쪽을 집었고, 프론트 수치를
    #     백엔드 수치로 덮어썼다 (#916 복구 직후 실측: 1449 → 6,417).
    #   · 'Backend tests.*[0-9,]+ tests' 로 넓히면 (a)는 되나 (b) 실패:
    #     첫 숫자 런이 같은 행의 "Codecov 1%" 라 1% 가 파괴된다.
    # 뒤따르는 '(statement' 로 Backend 행을 식별하면 둘 다 만족한다 (Frontend 행에는 없음).
    update_comma_number docs/ARCHITECTURE.md '[0-9,]+ backend tests across'
    update_comma_number docs/STRATEGY.md     '[0-9,]+ tests, [0-9]+ files \(statement'
    update_comma_number README.md            '[0-9,]+ collected across'
fi

echo ""
if [ "$FAILED" -gt 0 ]; then
    echo -e "${RED}$FAILED claim(s) could not be processed — the manifest above points at text that no longer exists.${NC}"
    echo -e "${RED}Fix the target list in this script; a stale entry means that claim is no longer auto-synced.${NC}"
    exit 1
fi
if [ "$CHANGED" -eq 0 ]; then
    echo -e "${CYAN}All doc counts already in sync.${NC}"
else
    echo -e "${GREEN}Updated $CHANGED location(s). Review the diff before committing.${NC}"
fi
exit 0
