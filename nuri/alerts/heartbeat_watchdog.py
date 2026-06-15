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

    msg = (
        f"🔴 **스케줄러 heartbeat STALE** — {age:.0f}분째 갱신 없음 "
        f"(임계 {STALE_THRESHOLD_MIN:.0f}분). 데이터 수집 중단 의심.\n"
        f"확인: `launchctl kickstart -k gui/$(id -u)/com.nuri-quant.scheduler`\n"
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
