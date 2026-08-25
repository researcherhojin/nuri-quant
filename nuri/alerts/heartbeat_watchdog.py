"""스케줄러 heartbeat staleness watchdog — DB·scheduler 무의존 독립 감시.

독립 launchd job (`com.nuri-quant.heartbeat-watchdog`, 15분 간격) 으로 실행.
`data/.scheduler_heartbeat` mtime 이 임계값보다 오래되면 Discord webhook 으로
직접 알림한다.

왜 SRE incident agent 와 별도인가:
  SREIncidentAgent 도 heartbeat staleness 를 탐지하지만, `_record_incident` 가
  **DB INSERT 성공 후에만** alert 를 publish 한다. DB 장애(`unable to open
  database file`) 가 곧 outage 인 경우 incident 기록 자체가 실패해 알림이 영영
  안 간다 — 자기감시가 가장 잘 죽는 서브시스템(DB)에 의존하는 chicken-and-egg.
  본 watchdog 은 파일 mtime + webhook 만 사용 (DB·scheduler 무의존) 하므로
  DB 장애나 scheduler 데몬 사망 같은 outage 자체를 잡는다.
  (2026-06-09 6일 silent outage 교훈 — heartbeat 가 6일 stale 인데 무알림.)

Usage:
    python -m nuri.alerts.heartbeat_watchdog
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from nuri.alerts.discord_bot import send_webhook_text
from nuri.core.timezone import kst_now


def _log(msg: str, err: bool = False) -> None:
    """타임스탬프 포함 로그 — 2026-08-25 42h 공백을 watchdog 로그로 재구성할 수
    없었던 이유가 무(無)타임스탬프였다 (#1190)."""
    print(f"[{kst_now().strftime('%Y-%m-%d %H:%M:%S KST')}] {msg}", file=sys.stderr if err else sys.stdout)


# 시스템 알림 컨벤션: per-channel webhook (DiscordPublisher Channel enum).
# heartbeat stale = 운영 incident → INCIDENTS 채널 우선. 빈 값이면 OPS → 범용 URL 순.
# generic DISCORD_WEBHOOK_URL 은 빈 값으로 두고 채널별 webhook 을 쓰는 배포가 정상.
_WEBHOOK_ENV_PRIORITY = ("DISCORD_WEBHOOK_INCIDENTS", "DISCORD_WEBHOOK_OPS", "DISCORD_WEBHOOK_URL")


def _resolve_webhook_url() -> str | None:
    """설정된(non-empty) per-channel webhook 을 우선순위대로 탐색."""
    for key in _WEBHOOK_ENV_PRIORITY:
        val = os.getenv(key, "").strip()
        if val:
            return val
    return None


# repo_root/data/.scheduler_heartbeat — heartbeat 는 1분 간격 기록 (nuri/scheduler.py).
HEARTBEAT_PATH = Path(__file__).resolve().parents[2] / "data" / ".scheduler_heartbeat"

# 30분 이상 stale 이면 alert. sre_incident_agent.SCHEDULER_WARN_MIN 과 동일값 유지.
STALE_THRESHOLD_MIN = 30.0

#: 원장 백업 디렉터리 + 경고 임계. 백업은 일 1회(cron `0 0 * * *`)라 48h 는
#: "하루 걸러도 봐주되 이틀은 아니다" 선 (#835 acceptance).
BACKUP_DIR = Path(__file__).resolve().parents[2] / "data" / "backups"
BACKUP_STALE_THRESHOLD_H = 48.0

# 자동 재시작 대상 launchd label. fd 누수(파일 디스크립터 고갈)로 데몬이 살아있되
# heartbeat 만 멈추는 경우 KeepAlive 는 무력(크래시 아님) — kickstart -k 만 fd 를 회수.
SCHEDULER_LABEL = "com.nuri-quant.scheduler"

# 표출 계층 포트 감시 대상 (#826) — launchd 에 로드된 머신(production)에서만 검사.
# api/dashboard 는 KeepAlive=true → launchd 가 크래시 자동복구. watchdog 은 kickstart
# 하지 않고 알림만 한다 (#857): kickstart -k 는 부팅 중 정상 프로세스까지 죽였고
# (2026-07-08 02:39 오탐), crash-loop 는 kickstart 로도 해결 안 되며, uvicorn/next 에
# 실질적 hung(포트 미바인딩 좀비)은 발생하지 않는다. scheduler 는 heartbeat 경로라
# fd 누수 hung 대비 kickstart 유지(별도).
SERVICE_PORTS: dict[str, int] = {
    "com.nuri-quant.api": int(os.getenv("API_PORT", "8001")),
    "com.nuri-quant.dashboard": int(os.getenv("FRONTEND_PORT", "3000")),
}

# 포트 down 판정 전 재확인 간격 (초) — 부팅/일시 미바인딩 흡수 (#857).
# 최초 launchd 설치 직후 uvicorn 부팅(SPY freshness 체크 등)이 수십초 걸려
# 단발 체크가 DOWN 오판하던 문제. 15분 주기 watchdog 에 재확인 sleep 은 무해.
SERVICE_RECHECK_DELAY_S = 15.0

#: 같은 카테고리의 재알림 쿨다운 (#1190). 2026-08-25 백업 stale 이 15분마다
#: 같은 알림을 다시 보내 incidents 채널을 도배했다 — 최초 감지는 즉시,
#: 조건이 지속되는 동안은 이 간격으로만 재알림. 복구되면 상태를 지워
#: 다음 incident 는 다시 즉시 알림된다.
REALERT_COOLDOWN_H = 6.0

#: 카테고리별 마지막 발송 시각 상태 파일 — heartbeat 파일과 같은 철학
#: (DB 무의존, 파일 하나). 깨진/없는 파일은 빈 상태로 취급 (fail-open: 알림).
ALERT_STATE_PATH = Path(__file__).resolve().parents[2] / "data" / ".watchdog_alert_state.json"


def _load_alert_state(path: Path | None = None) -> dict[str, float]:
    p = path or ALERT_STATE_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in data.items()}
    except Exception:  # 부재/corrupt — 억제보다 알림이 안전하다 (fail-open)
        return {}


def _save_alert_state(state: dict[str, float], path: Path | None = None) -> None:
    p = path or ALERT_STATE_PATH
    try:
        p.write_text(json.dumps(state), encoding="utf-8")
    except Exception as e:  # 상태 저장 실패는 억제 실패일 뿐 — 알림 자체를 막지 않는다
        _log(f"alert state 저장 실패 (무시): {e}", err=True)


def _kickstart(label: str) -> bool:
    """launchd job 강제 재시작(kickstart -k). 성공 시 True.

    stale 의 주원인은 fd 고갈로 인한 hung 상태이므로, 알림과 함께 데몬을
    재시작해 자동 복구한다(외근 중 수동 개입 불가 대비).
    """
    target = f"gui/{os.getuid()}/{label}"
    try:
        proc = subprocess.run(
            ["launchctl", "kickstart", "-k", target],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as e:  # launchctl 부재(비배포 환경)/타임아웃 — 알림은 계속 진행
        print(f"auto-restart 호출 실패 ({label}): {e}", file=sys.stderr)
        return False
    if proc.returncode == 0:
        return True
    print(f"auto-restart launchctl rc={proc.returncode} ({label}): {proc.stderr.strip()}", file=sys.stderr)
    return False


def _kickstart_scheduler() -> bool:
    """scheduler 데몬 재시작 — 재시작 후 heartbeat 는 ~45초 내 갱신되므로
    15분 간격 watchdog 에서 restart-loop 없음."""
    return _kickstart(SCHEDULER_LABEL)


def _label_loaded(label: str) -> bool:
    """launchd 에 해당 label 이 로드돼 있으면 True — 미설치 머신(dev)은 감시 skip."""
    try:
        proc = subprocess.run(
            ["launchctl", "list", label],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:  # launchctl 부재 (CI/linux) — 미배포 취급
        return False
    return proc.returncode == 0


def _port_open(port: int, timeout_s: float = 3.0) -> bool:
    """127.0.0.1:port TCP 연결 가능 여부 — DB·HTTP 스택 무의존 (socket 만)."""
    import socket

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout_s):
            return True
    except OSError:
        return False


def check_services(recheck_delay_s: float = SERVICE_RECHECK_DELAY_S) -> list[tuple[str, str]]:
    """로드된 표출 서비스의 포트가 재확인에도 닫혀 있으면 (category, 알림 라인) 반환 (#826/#857).

    category (`service:<short>`) 는 재알림 쿨다운의 dedup 키다 (#1190).

    heartbeat 감시와 동일 철학: launchctl + socket 만 사용 (DB 무의존).
    launchd 미설치 머신(dev MBP)은 label 미로드로 자동 skip — 환경 분기 불필요.

    KeepAlive 서비스이므로 kickstart 하지 않는다 (launchd 가 크래시 복구 담당).
    부팅/일시 미바인딩 오탐 방지 위해 `recheck_delay_s` 후 재확인 — 그 사이 포트가
    열리면(부팅 중이었음) 알림 없음. 재확인에도 닫혀 있으면 launchd 도 못 살리는
    상태(crash-loop 등)이므로 수동 확인을 안내한다.
    """
    down = [(label, port) for label, port in SERVICE_PORTS.items() if _label_loaded(label) and not _port_open(port)]
    if not down:
        return []

    # 부팅/일시 미바인딩 흡수 — 재확인 전 대기 (테스트는 0 주입).
    if recheck_delay_s > 0:
        time.sleep(recheck_delay_s)

    problems: list[tuple[str, str]] = []
    for label, port in down:
        if _port_open(port):
            continue  # 재확인 시 복구 = 부팅 중이었음 (오탐 아님)
        short = label.removeprefix("com.nuri-quant.")
        problems.append(
            (
                f"service:{short}",
                f"🔴 **{short} DOWN** — 127.0.0.1:{port} {recheck_delay_s:.0f}s 재확인에도 무응답 "
                f"(launchd 로드 상태, KeepAlive 자동복구 실패 의심). "
                f"수동 확인: `launchctl kickstart -k gui/$(id -u)/{label}`",
            )
        )
    return problems


def backup_age_hours(backup_dir: Path | None = None, now_epoch: float | None = None) -> float | None:
    """최신 원장 백업의 age(시간). 디렉터리/백업 미존재 시 None (미배포 환경 → skip).

    §3.11 원장은 Mac mini 단일본이라 백업이 유일한 안전망이다. 백업 job 은
    scheduler 안에서 돌기 때문에 scheduler 가 죽으면 heartbeat 와 **함께** 멈춘다
    — 즉 heartbeat 감시만으로는 "백업이 며칠째 안 돌았다" 를 따로 못 잡는다
    (2026-04-30 ~ 07-08, #557 경로 drift 로 백업이 두 달 넘게 조용히 실패한 전력).
    """
    d = backup_dir or BACKUP_DIR
    if not d.is_dir():
        return None
    snapshots = list(d.glob("portfolio_*.db"))
    if not snapshots:
        return None
    newest = max(s.stat().st_mtime for s in snapshots)
    now = now_epoch if now_epoch is not None else time.time()
    return (now - newest) / 3600.0


def heartbeat_age_minutes(path: Path | None = None, now_epoch: float | None = None) -> float | None:
    """heartbeat 파일 mtime 의 age(분) 반환. 파일 미존재 시 None (미배포 환경 → skip)."""
    p = path or HEARTBEAT_PATH
    if not p.exists():
        return None
    now = now_epoch if now_epoch is not None else time.time()
    return (now - p.stat().st_mtime) / 60.0


def main() -> int:
    """exit code: 0 = OK/skip, 2 = 이상 감지 (억제 여부와 무관). DB·scheduler 미접근.

    재알림 쿨다운 (#1190): 최초 감지는 즉시 알림, 조건이 지속되는 동안은
    카테고리별 `REALERT_COOLDOWN_H` 간격으로만 재알림. 복구된 카테고리는
    상태에서 지워 다음 incident 가 다시 즉시 알림되게 한다. kickstart 등
    자동 복구 동작은 억제 대상이 아니다 — 억제되는 건 Discord 메시지뿐.
    """
    alerts: list[tuple[str, str]] = []

    age = heartbeat_age_minutes()
    if age is None:
        _log(f"heartbeat 파일 없음 ({HEARTBEAT_PATH}) — skip (미배포 환경)")
    elif age <= STALE_THRESHOLD_MIN:
        _log(f"heartbeat OK ({age:.1f}분, 임계 {STALE_THRESHOLD_MIN:.0f}분)")
    else:
        # stale 감지 → 데몬 자동 재시작 후 결과를 알림에 포함.
        restarted = _kickstart_scheduler()
        restart_note = (
            "🔄 자동 재시작 완료 (`launchctl kickstart -k`) — heartbeat 곧 갱신."
            if restarted
            else "⚠️ 자동 재시작 실패 — 수동 확인: `launchctl kickstart -k gui/$(id -u)/com.nuri-quant.scheduler`"
        )
        alerts.append(
            (
                "heartbeat",
                f"🔴 **스케줄러 heartbeat STALE** — {age:.0f}분째 갱신 없음 "
                f"(임계 {STALE_THRESHOLD_MIN:.0f}분). 데이터 수집 중단 의심.\n{restart_note}",
            )
        )

    # 원장 백업 나이 감시 (#835). scheduler 와 독립적으로 파일 mtime 만 보므로
    # scheduler 가 죽어도, 백업 job 만 조용히 실패해도 둘 다 여기서 잡힌다.
    b_age = backup_age_hours()
    if b_age is None:
        _log(f"백업 없음 ({BACKUP_DIR}) — skip (미배포 환경)")
    elif b_age <= BACKUP_STALE_THRESHOLD_H:
        _log(f"backup OK ({b_age:.1f}시간, 임계 {BACKUP_STALE_THRESHOLD_H:.0f}시간)")
    else:
        alerts.append(
            (
                "backup",
                f"🔴 **원장 백업 STALE** — 최신 스냅샷이 {b_age:.0f}시간 전 "
                f"(임계 {BACKUP_STALE_THRESHOLD_H:.0f}시간). §3.11 판정 원장은 이 머신 단일본이라 "
                f"백업이 유일한 안전망이다.\n"
                f"확인: `tail -20 data/logs/scheduler.log | grep backup` · "
                f"수동 실행: `bash scripts/db/backup.sh`",
            )
        )

    # 표출 계층 (API/dashboard) 포트 감시 — 미설치 머신은 내부에서 skip (#826).
    alerts.extend(check_services())

    state = _load_alert_state()
    firing = {cat for cat, _ in alerts}
    # 복구된 카테고리는 상태에서 제거 — 다음 incident 는 즉시 알림
    recovered = set(state) - firing
    for cat in recovered:
        del state[cat]

    if not alerts:
        if recovered:
            _save_alert_state(state)
        return 0

    now = time.time()
    cooldown_s = REALERT_COOLDOWN_H * 3600.0
    due = [(cat, text) for cat, text in alerts if now - state.get(cat, 0.0) >= cooldown_s]
    suppressed = len(alerts) - len(due)

    if not due:
        _save_alert_state(state)  # recovered 반영
        _log(f"이상 {len(alerts)}건 지속 — 쿨다운({REALERT_COOLDOWN_H:.0f}h) 내 재알림 억제")
        return 2

    msg = "\n".join(text for _, text in due) + f"\n[{kst_now().strftime('%Y-%m-%d %H:%M KST')}]"
    webhook_url = _resolve_webhook_url()
    try:
        sent = send_webhook_text(msg, webhook_url=webhook_url)
    except Exception as e:  # 네트워크/webhook 실패도 outage 신호 — 삼키지 말고 surface
        # recovered 정리는 발송 실패와 무관하게 저장 — 안 하면 복구됐던 카테고리의
        # 옛 타임스탬프가 남아, 웹훅 복구 후 **새** incident 가 재알림으로 오인돼
        # 쿨다운에 억제된다 (#1190 Codex P2).
        _save_alert_state(state)
        _log(f"이상 감지 but webhook FAILED: {e}", err=True)
        return 2
    if sent:
        for cat, _ in due:
            state[cat] = now
    _save_alert_state(state)
    _log(f"alert {'sent' if sent else 'NOT sent (no webhook url)'} — {len(due)}건 (억제 {suppressed}건)")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
