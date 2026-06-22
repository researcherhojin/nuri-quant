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


def _kickstart_scheduler() -> bool:
    """scheduler 데몬을 강제 재시작(kickstart -k). 성공 시 True.

    stale 의 주원인은 fd 고갈로 인한 hung heartbeat 이므로, 알림과 함께
    데몬을 재시작해 자동 복구한다(외근 중 수동 개입 불가 대비). 재시작 후
    heartbeat 는 ~45초 내 갱신되므로 15분 간격 watchdog 에서 restart-loop 없음.
    """
    target = f"gui/{os.getuid()}/{SCHEDULER_LABEL}"
    try:
        proc = subprocess.run(
            ["launchctl", "kickstart", "-k", target],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as e:  # launchctl 부재(비배포 환경)/타임아웃 — 알림은 계속 진행
        print(f"auto-restart 호출 실패: {e}", file=sys.stderr)
        return False
    if proc.returncode == 0:
        return True
    print(f"auto-restart launchctl rc={proc.returncode}: {proc.stderr.strip()}", file=sys.stderr)
    return False


def heartbeat_age_minutes(path: Path | None = None, now_epoch: float | None = None) -> float | None:
    """heartbeat 파일 mtime 의 age(분) 반환. 파일 미존재 시 None (미배포 환경 → skip)."""
    p = path or HEARTBEAT_PATH
    if not p.exists():
        return None
    now = now_epoch if now_epoch is not None else time.time()
    return (now - p.stat().st_mtime) / 60.0


def main() -> int:
    """exit code: 0 = OK/skip, 2 = stale (alert 시도). DB·scheduler 미접근."""
    age = heartbeat_age_minutes()
    if age is None:
        print(f"heartbeat 파일 없음 ({HEARTBEAT_PATH}) — skip (미배포 환경)")
        return 0
    if age <= STALE_THRESHOLD_MIN:
        print(f"heartbeat OK ({age:.1f}분, 임계 {STALE_THRESHOLD_MIN:.0f}분)")
        return 0

    # stale 감지 → 데몬 자동 재시작 후 결과를 알림에 포함.
    restarted = _kickstart_scheduler()
    restart_note = (
        "🔄 자동 재시작 완료 (`launchctl kickstart -k`) — heartbeat 곧 갱신."
        if restarted
        else "⚠️ 자동 재시작 실패 — 수동 확인: `launchctl kickstart -k gui/$(id -u)/com.nuri-quant.scheduler`"
    )
    msg = (
        f"🔴 **스케줄러 heartbeat STALE** — {age:.0f}분째 갱신 없음 "
        f"(임계 {STALE_THRESHOLD_MIN:.0f}분). 데이터 수집 중단 의심.\n"
        f"{restart_note}\n"
        f"[{kst_now().strftime('%Y-%m-%d %H:%M KST')}]"
    )
    webhook_url = _resolve_webhook_url()
    try:
        sent = send_webhook_text(msg, webhook_url=webhook_url)
    except Exception as e:  # 네트워크/webhook 실패도 outage 신호 — 삼키지 말고 surface
        print(f"STALE detected ({age:.1f}분) but webhook FAILED: {e}", file=sys.stderr)
        return 2
    print(f"STALE alert {'sent' if sent else 'NOT sent (no webhook url)'} ({age:.1f}분)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
