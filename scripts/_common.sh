#!/usr/bin/env bash
# scripts/_common.sh — Shared shell helpers sourced by other nuri scripts.
#
# What this provides:
#   1. ANSI color codes (GREEN, RED, YELLOW, CYAN, NC)
#   2. PYTHON path (.venv/bin/python, override via PYTHON env var)
#   3. Repo root cd (idempotent — safe to source from any subdir)
#   4. pass/fail/warn counter functions with consistent output
#
# How to use:
#   source "$(dirname "$0")/_common.sh"
#   pass "ruff check"
#   fail "tests"
#   warn "deprecated import"
#   echo "Pass: $PASS  Fail: $FAIL  Warn: $WARN"
#
# Why a sourced helper instead of a CLI:
#   Several scripts (verify_all, pre-deploy-check, demo, etc.) duplicated
#   the same color codes + counter functions + PYTHON path. Centralizing
#   here removes ~30 lines of duplication per script and ensures consistent
#   output formatting across the toolchain.

# ─── ANSI colors ──────────────────────────────────────────────
# Use \033[ instead of \e[ for portability (some macOS sh variants).
export GREEN='\033[0;32m'
export RED='\033[0;31m'
export YELLOW='\033[1;33m'
export CYAN='\033[0;36m'
export BLUE='\033[0;34m'
export BOLD='\033[1m'
export NC='\033[0m'

# ─── Python interpreter ───────────────────────────────────────
# Override via env: PYTHON=python3.13 bash scripts/foo.sh
export PYTHON="${PYTHON:-.venv/bin/python}"

# ─── Repo root cd ─────────────────────────────────────────────
# Idempotent: only cd if we're not already at the repo root (detected
# by presence of pyproject.toml). Caller can override REPO_ROOT.
_common_repo_root() {
    if [ -n "${REPO_ROOT:-}" ]; then
        echo "$REPO_ROOT"
        return
    fi
    # Walk up from this script's directory to find pyproject.toml
    local d
    d="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    echo "$d"
}
REPO_ROOT="$(_common_repo_root)"
cd "$REPO_ROOT" || { echo "ERROR: cannot cd to repo root: $REPO_ROOT" >&2; exit 1; }

# ─── Counter functions ────────────────────────────────────────
# Initialize counters. Caller can read PASS, FAIL, WARN after calling.
PASS=${PASS:-0}
FAIL=${FAIL:-0}
WARN=${WARN:-0}

pass()  { echo -e "  ${GREEN}✓ $1${NC}"; PASS=$((PASS + 1)); }
fail()  { echo -e "  ${RED}✗ $1${NC}"; FAIL=$((FAIL + 1)); }
warn()  { echo -e "  ${YELLOW}⚠ $1${NC}"; WARN=$((WARN + 1)); }
info()  { echo -e "  ${CYAN}ℹ $1${NC}"; }

# Banner — 50-char wide centered title in CYAN.
banner() {
    local title="$1"
    echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
    printf "${CYAN}║  %-48s║${NC}\n" "$title"
    echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
}

# Final summary line — call at end of script.
summary() {
    local total=$((PASS + FAIL + WARN))
    if [ "$FAIL" -gt 0 ]; then
        echo -e "\n${RED}Summary: $FAIL failed, $PASS passed, $WARN warnings ($total checks)${NC}"
    elif [ "$WARN" -gt 0 ]; then
        echo -e "\n${YELLOW}Summary: $PASS passed, $WARN warnings ($total checks)${NC}"
    else
        echo -e "\n${GREEN}Summary: $PASS passed ($total checks)${NC}"
    fi
}

# Conditional check helper — wraps a command and updates counters by exit code.
# Usage: check "ruff check" ruff check nuri/
check_cmd() {
    local label="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        pass "$label"
        return 0
    else
        fail "$label"
        return 1
    fi
}
