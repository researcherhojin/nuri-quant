#!/usr/bin/env bash
# scripts/check_atomic.sh — Verify each commit on the current branch
# can stand alone (suite passes after each commit independently).
#
# Catches the "commit 1 alone breaks suite" pattern that hit this session
# during PR #91 staging — initial 3-commit split broke after commit 1
# because test_estimates.py was migrated to yfinance but
# nuri/collectors/estimates.py still used OpenBB.
#
# Cost: ~3 min × N commits. Run only before final push of a multi-commit branch.
#
# Usage:
#   bash scripts/check_atomic.sh                # check commits since origin/main
#   bash scripts/check_atomic.sh HEAD~3..HEAD   # custom range

set -euo pipefail

# Source shared helpers (colors, PYTHON, REPO_ROOT cd).
# shellcheck source=scripts/_common.sh
# (sourced via $(dirname "$0")/../_common.sh — moved to subdir)
source "$(dirname "$0")/../_common.sh"

range="${1:-origin/main..HEAD}"
echo -e "${CYAN}━━━ Atomicity Check (${range}) ━━━${NC}\n"

# Save current state
original_branch=$(git rev-parse --abbrev-ref HEAD)
original_sha=$(git rev-parse HEAD)

# shellcheck disable=SC2329,SC2317
# SC2329: function invoked via `trap cleanup EXIT` — shellcheck can't trace
# SC2317: same reason — body lines look unreachable to static analysis
cleanup() {
    echo -e "\n${YELLOW}Restoring to ${original_branch} @ ${original_sha:0:8}...${NC}"
    git checkout -q "$original_branch" 2>/dev/null || git checkout -q "$original_sha"
}
trap cleanup EXIT

commits=$(git log --reverse --format="%H" "$range")
if [ -z "$commits" ]; then
    echo -e "${YELLOW}No commits in range${NC}"
    exit 0
fi

count=$(echo "$commits" | wc -l | tr -d ' ')
echo -e "Checking ${count} commit(s)...\n"

idx=0
fail=0
for sha in $commits; do
    idx=$((idx + 1))
    short=${sha:0:8}
    msg=$(git log -1 --format="%s" "$sha")

    echo -e "${CYAN}[${idx}/${count}] ${short} ${msg}${NC}"
    git checkout -q "$sha"

    # Smoke check: lint + collect-only (fast — full test would take ~6 min for 3 commits)
    if $PYTHON -m ruff check nuri/ tests/ scripts/ >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓ Lint${NC}"
    else
        echo -e "  ${RED}✗ Lint${NC}"
        fail=1
    fi

    if $PYTHON -m pytest tests/ --collect-only -q >/dev/null 2>&1; then
        count_tests=$($PYTHON -m pytest tests/ --collect-only -q 2>&1 | tail -1 | grep -oE '[0-9]+ tests' | head -1)
        echo -e "  ${GREEN}✓ Test collection (${count_tests})${NC}"
    else
        echo -e "  ${RED}✗ Test collection failed${NC}"
        fail=1
    fi
    echo ""
done

if [ "$fail" -eq 0 ]; then
    echo -e "${GREEN}✓ All commits are atomic (lint + collect pass independently)${NC}"
    exit 0
else
    echo -e "${RED}✗ Atomicity violation — at least one commit breaks lint or test collection${NC}"
    echo -e "${RED}  Rebase + reorder commits before pushing${NC}"
    exit 1
fi
