#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# Nuri-Quant Doc Count Sync
# 문서의 수치 claim 을 코드 실측으로 동기화.
# Covers: collectors, endpoints, backend/frontend test files, e2e specs, pytest count.
# Pair: scripts/verify_doc_counts.sh (read-only CI gate).
# ═══════════════════════════════════════════════════════
set -euo pipefail

# shellcheck source=scripts/_common.sh
source "$(dirname "$0")/_common.sh"

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

live_test_files_fe() { find frontend -name "*.test.ts" -o -name "*.test.tsx" 2>/dev/null \
    | grep -v node_modules | wc -l | tr -d ' '; }

live_e2e_specs()    { find frontend/e2e -name "*.spec.ts" 2>/dev/null \
    | grep -v node_modules | wc -l | tr -d ' '; }

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
    current=$(grep -oE "$pattern" "$file" | head -1)
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

# Collectors (3 sites)
update_claim live_collectors     CLAUDE.md                     '[0-9]+ collector modules'
update_claim live_collectors     nuri/collectors/CLAUDE.md     '[0-9]+ Data Collectors'
update_claim live_collectors     README.md                     '[0-9]+ collectors \(BaseCollector'

# Endpoints (3 sites)
update_claim live_endpoints      CLAUDE.md                     '\([0-9]+ endpoints, routes/'
update_claim live_endpoints      docs/ARCHITECTURE.md          '## API \([0-9]+ endpoints\)'
update_claim live_endpoints      docs/ARCHITECTURE.md          '— [0-9]+ REST endpoints'

# Backend test files (2 sites)
update_claim live_test_files_be  docs/ARCHITECTURE.md          'backend tests across [0-9]+ files'
update_claim live_test_files_be  docs/STRATEGY.md              'Backend tests.*tests, [0-9]+ files'

# Frontend test files (2 sites)
update_claim live_test_files_fe  docs/ARCHITECTURE.md          'frontend vitest \([0-9]+ files\)'
update_claim live_test_files_fe  docs/STRATEGY.md              'Frontend tests.*tests, [0-9]+ files'

# E2E specs (1 site)
update_claim live_e2e_specs      docs/ARCHITECTURE.md          'Playwright E2E \([0-9]+ spec files\)'

# Pytest collect count — runs pytest which is slow; do last so failures above
# don't waste the call. Updates any "[0-9,]+ backend tests" / "[0-9,]+ tests,"
# phrase where the number has a thousands-comma format.
TESTS_BE=$(live_tests_be || echo "")
if [ -n "$TESTS_BE" ]; then
    TESTS_DISPLAY=$(printf "%'d" "$TESTS_BE" 2>/dev/null || echo "$TESTS_BE")

    update_comma_number() {
        local file="$1" pattern="$2"
        [ ! -f "$file" ] && return
        local current new
        current=$(grep -oE "$pattern" "$file" | head -1)
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

    # STRATEGY.md Backend row also contains "1%" before "2,993 tests"; narrow
    # pattern to the "X,YYY tests, NN files |" suffix so "1%" isn't clobbered.
    update_comma_number docs/ARCHITECTURE.md '[0-9,]+ backend tests across'
    update_comma_number docs/STRATEGY.md     '[0-9,]+ tests, [0-9]+ files \|'
    update_comma_number README.md            '\([0-9,]+ backend \+'
fi

echo ""
if [ "$FAILED" -gt 0 ]; then
    echo -e "${YELLOW}$FAILED claim(s) could not be processed. Manifest may be out of date.${NC}"
fi
if [ "$CHANGED" -eq 0 ]; then
    echo -e "${CYAN}All doc counts already in sync.${NC}"
else
    echo -e "${GREEN}Updated $CHANGED location(s). Review the diff before committing.${NC}"
fi
exit 0
