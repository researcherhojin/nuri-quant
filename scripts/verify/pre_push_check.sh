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
#   bash scripts/pre_push_check.sh           # full check (106s)
#   bash scripts/pre_push_check.sh --quick   # skip full test run (6s)
#   bash scripts/pre_push_check.sh --skip-tests   # lint + drift only

set -euo pipefail

# Source shared helpers (colors, PYTHON, REPO_ROOT cd).
# shellcheck source=scripts/_common.sh
# (sourced via $(dirname "$0")/../_common.sh — moved to subdir)
source "$(dirname "$0")/../_common.sh"

mode="${1:-full}"
fail=0

# `$PYTHON` 은 존재 확인 없는 경로다 (`_common.sh`). 인터프리터가 없으면 아래 python
# 단계들이 rc=127 로 죽는데, 각 단계의 `if` 는 그걸 그 단계의 **발견**으로 보고한다 —
# `.venv` 없는 clone 에서 "Personal financial data leak detected" 가 찍히지만 실제로는
# 스캐너가 한 번도 돈 적이 없다. 실패와 미실행이 구분 안 되는 형태(#910/#911)이고,
# 훅으로 돌면 이 거짓말이 곧 `--no-verify` 습관이 된다.
if ! "$PYTHON" -c '' > /dev/null 2>&1; then
    echo -e "${RED}✗ python 인터프리터 없음: ${PYTHON}${NC}" >&2
    echo -e "${RED}  검사를 하나도 실행하지 못했다 — '깨끗함' 이 아니라 '미확인' 이다.${NC}" >&2
    echo -e "${RED}  'make setup' 으로 venv 를 만들거나 PYTHON=... 로 지정할 것.${NC}" >&2
    echo -e "${RED}  우회: git push --no-verify${NC}" >&2
    exit 1
fi

echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Pre-Push Check (mode: ${mode})${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

# ─── 1. Drift check ─────────────────────────────────
echo -e "${YELLOW}━━━ 1. Drift Check ━━━${NC}"
if $PYTHON scripts/verify/check_drift.py --strict; then
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

# ─── 2b. Shell Lint (shellcheck) ─────────────────────────────────
# Local mirror of CI's `shell-lint` job. Added after PR #355 merged with a
# red Shell Lint check because I did not run shellcheck locally — this
# section prevents that class of recurrence (see memory
# feedback_ci_check_reading.md).
if command -v shellcheck > /dev/null 2>&1; then
    echo -e "${YELLOW}━━━ 2b. Shell Lint (shellcheck) ━━━${NC}"
    if find scripts -name '*.sh' -exec shellcheck --source-path=SCRIPTDIR --external-sources {} +; then
        echo -e "${GREEN}✓ Shell lint clean${NC}\n"
    else
        echo -e "${RED}✗ Shellcheck failed — mirrors CI job 'Shell Lint'${NC}\n"
        fail=1
    fi
else
    echo -e "${YELLOW}━━━ 2b. Shell Lint ━━━${NC}"
    echo -e "${YELLOW}⚠ shellcheck not installed — \`brew install shellcheck\`. CI will enforce.${NC}\n"
fi

# ─── 2c. Doc count drift ─────────────────────────────────
# Local mirror of CI's `doc-counts-verify` job. Catches drift between docs and
# live code (collectors/endpoints/test files/e2e specs) before push. Fast
# (<1s, find + grep only).
echo -e "${YELLOW}━━━ 2c. Doc Count Drift ━━━${NC}"
if bash scripts/verify/verify_doc_counts.sh > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Doc counts match live code${NC}\n"
else
    echo -e "${RED}✗ Doc drift detected — run \`make sync-doc-counts\` then amend commit${NC}"
    bash scripts/verify/verify_doc_counts.sh 2>&1 | grep -E "✗|DRIFT" | head -5
    echo ""
    fail=1
fi

# ─── 2d. Spellcheck + pyright ratchet (#1086) ─────────────────────────────
# `make diagnostics` 는 이미 존재했지만 **어떤 게이트도 부르지 않아** 이 진단은
# 에디터에만 떴다. 2026-08-18 에 사용자가 Pylance/cSpell 경고를 직접 붙여넣어야 했고,
# 그중 하나는 그 직전 머지가 만든 새 경고였다. 사용자가 할 일이 아니라 게이트가 할 일이다.
#
# 성격이 달라 게이트도 다르게 건다:
#   - cspell  : 결정론적이고 잔여 0건 → **하드 게이트** (전체 스캔)
#   - pyright : 172건 소음 바닥 → **이번 변경이 추가한 줄만** (기존 오류는 대상 아님)
# 처음엔 총합 baseline 래칫이었는데, 손으로 유지하는 숫자는 낡고 낡으면 게이트가
# 조용히 느슨해진다 — 그래서 상태 없는 diff 스코핑으로 바꿨다 (#1088).
# .py 를 안 건드리는 push 는 pyright 를 아예 안 돈다.
if command -v npx > /dev/null 2>&1; then
    echo -e "${YELLOW}━━━ 2d. Spellcheck ━━━${NC}"
    if $PYTHON -c '' > /dev/null 2>&1 && make spellcheck 2>&1 | grep -q "Unknown word"; then
        echo -e "${RED}✗ 미등록 단어 — 도메인 용어면 .cspell.json 에 추가, 오타면 고칠 것${NC}"
        make spellcheck 2>&1 | grep "Unknown word" | head -5
        echo ""
        fail=1
    else
        echo -e "${GREEN}✓ Spellcheck clean${NC}\n"
    fi

    echo -e "${YELLOW}━━━ 2e. Pyright (changed lines) ━━━${NC}"
    if $PYTHON scripts/verify/check_pyright_diff.py; then
        echo ""
    else
        echo ""
        fail=1
    fi
else
    echo -e "${YELLOW}━━━ 2d/2e. Diagnostics ━━━${NC}"
    echo -e "${YELLOW}⚠ npx 없음 — cspell/pyright 를 못 돌렸다 (‘깨끗함’ 아님). Node.js 설치 권장.${NC}\n"
fi

# ─── 3. Tests (skipped in --skip-tests) ─────────────────────────────────
if [ "$mode" != "--skip-tests" ]; then
    echo -e "${YELLOW}━━━ 3. Tests (CI parity) ━━━${NC}"
    if [ "$mode" == "--quick" ]; then
        echo -e "  ${YELLOW}Mode: quick (smoke only)${NC}"
        if bash scripts/dev/ci_local.sh --quick; then
            echo -e "${GREEN}✓ Smoke tests pass${NC}\n"
        else
            echo -e "${RED}✗ Smoke tests failed${NC}\n"
            fail=1
        fi
    else
        echo -e "  ${YELLOW}Mode: full (106s, exact CI command)${NC}"
        if bash scripts/dev/ci_local.sh; then
            echo -e "${GREEN}✓ Full test parity passed${NC}\n"
        else
            echo -e "${RED}✗ Tests failed — fix before pushing${NC}\n"
            fail=1
        fi
    fi
fi

# ─── 4. Privacy leak scan (#138) ─────────────────────────────────
echo -e "${YELLOW}━━━ 4. Privacy Leak Scan (files) ━━━${NC}"
if $PYTHON scripts/verify/check_privacy_leak.py --quiet; then
    echo -e "${GREEN}✓ No personal financial data leaks in tracked files${NC}\n"
else
    echo -e "${RED}✗ Personal financial data leak detected — see above${NC}"
    echo -e "${RED}  See docs/STRATEGY.md §4.4 for the privacy enforcement rules.${NC}\n"
    fail=1
fi

# ─── 4b. Unpushed commit messages (ticker+PnL, PR #202 class) ──────
echo -e "${YELLOW}━━━ 4b. Commit Message Privacy Scan ━━━${NC}"
if $PYTHON scripts/verify/check_privacy_leak.py --unpushed-commits --quiet; then
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
