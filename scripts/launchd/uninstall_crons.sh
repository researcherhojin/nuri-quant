#!/usr/bin/env bash
# scripts/launchd/uninstall_crons.sh — nuri-quant 모든 launchd cron 통합 uninstaller.
set -euo pipefail

cd "$(dirname "$0")/../.."
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
PLIST_SRC_DIR="scripts/launchd"

ALL_PLISTS=()
while IFS= read -r line; do
    ALL_PLISTS+=("$line")
done < <(find "$PLIST_SRC_DIR" -name "com.nuri-quant.*.plist" -type f -exec basename {} \; | sort)

ONLY=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --only) shift; while [ "$#" -gt 0 ] && [[ "$1" != --* ]]; do ONLY+=("$1"); shift; done ;;
        *) echo " ❌ unknown flag: $1"; exit 2 ;;
    esac
done

echo "═══ nuri-quant launchd cron uninstall ═══"

for plist in "${ALL_PLISTS[@]}"; do
    short="${plist#com.nuri-quant.}"
    short="${short%.plist}"
    if [ "${#ONLY[@]}" -gt 0 ]; then
        match=0
        for o in "${ONLY[@]}"; do [ "$o" = "$short" ] && match=1; done
        [ "$match" = "0" ] && continue
    fi

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
