#!/usr/bin/env bash
# scripts/launchd/install_daemons.sh — **시스템 도메인** LaunchDaemon installer (#1443).
#
# `install_crons.sh` 와 짝이지만 도메인이 다르다:
#
#   install_crons.sh    ~/Library/LaunchAgents   gui/$UID   콘솔 로그인 후에만 로드
#   install_daemons.sh  /Library/LaunchDaemons   system     부팅 직후 로드 (로그인 무관)
#
# 로그인 게이트를 벗어나야 하는 것만 여기 온다. 지금은 machine-alive 하나뿐이다 —
# 감시가 목적이라 반경을 최소로 유지한다. 앱 본체(scheduler·api)의 이관은 홈 경로·venv·
# TCC 권한이 시스템 도메인에서 달라지므로 별도 판단이 필요하다 (#1443 제안 1).
#
# 사용:
#   sudo bash scripts/launchd/install_daemons.sh          # 설치
#   bash scripts/launchd/install_daemons.sh --dry         # sudo 없이 확인만
set -euo pipefail

cd "$(dirname "$0")/../.."
DAEMON_DIR="/Library/LaunchDaemons"
PLIST_SRC_DIR="scripts/launchd/system"

DRY=0
[ "${1:-}" = "--dry" ] && DRY=1

# 실행 주체 판별: sudo 로 왔으면 원래 사용자를, 아니면 현재 사용자를 쓴다. root 의 홈
# (`/var/root`)을 치환값으로 쓰면 deploy key 와 레포를 못 찾는다.
TARGET_USER="${SUDO_USER:-$(id -un)}"
if [ "$TARGET_USER" = "root" ]; then
    echo " ❌ root 를 실행 주체로 설치할 수 없다 — sudo 로 실행하되 원래 계정이 필요하다"
    exit 2
fi
TARGET_HOME=$(eval echo "~$TARGET_USER")

ALL=()
while IFS= read -r line; do
    ALL+=("$line")
done < <(find "$PLIST_SRC_DIR" -maxdepth 1 -name "com.nuri-quant.*.plist" -type f -exec basename {} \; | sort)

if [ "${#ALL[@]}" -eq 0 ]; then
    echo " ❌ no plist under $PLIST_SRC_DIR/"
    exit 2
fi

echo "═══ nuri-quant LaunchDaemon install (system domain) ═══"
echo " USER:    $TARGET_USER  ($TARGET_HOME)"
echo " TARGET:  $DAEMON_DIR"
echo " DRY-RUN: $DRY"
echo " plists:  ${#ALL[@]}"
echo "──────────────────────────────────"

if [ "$DRY" = "0" ] && [ "$(id -u)" != "0" ]; then
    echo " ❌ 시스템 도메인 설치는 root 권한이 필요하다: sudo bash $0"
    exit 2
fi

for plist in "${ALL[@]}"; do
    src="$PLIST_SRC_DIR/$plist"
    dst="$DAEMON_DIR/$plist"
    label="${plist%.plist}"

    if [ "$DRY" = "1" ]; then
        echo " [DRY] $plist → $dst (USER → $TARGET_USER)"
        continue
    fi

    # 이미 있으면 먼저 내린다. `bootout` 은 없는 서비스에도 비영(non-zero)을 내므로 무시.
    launchctl bootout "system/$label" 2>/dev/null || true

    # 치환 → temp → 원자 교체. `cp` 후 in-place sed 는 그 사이 목적지가 `/Users/USER` 를
    # 담아 launchd 가 exit 78 (EX_CONFIG) 로 조용히 죽는다 (#988 의 실제 고장).
    if ! sed "s|/Users/USER|$TARGET_HOME|g; s|<string>USER</string>|<string>$TARGET_USER</string>|g" \
            "$src" > "$dst.tmp" || ! mv "$dst.tmp" "$dst"; then
        rm -f "$dst.tmp"
        echo " ❌ 치환 실패: $plist (load 하지 않음)"
        continue
    fi
    # LaunchDaemon 은 root:wheel 644 여야 launchd 가 로드한다 — 아니면 조용히 무시된다.
    chown root:wheel "$dst"
    chmod 644 "$dst"
    launchctl bootstrap system "$dst"
    echo " ✅ installed: $plist"
done

if [ "$DRY" = "0" ]; then
    echo "──────────────────────────────────"
    echo " 확인:"
    for plist in "${ALL[@]}"; do
        label="${plist%.plist}"
        status=$(launchctl list | awk -v l="$label" '$3==l {print $1}')
        echo "   $label → ${status:-not loaded}"
    done
    echo ""
    echo " ⚠️  진짜 검증은 **재부팅 후 로그인 없이** ref 가 갱신되는지다 —"
    echo "     load 성공은 로그인 게이트를 벗어났다는 증거가 아니다."
    echo "     git ls-remote origin 'refs/nuri/machine-mini'"
fi
