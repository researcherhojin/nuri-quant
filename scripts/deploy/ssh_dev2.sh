#!/usr/bin/env bash
# DEV2 원격 ssh 공용 helper — ssh -4 강제 + .local 해석 실패 시 dscacheutil IPv4 fallback (#827)
#
# 실측 문제 2건:
#   (a) 외근망: IPv6 우선 해석 → No route to host  → ssh -4 로 IPv4 강제
#   (b) 홈 LAN: .local 이름 해석 자체 실패          → dscacheutil -q host 로 IPv4 를 얻어 직접 접속
#
# 사용법 (ssh drop-in — 옵션은 destination 앞에 위치해야 함, 기존 호출처 전부 충족):
#   scripts/deploy/ssh_dev2.sh [ssh옵션...] <[user@]host> [원격명령...]
#   scp -S scripts/deploy/ssh_dev2.sh ...   # scp 전송 프로그램으로도 사용 가능
#
# 동작:
#   1차: ssh -4 <원본 인자 그대로>
#   1차가 exit 255 (ssh 연결층 실패 = 원격 명령 미실행) 인 경우에만:
#     dscacheutil 로 IPv4 를 얻어 destination 을 IP 로 치환해 재시도.
#     -o HostKeyAlias=<원래 host> 로 known_hosts 검증은 hostname 기준 유지.
#   원격 명령 자체의 실패 (exit != 255) 는 재시도 없이 그대로 전파.

set -euo pipefail

usage() {
    echo "usage: ssh_dev2.sh [ssh options...] <[user@]host> [remote command...]" >&2
    exit 2
}

(( $# >= 1 )) || usage

# ── destination (첫 non-option 인자) 탐색 ──
args=("$@")
dest_idx=-1
i=0
while (( i < ${#args[@]} )); do
    case "${args[i]}" in
        --)
            # scp -S 가 '-- host cmd...' 형태로 호출 — 다음 인자가 destination
            dest_idx=$((i + 1))
            break
            ;;
        -o | -l | -p | -i | -F | -E | -J | -b | -c | -e | -m | -w | -B | -D | -L | -R | -W | -S)
            # 값을 별도 인자로 받는 옵션 — 다음 인자를 값으로 소비
            i=$((i + 2))
            ;;
        -*)
            i=$((i + 1))
            ;;
        *)
            dest_idx=$i
            break
            ;;
    esac
done
if (( dest_idx < 0 || dest_idx >= ${#args[@]} )); then usage; fi
dest="${args[dest_idx]}"

# user@ 접두 분리 (없으면 빈 문자열)
userpart=""
host="${dest}"
if [[ "${dest}" == *@* ]]; then
    userpart="${dest%%@*}@"
    host="${dest#*@}"
fi

# ── 1차 시도: IPv4 강제 (외근망 IPv6 우선 해석 → no-route 회피) ──
rc=0
ssh -4 "$@" || rc=$?
if (( rc != 255 )); then
    exit "${rc}"
fi

# ── 2차 시도: dscacheutil IPv4 fallback (.local 이름 해석 실패 시) ──
if [[ "${host}" =~ ^[0-9]+(\.[0-9]+){3}$ ]]; then
    exit "${rc}"  # 이미 IPv4 literal — fallback 무의미
fi

ip="$(dscacheutil -q host -a name "${host}" 2>/dev/null | awk '/^ip_address:/ { print $2; exit }' || true)"
if [[ -z "${ip}" ]]; then
    echo "ssh_dev2: dscacheutil 로도 '${host}' IPv4 해석 실패 — fallback 불가 (exit ${rc})" >&2
    exit "${rc}"
fi

echo "ssh_dev2: ssh 연결 실패 (255) → dscacheutil fallback: ${host} → ${ip}" >&2

# destination 을 IP 로 치환 후 재시도 — known_hosts 는 HostKeyAlias 로 원래 hostname 기준 검증
args[dest_idx]="${userpart}${ip}"
exec ssh -4 -o "HostKeyAlias=${host}" "${args[@]}"
