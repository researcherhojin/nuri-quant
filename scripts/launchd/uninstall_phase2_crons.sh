#!/usr/bin/env bash
# scripts/launchd/uninstall_phase2_crons.sh — #529 Phase 2 운영 cron 제거.
set -euo pipefail

LAUNCHD_DIR="$HOME/Library/LaunchAgents"
PLISTS=(
    "com.nuri-quant.track-forward.plist"
    "com.nuri-quant.sre-scan.plist"
)

echo "═══ #529 Phase 2 cron uninstall ═══"

for plist in "${PLISTS[@]}"; do
    dst="$LAUNCHD_DIR/$plist"
    label="${plist%.plist}"

    if [ -f "$dst" ]; then
        if launchctl list | grep -q "$label"; then
            launchctl unload "$dst" 2>/dev/null || true
            echo " ⏸  unloaded: $label"
        fi
        rm -f "$dst"
        echo " 🗑  removed: $dst"
    else
        echo " ℹ  not installed: $plist"
    fi
done
