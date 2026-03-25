"""
IRIS 스케줄러 — APScheduler 기반 작업 자동화.

crontab.txt 대체. Python 네이티브로 모든 정기 작업을 스케줄링.
Mac Mini에서 `python -m nuri.scheduler`로 24/7 운영.

사용법:
    python -m nuri.scheduler              # 실행
    python -m nuri.scheduler --dry-run    # 등록된 작업 확인만
"""
import argparse
import logging
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("nuri.scheduler")


def _run_collector(name: str, **kwargs):
    """Collector를 안전하게 실행."""
    try:
        if name == "stock":
            from nuri.collectors.stock import StockCollector
            StockCollector().run(**kwargs)
        elif name == "stock_kr":
            from nuri.collectors.stock_kr import StockKRCollector
            StockKRCollector().run(**kwargs)
        elif name == "macro":
            from nuri.collectors.macro import MacroCollector
            MacroCollector().run()
        elif name == "technical":
            from nuri.collectors.technical import TechnicalCollector
            TechnicalCollector().run()
        elif name == "fear_greed":
            from nuri.collectors.fear_greed import FearGreedCollector
            FearGreedCollector().run()
        elif name == "ark":
            from nuri.collectors.ark import ARKCollector
            ARKCollector().run()
        elif name == "events":
            from nuri.collectors.events import EventsCollector
            EventsCollector().run()
        elif name == "news":
            from nuri.collectors.news import NewsCollector
            NewsCollector().run()
    except Exception as e:
        logger.error(f"[{name}] 실행 실패: {e}", exc_info=True)


def _run_report():
    """일일 리포트를 안전하게 실행."""
    try:
        from nuri.alerts.daily_report import main as report_main
        report_main()
    except Exception as e:
        logger.error(f"[daily_report] 실행 실패: {e}", exc_info=True)


def _run_backup():
    """DB 백업을 안전하게 실행."""
    import subprocess
    try:
        subprocess.run(["bash", "scripts/backup.sh"], check=True)
    except Exception as e:
        logger.error(f"[backup] 실행 실패: {e}", exc_info=True)


# ═══════════════════════════════════════════════════════
# 스케줄 정의
# ═══════════════════════════════════════════════════════

SCHEDULES = [
    # 미국장 주가 (KST 23:30~06:00, 5분)
    {"name": "stock_us_night", "func": _run_collector, "args": ("stock",),
     "cron": "*/5 23 * * 1-5"},
    {"name": "stock_us_dawn", "func": _run_collector, "args": ("stock",),
     "cron": "*/5 0-6 * * 2-6"},

    # 한국장 주가 (KST 09:00~15:30, 5분)
    {"name": "stock_kr", "func": _run_collector, "args": ("stock_kr",),
     "cron": "*/5 9-15 * * 1-5"},

    # 매크로 (매시)
    {"name": "macro", "func": _run_collector, "args": ("macro",),
     "cron": "0 * * * *"},

    # 기술적 지표 (미장 마감 후 07:00)
    {"name": "technical", "func": _run_collector, "args": ("technical",),
     "cron": "0 7 * * 2-6"},

    # Fear & Greed (매일 08:00)
    {"name": "fear_greed", "func": _run_collector, "args": ("fear_greed",),
     "cron": "0 8 * * *"},

    # ARK 매매 (미장 마감 후 07:30)
    {"name": "ark", "func": _run_collector, "args": ("ark",),
     "cron": "30 7 * * 2-6"},

    # 이벤트 캘린더 (매일 07:00)
    {"name": "events", "func": _run_collector, "args": ("events",),
     "cron": "0 7 * * *"},

    # 뉴스 (6시간)
    {"name": "news", "func": _run_collector, "args": ("news",),
     "cron": "0 */6 * * *"},

    # 일일 리포트 (매일 08:00)
    {"name": "daily_report", "func": _run_report, "args": (),
     "cron": "0 8 * * *"},

    # DB 백업 (매일 자정)
    {"name": "backup", "func": _run_backup, "args": (),
     "cron": "0 0 * * *"},
]


def create_scheduler() -> BlockingScheduler:
    """스케줄러 생성 및 작업 등록."""
    scheduler = BlockingScheduler()

    for job in SCHEDULES:
        trigger = CronTrigger.from_crontab(job["cron"])
        scheduler.add_job(
            job["func"],
            trigger=trigger,
            args=job.get("args", ()),
            id=job["name"],
            name=job["name"],
            misfire_grace_time=300,  # 5분 유예
        )

    return scheduler


def print_schedule():
    """등록된 스케줄 출력."""
    print(f"\n{'=' * 60}")
    print(f"  IRIS Scheduler — {len(SCHEDULES)}개 작업 등록")
    print(f"{'=' * 60}")
    for job in SCHEDULES:
        print(f"  {job['name']:<20} {job['cron']}")
    print()


def main():
    parser = argparse.ArgumentParser(description="IRIS 스케줄러")
    parser.add_argument("--dry-run", action="store_true", help="작업 목록만 출력")
    args = parser.parse_args()

    if args.dry_run:
        print_schedule()
        return

    scheduler = create_scheduler()

    # SIGINT/SIGTERM으로 안전 종료
    def shutdown(signum, frame):
        logger.info("스케줄러 종료 중...")
        scheduler.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info(f"IRIS 스케줄러 시작 ({len(SCHEDULES)}개 작업)")
    print_schedule()
    scheduler.start()


if __name__ == "__main__":
    main()
