#!/usr/bin/env bash
# scripts/pre_push_check.sh — Sanity check before pushing.
#
# Catches the failure modes that hit this session:
# 1. Drift between working tree and committed state
# 2. Lint failures that pass locally with stale config
# 3. Test failures that only show up in CI (parallelism, ordering)
# 4. Massive uncommitted file count (>20 = high drift risk)
#
# Usage:
#   bash scripts/pre_push_check.sh           # full check (~2 min)
#   bash scripts/pre_push_check.sh --quick   # skip full test run (~30s)
#   bash scripts/pre_push_check.sh --skip-tests   # lint + drift only

set -euo pipefail

# Source shared helpers (colors, PYTHON, REPO_ROOT cd).
# shellcheck source=scripts/_common.sh
source "$(dirname "$0")/_common.sh"

mode="${1:-full}"
fail=0

echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Pre-Push Check (mode: ${mode})${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

# ─── 1. Drift check ─────────────────────────────────
echo -e "${YELLOW}━━━ 1. Drift Check ━━━${NC}"
if $PYTHON scripts/check_drift.py --strict; then
    echo -e "${GREEN}✓ No drift risk${NC}\n"
else
    echo -e "${RED}✗ Drift risk detected — see analysis above${NC}"
    echo -e "${RED}  This is the #1 cause of 'passes locally / fails CI' issues.${NC}\n"
    fail=1
fi

# ─── 2. Lint ─────────────────────────────────
echo -e "${YELLOW}━━━ 2. Lint (ruff check) ━━━${NC}"
if $PYTHON -m ruff check nuri/ tests/ scripts/; then
    echo -e "${GREEN}✓ Lint clean${NC}\n"
else
    echo -e "${RED}✗ Lint failed${NC}\n"
    fail=1
fi

# ─── 3. Tests (skipped in --skip-tests) ─────────────────────────────────
if [ "$mode" != "--skip-tests" ]; then
    echo -e "${YELLOW}━━━ 3. Tests (CI parity) ━━━${NC}"
    if [ "$mode" == "--quick" ]; then
        echo -e "  ${YELLOW}Mode: quick (smoke only)${NC}"
        if bash scripts/ci_local.sh --quick; then
            echo -e "${GREEN}✓ Smoke tests pass${NC}\n"
        else
            echo -e "${RED}✗ Smoke tests failed${NC}\n"
            fail=1
        fi
    else
        echo -e "  ${YELLOW}Mode: full (~2 min, exact CI command)${NC}"
        if bash scripts/ci_local.sh; then
            echo -e "${GREEN}✓ Full test parity passed${NC}\n"
        else
            echo -e "${RED}✗ Tests failed — fix before pushing${NC}\n"
            fail=1
        fi
    fi
fi

# ─── 4. Privacy leak scan (#138) ─────────────────────────────────
echo -e "${YELLOW}━━━ 4. Privacy Leak Scan (files) ━━━${NC}"
if $PYTHON scripts/check_privacy_leak.py --quiet; then
    echo -e "${GREEN}✓ No personal financial data leaks in tracked files${NC}\n"
else
    echo -e "${RED}✗ Personal financial data leak detected — see above${NC}"
    echo -e "${RED}  See docs/STRATEGY.md §4.4 for the privacy enforcement rules.${NC}\n"
    fail=1
fi

# ─── 4b. Unpushed commit messages (ticker+PnL, PR #202 class) ──────
echo -e "${YELLOW}━━━ 4b. Commit Message Privacy Scan ━━━${NC}"
if $PYTHON scripts/check_privacy_leak.py --unpushed-commits --quiet; then
    echo -e "${GREEN}✓ No ticker+PnL leaks in unpushed commit messages${NC}\n"
else
    echo -e "${RED}✗ Ticker + PnL disclosure detected in a commit message${NC}"
    echo -e "${RED}  Once pushed, this enters git history permanently (see PR #202).${NC}"
    echo -e "${RED}  Amend the commit: git commit --amend  (or interactive rebase).${NC}\n"
    fail=1
fi

# ─── 5. Conventional commit check (latest commit only) ───────────────
echo -e "${YELLOW}━━━ 5. Latest Commit Message Format ━━━${NC}"
last_msg=$(git log -1 --no-merges --format="%s" 2>/dev/null || echo "")
TYPE='(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)'
SCOPE='(\([^)]+\))?'
PATTERN="^${TYPE}${SCOPE}(\+${TYPE}${SCOPE})*: .+"
if echo "$last_msg" | grep -qE "$PATTERN"; then
    echo -e "${GREEN}✓ Conventional commit format OK${NC}"
    echo -e "  ${last_msg}\n"
else
    echo -e "${YELLOW}⚠ Last commit doesn't match conventional format:${NC}"
    echo -e "  ${last_msg}"
    echo -e "  ${YELLOW}Expected: type(scope): message${NC}\n"
fi

# ─── Summary ─────────────────────────────────
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
if [ "$fail" -eq 0 ]; then
    echo -e "${GREEN}  ✓ ALL CHECKS PASSED — safe to push${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    exit 0
else
    echo -e "${RED}  ✗ FAILED — fix issues before pushing${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    exit 1
fi
