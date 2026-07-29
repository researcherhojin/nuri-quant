#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# Nuri-Quant Doc Count Verify (read-only)
# 문서의 수치 claim 이 코드 실측과 일치하는지 검증. drift 발견 시 exit 1.
# Pair: scripts/doc/sync_doc_counts.sh (mutator).
# Intended for CI — catches drift before merge.
# ═══════════════════════════════════════════════════════
set -euo pipefail

# shellcheck source=scripts/_common.sh
# (sourced via $(dirname "$0")/../_common.sh — moved to subdir)
source "$(dirname "$0")/../_common.sh"

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

# 2026-04-29: regime + DB-table counts. README claims "10 regimes (6 base + 4 special)"
# and "32 tables" were drift-prone (no code-truth verification). Backed by
# nuri.quant.regime.classifier.ALL_REGIMES tuple + live init_db sqlite_master count.
#
# CI contract preservation: this script must run in <1s with no Python env (per
# CI workflow comment "find + grep only"). When .venv/bin/python is absent
# (CI / fresh clone), these checks gracefully skip (return empty → check_claim
# emits warning, not failure). Local `make verify-doc-counts` catches drift.
live_regimes()      {
    [ -x .venv/bin/python ] || { echo ""; return; }
    .venv/bin/python -c \
        "from nuri.quant.regime.classifier import ALL_REGIMES; print(len(ALL_REGIMES))" 2>/dev/null || echo ""
}

live_db_tables()    {
    [ -x .venv/bin/python ] || { echo ""; return; }
    .venv/bin/python -c "
import tempfile, sqlite3
from pathlib import Path
from nuri.core.db import init_db
with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as _f:
    _p = _f.name
init_db(Path(_p))
print(sqlite3.connect(_p).execute(\"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'\").fetchone()[0])
" 2>/dev/null || echo ""
}

# 2026-07-08: migrations / scheduler jobs / rules.yaml lines — previously
# manual-tracked (silent drift; migration 44→45 slipped through #863). grep/wc
# based (no Python) so they HARD-GATE in CI, unlike regimes/db_tables above.
live_migrations()     { grep -cE '^        [0-9]+,$' nuri/core/db_migrations.py || true; }
live_scheduler_jobs() { grep -cE '"cron":' nuri/scheduler.py || true; }
live_rules_lines()    { wc -l < config/rules.yaml | tr -d ' '; }

# Extract the target integer from EVERY occurrence of a claim in a file.
# Strategy: match the claim's context substring, then take the LAST [0-9]+ in
# each match. Target numbers are consistently the rightmost digit run in each
# claim's phrasing (e.g., "Playwright E2E (6 spec files)" — the '2' in 'E2E' is
# ignored because 6 is last). One number per line of output.
#
# All occurrences, not just the first: a README states the same count in more
# than one place (mermaid node + stats table), and `head -1` verified only the
# first, leaving every later copy free to drift silently — a gate that reads as
# green while half the numbers it names are unchecked.
# Usage: extract_nums <file> <ctx_pattern>
extract_nums() {
    local file="$1" pattern="$2"
    [ ! -f "$file" ] && return
    grep -oE "$pattern" "$file" | while IFS= read -r m; do
        echo "$m" | grep -oE '[0-9]+' | tail -1
    done
}

# Check a claim at every site it appears. Returns 0 only if all agree.
check_claim() {
    local label="$1" expected="$2" file="$3" pattern="$4"
    local nums count bad
    nums=$(extract_nums "$file" "$pattern")
    if [ -z "$nums" ]; then
        warn "$label: pattern not found in $file — $pattern"
        return 1
    fi
    count=$(echo "$nums" | wc -l | tr -d ' ')
    bad=$(echo "$nums" | grep -vxF "$expected" | sort -u | paste -sd, - || true)
    if [ -z "$bad" ]; then
        if [ "$count" -gt 1 ]; then
            pass "$label ($file): $expected (${count} sites)"
        else
            pass "$label ($file): $expected"
        fi
        return 0
    else
        fail "$label ($file): doc=$bad, live=$expected — DRIFT (${count} sites checked)"
        return 1
    fi
}

banner "Doc Count Verify"

COLL=$(live_collectors)
EP=$(live_endpoints)
TFBE=$(live_test_files_be)
TFFE=$(live_test_files_fe)
E2E=$(live_e2e_specs)
REGIMES=$(live_regimes)
DBT=$(live_db_tables)
MIG=$(live_migrations)
JOBS=$(live_scheduler_jobs)
RULES=$(live_rules_lines)

# Claim checks: pattern must uniquely identify the phrase containing the target
# number. Target is always the LAST [0-9]+ in the matched substring.
check_claim "collectors"     "$COLL" ".claude/rules/architecture.md" '[0-9]+ collector modules' || true
check_claim "collectors"     "$COLL" "nuri/collectors/CLAUDE.md"  '[0-9]+ Data Collectors' || true
check_claim "collectors"     "$COLL" "README.md"                  '[0-9]+ collectors \(BaseCollector' || true
check_claim "endpoints"      "$EP"   ".claude/rules/architecture.md" '\([0-9]+ endpoints, routes/' || true
check_claim "endpoints"      "$EP"   "docs/ARCHITECTURE.md"       '## API \([0-9]+ endpoints\)' || true
check_claim "endpoints"      "$EP"   "docs/ARCHITECTURE.md"       '— [0-9]+ REST endpoints' || true
check_claim "endpoints"      "$EP"   "nuri/api/CLAUDE.md"         'read surface \([0-9]+ endpoints\)' || true
check_claim "test_files_be"  "$TFBE" "docs/ARCHITECTURE.md"       'backend tests across [0-9]+ files' || true
check_claim "test_files_be"  "$TFBE" "docs/STRATEGY.md"           'Backend tests.*tests, [0-9]+ files' || true
check_claim "test_files_be"  "$TFBE" "README.md"                  'collected across [0-9]+ files' || true
check_claim "test_files_fe"  "$TFFE" "docs/ARCHITECTURE.md"       'frontend vitest \([0-9]+ files\)' || true
check_claim "test_files_fe"  "$TFFE" "docs/STRATEGY.md"           'Frontend tests.*tests, [0-9]+ files' || true
check_claim "e2e_specs"      "$E2E"  "docs/ARCHITECTURE.md"       'Playwright E2E \([0-9]+ spec files\)' || true
# Python-dependent checks: skip silently when .venv absent (CI contract — see live_regimes comment)
if [ -n "$REGIMES" ]; then
    check_claim "regimes"    "$REGIMES" "README.md"                '· [0-9]+ regimes' || true
else
    info "regimes: skipped (no .venv/bin/python — local check via make verify-doc-counts)"
fi
if [ -n "$DBT" ]; then
    check_claim "db_tables"  "$DBT"  "README.md"                   'SQLite WAL · [0-9]+ tables' || true
else
    info "db_tables: skipped (no .venv/bin/python)"
fi
# grep/wc-based (no Python) — always run, including CI
check_claim "migrations"       "$MIG"   "README.md"            '[0-9]+ forward-only migrations' || true
# ARCHITECTURE 도 같은 수치를 적는데 게이트가 없어 조용히 갈렸다 (2026-07-30 실측 46 vs 49).
check_claim "migrations"       "$MIG"   "docs/ARCHITECTURE.md" '\([0-9]+ migrations as of' || true
check_claim "scheduler_jobs"   "$JOBS"  "docs/ARCHITECTURE.md" '[0-9]+ cron jobs in' || true
check_claim "rules_yaml_lines" "$RULES" "config/CLAUDE.md"     '\| [0-9]+ \| Investment rules' || true

# Note: agent count + pytest collect count intentionally excluded from hard
# verify. Agent count has no single stable grep pattern across docs (multiple
# phrasings "10-agent", "10 agents", "10개"), and pytest collect takes 30+s
# which would slow PR CI. Those are covered by sync_doc_counts.sh best-effort.

# 2026-07-08: doc integrity guard. Merge conflict markers were committed into
# docs/ARCHITECTURE.md and sat undetected — the count greps above still matched
# inside the conflict block, so this check stayed green. Hard-fail if any tracked
# .md carries a git conflict marker. (git grep = tracked files only; no git → skip.)
CONFLICTS=$(git grep -lE '^(<<<<<<<|>>>>>>>)' -- '*.md' 2>/dev/null || true)
if [ -n "$CONFLICTS" ]; then
    fail "merge conflict markers in tracked .md: $(echo "$CONFLICTS" | tr '\n' ' ')"
else
    pass "no merge conflict markers in tracked .md"
fi

summary
if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo -e "${RED}Doc drift detected. Run: bash scripts/doc/sync_doc_counts.sh${NC}"
    exit 1
fi
exit 0
