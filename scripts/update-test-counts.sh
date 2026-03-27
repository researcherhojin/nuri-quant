#!/bin/bash
# ═══════════════════════════════════════════════════════
# Nuri-Quant Test Count Updater
# README.md 배지의 테스트 수를 자동 업데이트
# ═══════════════════════════════════════════════════════
set -e
cd "$(dirname "$0")/.."

PYTHON=${PYTHON:-.venv/bin/python}

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
    echo "Failed to extract test count"
    exit 1
fi

echo "Test count: $TEST_COUNT"

# README 업데이트
OLD_BADGE=$(grep -oE 'Tests-[0-9]+_passed' README.md | head -1)
NEW_BADGE="Tests-${TEST_COUNT}_passed"

if [ "$OLD_BADGE" != "$NEW_BADGE" ]; then
    sedi "s/$OLD_BADGE/$NEW_BADGE/g" README.md
    echo "Updated README: $OLD_BADGE → $NEW_BADGE"

    # CLAUDE.md 업데이트
    OLD_CMD=$(grep -oE 'pytest tests.*\([0-9]+ tests\)' CLAUDE.md | head -1)
    if [ -n "$OLD_CMD" ]; then
        NEW_CMD=$(echo "$OLD_CMD" | sed "s/[0-9]* tests/$TEST_COUNT tests/")
        sedi "s|$OLD_CMD|$NEW_CMD|g" CLAUDE.md
        echo "Updated CLAUDE.md: $TEST_COUNT tests"
    fi
else
    echo "No change needed ($TEST_COUNT tests)"
fi
