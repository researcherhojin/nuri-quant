#!/usr/bin/env bash
# scripts/launchd/install_crons.sh — nuri-quant 모든 launchd cron 통합 installer.
#
# 자동 발견: scripts/launchd/com.nuri-quant.*.plist 전부 install 후보.
# 각 plist 는 opt-in (default 는 모두 설치, --only/--exclude 로 필터).
#
# 사용:
#   bash scripts/launchd/install_crons.sh                    # 전부 설치
#   bash scripts/launchd/install_crons.sh --dry              # dry-run
#   bash scripts/launchd/install_crons.sh --only sre-scan track-forward
#   bash scripts/launchd/install_crons.sh --exclude discord-bot
#
# Uninstall:
#   bash scripts/launchd/uninstall_crons.sh
set -euo pipefail

cd "$(dirname "$0")/../.."
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
PLIST_SRC_DIR="scripts/launchd"
LOG_DIR="$PWD/data/logs"

# Discover all plists (bash 3.2 compatible — macOS default).
ALL_PLISTS=()
while IFS= read -r line; do
    ALL_PLISTS+=("$line")
done < <(find "$PLIST_SRC_DIR" -name "com.nuri-quant.*.plist" -type f -exec basename {} \; | sort)

if [ "${#ALL_PLISTS[@]}" -eq 0 ]; then
    echo " ❌ no plist found under $PLIST_SRC_DIR/"
    exit 2
fi

# Parse flags.
DRY=0
ONLY=()
EXCLUDE=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry) DRY=1; shift ;;
        --only) shift; while [ "$#" -gt 0 ] && [[ "$1" != --* ]]; do ONLY+=("$1"); shift; done ;;
        --exclude) shift; while [ "$#" -gt 0 ] && [[ "$1" != --* ]]; do EXCLUDE+=("$1"); shift; done ;;
        --help|-h) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo " ❌ unknown flag: $1"; exit 2 ;;
    esac
done

# Filter.
SELECTED=()
for plist in "${ALL_PLISTS[@]}"; do
    short="${plist#com.nuri-quant.}"
    short="${short%.plist}"
    if [ "${#ONLY[@]:-0}" -gt 0 ]; then
        for o in "${ONLY[@]}"; do
            if [ "$o" = "$short" ]; then SELECTED+=("$plist"); break; fi
        done
    else
        skip=0
        if [ "${#EXCLUDE[@]:-0}" -gt 0 ]; then
            for e in "${EXCLUDE[@]}"; do
                if [ "$e" = "$short" ]; then skip=1; break; fi
            done
        fi
        [ "$skip" = "0" ] && SELECTED+=("$plist")
    fi
done

if [ "${#SELECTED[@]}" -eq 0 ]; then
    echo " ⚠️  no plist matched filter"
    exit 1
fi

echo "═══ nuri-quant launchd cron install ═══"
echo " HOME:       $HOME"
echo " LAUNCHD:    $LAUNCHD_DIR"
echo " LOG_DIR:    $LOG_DIR"
echo " DRY-RUN:    $DRY"
echo " selected:   ${#SELECTED[@]} of ${#ALL_PLISTS[@]} plist"
echo "──────────────────────────────────"

mkdir -p "$LAUNCHD_DIR" "$LOG_DIR"

for plist in "${SELECTED[@]}"; do
    src="$PLIST_SRC_DIR/$plist"
    dst="$LAUNCHD_DIR/$plist"
    label="${plist%.plist}"

    if [ "$DRY" = "1" ]; then
        echo " [DRY] $plist → $dst (USER substitute → $HOME)"
        continue
    fi

    if launchctl list | grep -q "$label"; then
        echo " ⏸  unloading existing: $label"
        launchctl unload "$dst" 2>/dev/null || true
    fi

    cp "$src" "$dst"
    sed -i '' "s|/Users/USER|$HOME|g" "$dst"
    launchctl load "$dst"
    echo " ✅ installed: $plist"
done

if [ "$DRY" = "0" ]; then
    echo "──────────────────────────────────"
    echo " 확인:"
    for plist in "${SELECTED[@]}"; do
        label="${plist%.plist}"
        status=$(launchctl list | awk -v l="$label" '$3==l {print $1}')
        echo "   $label → ${status:-not loaded}"
    done
    echo ""
    echo " 로그 위치: $LOG_DIR/"
fi
