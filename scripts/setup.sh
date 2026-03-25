#!/bin/bash
# Nuri-Quant 초기 환경 설정 스크립트
set -e

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
source .venv/bin/activate
uv pip install -e "."

# Create data directories
mkdir -p data/backups data/exports

# .env from template
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from template — please fill in API keys"
fi

echo "=== Setup complete ==="
