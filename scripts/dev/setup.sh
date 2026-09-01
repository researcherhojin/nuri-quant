#!/usr/bin/env bash
# Nuri-Quant 초기 환경 설정 스크립트
set -euo pipefail

echo "=== Nuri-Quant Setup ==="

# TA-Lib C library
if ! brew list ta-lib &>/dev/null; then
    echo "Installing ta-lib..."
    brew install ta-lib
fi

# Python venv
if [ ! -d ".venv" ]; then
    echo "Creating venv with Python 3.12..."
    uv venv --python 3.12
fi

# Install dependencies
echo "Installing Python packages..."
# shellcheck disable=SC1091
source .venv/bin/activate
# 로컬 GGUF fallback 은 opt-in extra 이지만 기존 make setup 동작은 보존한다 (#1406).
# Test: tests/scripts/test_local_llm_extra.py::TestLocalLlmExtraPolicy::test_dev_setup_includes_local_llm
uv sync --extra dev --extra local-llm

# Create data directories
mkdir -p data/backups data/exports

# .env from template
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from template — please fill in API keys"
fi

echo "=== Setup complete ==="
