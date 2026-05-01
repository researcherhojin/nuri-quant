#!/usr/bin/env bash
# scripts/launchd/install_phase2_crons.sh — #529 Phase 2 운영 cron 설치 (O2 + O3).
#
# 설치 대상 (HOME 자동 substitute):
#   com.nuri-quant.track-forward — 매일 KST 17:00 ForwardOutcomeTracker.scan
#   com.nuri-quant.sre-scan      — 매시간 SREIncidentAgent.scan
#
# 사용:
#   bash scripts/launchd/install_phase2_crons.sh        # 설치 + load
#   bash scripts/launchd/install_phase2_crons.sh --dry  # 무엇이 설치될지만 표시
#
# Uninstall:
#   bash scripts/launchd/uninstall_phase2_crons.sh
set -euo pipefail

cd "$(dirname "$0")/../.."
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PWD/data/logs"

PLISTS=(
    "com.nuri-quant.track-forward.plist"
    "com.nuri-quant.sre-scan.plist"
)

DRY=0
[ "${1:-}" = "--dry" ] && DRY=1

echo "═══ #529 Phase 2 cron install ═══"
echo " HOME:       $HOME"
echo " LAUNCHD:    $LAUNCHD_DIR"
echo " LOG_DIR:    $LOG_DIR"
echo " DRY-RUN:    $DRY"
echo "──────────────────────────────────"

mkdir -p "$LAUNCHD_DIR" "$LOG_DIR"

for plist in "${PLISTS[@]}"; do
    src="scripts/launchd/$plist"
    dst="$LAUNCHD_DIR/$plist"

    if [ ! -f "$src" ]; then
        echo " ❌ source missing: $src"
        exit 2
    fi

    if [ "$DRY" = "1" ]; then
        echo " [DRY] would copy: $src → $dst"
        echo " [DRY] would substitute /Users/USER → $HOME"
        echo " [DRY] would launchctl load $dst"
        continue
    fi

    # 기존 load 해제 (idempotent)
    if launchctl list | grep -q "${plist%.plist}"; then
        echo " ⏸  unloading existing: $plist"
        launchctl unload "$dst" 2>/dev/null || true
    fi

    # 복사 + USER substitute
    cp "$src" "$dst"
    sed -i '' "s|/Users/USER|$HOME|g" "$dst"

    # load
    launchctl load "$dst"
    echo " ✅ installed: $plist"
done

if [ "$DRY" = "0" ]; then
    echo "──────────────────────────────────"
    echo " 확인:"
    for plist in "${PLISTS[@]}"; do
        label="${plist%.plist}"
        status=$(launchctl list | awk -v l="$label" '$3==l {print $1}')
        echo "   $label → PID/exit: ${status:-not loaded}"
    done
    echo ""
    echo " 로그 확인:"
    echo "   tail -f $LOG_DIR/track_forward.log"
    echo "   tail -f $LOG_DIR/sre_scan.log"
fi
