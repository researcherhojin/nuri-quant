#!/bin/bash
# ═══════════════════════════════════════════════════════
# Nuri-Quant Test Count Updater
# README badge + CLAUDE.md test count 자동 업데이트
# ═══════════════════════════════════════════════════════
set -e

# Source shared helpers (PYTHON, REPO_ROOT cd, colors).
source "$(dirname "$0")/_common.sh"

# Cross-platform sed -i
sedi() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "$@"
    else
        sed -i "$@"
    fi
}

# 테스트 수 추출
echo "Running pytest..."
TEST_OUTPUT=$($PYTHON -m pytest tests/ -q --tb=no 2>&1 | tail -1)
TEST_COUNT=$(echo "$TEST_OUTPUT" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+')

if [ -z "$TEST_COUNT" ]; then
    echo -e "${RED}Failed to extract test count${NC}"
    exit 1
fi

# 파일 수 (CLAUDE.md numeric claim 동기화용)
FILE_COUNT=$(find tests -name "test_*.py" -type f | wc -l | tr -d ' ')

echo "Test count: $TEST_COUNT  |  File count: $FILE_COUNT"

# README 업데이트
OLD_BADGE=$(grep -oE 'Tests-[0-9]+_passed' README.md | head -1)
NEW_BADGE="Tests-${TEST_COUNT}_passed"
README_CHANGED=0

if [ -n "$OLD_BADGE" ] && [ "$OLD_BADGE" != "$NEW_BADGE" ]; then
    sedi "s/$OLD_BADGE/$NEW_BADGE/g" README.md
    echo -e "${GREEN}Updated README badge: $OLD_BADGE → $NEW_BADGE${NC}"
    README_CHANGED=1
fi

# CLAUDE.md 업데이트 — 새 형식 매칭
# Pattern: "<NUM> backend tests across <NUM> files" (Testing 섹션 한 줄)
CLAUDE_PATTERN='[0-9,]+ backend tests across [0-9]+ files'
OLD_CLAUDE=$(grep -oE "$CLAUDE_PATTERN" CLAUDE.md | head -1)

# 콤마 포함한 표시 형식 (e.g., 2,253)
TEST_DISPLAY=$(printf "%'d" "$TEST_COUNT" 2>/dev/null || echo "$TEST_COUNT")
NEW_CLAUDE="${TEST_DISPLAY} backend tests across ${FILE_COUNT} files"
CLAUDE_CHANGED=0

if [ -n "$OLD_CLAUDE" ] && [ "$OLD_CLAUDE" != "$NEW_CLAUDE" ]; then
    sedi "s|$OLD_CLAUDE|$NEW_CLAUDE|g" CLAUDE.md
    echo -e "${GREEN}Updated CLAUDE.md: $OLD_CLAUDE → $NEW_CLAUDE${NC}"
    CLAUDE_CHANGED=1
fi

if [ "$README_CHANGED" -eq 0 ] && [ "$CLAUDE_CHANGED" -eq 0 ]; then
    echo -e "${CYAN}No changes — already in sync ($TEST_COUNT tests, $FILE_COUNT files)${NC}"
fi
