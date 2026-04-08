#!/usr/bin/env bash
# scripts/ci_local.sh — Run the EXACT command CI runs, locally.
#
# Purpose: prevent the "passes locally / fails CI" pattern.
# This session lost ~30 minutes to drift bugs because local pytest
# used different flags than CI's `-n auto --cov`.
#
# Usage:
#   bash scripts/ci_local.sh           # full backend test parity
#   bash scripts/ci_local.sh --lint    # lint only (10s)
#   bash scripts/ci_local.sh --quick   # smoke test (~30s)

set -e

# Source shared helpers (colors, PYTHON, REPO_ROOT cd).
source "$(dirname "$0")/_common.sh"

mode="${1:-full}"

echo -e "${YELLOW}━━━ CI Parity Check (${mode}) ━━━${NC}"

case "$mode" in
    --lint)
        # CI: backend-lint job — uses astral-sh/ruff-action@v3
        echo -e "${YELLOW}Running: ruff check nuri/ tests/ scripts/${NC}"
        $PYTHON -m ruff check nuri/ tests/ scripts/
        echo -e "${GREEN}✓ Lint OK${NC}"
        ;;

    --quick)
        # Smoke test — collect only + critical paths
        echo -e "${YELLOW}Running: pytest --collect-only${NC}"
        $PYTHON -m pytest tests/ --collect-only -q 2>&1 | tail -3
        echo -e "${YELLOW}Running: pytest tests/test_db.py tests/test_trading_engine_all.py::TestGate -q${NC}"
        $PYTHON -m pytest tests/test_db.py tests/test_trading_engine_all.py::TestGate -q --tb=line
        echo -e "${GREEN}✓ Quick smoke OK${NC}"
        ;;

    full)
        # CI: backend-tests job — EXACT command from .github/workflows/main-ci-cd.yml
        echo -e "${YELLOW}Step 1/2: ruff check nuri/ tests/ scripts/${NC}"
        $PYTHON -m ruff check nuri/ tests/ scripts/
        echo -e "${GREEN}✓ Lint OK${NC}"

        echo ""
        echo -e "${YELLOW}Step 2/2: pytest -q --tb=short -n auto --cov=nuri --cov-report=term${NC}"
        echo -e "${YELLOW}(this is the EXACT command CI runs)${NC}"
        $PYTHON -m pytest tests/ -q --tb=short -n auto --cov=nuri --cov-report=term

        echo ""
        echo -e "${GREEN}✓ CI parity check passed — safe to push${NC}"
        ;;

    *)
        echo -e "${RED}Unknown mode: $mode${NC}"
        echo "Usage: bash scripts/ci_local.sh [--lint | --quick | full]"
        exit 1
        ;;
esac
