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

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from nuri.core.db import init_db


def _configure_logging() -> None:
    """Set up scheduler logging with optional file rotation.

    Mac mini 24/7 receiver runs the scheduler indefinitely; without rotation
    `data/logs/scheduler.log` grows unbounded. Activate via env var
    `NURI_SCHEDULER_LOG_DIR=<path>` (default: `data/logs/` under repo root)
    or `NURI_SCHEDULER_LOG_DISABLE_FILE=1` to opt out (e.g. CI / tests).

    Format and console behavior unchanged — only adds a rotating sibling.
    """
    fmt = "%(asctime)s %(name)s %(levelname)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)

    # yfinance internal logger emits 401 Crumb / 404 ETF-calendar noise at INFO/ERROR
    # for routine cases (ETFs without earnings calendar, transient cookie refresh).
    # Each line is per-ticker and floods scheduler.log on universe runs (746 tickers).
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
    handler.setFormatter(logging.Formatter(fmt))
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)


_configure_logging()
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

            results = analyze_portfolio()
            saved = save_to_recommendations(results)
            logger.info(f"[consensus] {len(results)}건 분석, {saved}건 저장")
        elif name == "holdings_monitor":
            # Holdings post-entry technical-divergence monitor (07:10 KST, after consensus 07:05).
            # JKHY-class entry-stage defenses (PR #303) cover before-buy; this covers after-buy
            # falling-knife. REVIEW CTA only — auto-trade deferred (STRATEGY §7.1).
            from nuri.trading.recommend.holdings_monitor import run_monitor, send_alerts

            summary = run_monitor()
            sent = send_alerts(summary)
            logger.info(
                f"[holdings_monitor] {summary.n_holdings}건 분석, {summary.n_alerted}건 alert, {sent}건 surface"
            )
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
    {"name": "postmarket_brief_us_a", "func": _run_postmarket_brief_us, "args": (), "cron": "30 6 * * 2-6"},
    {"name": "postmarket_brief_us_b", "func": _run_postmarket_brief_us, "args": (), "cron": "30 7 * * 2-6"},
    # Brief auditor (Discord-as-dev-loop) — 매 6시간 #brief 품질 self-audit.
    # decision_compiler emit 의 conflict / noise / identical-conviction 검출 →
    # #incidents 로 ticket 자동 emit. dedupe 24h. recommend-only, ZERO LLM.
    {"name": "brief_audit", "func": _run_brief_audit, "args": (), "cron": "0 */6 * * *"},
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
                "0": "sun",
                "1": "mon",
                "2": "tue",
                "3": "wed",
                "4": "thu",
                "5": "fri",
                "6": "sat",
                "1-5": "mon-fri",
                "0-6": "mon-sun",
                "*": "*",
            }
            dow = dow_map.get(dow_raw, dow_raw)
            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=dow,
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
