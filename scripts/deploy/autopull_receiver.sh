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
#   3b. 새 커밋의 main CI 가 success 가 아니면 보류 — 다음 주기에 다시 본다 (#1808)
#   4. 변경 있으면 ff-only merge → 비-FF면 거부 + 로그 (수동 처리 유도)
#   5. 변경된 파일 분석 → dependency/schema 변경 시 경고
#   6. 상주 python 서비스 재기동 (#1023)
#   7. frontend 빌드 self-heal — 새 커밋이 없는 주기에도 (#1462)
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

# 프론트 빌드는 별도 스크립트가 맡는다 (#1462) — 수동 경로(deploy_to_mini.sh 4단계)와 **같은
# 것**을 부른다. 새 커밋이 없는 주기에도 부른다: 판정이 "코드 > 빌드" 라 밀린·실패한 빌드를
# self-heal 하고, 최신이면 아무것도 안 찍는다. 이전에는 여기가 `frontend/package*.json` 변경에만
# 찍히는 WARN 한 줄이었다 — 8/30 이후 17번 찍혔지만 아무도 안 받았고, 소스만 바뀐 커밋은 그
# WARN 조차 없어서 프로덕션이 9일 된 빌드를 서빙했다.
ensure_frontend_build() {
    # 형제 스크립트는 **이 파일 기준**으로 찾는다 — $REPO 기준이면 NURI_REPO 로 임시 레포를
    # 가리키는 실행 테스트에서 스크립트가 없어 조용히 실패한다 (첫 판에서 실제로 그랬다).
    if ! bash "$(cd "$(dirname "$0")" && pwd)/build_frontend.sh" >>"$LOG" 2>&1; then
        log "ERROR: frontend 빌드 실패 — 이전 빌드 유지 (위 출력 참조). 같은 커밋은 재시도하지 않는다(frontend/.next.failed) — 새 frontend 커밋 또는 deploy_to_mini 가 지운다; 재기동만 실패했으면 다음 주기에 재기동 재시도"
    fi
}

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
    # 변경 없음 — 조용히 종료 (로그 줄이려고). 프론트 빌드만 확인한다: 최신이면 무출력이고,
    # 지난 주기에 실패했거나 밀렸으면 여기서 따라잡는다.
    ensure_frontend_build
    exit 0
fi

# ── CI 게이트: main CI 가 초록인 커밋만 배포한다 (#1808) ─────────────────────
# 이 게이트 전에는 branch protection 의 `strict`(PR 이 최신 main 을 포함해야 머지)가 사실상
# 배포 안전장치였다 — PR CI 가 머지 뒤 트리를 그대로 검사했으니까. `strict` 를 끄면 각자
# 초록인 두 PR 이 합쳐진 트리는 main push CI 만 검사하므로 여기서 그 결과를 기다린다.
# 판정할 수 없으면(런 없음 · 진행 중 · API 실패) 배포하지 않고 다음 주기에 다시 본다. 빨간
# HEAD 는 고치는 커밋이 초록이 될 때까지 보류된다. 수동 배포(`make deploy-mini`)는 거치지 않는다.
# mini 의 gh 는 로그인돼 있지 않아 공개 REST 를 curl 로 읽는다 — 새 커밋이 있을 때만 부르므로
# 비인증 한도(시간당 60)에 닿지 않는다.
# 막는 것: 빨간 · 진행 중 · 아직 없는 런과 API 실패. 막지 않는 것: 응답 본문 자체를 조작할 수 있는
# 쪽(TLS 를 뚫은 MITM · GitHub 침해) — 그쪽은 정상적인 success 응답을 그대로 보내면 되므로 파싱을
# 어떻게 고쳐도 소용없다. 그런 입력(본문 속 날 NUL 등)을 겨냥한 수정은 하지 않는다.
# Test: tests/scripts/test_autopull_restarts_daemons.py::TestAutopullWaitsForGreenCi
ci_verdict() {
    local slug py body
    slug=$(git remote get-url origin 2>/dev/null | sed -E 's#\.git$##; s#^.*github\.com[:/]##')
    py="$REPO/.venv/bin/python"
    [ -x "$py" ] || py=python3
    # curl 의 종료 코드를 따로 본다. 파이프로 바로 넘기면(pipefail 없음) 본문을 받은 뒤 실패한
    # 응답(exit 18 · 28 등)도 그 본문대로 읽힌다.
    body=$(curl -sf -m 20 -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/${slug}/actions/workflows/main-ci-cd.yml/runs?head_sha=$1&branch=main&per_page=10" 2>/dev/null) \
        || { echo "unreadable"; return; }
    # 판정은 Python 안에서 정확히 비교한다. ("completed", "success") 일 때만 고정 토큰 "green" 을,
    # 그 밖에는 고정 접두사 "hold " 뒤에 repr 로 escape 한 값을 내보낸다 — 응답에서 온 문자열이
    # 출력의 앞머리가 되지 않으니 어떤 값도 "green" 과 같아질 수 없다. bash 쪽에서 비교하거나 값을
    # 그대로 찍으면 $(...) 가 지우는 끝 줄바꿈 · NUL 로 "success\n" 이나 "green\0…" 가 통과했다
    # (#1808 Codex 리뷰가 재현). f-string 을 안 쓰는 건 venv 가 없을 때의 /usr/bin/python3 (3.9) 때문.
    # main 의 런이면 push 든, GITHUB_TOKEN 머지에 main-ci-catchup.yml 이 띄운 workflow_dispatch 든
    # 인정한다 (#1812). 가장 최근 런 하나가 아니라 "그 SHA 의 main 런 중 성공한 것이 있는가" 를
    # 본다 — 취소된 push 런과 성공한 dispatch 런(또는 그 반대)이 같이 있어도 보류가 끝나도록.
    printf '%s' "$body" \
        | "$py" -c 'import json, sys; rs = [r for r in (json.load(sys.stdin).get("workflow_runs") or []) if isinstance(r, dict)]; ok = any((r.get("event") in ("push", "workflow_dispatch"), r.get("head_branch"), r.get("status"), r.get("conclusion")) == (True, "main", "completed", "success") for r in rs); print("green" if ok else "hold " + ("no-run" if not rs else repr(tuple(rs[0].get(k) for k in ("event", "status", "conclusion")))[:80]))' 2>/dev/null \
        || echo "unreadable"
}

CI_VERDICT=$(ci_verdict "$UPSTREAM")
if [ "$CI_VERDICT" != "green" ]; then
    log "hold ${UPSTREAM:0:7}: main CI = ${CI_VERDICT#hold } — 초록이 될 때까지 배포하지 않는다"
    ensure_frontend_build
    exit 0
fi

# ── thesis 채점 배치 보호 (#1989) ────────────────────────────────────────
# 채점 배치(thesis_batches.status='open')가 도는 동안은 이 주기를 통째로 건너뛴다 — pull 도 재기동도 안 한다.
# 재기동은 배치를 중간에 죽이고, pull 만 해도 배치가 늦게 import 하는 모듈과 팔 정의 해시(디스크의 파일을
# 읽는다)가 새 코드로 바뀌어 한 배치 안에 정의가 섞인다. 상한(THESIS_DEFER_HOURS, 기본 6시간)보다 오래 열린
# 배치는 멈춘 것으로 보고 무시한다 — 멈춘 배치가 배포를 영원히 막지 않게. DB 파일이나 테이블이 없으면
# (migration 76 이전) 막지 않는다. 표를 **읽지 못하면**(잠김 · 손상) 보류한다 — 0 으로 떨어뜨리면 열린 배치가
# 있어도 배포해 버린다. sqlite3 CLI 자체가 없으면 보호를 못 하므로 WARN 을 남기고 진행한다(macOS 기본 탑재).
# 시간 값은 SQL 에 들어가므로 1~99 의 정수만 받는다 — 그 밖의 값은 수정자 오류로 0 건을 내거나 질의를 바꾼다.
# 막지 않는 것: 대시보드 빌드·재기동(위 ensure_frontend_build) — pull 도 python 재기동도 아니라 배치와 무관하다.
# Test: tests/scripts/test_autopull_restarts_daemons.py::TestAutopullDefersForAnOpenThesisBatch
THESIS_DEFER_HOURS="${THESIS_DEFER_HOURS:-6}"
if ! [[ "$THESIS_DEFER_HOURS" =~ ^[1-9][0-9]?$ ]]; then
    log "WARN: THESIS_DEFER_HOURS='${THESIS_DEFER_HOURS:0:20}' 무효 — 6 으로 본다"
    THESIS_DEFER_HOURS=6
fi
open_thesis_batches() {
    local db="${NURI_DB_PATH:-$REPO/data/portfolio.db}" out
    [ -f "$db" ] || { echo 0; return; }
    command -v sqlite3 >/dev/null 2>&1 || { echo "no-cli"; return; }
    # 표 이름은 문장 준비 시점에 확인되므로(CASE 로 감싸도 "no such table") 존재 확인을 따로 한다.
    # -readonly · mode=ro 로 열지 않는다(#1995): mini 의 Apple sqlite3 3.51 은 연결이 하나도 없어 -wal/-shm 이
    # 지워진 WAL DB 를 읽기 전용으로 열지 못하고(code 14) 보류가 된다 — 배포가 무작위로 막힌다. 보통으로 열어
    # -shm 을 만들 수 있게 하고, 쓰기는 PRAGMA query_only 로 막는다(sqlite.org/pragma.html#pragma_query_only).
    q() { sqlite3 -cmd ".timeout 5000" -cmd "PRAGMA query_only = ON;" "$db" "$1" 2>&1; }
    out=$(q "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'thesis_batches';") \
        || { echo "unreadable: ${out:0:120}"; return; }
    [ "$out" = "0" ] && { echo 0; return; }
    out=$(q "SELECT COUNT(*) FROM thesis_batches WHERE status = 'open' AND julianday(started_at) > julianday('now', '-${THESIS_DEFER_HOURS} hours');") \
        || { echo "unreadable: ${out:0:120}"; return; }
    [[ "$out" =~ ^[0-9]+$ ]] && echo "$out" || echo "unreadable: ${out:0:120}"
}
OPEN_BATCHES=$(open_thesis_batches)
case "$OPEN_BATCHES" in
    0) ;;
    no-cli) log "WARN: sqlite3 CLI 없음 — thesis 배치 보호 없이 진행" ;;
    unreadable*)
        log "defer ${UPSTREAM:0:7}: thesis_batches ${OPEN_BATCHES} — 읽을 수 있을 때까지 배포하지 않는다"
        exit 0 ;;
    *)
        log "defer ${UPSTREAM:0:7}: thesis batch open (${OPEN_BATCHES}) — 배치가 끝나거나 ${THESIS_DEFER_HOURS}h 가 지나면 배포한다"
        exit 0 ;;
esac

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

# frontend/ 변경은 여기서 보지 않는다 — 맨 아래 ensure_frontend_build 가 커밋 시각 vs 빌드
# 시각으로 판정한다 (package-lock 이 빌드보다 새로우면 npm ci 까지). 파일명 grep 은 소스만 바뀐
# 커밋을 놓친다 — 그게 #1462 의 무신호 경로였다.

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
            #
            # soft-fail 이후에도 **재기동은 한다** — 의도된 선택이다. "구 venv + 새
            # 코드" 에 ImportError 위험이 있는 건 맞지만, 대안(재기동 보류)은 #1017
            # 사고 그대로다: autopull 이 bounce 를 안 해 7일간 구코드로 돌았고 신호가
            # 없었다. 크래시는 KeepAlive·watchdog 이 표면화하지만 침묵은 못 본다.
            # 잠금: tests/scripts/test_autopull_restarts_daemons.py
            #       ::test_daemons_still_restart_when_sync_fails
            # production 의 opt-in GGUF fallback 을 보존한다 (#1406).
            # Test: tests/scripts/test_local_llm_extra.py::TestLocalLlmExtraPolicy::test_deploy_paths_include_local_llm
            log "deps changed → $UV_BIN sync --extra dev --extra local-llm --locked"
            "$UV_BIN" sync --extra dev --extra local-llm --locked >>"$LOG" 2>&1 || log "ERROR: uv sync 실패 — 구 venv 로 재기동된다"
        else
            log "ERROR: uv 를 못 찾음 ($UV_BIN) — deps 미동기화 상태로 재기동한다"
        fi
    fi

    # 상주 python 서비스. plist 판정 기준(StartInterval 없음 + .venv/bin/python)과
    # 일치해야 하며 `tests/scripts/test_deploy_bounces_resident_services.py` 가 대조한다.
    # dashboard 는 빌드 산출물을 서빙하므로 제외 — 재빌드했을 때만 build_frontend.sh 가 재기동한다 (#1462).
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

# ── frontend 빌드 (#1462) ────────────────────────────────────────────────
# python 재기동 **뒤**에 둔다: 빌드가 수십 초 걸리는 동안 데몬이 구코드로 남아 있을 이유가 없다.
ensure_frontend_build
