#!/usr/bin/env bash
# Mac mini receiver: 5분마다 origin/main을 fetch하고, HEAD가 바뀌면 ff-only merge.
#
# 트리거: ~/Library/LaunchAgents/com.nuri-quant.autopull.plist (StartInterval=300)
# 로그:   ~/Library/Logs/nuri-quant-autopull.log
#
# 동작:
#   1. fetch (실패 시 조용히 retry — 네트워크 끊김 대응)
#   2. 로컬 HEAD vs origin/main 비교
#   3. 변경 없으면 종료 (silent)
#   4. 변경 있으면 ff-only merge → 비-FF면 거부 + 로그 (수동 처리 유도)
#   5. 변경된 파일 분석 → dependency/schema 변경 시 경고
#   6. (선택) 24/7 서비스 재시작 hook — 현재는 placeholder
#
# 수동 테스트:
#   bash scripts/autopull_receiver.sh
#
# 설치 (권장): make crons-install   — 치환 + 원자 교체를 대신 해준다
#
# 손수 할 때. bare cp 금지 — #980 이후 repo plist 는 `/Users/USER/` 플레이스홀더를
# 담아서, 그대로 복사하면 launchd 가 exit 78 (EX_CONFIG) 로 죽는다 (#988).
#   N=com.nuri-quant.autopull.plist
#   sed "s|/Users/USER/|$HOME/|g" scripts/launchd/$N > ~/Library/LaunchAgents/$N.tmp \
#     && mv ~/Library/LaunchAgents/$N.tmp ~/Library/LaunchAgents/$N \
#     && launchctl load ~/Library/LaunchAgents/$N
#
# ⚠️ make deploy-mini 는 이 plist 를 설치하지 않는다 — 상태를 읽기만 한다 (7단계).
#
# 상태 확인:
#   launchctl list | grep autopull
#   tail -f ~/Library/Logs/nuri-quant-autopull.log

set -u   # set -e 사용 안 함 — 한 단계 실패가 launchd 전체를 멈추게 하면 안 됨

# NURI_REPO 미설정 시 폴백 — scripts/deploy/ 이므로 두 단계 (#946).
# git 은 하위 디렉터리에서도 워크트리 전체에 작동해 여태 운으로 동작했다.
REPO="${NURI_REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"
LOG="$HOME/Library/Logs/nuri-quant-autopull.log"

mkdir -p "$(dirname "$LOG")"
cd "$REPO" || { echo "[$(date '+%F %T')] FATAL: $REPO 없음" >> "$LOG"; exit 0; }

ts() { date '+%F %T'; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

# 로그 회전 — 1MB 넘으면 백업 후 새로 시작
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG" 2>/dev/null || echo 0)" -gt 1048576 ]; then
    mv "$LOG" "${LOG}.1"
    log "log rotated"
fi

BEFORE=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

# fetch — non-interactive, git 자체 low-speed timeout (30초간 1KB/s 미만이면 abort)
# macOS 기본에 GNU timeout이 없으므로 git의 내장 timeout 변수 사용
if ! GIT_TERMINAL_PROMPT=0 GIT_HTTP_LOW_SPEED_LIMIT=1000 GIT_HTTP_LOW_SPEED_TIME=30 \
        git fetch origin main >/dev/null 2>&1; then
    log "fetch failed (network/timeout) — will retry next interval"
    exit 0
fi

UPSTREAM=$(git rev-parse origin/main 2>/dev/null || echo "unknown")

if [ "$BEFORE" = "$UPSTREAM" ]; then
    # 변경 없음 — 조용히 종료 (로그 줄이려고)
    exit 0
fi

# 새 커밋 발견
log "new commits detected: ${BEFORE:0:7}..${UPSTREAM:0:7}"
git log --oneline --no-decorate "${BEFORE}..${UPSTREAM}" 2>/dev/null | head -10 | while read -r line; do
    log "  $line"
done

# 로컬에 uncommitted 변경이 있으면 ff-only가 거부됨 — 명시적으로 체크
if ! git diff --quiet HEAD 2>/dev/null; then
    log "ABORT: uncommitted local changes present. Manual resolution needed:"
    log "  cd $REPO && git status"
    exit 0
fi

# ff-only merge
if ! git merge --ff-only origin/main >/dev/null 2>&1; then
    log "ABORT: non-fast-forward. Local diverged from origin/main."
    log "  cd $REPO && git status && git log --oneline -5"
    exit 0
fi

AFTER=$(git rev-parse HEAD)
log "updated to ${AFTER:0:7}"

# ── 변경 분석: 수동 조치가 필요한 변경이면 경고만 로그 ──────────────────
CHANGED=$(git diff --name-only "$BEFORE" "$AFTER" 2>/dev/null)

DEPS_CHANGED=0
if echo "$CHANGED" | grep -qE "^(pyproject\.toml|uv\.lock)$"; then
    DEPS_CHANGED=1
fi

if echo "$CHANGED" | grep -qE "^frontend/package(-lock)?\.json$"; then
    log "WARN: Frontend deps changed. Run manually:"
    log "  cd $REPO/frontend && npm ci"
fi

if echo "$CHANGED" | grep -qE "^(nuri/core/db/.*\.py|nuri/core/db_migrations\.py|scripts/db/migrate\.py)$"; then
    log "WARN: DB schema may have changed. Run manually:"
    log "  cd $REPO && .venv/bin/python scripts/db/migrate.py"
fi

if echo "$CHANGED" | grep -qE "^config/"; then
    log "INFO: config/ files changed. Verify rules/agents/portfolio still valid."
fi

# ── 상주 서비스 재기동 ──────────────────────────────────────────────────
# 여기는 오래 "24/7 서비스가 등록되어 있지 않아 no-op" 이라는 주석만 있는 placeholder
# 였다. 그 문장은 서비스가 7개 등록된 뒤로 거짓이었고, **자동 경로만** 데몬을 안 재웠다
# — 수동 경로(`deploy_to_mini.sh`)는 #940 이후 제대로 bounce 하고 테스트로 잠겨 있다.
#
# 안 재우면 **디스크의 새 코드 + 메모리의 낡은 모듈** 조합이 된다. 2026-08-10 실측:
# #1017 이 `nuri/core/rules.py` 에 심볼을 추가한 날 밤 22:00 `premarket_brief` 가 새
# `vix_gate` 를 lazy import 하다 캐시된 옛 `rules` 에서 `VIX_MAX_AGE_BUSINESS_DAYS` 를
# 못 찾아 ImportError 로 죽었고 — certifications · decisions · 브리핑 md **3개 산출물이
# 통째로 안 만들어졌다**. APScheduler 는 바로 다음 줄에 `executed successfully` 를 찍어
# 아무 신호도 없었다. 같은 계열이 #576 에 이미 기록돼 있었다.
#
# **재기동은 어느 경우에도 안 하는 것보다 낫다**: 안 재운 프로세스는 이미 하이브리드
# (메모리는 옛 모듈, lazy import 는 새 파일)라 일관성이 없다. 재기동하면 최소한 전부
# 새 코드가 된다. 스키마 변경도 마찬가지 — 그건 위 WARN 이 사람에게 알린다.
#
# 트레이드오프: 머지가 긴 잡(22:00 브리핑 ~5분) 도중에 떨어지면 그 잡이 죽는다. 그러나
# 대안은 **확정적** ImportError 라, 드문 충돌 쪽을 택한다. 죽은 잡은 다음 cron 에 다시 돈다.
CODE_CHANGED=0
if echo "$CHANGED" | grep -qE "^nuri/.*\.py$"; then
    CODE_CHANGED=1
fi

if [ "$CODE_CHANGED" = "1" ] || [ "$DEPS_CHANGED" = "1" ]; then
    # 순서가 중요하다: sync 를 재기동 **앞**에 둔다. 뒤에 두면 새 프로세스가 옛 venv 로
    # 뜬 뒤 패키지만 바뀌어, 재기동을 한 번 더 해야 한다 (2026-08-10 수동 조치 때 밟음).
    if [ "$DEPS_CHANGED" = "1" ]; then
        # launchd 는 로그인 셸 PATH 를 안 물려준다 — `uv` 를 이름으로 부르면
        # `command not found` 로 조용히 건너뛴다 (2026-08-10 실측).
        UV_BIN=$(command -v uv 2>/dev/null || echo "/opt/homebrew/bin/uv")
        if [ -x "$UV_BIN" ]; then
            # `--locked` 필수 (#1350). 플래그 없는 sync 는 lock 을 **다시 쓴다**
            # (`--frozen` = "sync without updating the uv.lock file" 의 대우).
            # uv.lock 은 tracked 라 재작성되면 워킹트리가 dirty 가 되고, 다음 주기가
            # 위 `ABORT: uncommitted local changes` 에 걸려 exit 0 으로 조용히 멈춘다
            # — 실패로도 안 보이는 영구 배포 동결. `--frozen` 은 오답이다: 트리는
            # 지키지만 구 버전을 무신호로 설치한다. `--locked` 는 불일치 시 아무것도
            # 쓰지 않고 non-zero 로 죽어 아래 soft-fail 로 떨어진다.
            log "deps changed → $UV_BIN sync --extra dev --locked"
            "$UV_BIN" sync --extra dev --locked >>"$LOG" 2>&1 || log "ERROR: uv sync 실패 — 구 venv 로 재기동된다"
        else
            log "ERROR: uv 를 못 찾음 ($UV_BIN) — deps 미동기화 상태로 재기동한다"
        fi
    fi

    # 상주 python 서비스. plist 판정 기준(StartInterval 없음 + .venv/bin/python)과
    # 일치해야 하며 `tests/scripts/test_deploy_bounces_resident_services.py` 가 대조한다.
    # dashboard 는 빌드 산출물을 서빙하므로 제외 — 프론트 변경은 위 WARN 이 담당.
    RESIDENT_SERVICES=(com.nuri-quant.scheduler com.nuri-quant.api com.nuri-quant.discord-bot)
    for RESIDENT in "${RESIDENT_SERVICES[@]}"; do
        if ! launchctl list 2>/dev/null | grep -q "${RESIDENT}\$"; then
            log "skip restart: ${RESIDENT} 미설치"
            continue
        fi
        if launchctl kickstart -k "gui/$(id -u)/${RESIDENT}" >>"$LOG" 2>&1; then
            log "restarted ${RESIDENT}"
        else
            log "ERROR: ${RESIDENT} kickstart 실패 — 구코드로 계속 돈다. 수동 확인 필요"
        fi
    done
else
    log "no python code/dep changes — services left running"
fi
