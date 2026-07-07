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

import os
import subprocess
import sys
import time
from pathlib import Path

from nuri.alerts.discord_bot import send_webhook_text
from nuri.core.timezone import kst_now

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


def check_services(recheck_delay_s: float = SERVICE_RECHECK_DELAY_S) -> list[str]:
    """로드된 표출 서비스의 포트가 재확인에도 닫혀 있으면 알림 라인 반환 (#826/#857).

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

    problems: list[str] = []
    for label, port in down:
        if _port_open(port):
            continue  # 재확인 시 복구 = 부팅 중이었음 (오탐 아님)
        short = label.removeprefix("com.nuri-quant.")
        problems.append(
            f"🔴 **{short} DOWN** — 127.0.0.1:{port} {recheck_delay_s:.0f}s 재확인에도 무응답 "
            f"(launchd 로드 상태, KeepAlive 자동복구 실패 의심). "
            f"수동 확인: `launchctl kickstart -k gui/$(id -u)/{label}`"
        )
    return problems


def heartbeat_age_minutes(path: Path | None = None, now_epoch: float | None = None) -> float | None:
    """heartbeat 파일 mtime 의 age(분) 반환. 파일 미존재 시 None (미배포 환경 → skip)."""
    p = path or HEARTBEAT_PATH
    if not p.exists():
        return None
    now = now_epoch if now_epoch is not None else time.time()
    return (now - p.stat().st_mtime) / 60.0


def main() -> int:
    """exit code: 0 = OK/skip, 2 = 이상 감지 (alert 시도). DB·scheduler 미접근."""
    alerts: list[str] = []

    age = heartbeat_age_minutes()
    if age is None:
        print(f"heartbeat 파일 없음 ({HEARTBEAT_PATH}) — skip (미배포 환경)")
    elif age <= STALE_THRESHOLD_MIN:
        print(f"heartbeat OK ({age:.1f}분, 임계 {STALE_THRESHOLD_MIN:.0f}분)")
    else:
        # stale 감지 → 데몬 자동 재시작 후 결과를 알림에 포함.
        restarted = _kickstart_scheduler()
        restart_note = (
            "🔄 자동 재시작 완료 (`launchctl kickstart -k`) — heartbeat 곧 갱신."
            if restarted
            else "⚠️ 자동 재시작 실패 — 수동 확인: `launchctl kickstart -k gui/$(id -u)/com.nuri-quant.scheduler`"
        )
        alerts.append(
            f"🔴 **스케줄러 heartbeat STALE** — {age:.0f}분째 갱신 없음 "
            f"(임계 {STALE_THRESHOLD_MIN:.0f}분). 데이터 수집 중단 의심.\n{restart_note}"
        )

    # 표출 계층 (API/dashboard) 포트 감시 — 미설치 머신은 내부에서 skip (#826).
    alerts.extend(check_services())

    if not alerts:
        return 0

    msg = "\n".join(alerts) + f"\n[{kst_now().strftime('%Y-%m-%d %H:%M KST')}]"
    webhook_url = _resolve_webhook_url()
    try:
        sent = send_webhook_text(msg, webhook_url=webhook_url)
    except Exception as e:  # 네트워크/webhook 실패도 outage 신호 — 삼키지 말고 surface
        print(f"이상 감지 but webhook FAILED: {e}", file=sys.stderr)
        return 2
    print(f"alert {'sent' if sent else 'NOT sent (no webhook url)'} — {len(alerts)}건")
    return 2


if __name__ == "__main__":
    sys.exit(main())
