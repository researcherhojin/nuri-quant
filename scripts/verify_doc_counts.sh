#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# Nuri-Quant Doc Count Verify (read-only)
# 문서의 수치 claim 이 코드 실측과 일치하는지 검증. drift 발견 시 exit 1.
# Pair: scripts/sync_doc_counts.sh (mutator).
# Intended for CI — catches drift before merge.
# ═══════════════════════════════════════════════════════
set -euo pipefail

# shellcheck source=scripts/_common.sh
source "$(dirname "$0")/_common.sh"

# ─── 실측 count 함수 (sync_doc_counts.sh 와 동일 — self-contained) ──
live_collectors()   { find nuri/collectors -maxdepth 1 -name "*.py" \
    ! -name "__init__.py" ! -name "base.py" -type f | wc -l | tr -d ' '; }

live_endpoints()    { grep -rhE '@router\.(get|post|put|delete|patch)' \
    nuri/api/routes/ | wc -l | tr -d ' '; }

live_test_files_be() { find tests -name "test_*.py" -type f | wc -l | tr -d ' '; }

live_test_files_fe() { find frontend \( -name "*.test.ts" -o -name "*.test.tsx" \) \
    ! -path '*/node_modules/*' 2>/dev/null | wc -l | tr -d ' '; }

live_e2e_specs()    { find frontend/e2e -name "*.spec.ts" \
    ! -path '*/node_modules/*' 2>/dev/null | wc -l | tr -d ' '; }

# Extract the target integer from a file.
# Strategy: match the claim's context substring (must be unique in the file),
# then take the LAST [0-9]+ in that substring. Target numbers are consistently
# the rightmost digit run in each claim's phrasing (e.g., "Playwright E2E
# (6 spec files)" — the '2' in 'E2E' is ignored because 6 is last).
# Usage: extract_num <file> <ctx_pattern>
extract_num() {
    local file="$1" pattern="$2"
    [ ! -f "$file" ] && { echo ""; return; }
    grep -oE "$pattern" "$file" | head -1 | grep -oE '[0-9]+' | tail -1
}

# Check a single claim. Returns 0 if match, 1 if drift.
check_claim() {
    local label="$1" expected="$2" file="$3" pattern="$4"
    local actual
    actual=$(extract_num "$file" "$pattern")
    if [ -z "$actual" ]; then
        warn "$label: pattern not found in $file — $pattern"
        return 1
    fi
    if [ "$actual" = "$expected" ]; then
        pass "$label ($file): $actual"
        return 0
    else
        fail "$label ($file): doc=$actual, live=$expected — DRIFT"
        return 1
    fi
}

banner "Doc Count Verify"

COLL=$(live_collectors)
EP=$(live_endpoints)
TFBE=$(live_test_files_be)
TFFE=$(live_test_files_fe)
E2E=$(live_e2e_specs)

# Claim checks: pattern must uniquely identify the phrase containing the target
# number. Target is always the LAST [0-9]+ in the matched substring.
check_claim "collectors"     "$COLL" "CLAUDE.md"                  '[0-9]+ collector modules' || true
check_claim "collectors"     "$COLL" "nuri/collectors/CLAUDE.md"  '[0-9]+ Data Collectors' || true
check_claim "collectors"     "$COLL" "README.md"                  '[0-9]+ collectors \(BaseCollector' || true
check_claim "endpoints"      "$EP"   "CLAUDE.md"                  '\([0-9]+ endpoints, routes/' || true
check_claim "endpoints"      "$EP"   "docs/ARCHITECTURE.md"       '## API \([0-9]+ endpoints\)' || true
check_claim "endpoints"      "$EP"   "docs/ARCHITECTURE.md"       '— [0-9]+ REST endpoints' || true
check_claim "test_files_be"  "$TFBE" "docs/ARCHITECTURE.md"       'backend tests across [0-9]+ files' || true
check_claim "test_files_be"  "$TFBE" "docs/STRATEGY.md"           'Backend tests.*tests, [0-9]+ files' || true
check_claim "test_files_fe"  "$TFFE" "docs/ARCHITECTURE.md"       'frontend vitest \([0-9]+ files\)' || true
check_claim "test_files_fe"  "$TFFE" "docs/STRATEGY.md"           'Frontend tests.*tests, [0-9]+ files' || true
check_claim "e2e_specs"      "$E2E"  "docs/ARCHITECTURE.md"       'Playwright E2E \([0-9]+ spec files\)' || true

# Note: agent count + pytest collect count intentionally excluded from hard
# verify. Agent count has no single stable grep pattern across docs (multiple
# phrasings "10-agent", "10 agents", "10개"), and pytest collect takes 30+s
# which would slow PR CI. Those are covered by sync_doc_counts.sh best-effort.

summary
if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo -e "${RED}Doc drift detected. Run: bash scripts/sync_doc_counts.sh${NC}"
    exit 1
fi
exit 0
