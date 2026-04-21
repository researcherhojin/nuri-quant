"""
Nuri-Quant 스케줄러 — APScheduler 기반 작업 자동화.

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
from pathlib import Path

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
        elif name == "macro_news":
            from nuri.collectors.macro_news import MacroNewsCollector
            MacroNewsCollector().run()
        elif name == "fundamental":
            from nuri.collectors.fundamental import FundamentalCollector
            FundamentalCollector().run()
        elif name == "superinvestors":
            from nuri.collectors.superinvestors import SuperinvestorCollector
            SuperinvestorCollector().run()
        elif name == "estimates":
            from nuri.collectors.estimates import EstimatesCollector
            EstimatesCollector().run()
        elif name == "etf_flows":
            from nuri.collectors.etf_flows import EtfFlowsCollector
            EtfFlowsCollector().run()
        elif name == "wallstreet":
            from nuri.collectors.wallstreet import WallStreetCollector
            WallStreetCollector().run()
        elif name == "memory_snapshot":
            from nuri.trading.engine.memory import save_snapshot
            n = save_snapshot()
            logger.info(f"[memory_snapshot] {n}건 저장")
        elif name == "decision_outcomes":
            from nuri.trading.engine.decisions import track_decision_outcomes
            n = track_decision_outcomes()
            logger.info(f"[decision_outcomes] {n}건 업데이트")
        elif name == "agent_accuracy":
            from nuri.trading.engine.decisions import save_agent_accuracy_snapshot
            n = save_agent_accuracy_snapshot()
            logger.info(f"[agent_accuracy] {n}건 저장")
        elif name == "consensus":
            # 10-agent 합의 결과를 recommendations 에 저장 → Learning Memory 자동 학습 input.
            # decision_outcomes 가 30 일 후 outcome_30d 채우면 _compute_weights 가 가중치 조정.
            from nuri.trading.agents.consensus import analyze_portfolio, save_to_recommendations
            results = analyze_portfolio()
            saved = save_to_recommendations(results)
            logger.info(f"[consensus] {len(results)}건 분석, {saved}건 저장")
    except Exception as e:
        logger.error(f"[{name}] 실행 실패: {e}", exc_info=True)


def _run_premarket_brief():
    """Pre-market brief (DST-aware, US/Eastern tz). PR #TBD.

    사용자 명령 없이도 매일 자동 실행되는 판단 trigger. 생성 실패해도
    scheduler 다음 job 영향 없게 exception 흡수.
    """
    try:
        from nuri.alerts.premarket_brief import main as brief_main
        brief_main([])
    except Exception as e:
        logger.error(f"[premarket_brief] 실행 실패: {e}", exc_info=True)


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


def _run_db_maintenance():
    """DB 유지보수 — 오래된 데이터 정리 + VACUUM."""
    try:
        from scripts.db_maintenance import run_maintenance
        run_maintenance()
    except Exception as e:
        logger.error(f"[db_maintenance] 실행 실패: {e}", exc_info=True)


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

    # 뉴스 (1시간 — SaveTicker 대체)
    {"name": "news", "func": _run_collector, "args": ("news",),
     "cron": "0 * * * *"},

    # 매크로 뉴스 (KST 08:00, 14:00, 20:00 — 시장 영향 큰 이벤트만)
    {"name": "macro_news", "func": _run_collector, "args": ("macro_news",),
     "cron": "0 8,14,20 * * *"},

    # 펀더멘탈 (주 1회 일요일 00:00)
    {"name": "fundamental", "func": _run_collector, "args": ("fundamental",),
     "cron": "0 0 * * 0"},

    # 슈퍼투자자 13F (주 1회 일요일 01:00)
    {"name": "superinvestors", "func": _run_collector, "args": ("superinvestors",),
     "cron": "0 1 * * 0"},

    # 애널리스트 컨센서스 (주 1회 일요일 02:00)
    {"name": "estimates", "func": _run_collector, "args": ("estimates",),
     "cron": "0 2 * * 0"},

    # ETF 자금흐름 (주 1회 일요일 03:00)
    {"name": "etf_flows", "func": _run_collector, "args": ("etf_flows",),
     "cron": "0 3 * * 0"},

    # Wall Street 데이터 (주 1회 일요일 03:30)
    {"name": "wallstreet", "func": _run_collector, "args": ("wallstreet",),
     "cron": "30 3 * * 0"},

    # Learning Memory 스냅샷 (주 1회 일요일 04:00)
    {"name": "memory_snapshot", "func": _run_collector, "args": ("memory_snapshot",),
     "cron": "0 4 * * 0"},

    # Decision outcome 추적 (매일 07:00 — 시장 개장 전)
    {"name": "decision_outcomes", "func": _run_collector, "args": ("decision_outcomes",),
     "cron": "0 7 * * *"},

    # 10-agent consensus (매일 07:05 — technical 07:00 완료 후, daily_report 08:00 전).
    # agent_verdicts 를 recommendations 테이블에 쌓아 Learning Memory 가 30 일 후 학습.
    # Phase 2 A-1a (PR #361) 의 read path fix 를 활용하려면 input 이 꾸준히 쌓여야 함.
    {"name": "consensus", "func": _run_collector, "args": ("consensus",),
     "cron": "5 7 * * *"},

    # Agent accuracy 스냅샷 (주 1회 일요일 08:00)
    {"name": "agent_accuracy", "func": _run_collector, "args": ("agent_accuracy",),
     "cron": "0 8 * * 0"},

    # 일일 리포트 (매일 08:00)
    {"name": "daily_report", "func": _run_report, "args": (),
     "cron": "0 8 * * *"},

    # Pre-market brief (평일 US/Eastern 09:00 — pre-market 30분 전).
    # DST-aware: tz="US/Eastern" 지정해 EDT/EST 전환 자동 처리 (codex Plan 권고).
    # EDT 기간 (3월~11월 초) KST 22:00, EST 기간 (11월 초~3월) KST 23:00.
    # 사용자 명령 없이도 매일 판단 trigger — session-start 에서 Claude 가
    # 이 brief 를 pick up 해 qualitative 뉴스와 cross-ref.
    {"name": "premarket_brief", "func": _run_premarket_brief, "args": (),
     "cron": "0 9 * * 1-5", "tz": "US/Eastern"},

    # DB 백업 (매일 자정)
    {"name": "backup", "func": _run_backup, "args": (),
     "cron": "0 0 * * *"},

    # DB 유지보수 (일요일 새벽 3시)
    {"name": "db_maintenance", "func": _run_db_maintenance, "args": (),
     "cron": "0 3 * * 0"},

    # Universe 1y backfill — US (일요일 새벽 5시, KST quiet window)
    # 기존 stock_us_night/dawn 은 source="portfolio" 기본으로 universe-only
    # 신규 ticker 를 수집하지 않음. 주 1회 1년치 + source="all" 로 gap 채움.
    # universe-only 730개 ticker 가 1-7일 stale 로 누적되는 현상 방지.
    {"name": "stock_us_backfill", "func": _run_collector, "args": ("stock",),
     "kwargs": {"period": "1y", "source": "all"},
     "cron": "0 5 * * 0"},

    # Universe 1y backfill — KR (일요일 새벽 5시 30분)
    # stock_kr 는 days= kwarg 사용. pykrx sequential + 0.1s delay 이미 내장.
    {"name": "stock_kr_backfill", "func": _run_collector, "args": ("stock_kr",),
     "kwargs": {"days": 365, "source": "all"},
     "cron": "30 5 * * 0"},
]


HEARTBEAT_PATH = Path(__file__).parent.parent / "data" / ".scheduler_heartbeat"


def _write_heartbeat():
    """heartbeat 파일에 현재 시각 기록 (API health check용)."""
    try:
        from nuri.core.timezone import kst_now
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_PATH.write_text(kst_now().strftime("%Y-%m-%dT%H:%M:%S"))
    except Exception:
        pass


def create_scheduler() -> BlockingScheduler:
    """스케줄러 생성 및 작업 등록."""
    scheduler = BlockingScheduler()

    for job in SCHEDULES:
        # tz kwarg optional — CronTrigger.from_crontab 은 tz 를 직접 지원 안 함.
        # tz 지정 job 은 CronTrigger() 직접 호출 (codex Plan: DST-aware).
        # ⚠️ WEEKDAY SEMANTICS — APScheduler CronTrigger 는 `day_of_week="0-6"`
        # 를 **Mon=0, Sun=6** 로 해석 (crontab standard 0=Sun 아님). 따라서
        # crontab literal `1-5` 를 그대로 넘기면 Tue-Sat 로 fire 됨 (codex
        # #432 Review). 안전하게 `mon-fri` 같은 명시적 literal 사용.
        if "tz" in job:
            import pytz
            parts = job["cron"].split()
            dow_raw = parts[4]
            dow_map = {
                "0": "sun", "1": "mon", "2": "tue", "3": "wed",
                "4": "thu", "5": "fri", "6": "sat",
                "1-5": "mon-fri", "0-6": "mon-sun", "*": "*",
            }
            dow = dow_map.get(dow_raw, dow_raw)
            trigger = CronTrigger(
                minute=parts[0], hour=parts[1], day=parts[2],
                month=parts[3], day_of_week=dow,
                timezone=pytz.timezone(job["tz"]),
            )
        else:
            trigger = CronTrigger.from_crontab(job["cron"])
        scheduler.add_job(
            job["func"],
            trigger=trigger,
            args=job.get("args", ()),
            kwargs=job.get("kwargs", {}),
            id=job["name"],
            name=job["name"],
            misfire_grace_time=300,  # 5분 유예
        )

    # heartbeat (1분 간격)
    scheduler.add_job(_write_heartbeat, "interval", minutes=1, id="heartbeat", name="heartbeat")

    return scheduler


def print_schedule():
    """등록된 스케줄 출력."""
    print(f"\n{'=' * 60}")
    print(f"  Nuri-Quant Scheduler — {len(SCHEDULES)}개 작업 등록")
    print(f"{'=' * 60}")
    for job in SCHEDULES:
        tz = f" ({job['tz']})" if "tz" in job else ""
        print(f"  {job['name']:<22} {job['cron']}{tz}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Nuri-Quant 스케줄러")
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

    logger.info(f"Nuri-Quant 스케줄러 시작 ({len(SCHEDULES)}개 작업)")
    print_schedule()
    scheduler.start()


if __name__ == "__main__":
    main()
