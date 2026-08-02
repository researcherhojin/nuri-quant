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
import logging.handlers
import os
import signal
import sys
from pathlib import Path
from typing import Any, Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from nuri.core.db import init_db


def _configure_logging() -> None:
    """Set up scheduler logging: INFO → rotating file, WARNING+ → console.

    Mac mini 24/7 receiver runs the scheduler indefinitely. Rotation covers the
    file (`scheduler.log`), but the console (stderr) is captured by launchd's
    `StandardErrorPath=scheduler.err` which has **no rotation** — the previous
    `basicConfig(INFO)` sent every INFO line (apscheduler 'job executed' etc) to
    stderr, growing scheduler.err unbounded (189MB, 2026-07-08, #859).

    Fix: console(stderr) handler is WARNING+ only (real warnings/errors/tracebacks
    that an operator should see in scheduler.err), while the full INFO stream goes
    to the rotating file. Env vars: `NURI_SCHEDULER_LOG_DIR=<path>` (default
    `data/logs/`), `NURI_SCHEDULER_LOG_DISABLE_FILE=1` to opt out of the file
    (CI / tests → console-only).
    """
    fmt = "%(asctime)s %(name)s %(levelname)s %(message)s"
    formatter = logging.Formatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # 중복 설치 방지 (importlib 재로드 / 재호출) — **본 함수가 붙인 핸들러만** 제거.
    # root.handlers 전체를 clear 하면 pytest caplog 핸들러까지 죽어 테스트 간
    # 로그 캡처가 shard 순서에 따라 깨진다 (CI Fast-1 실패, 2026-07-08).
    for h in [h for h in root.handlers if getattr(h, "_nuri_scheduler", False)]:
        root.removeHandler(h)

    # console(stderr) — launchd scheduler.err 무한성장 방지 위해 WARNING+ 만 (#859).
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(formatter)
    console._nuri_scheduler = True  # type: ignore[attr-defined]  # 재구성 시 식별 마커
    root.addHandler(console)

    # yfinance internal logger emits 401 Crumb / 404 ETF-calendar noise at INFO/ERROR
    # for routine cases (ETFs without earnings calendar, transient cookie refresh).
    # Each line is per-ticker and floods logs on universe runs (746 tickers).
    # Raise to WARNING — we still see real auth/network failures, but the routine
    # 4xx-on-missing-data noise stops. fundamental.py already does this per-source
    # (CRITICAL on universe); this is the global belt-and-suspenders.
    # MUST be set before any early-return so DISABLE_FILE / read-only paths still silence.
    logging.getLogger("yfinance").setLevel(logging.WARNING)

    if os.environ.get("NURI_SCHEDULER_LOG_DISABLE_FILE", "0") == "1":
        return

    repo_root = Path(__file__).resolve().parent.parent
    log_dir_env = os.environ.get("NURI_SCHEDULER_LOG_DIR")
    log_dir = Path(log_dir_env) if log_dir_env else (repo_root / "data" / "logs")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Read-only filesystem (CI sandboxes) — keep console-only logging.
        return

    handler = logging.handlers.RotatingFileHandler(
        log_dir / "scheduler.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB per file
        backupCount=3,  # keep 3 rotated archives → 20 MB total cap
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)  # 전체 INFO 스트림은 로테이션 파일로만
    handler._nuri_scheduler = True  # type: ignore[attr-defined]  # 재구성 시 식별 마커
    root.addHandler(handler)


_configure_logging()
logger = logging.getLogger("nuri.scheduler")


# 잡 이름 → 파이프라인 스테이지 (#921).
# 여기 없는 잡은 스테이지에 속하지 않으며 lifecycle 이벤트를 남기지 않는다 —
# 브리프·디스패처·백업 같은 운영 잡이 그렇다.
_STAGE_OF_JOB = {
    # collect — 25개 수집 잡이 전부 이 스테이지다
    "stock": "collect",
    "stock_kr": "collect",
    "macro": "collect",
    "technical": "collect",
    "fear_greed": "collect",
    "ark": "collect",
    "events": "collect",
    "cboe": "collect",
    "coingecko": "collect",
    "reddit": "collect",
    "fred_calendar": "collect",
    "institutional": "collect",
    "finviz": "collect",
    "news": "collect",
    "macro_news": "collect",
    "fundamental": "collect",
    "kis_analyst_opinion": "collect",
    "superinvestors": "collect",
    "estimates": "collect",
    "etf_flows": "collect",
    "wallstreet": "collect",
    # consensus — 하나뿐이며, 그 안에서 certify(record_decisions)까지 in-memory 로 이어진다
    "consensus": "consensus",
    # track
    "decision_pnl": "track",
    "recommendation_outcomes": "track",
    "alpha_tracking": "track",
    "agent_accuracy": "track",
}


def _dispatch_collector(name: str, **kwargs):
    """잡 이름 → 실제 실행. 예외를 잡지 않는다 (호출자가 처리)."""
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
    elif name == "cboe":
        from nuri.collectors.cboe import CBOECollector

        CBOECollector().run()
    elif name == "coingecko":
        from nuri.collectors.coingecko import CoinGeckoCollector

        CoinGeckoCollector().run()
    elif name == "reddit":
        from nuri.collectors.reddit import RedditCollector

        RedditCollector().run()
    elif name == "fred_calendar":
        from nuri.collectors.fred_calendar import FREDCalendarCollector

        FREDCalendarCollector().run()
    elif name == "institutional":
        from nuri.collectors.institutional import InstitutionalCollector

        InstitutionalCollector().run()
    elif name == "finviz":
        from nuri.collectors.finviz import FINVIZCollector

        FINVIZCollector().run()
    elif name == "kis_analyst_opinion":
        from nuri.collectors.kis_analyst_opinion import KISAnalystOpinionCollector

        KISAnalystOpinionCollector().run()
    elif name == "superinvestors":
        from nuri.collectors.superinvestors import SuperinvestorCollector

        SuperinvestorCollector().run()
    elif name == "estimates":
        from nuri.collectors.estimates import EstimatesCollector

        EstimatesCollector().run(**kwargs)
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
    elif name == "decision_pnl":
        # decisions 테이블의 7/30/60/90d raw P&L 갱신.
        # NOTE: decision_outcomes(alpha) 테이블이 아님 — alpha 는 아래 alpha_tracking job.
        from nuri.trading.engine.decisions import track_decision_outcomes

        n = track_decision_outcomes()
        logger.info(f"[decision_pnl] {n}건 업데이트")
    elif name == "recommendation_outcomes":
        # recommendations 테이블의 7/14/21/30/60/90d forward return 갱신.
        # NOTE: decisions 테이블이 아님 — 그쪽은 바로 위 decision_pnl.
        #
        # 이 호출은 `make recommend` CLI(tracker.main) 에만 있었다. 스케줄러에는
        # 없어서 프로덕션 `recommendations.outcome_*` 1,170행이 **전부 NULL** 이었고
        # (창이 닫힌 550행 포함), learning_memory 의 canonical(outcome_30d) /
        # provisional(outcome_21d) 가중치가 표본 0 으로 DEFAULT_WEIGHTS 에 영구
        # 고정돼 있었다. dev 에서는 사람이 `make recommend` 를 돌려 채워지므로
        # 학습이 도는 것처럼 보였다 — 그게 3.5개월 안 들킨 이유다 (#899).
        from nuri.trading.recommend.tracker import track_outcomes

        n = track_outcomes()
        logger.info(f"[recommendation_outcomes] {n}건 업데이트")
    elif name == "alpha_tracking":
        # ForwardOutcomeTracker: emit 된 추천 vs SPY benchmark → realized alpha 를
        # decision_outcomes 테이블에 기록 (recommendations → agent_decisions 백필 포함).
        # canonical scheduler 경로 — 과거 launchd track-forward.plist 를 흡수(이제 redundant).
        from nuri.agents.actors.forward_outcome_tracker import ForwardOutcomeTracker

        res = ForwardOutcomeTracker().run({"action": "scan", "max_decisions": 2000})
        out = res.output if isinstance(res.output, dict) else {}
        logger.info(
            f"[alpha_tracking] synced={out.get('synced_from_recommendations', 0)} "
            f"measured={out.get('n_measurements', 0)}"
        )
    elif name == "agent_accuracy":
        from nuri.trading.engine.decisions import save_agent_accuracy_snapshot

        n = save_agent_accuracy_snapshot()
        logger.info(f"[agent_accuracy] {n}건 저장")
    elif name == "consensus":
        # 10-agent 합의 결과를 recommendations 에 저장 → Learning Memory 자동 학습 input.
        # decision_outcomes 가 30 일 후 outcome_30d 채우면 _compute_weights 가 가중치 조정.
        from nuri.trading.agents.consensus import analyze_portfolio, save_to_recommendations
        from nuri.trading.engine.decisions import record_decisions

        results = analyze_portfolio()
        saved = save_to_recommendations(results)
        # decisions 기록은 CLI(`python -m nuri.trading.agents.consensus`) 에만 있었다.
        # 자동화(#363, 2026-04-17)가 수동 실행을 대체하면서 이 호출이 빠져 decisions 가
        # 2026-04-14 이후 3.5 개월 동결됐다 — /decisions 대시보드가 4월 데이터를 서빙
        # 했는데 헬스 지표는 전부 초록이었다 (#897).
        recorded = record_decisions(results)
        logger.info(f"[consensus] {len(results)}건 분석, recommendations {saved}건, decisions {recorded}건")
    elif name == "holdings_monitor":
        # Holdings post-entry technical-divergence monitor (07:10 KST, after consensus 07:05).
        # JKHY-class entry-stage defenses (PR #303) cover before-buy; this covers after-buy
        # falling-knife. REVIEW CTA only — auto-trade deferred (STRATEGY §7.1).
        from nuri.trading.recommend.holdings_monitor import run_monitor, send_alerts

        summary = run_monitor()
        sent = send_alerts(summary)
        logger.info(f"[holdings_monitor] {summary.n_holdings}건 분석, {summary.n_alerted}건 alert, {sent}건 surface")


def _run_collector(name: str, **kwargs):
    """Collector를 안전하게 실행.

    스테이지에 속한 잡은 `run_step` 으로 감싸 lifecycle 이벤트(step_started /
    step_completed / step_failed)를 남긴다. `warn_only=True` 이므로 의존성이
    안 맞아도 **실행을 막지 않고** 경고 이벤트만 남긴다 — 관측이 본 작업을
    게이트하면 DB 하나로 파이프라인이 조용히 선다 (#894). `reraise=True` 라
    실패 로깅은 아래 except 가 그대로 담당한다 (#921).
    """
    stage = _STAGE_OF_JOB.get(name)
    try:
        if stage:
            from nuri.core.pipeline import run_step

            run_step(stage, _dispatch_collector, warn_only=True, reraise=True, name=name, **kwargs)
        else:
            _dispatch_collector(name, **kwargs)
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


def _run_postmarket_brief_kr():
    """KR session post-market brief (KST 16:00, KOSPI close 15:30 + 30min)."""
    try:
        from nuri.alerts.postmarket_brief import write_brief

        write_brief("kr")
    except Exception as e:
        logger.error(f"[postmarket_brief_kr] 실행 실패: {e}", exc_info=True)


def _run_postmarket_brief_us():
    """US session post-market brief (NYSE 16:00 ET + 30min, DST-aware).

    Dual-cron (06:30 / 07:30 KST) 등록 — `run_postmarket_us_dst_aware` 가 현재
    시각이 NYSE 16:30 ET ± 15분 window 인지 확인 후 진행. 2회 fire risk 는
    idempotent persist (UPSERT) 로 mitigate.
    """
    try:
        from nuri.alerts.postmarket_brief import run_postmarket_us_dst_aware

        run_postmarket_us_dst_aware()
    except Exception as e:
        logger.error(f"[postmarket_brief_us] 실행 실패: {e}", exc_info=True)


def _run_report():
    """일일 리포트를 안전하게 실행."""
    try:
        from nuri.alerts.daily_report import main as report_main

        report_main()
    except Exception as e:
        logger.error(f"[daily_report] 실행 실패: {e}", exc_info=True)


# 백업 스크립트 경로 — #557 scripts/ 7-subdir 리팩터로 이동 (#836 경로 drift 회귀 fix).
# 상수로 노출해 lock test 가 실존을 검증한다 (mock-only 테스트로는 경로 drift 미탐).
BACKUP_SCRIPT = "scripts/db/backup.sh"


def _run_backup():
    """DB 백업을 안전하게 실행."""
    import subprocess

    try:
        subprocess.run(["bash", BACKUP_SCRIPT], check=True)
    except Exception as e:
        logger.error(f"[backup] 실행 실패: {e}", exc_info=True)


def _run_db_maintenance():
    """DB 유지보수 — 오래된 데이터 정리 + VACUUM."""
    try:
        from scripts.db.maintenance import run_maintenance

        run_maintenance()
    except Exception as e:
        logger.error(f"[db_maintenance] 실행 실패: {e}", exc_info=True)


def _run_alpha_report():
    """월간 alpha 진행 리포트 → #brief (§3.11 측정 모드 표출, #856).

    매월 1일 KST. `decision_alpha.adjudicate()` 를 돌려 n / mean / p / halves /
    결측률 / 판정일까지 D-day 를 한 줄로 stage. verdict 는 판정일 이전엔
    `PROGRESS_REPORT` 로 고정 — 조기 승격 금지(§3.11 원안 4번).

    stage 는 `NURI_ROLE=production` 에서만 (원장 단일). dev 스케줄러가 돌아도
    replica 숫자가 brief 로 새지 않는다. 실행 실패는 흡수 (다른 _run_* 와 동일).

    실행할 때마다 `pipeline_events` 에 `alpha_report_run` heartbeat 를 **반드시**
    한 행 남긴다 (#894). 없으면 "안 나감(정상: 이번 달 이미 발화)" 과 "안 나감
    (고장: role 누락 / 예외 / mini 다운)" 이 관측상 완전히 동일하다 — NURI_ROLE 이
    비어 있으면 판정일까지 한 번도 안 나가는데 아무 신호가 없다.
    `SREIncidentAgent._detect_alpha_report_stale` 가 이 heartbeat 를 읽는다.
    """
    from nuri.core.timezone import today_kst

    month = str(today_kst())[:7]
    role_ok = False
    already: bool | None = None
    outbox_id = None
    error = None
    try:
        from nuri.alerts.alpha_report import already_emitted, is_production, stage_alpha_progress_brief

        role_ok = is_production()
        # stage **이전** 상태를 찍어야 skip 사유가 구분된다 (stage 후엔 항상 True).
        # ⚠️ 자체 try — 이건 관측용 부가 정보다. 여기서 실패했다고 본 작업(stage)까지
        # 막으면 observability 가 관측 대상을 죽인다. DB 가 없는 CI 에서 실제로 그랬고,
        # 프로덕션에서도 일시적 DB 잠금이 리포트를 통째로 건너뛰게 만들 수 있었다.
        try:
            already = already_emitted(month)
        except Exception:  # noqa: BLE001 — 관측 실패는 본 작업과 무관
            already = None
        outbox_id = stage_alpha_progress_brief()
        logger.info(f"[alpha_report] staged={outbox_id is not None} (id={outbox_id})")
    except Exception as e:
        error = str(e)[:200]
        logger.error(f"[alpha_report] 실행 실패: {e}", exc_info=True)

    # heartbeat 는 위 성공/실패와 무관하게 남긴다 — 무기록 = 'job 자체가 안 돌았다'.
    try:
        from nuri.core.events import emit_event

        emit_event(
            "alpha_report_run",
            step="alpha_report",
            payload={
                "month": month,
                "role_ok": role_ok,
                "already_emitted": already,
                "staged": outbox_id is not None,
                "error": error,
            },
        )
    except Exception as e:
        logger.error(f"[alpha_report] heartbeat 기록 실패: {e}", exc_info=True)


def _run_brief_audit():
    """BriefAuditor — Discord-as-dev-loop self-quality check.

    매 6시간마다 #brief 채널 emit 24h windowing audit. quality issue 발견 시
    deterministic check (C1-C3) 결과를 #incidents 로 surface. dedupe 24h.
    실행 실패가 다음 job 영향 없게 exception 흡수 (다른 _run_* 와 동일).
    """
    try:
        from nuri.agents.actors.brief_auditor import BriefAuditor

        result = BriefAuditor().run({"hours": 24})
        logger.info(
            f"[brief_audit] decisions={result.output['decisions_audited']} "
            f"found={result.output['issues_found']} "
            f"emitted={result.output['issues_emitted']}"
        )
    except Exception as e:
        logger.error(f"[brief_audit] 실행 실패: {e}", exc_info=True)


def _run_channel_dispatcher(channel: str):
    """ChannelDispatcher — single-writer Discord outbox flush (Codex Round 6).

    pending events 종합 → 1 embed → webhook. #brief 만 quiet-period (60s) gate.
    """
    try:
        from nuri.agents.actors.channel_dispatcher import ChannelDispatcher

        result = ChannelDispatcher().run({"channel": channel})
        out = result.output
        if "skipped" in out:
            logger.info(f"[dispatcher:{channel}] skipped={out['skipped']}")
        else:
            logger.info(
                f"[dispatcher:{channel}] claimed={out.get('claimed_n')} "
                f"sent={out.get('marked_sent_n')} http={out.get('http_status')}"
            )
    except Exception as e:
        logger.error(f"[dispatcher:{channel}] 실행 실패: {e}", exc_info=True)


def _run_held_add_shadow():
    """held_add shadow emit (#518 phase 2a) — 매일 보유 종목 add 후보 평가.

    shadow_mode_until 까지: held_add_shadow 테이블에만 persist (brief surface
    안 함). 14d 누적 후 #519 2c calibration sample.

    Providers wire-up: buy_candidate_emitter helpers 재사용 — score (factor
    composite × 100), rsi (RSI snapshot), regime (regime_transitions + VIX),
    sector_mom (price 5d momentum proxy), breakout_above_trim (False default
    — strict, false-positive 회피).
    """
    try:
        from nuri.trading.recommend.buy_candidate_emitter import (
            _get_factor_scores,
            _get_price_signals,
            _get_regime,
            _get_rsi_snapshot,
        )
        from nuri.trading.recommend.held_add import emit_held_add_shadow

        factors = _get_factor_scores()
        rsi_map = _get_rsi_snapshot()
        prices = _get_price_signals()
        regime, vix = _get_regime()

        def _score(t: str) -> float:
            f = factors.get(t)
            return float((f or {}).get("composite", 0.0)) * 100.0

        def _rsi(t: str) -> float | None:
            return rsi_map.get(t)

        def _regime() -> tuple[str, float]:
            return regime, vix

        def _sector_mom(t: str) -> float:
            # 5d return 을 sector momentum proxy 로 사용 — 진짜 sector index
            # 가 없을 때 ticker 자체 momentum 으로 대체. shadow 단계에서 acceptable.
            return float((prices.get(t) or {}).get("ret_5d", 0.0))

        result = emit_held_add_shadow(
            score_provider=_score,
            rsi_provider=_rsi,
            regime_provider=_regime,
            sector_mom_provider=_sector_mom,
        )
        n_emit = len(result.candidates)
        n_skip = len(result.skipped)
        logger.info(
            f"[held_add_shadow] {n_emit}건 emit / {n_skip}건 skip "
            f"(shadow={result.shadow_mode}, until={result.shadow_mode_until})"
        )
    except Exception as e:
        logger.error(f"[held_add_shadow] 실행 실패: {e}", exc_info=True)


def _run_outbox_watchdog():
    """OutboxWatchdog — 직접 #ops 발송 (recursion 방지). 10분 마다."""
    try:
        from nuri.agents.actors.outbox_watchdog import OutboxWatchdog

        result = OutboxWatchdog().run({})
        n = len(result.output.get("breaches", []))
        if n > 0:
            logger.warning(f"[outbox_watchdog] {n} breach(es) — alert sent")
        else:
            logger.info("[outbox_watchdog] healthy")
    except Exception as e:
        logger.error(f"[outbox_watchdog] 실행 실패: {e}", exc_info=True)


# ═══════════════════════════════════════════════════════
# 스케줄 정의
# ═══════════════════════════════════════════════════════


def _self_restart():
    """fd 누수 누적 차단용 일일 자가 재시작 (#780).

    yfinance 내부 SQLite 캐시(tkr-tz.db/cookies.db)와 curl-cffi 소켓 fd 가 장수
    데몬에서 단조 증가한다 (#778: 6일째 536 fd → 256 천장 → sqlite unable-to-open).
    누수는 yfinance 내부라 직접 못 닫으므로, 하루 1회 fresh 프로세스로 교체해 fd 를
    회수한다. `launchctl kickstart -k` → SIGTERM (graceful shutdown handler) → launchd
    재기동. 재시작 후 heartbeat 는 ~45초 내 갱신되어 watchdog 30분 임계 미달 → false
    STALE 없음. launchctl 부재(비배포 dev) 시 graceful skip.
    """
    import subprocess

    target = f"gui/{os.getuid()}/com.nuri-quant.scheduler"
    logger.info("일일 자가 재시작 — fd 회수 (#780)")
    try:
        subprocess.run(["launchctl", "kickstart", "-k", target], timeout=30, check=False)
    except Exception as e:  # launchctl 부재(비배포)/타임아웃 — 데몬은 계속 구동
        logger.warning(f"self-restart skip (비배포 환경?): {e}")


SCHEDULES = [
    # 미국장 주가 (KST 23:30~06:00, 5분)
    {"name": "stock_us_night", "func": _run_collector, "args": ("stock",), "cron": "*/5 23 * * 1-5"},
    {"name": "stock_us_dawn", "func": _run_collector, "args": ("stock",), "cron": "*/5 0-6 * * 2-6"},
    # 한국장 주가 (KST 09:00~15:30, 5분)
    {"name": "stock_kr", "func": _run_collector, "args": ("stock_kr",), "cron": "*/5 9-15 * * 1-5"},
    # 매크로 (매시)
    {"name": "macro", "func": _run_collector, "args": ("macro",), "cron": "0 * * * *"},
    # 기술적 지표 (미장 마감 후 07:00)
    {"name": "technical", "func": _run_collector, "args": ("technical",), "cron": "0 7 * * 2-6"},
    # Fear & Greed (매일 08:00)
    {"name": "fear_greed", "func": _run_collector, "args": ("fear_greed",), "cron": "0 8 * * *"},
    # ARK 매매 (미장 마감 후 07:30)
    {"name": "ark", "func": _run_collector, "args": ("ark",), "cron": "30 7 * * 2-6"},
    # 이벤트 캘린더 (매일 07:00)
    {"name": "events", "func": _run_collector, "args": ("events",), "cron": "0 7 * * *"},
    # ── `make collect` 에는 있었으나 SCHEDULES 에 없던 4종 (#900) ──────────────
    # 2026-04-14 이후 한 행도 안 쌓였다 — 그날이 마지막 수동 `make collect` 이고,
    # 자동화가 이 넷을 안 가져갔다. consensus(07:05) **전**에 배치해 같은 날 데이터로
    # 투표하게 한다. 특히 reddit 은 retail_agent 의 유일한 입력이라, 없으면 10-agent
    # 중 하나가 3.5 개월 묵은 값으로 표를 던진다.
    #   cboe          → macro.put_call_ratio  (공포/과열)
    #   coingecko     → macro.btc_dominance
    #   reddit        → macro.wsb_post_count / wsb_mention_<ticker>  → retail_agent
    #   fred_calendar → events (경제지표 발표 일정 — 실적/FOMC 는 위 events collector 담당, 상보적)
    {"name": "cboe", "func": _run_collector, "args": ("cboe",), "cron": "20 6 * * *"},
    {"name": "coingecko", "func": _run_collector, "args": ("coingecko",), "cron": "25 6 * * *"},
    {"name": "reddit", "func": _run_collector, "args": ("reddit",), "cron": "35 6 * * *"},
    {"name": "fred_calendar", "func": _run_collector, "args": ("fred_calendar",), "cron": "45 6 * * *"},
    # 기관/외국인 수급 — `korean_market` 에이전트가 `institutional_flows.foreign_net` 을 읽는다
    # (`korean_market.py:166`). collector 는 스케줄러에도 `make collect` 에도 없어서 2026-04-14
    # 이후 갱신이 끊겼고, 10-agent 중 하나가 4 개월 묵은 수급으로 표를 던지고 있었다.
    # KIS rate limit 0.4s/종목, portfolio KR 11 종목 = 실측 6.1 초. consensus(07:05) 전.
    {"name": "institutional", "func": _run_collector, "args": ("institutional",), "cron": "50 6 * * *"},
    # FINVIZ 스크리너 보조 시그널 — `technical` 에이전트(가중치 최대)가 읽는다
    # (`technical.py:143` → `external_analysis` source='FINVIZ'). `make collect` 에만 있어
    # 2026-04-14 이후 3 행에서 멈춰 있었고, config/agents.yaml 의 buy_boost/sell_boost 가
    # 사실상 무효였다. consensus(07:05) 전.
    {"name": "finviz", "func": _run_collector, "args": ("finviz",), "cron": "55 6 * * *"},
    # 뉴스 (1시간 — SaveTicker 대체)
    {"name": "news", "func": _run_collector, "args": ("news",), "cron": "0 * * * *"},
    # 매크로 뉴스 (KST 08:00, 14:00, 20:00 — 시장 영향 큰 이벤트만)
    {"name": "macro_news", "func": _run_collector, "args": ("macro_news",), "cron": "0 8,14,20 * * *"},
    # 펀더멘탈 (주 1회 일요일 00:00)
    {"name": "fundamental", "func": _run_collector, "args": ("fundamental",), "cron": "0 0 * * 0"},
    # KR 애널리스트 투자의견 (#418, KIS Open API invest-opinion). 주 1회 일요일 00:30.
    # 펀더멘탈 직후 배치 — 같은 KIS-data 패밀리 (codex Round 1 권고: data-family grouping).
    # universe ~200 KR tickers × 0.4s ≈ 80s + pagination retry. KIS creds 미설정 시 surface 후 skip.
    {"name": "kis_analyst_opinion", "func": _run_collector, "args": ("kis_analyst_opinion",), "cron": "30 0 * * 0"},
    # 슈퍼투자자 13F (주 1회 일요일 01:00)
    {"name": "superinvestors", "func": _run_collector, "args": ("superinvestors",), "cron": "0 1 * * 0"},
    # 애널리스트 컨센서스 (주 1회 일요일 02:00) — universe 전체 (#420).
    # universe 543 US tickers ~27s elapsed (2026-04-28 live probe 96.7% OK / 0 rate-limit).
    # universe ⊃ portfolio 이므로 별도 portfolio entry 없어도 보유종목 자동 갱신.
    {
        "name": "estimates",
        "func": _run_collector,
        "args": ("estimates",),
        "kwargs": {"source": "universe"},
        "cron": "0 2 * * 0",
    },
    # ETF 자금흐름 (주 1회 일요일 03:00)
    {"name": "etf_flows", "func": _run_collector, "args": ("etf_flows",), "cron": "0 3 * * 0"},
    # Wall Street 데이터 (주 1회 일요일 03:30)
    {"name": "wallstreet", "func": _run_collector, "args": ("wallstreet",), "cron": "30 3 * * 0"},
    # Learning Memory 스냅샷 (주 1회 일요일 04:00)
    {"name": "memory_snapshot", "func": _run_collector, "args": ("memory_snapshot",), "cron": "0 4 * * 0"},
    # decisions 테이블 raw P&L 갱신 (매일 07:00 — 시장 개장 전). NOT alpha (아래 alpha_tracking).
    {"name": "decision_pnl", "func": _run_collector, "args": ("decision_pnl",), "cron": "0 7 * * *"},
    # recommendations forward return 갱신 (매일 07:02 — decision_pnl 직후, consensus 07:05 **전**).
    # 순서가 계약이다: consensus 의 learning_memory 가 같은 날 갱신된 outcome 으로 가중치를
    # 계산해야 한다. 07:00 대인 이유는 stock_us_dawn(00~06:59, 5분 간격)이 미국 종가를
    # 이미 넣어둔 시각이기 때문 — decision_pnl 이 같은 근거로 07:00 이다 (#899).
    {
        "name": "recommendation_outcomes",
        "func": _run_collector,
        "args": ("recommendation_outcomes",),
        "cron": "2 7 * * *",
    },
    # 실현 alpha 추적 (매일 17:00 — 한국장 마감 후). ForwardOutcomeTracker scan →
    # decision_outcomes (realized vs SPY benchmark). 과거 launchd track-forward.plist 를 scheduler 로 흡수.
    {"name": "alpha_tracking", "func": _run_collector, "args": ("alpha_tracking",), "cron": "0 17 * * *"},
    # 10-agent consensus (매일 07:05 — technical 07:00 완료 후, daily_report 08:00 전).
    # agent_verdicts 를 recommendations 테이블에 쌓아 Learning Memory 가 30 일 후 학습.
    # Phase 2 A-1a (PR #361) 의 read path fix 를 활용하려면 input 이 꾸준히 쌓여야 함.
    {"name": "consensus", "func": _run_collector, "args": ("consensus",), "cron": "5 7 * * *"},
    # Holdings post-entry technical-divergence monitor (매일 07:10 — consensus 직후).
    # JKHY-class entry 단계 보호 (PR #303) 의 hold-stage 보강. REVIEW alert only,
    # auto-trade 없음 (STRATEGY §7.1 deferred). pipeline_events 로 7d dedup.
    {"name": "holdings_monitor", "func": _run_collector, "args": ("holdings_monitor",), "cron": "10 7 * * *"},
    # held_add shadow emit (#518 phase 2a, 매일 07:15 — holdings_monitor 직후).
    # 보유 종목에 대한 add 후보 평가 (3 modes + earnings blackout). shadow_mode_until
    # 까지 held_add_shadow 테이블 only — brief surface 안 함. 14d 누적 후 2c calibration.
    {"name": "held_add_shadow", "func": _run_held_add_shadow, "args": (), "cron": "15 7 * * *"},
    # Agent accuracy 스냅샷 (주 1회 일요일 08:00)
    {"name": "agent_accuracy", "func": _run_collector, "args": ("agent_accuracy",), "cron": "0 8 * * 0"},
    # 일일 리포트 (매일 08:00)
    {"name": "daily_report", "func": _run_report, "args": (), "cron": "0 8 * * *"},
    # Pre-market brief (평일 US/Eastern 09:00 — pre-market 30분 전).
    # DST-aware: tz="US/Eastern" 지정해 EDT/EST 전환 자동 처리 (codex Plan 권고).
    # EDT 기간 (3월~11월 초) KST 22:00, EST 기간 (11월 초~3월) KST 23:00.
    # 사용자 명령 없이도 매일 판단 trigger — session-start 에서 Claude 가
    # 이 brief 를 pick up 해 qualitative 뉴스와 cross-ref.
    {"name": "premarket_brief", "func": _run_premarket_brief, "args": (), "cron": "0 9 * * 1-5", "tz": "US/Eastern"},
    # Post-market brief — KR session (KST 16:00, KOSPI close 15:30 + 30min, 평일).
    # holdings PnL + KOSPI200 시장 proxy + macro snapshot. pension 계좌 제외.
    {"name": "postmarket_brief_kr", "func": _run_postmarket_brief_kr, "args": (), "cron": "0 16 * * 1-5"},
    # Post-market brief — US session (NYSE 16:00 ET + 30min, DST-aware).
    # Dual-cron 06:30/07:30 KST 등록, 함수 내부에서 NYSE 16:30 ET window 일치
    # 시점만 진행. EDT 기간 → 05:30 KST (둘 다 skip → 다음날 fire),
    # EST 기간 → 06:30 KST 매칭. 함수 idempotent UPSERT 라 2회 fire 도 안전.
    # NYSE 16:30 ET(종가+30분)에 해당하는 KST 시각은 DST 에 따라 갈린다:
    #   EDT(3월중~11월초) = 05:30 KST · EST(11월초~3월중) = 06:30 KST
    # `run_postmarket_us_dst_aware` 가 ±15분 window 로 맞는 쪽만 통과시키므로 두 시각을
    # 모두 등록해야 한다. 이전 등록은 06:30·07:30 이었고 **07:30 은 두 시기 모두 window
    # 밖**(EST 17:30 ET / EDT 18:30 ET)이라 발화 불가였다. 그 결과 EDT 8개월 동안
    # US 브리프가 통째로 안 돌았다 — 손절 SELL·장마감 요약뿐 아니라 `session == "us"`
    # 안에 있는 집중도·섹터·슬리브 REBALANCE(Tier 1b/1c/1d)까지 함께 침묵했다.
    {"name": "postmarket_brief_us_a", "func": _run_postmarket_brief_us, "args": (), "cron": "30 5 * * 2-6"},
    {"name": "postmarket_brief_us_b", "func": _run_postmarket_brief_us, "args": (), "cron": "30 6 * * 2-6"},
    # Brief auditor (Discord-as-dev-loop) — 매 6시간 #brief 품질 self-audit.
    # decision_compiler emit 의 conflict / noise / identical-conviction 검출 →
    # #incidents 로 ticket 자동 emit. dedupe 24h. recommend-only, ZERO LLM.
    {"name": "brief_audit", "func": _run_brief_audit, "args": (), "cron": "0 */6 * * *"},
    # 월간 alpha 진행 리포트 (§3.11 측정 모드 표출, #856) — 09:00 KST 매일 확인.
    # 왜 매일인가: `0 9 1 * *` 로 두면 그 5분(misfire_grace_time)에 mini 가 재시작
    # 중이거나 절전이면 그 달 리포트가 조용히 사라진다. 월 1회 보장은 cron 이 아니라
    # `already_emitted()` 가 한다(pending/claimed/sent 전부 확인) — 이미 나갔으면
    # adjudicate() 순열 1,000회를 돌리기 전에 빠져나오므로 매일 실행이 싸다.
    # 결과적으로 1일에 놓쳐도 2일에 따라잡는다.
    # 09:00 = 미장 마감(06:00) 후 alpha_tracking 이 전일분을 확정한 뒤.
    {"name": "alpha_report", "func": _run_alpha_report, "args": (), "cron": "0 9 * * *"},
    # Discord channel dispatcher (Codex Round 6, 2026-05-02) — single-writer outbox flush.
    # PR1 shadow mode: outbox 는 비어있으므로 발송 없음. 실제 사용자 화면 변화는 PR2/PR3 channel-migration 시.
    # #brief: 1분 polling + quiet-period gate (60s no-new-event)
    # #ops: 10분, #incidents: 10분, #rollout: 일요일 06:00 KST
    {"name": "dispatcher_brief", "func": _run_channel_dispatcher, "args": ("brief",), "cron": "* * * * *"},
    {"name": "dispatcher_ops", "func": _run_channel_dispatcher, "args": ("ops",), "cron": "*/10 * * * *"},
    {"name": "dispatcher_incidents", "func": _run_channel_dispatcher, "args": ("incidents",), "cron": "*/10 * * * *"},
    {"name": "dispatcher_rollout", "func": _run_channel_dispatcher, "args": ("rollout",), "cron": "0 6 * * 0"},
    # Watchdog — outbox backlog / oldest-pending-age threshold breach 시 #ops 직접 발송 (recursion 방지).
    {"name": "outbox_watchdog", "func": _run_outbox_watchdog, "args": (), "cron": "*/10 * * * *"},
    # DB 백업 (매일 자정)
    {"name": "backup", "func": _run_backup, "args": (), "cron": "0 0 * * *"},
    # DB 유지보수 (일요일 새벽 3시)
    {"name": "db_maintenance", "func": _run_db_maintenance, "args": (), "cron": "0 3 * * 0"},
    # Universe 1y backfill — US (일요일 새벽 5시, KST quiet window)
    # 기존 stock_us_night/dawn 은 source="portfolio" 기본으로 universe-only
    # 신규 ticker 를 수집하지 않음. 주 1회 1년치 + source="all" 로 gap 채움.
    # universe-only 730개 ticker 가 1-7일 stale 로 누적되는 현상 방지.
    {
        "name": "stock_us_backfill",
        "func": _run_collector,
        "args": ("stock",),
        "kwargs": {"period": "1y", "source": "all"},
        "cron": "0 5 * * 0",
    },
    # Universe 1y backfill — KR (일요일 새벽 5시 30분)
    # stock_kr 는 days= kwarg 사용. pykrx sequential + 0.1s delay 이미 내장.
    {
        "name": "stock_kr_backfill",
        "func": _run_collector,
        "args": ("stock_kr",),
        "kwargs": {"days": 365, "source": "all"},
        "cron": "30 5 * * 0",
    },
    # 측정 모드 벤치마크(SPY) + SIEGE freshness 티커 일일 수집 (#457 도구 배선 — #860 fix).
    # stock_us_night/dawn 은 source="portfolio"(held) 만 → SPY/TLT/GC=F(universe-only,
    # 미보유 벤치마크)가 주간 backfill 에만 의존해 최대 1주 stale 이었음. §3.11 alpha 측정
    # (forward_outcome_tracker, 매일 17:00) + 레짐 분류가 매일 SPY 를 필요로 한다.
    # KST 화~토 06:10/06:40 — 미국 정규장 마감(서머 05:00 / 표준 06:00) 후 데이터 확정 창.
    {
        "name": "stock_us_freshness",
        "func": _run_collector,
        "args": ("stock",),
        "kwargs": {"period": "5d", "source": "freshness"},
        "cron": "10,40 6 * * 2-6",
    },
    # 일일 자가 재시작 (#780) — KST 08:40, 모닝 배치(07-08) 종료 후·KR 개장(09:00) 전 idle
    # window. yfinance fd 누수를 fresh 프로세스 교체로 회수 (plist 4096 천장도 결국 고갈).
    {"name": "self_restart", "func": _self_restart, "args": (), "cron": "40 8 * * *"},
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


def _make_trigger(cron: str, tz: Optional[str] = None) -> CronTrigger:
    """crontab 문자열 → CronTrigger. 요일은 crontab 규약으로 해석한다.

    `CronTrigger.from_crontab()` 은 요일 필드를 **변환 없이** APScheduler 의
    `day_of_week`(Mon=0…Sun=6)로 넘긴다. crontab 은 0=Sun 이므로 그대로 쓰면 모든
    job 이 하루씩 밀린다 — `1-5`(월–금)가 화–토로, `0`(일)이 월요일로 fire 된다.

    이 함정은 #432 리뷰에서 이미 지적돼 주석으로 남아 있었지만 변환은 `tz` 있는
    job 에만 걸려 있었다. 나머지 22 개는 밀린 채였고, 그 결과 `stock_us_freshness`
    가 화요일에 안 돌아 §3.11 벤치마크(SPY)가 매주 월·화 stale 이었다 (#929).
    `period=5d` 가 뒤늦게 메꿔 영구 결손이 아니었던 탓에 조용히 지나갔다.

    변환을 한 곳에 두어 `tz` 유무와 무관하게 같은 의미가 되게 한다.
    """
    parts = cron.split()
    if len(parts) != 5:
        raise ValueError(f"cron 필드가 5개가 아님: {cron!r}")
    minute, hour, day, month, dow = parts
    kwargs: dict[str, Any] = {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": _crontab_dow(dow),
    }
    if tz:
        import pytz

        kwargs["timezone"] = pytz.timezone(tz)
    return CronTrigger(**kwargs)


# crontab 요일 숫자(0=일) → 이름. crontab 은 0 과 7 을 모두 일요일로 본다.
_CRONTAB_DOW_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat", "sun")
_NAME_TO_CRONTAB_DOW = {n: i for i, n in enumerate(_CRONTAB_DOW_NAMES[:7])}


def _crontab_dow(field: str) -> str:
    """crontab 요일 필드 → APScheduler `day_of_week` 문자열.

    치환이 아니라 **열거**한다. `mon-fri` 로 문자열만 바꾸면 `*/2` 같은 step 형식이
    조용히 다른 요일 집합이 된다 — crontab `*/2` 는 0 부터라 일·화·목·토, APScheduler
    `*/2` 는 월부터라 월·수·금·일이다. 이 이슈 자체가 그런 조용한 불일치였으므로
    같은 함정을 함수 안에 남기지 않는다.
    """
    if field.strip() == "*":
        return "*"
    days = sorted(_parse_crontab_dow(field))  # crontab 번호 (0=일)
    # APScheduler 는 이름을 Mon=0…Sun=6 로 읽으므로 월요일부터 정렬해 내보낸다.
    ordered = sorted(days, key=lambda d: (d - 1) % 7)
    return ",".join(_CRONTAB_DOW_NAMES[d] for d in ordered)


def _parse_crontab_dow(field: str) -> set[int]:
    """crontab 요일 필드 → {0..6} (0=일). 7 은 0 으로 정규화."""
    out: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, _, step_raw = part.partition("/")
            step = int(step_raw)
            if step < 1:
                raise ValueError(f"crontab 요일 step 이 1 미만: {field!r}")
        if part == "*":
            lo, hi = 0, 6
        elif "-" in part:
            lo_raw, _, hi_raw = part.partition("-")
            lo, hi = _dow_num(lo_raw), _dow_num(hi_raw)
        else:
            lo = hi = _dow_num(part)
        # crontab 은 lo > hi 인 wrap 범위(fri-mon 등)를 표준으로 지원하지 않는다.
        if lo > hi:
            raise ValueError(f"crontab 요일 범위가 역순: {field!r}")
        out.update(range(lo, hi + 1, step))
    return out


def _dow_num(token: str) -> int:
    """요일 토큰 → crontab 번호(0=일). 숫자와 이름 모두 허용."""
    token = token.strip().lower()
    if token.isdigit():
        n = int(token)
        if not 0 <= n <= 7:
            raise ValueError(f"crontab 요일 범위 밖: {token!r}")
        return n % 7
    if token not in _NAME_TO_CRONTAB_DOW:
        raise ValueError(f"알 수 없는 요일 토큰: {token!r}")
    return _NAME_TO_CRONTAB_DOW[token]


def create_scheduler() -> BlockingScheduler:
    """스케줄러 생성 및 작업 등록."""
    scheduler = BlockingScheduler()

    for job in SCHEDULES:
        # 요일 규약 변환은 `_make_trigger` 안에 있다 (#929) — tz 유무로 갈리지 않는다.
        trigger = _make_trigger(job["cron"], job.get("tz"))
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

    # 부트스트랩 시 DB 스키마 / 마이그레이션 멱등 적용 — 신규 deploy 후 첫 부팅에서
    # `_MIGRATIONS` 누적 drift 가 자동 catch-up 되도록 한다 (#575).
    # init_db() 는 functionally idempotent: `_SCHEMA` / `_SCHEMA_VERSION_TABLE` 는
    # `IF NOT EXISTS` 기반이라 재실행해도 결과 동일. 미적용 마이그레이션만 새로 INSERT.
    init_db()
    logger.info("DB schema initialized (idempotent)")

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
