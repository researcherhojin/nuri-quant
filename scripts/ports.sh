#!/bin/bash
# ═══════════════════════════════════════════════════════
# Nuri-Quant Port Manager
# 사용법: bash scripts/ports.sh [kill]
# ═══════════════════════════════════════════════════════

declare -A PORTS=(
    [8001]="FastAPI"
    [3000]="Next.js"
    [11434]="Ollama"
)

ACTION=${1:-status}

echo "═══════════════════════════════════════════════════════"
echo "  Nuri-Quant Ports ($ACTION)"
echo "═══════════════════════════════════════════════════════"

for PORT in "${!PORTS[@]}"; do
    NAME="${PORTS[$PORT]}"
    PID=$(lsof -i ":$PORT" -sTCP:LISTEN -t 2>/dev/null | head -1)

    if [ -n "$PID" ]; then
        PROC=$(ps -p "$PID" -o comm= 2>/dev/null || echo "unknown")
        echo "  :$PORT  $NAME  PID=$PID ($PROC)"

        if [ "$ACTION" = "kill" ]; then
            kill "$PID" 2>/dev/null
            sleep 1
            if kill -0 "$PID" 2>/dev/null; then
                kill -9 "$PID" 2>/dev/null
                echo "         → force killed"
            else
                echo "         → stopped"
            fi
        fi
    else
        echo "  :$PORT  $NAME  (free)"
    fi
done
