"""Scheduler tests — all classes testing nuri.scheduler.

Sources (consolidated from legacy coverage rounds, renamed from test_scheduler_all.py):
  - test_coverage_round17.py  → TestScheduler (first occurrence, keeps name)
  - test_coverage_round2.py   → TestScheduler_R2
  - test_coverage_round27.py  → TestScheduler_R27
  - test_coverage_round26.py  → TestScheduler_R26
  - test_coverage_final.py    → TestScheduler_Final
  - test_coverage_round5.py   → TestSchedulerLazy
  - test_coverage_round6.py   → TestSchedulerLazy_R6
  - test_coverage_round3.py   → TestSchedulerDispatch
  - test_coverage_push.py     → TestSchedulerExtended
  - test_pipeline_api.py      → TestWriteHeartbeat_PipelineApi
  - test_db.py                → TestSchedulerDbMaintenance_Db
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from nuri.core.db import init_db

# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Isolated DB for scheduler tests."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


# ═══════════════════════════════════════════════════════
# TestScheduler — from test_coverage_round17.py
# ═══════════════════════════════════════════════════════


class TestScheduler:
    """Tests for nuri/scheduler.py."""

    def test_run_collector_stock(self):
        """_run_collector dispatches to StockCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.stock.StockCollector", return_value=mock_collector):
            _run_collector("stock")
        mock_collector.run.assert_called_once()

    def test_run_collector_stock_kr(self):
        """_run_collector dispatches to StockKRCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.stock_kr.StockKRCollector", return_value=mock_collector):
            _run_collector("stock_kr")
        mock_collector.run.assert_called_once()

    def test_run_collector_macro(self):
        """_run_collector dispatches to MacroCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.macro.MacroCollector", return_value=mock_collector):
            _run_collector("macro")
        mock_collector.run.assert_called_once()

    def test_run_collector_technical(self):
        """_run_collector dispatches to TechnicalCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.technical.TechnicalCollector", return_value=mock_collector):
            _run_collector("technical")
        mock_collector.run.assert_called_once()

    def test_run_collector_fear_greed(self):
        """_run_collector dispatches to FearGreedCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.fear_greed.FearGreedCollector", return_value=mock_collector):
            _run_collector("fear_greed")
        mock_collector.run.assert_called_once()

    def test_run_collector_ark(self):
        """_run_collector dispatches to ARKCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.ark.ARKCollector", return_value=mock_collector):
            _run_collector("ark")
        mock_collector.run.assert_called_once()

    def test_run_collector_events(self):
        """_run_collector dispatches to EventsCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.events.EventsCollector", return_value=mock_collector):
            _run_collector("events")
        mock_collector.run.assert_called_once()

    def test_run_collector_news(self):
        """_run_collector dispatches to NewsCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.news.NewsCollector", return_value=mock_collector):
            _run_collector("news")
        mock_collector.run.assert_called_once()

    def test_run_collector_fundamental(self):
        """_run_collector dispatches to FundamentalCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.fundamental.FundamentalCollector", return_value=mock_collector):
            _run_collector("fundamental")
        mock_collector.run.assert_called_once()

    def test_run_collector_superinvestors(self):
        """_run_collector dispatches to SuperinvestorCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.superinvestors.SuperinvestorCollector", return_value=mock_collector):
            _run_collector("superinvestors")
        mock_collector.run.assert_called_once()

    def test_run_collector_estimates(self):
        """_run_collector dispatches to EstimatesCollector + forwards kwargs (#420)."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.estimates.EstimatesCollector", return_value=mock_collector):
            _run_collector("estimates", source="universe")
        mock_collector.run.assert_called_once_with(source="universe")

    def test_run_collector_etf_flows(self):
        """_run_collector dispatches to EtfFlowsCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.etf_flows.EtfFlowsCollector", return_value=mock_collector):
            _run_collector("etf_flows")
        mock_collector.run.assert_called_once()

    def test_run_collector_wallstreet(self):
        """_run_collector dispatches to WallStreetCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.wallstreet.WallStreetCollector", return_value=mock_collector):
            _run_collector("wallstreet")
        mock_collector.run.assert_called_once()

    def test_run_collector_memory_snapshot(self):
        """_run_collector dispatches to memory save_snapshot."""
        from nuri.scheduler import _run_collector

        with patch("nuri.trading.engine.memory.save_snapshot", return_value=5) as mock_snap:
            _run_collector("memory_snapshot")
        mock_snap.assert_called_once()

    def test_run_collector_exception_handled(self):
        """_run_collector catches exceptions and logs them."""
        from nuri.scheduler import _run_collector

        with patch("nuri.collectors.stock.StockCollector", side_effect=RuntimeError("boom")):
            # should not raise
            _run_collector("stock")

    def test_run_collector_unknown_name(self):
        """_run_collector does nothing for unknown collector names."""
        from nuri.scheduler import _run_collector

        # no exception, just returns
        _run_collector("nonexistent_collector")

    def test_run_report(self):
        """_run_report calls daily_report.main."""
        from nuri.scheduler import _run_report

        with patch("nuri.alerts.daily_report.main") as mock_main:
            _run_report()
        mock_main.assert_called_once()

    def test_run_report_exception(self):
        """_run_report catches exceptions."""
        from nuri.scheduler import _run_report

        with patch("nuri.alerts.daily_report.main", side_effect=RuntimeError("fail")):
            # should not raise
            _run_report()

    def test_run_backup(self):
        """_run_backup calls subprocess."""
        from nuri.scheduler import _run_backup

        with patch("subprocess.run") as mock_run:
            _run_backup()
        mock_run.assert_called_once()

    def test_backup_script_path_exists(self):
        """Gotcha-Test Pair (#836): scheduler 가 참조하는 백업 스크립트 경로 실존 lock.

        #557 리팩터가 scripts/backup.sh → scripts/db/backup.sh 로 옮기면서
        scheduler 호출 경로가 2개월간 silent 404 (rc=127, logger.error 만) —
        mock-only 테스트 (위 test_run_backup) 로는 경로 drift 를 못 잡는다.
        스크립트를 다시 옮기면 본 테스트가 즉시 FAIL.
        """
        from pathlib import Path

        from nuri.scheduler import BACKUP_SCRIPT

        repo_root = Path(__file__).resolve().parents[1]
        script = repo_root / BACKUP_SCRIPT
        assert script.is_file(), f"백업 스크립트 경로 drift: {script} 없음 (#836)"

    def test_run_backup_exception(self):
        """_run_backup catches exceptions."""
        from nuri.scheduler import _run_backup

        with patch("subprocess.run", side_effect=RuntimeError("fail")):
            _run_backup()

    def test_run_db_maintenance(self):
        """_run_db_maintenance calls run_maintenance."""
        from nuri.scheduler import _run_db_maintenance

        with patch("scripts.db.maintenance.run_maintenance") as mock_maint:
            _run_db_maintenance()
        mock_maint.assert_called_once()

    def test_run_db_maintenance_exception(self):
        """_run_db_maintenance catches exceptions."""
        from nuri.scheduler import _run_db_maintenance

        with patch("scripts.db.maintenance.run_maintenance", side_effect=RuntimeError("fail")):
            _run_db_maintenance()

    def test_create_scheduler(self):
        """create_scheduler() registers all jobs."""
        from nuri.scheduler import SCHEDULES, create_scheduler

        scheduler = create_scheduler()
        jobs = scheduler.get_jobs()

        # +1 for heartbeat
        assert len(jobs) == len(SCHEDULES) + 1

        job_names = {j.id for j in jobs}
        assert "heartbeat" in job_names
        assert "stock_us_night" in job_names
        assert "backup" in job_names

    def test_print_schedule(self, capsys):
        """print_schedule() outputs schedule list."""
        from nuri.scheduler import print_schedule

        print_schedule()
        out = capsys.readouterr().out
        assert "stock_us_night" in out

    def test_write_heartbeat(self, tmp_path, monkeypatch):
        """_write_heartbeat() writes timestamp file."""
        from nuri.scheduler import _write_heartbeat

        hb_path = tmp_path / ".scheduler_heartbeat"
        monkeypatch.setattr("nuri.scheduler.HEARTBEAT_PATH", hb_path)
        _write_heartbeat()
        assert hb_path.exists()

    def test_self_restart_kickstarts_scheduler(self):
        """_self_restart() launchctl kickstart -k 로 자가 재시작 요청 (#780)."""
        from nuri.scheduler import _self_restart

        with patch("subprocess.run") as mock_run:
            _self_restart()
        mock_run.assert_called_once()
        cmd = mock_run.call_args.args[0]
        assert cmd[:3] == ["launchctl", "kickstart", "-k"]
        assert cmd[3].endswith("com.nuri-quant.scheduler")

    def test_self_restart_handles_missing_launchctl(self):
        """launchctl 부재(비배포) — 예외 삼키고 데몬 계속 (#780)."""
        from nuri.scheduler import _self_restart

        with patch("subprocess.run", side_effect=FileNotFoundError("launchctl")):
            _self_restart()  # 예외 전파 없이 graceful skip


# ═══════════════════════════════════════════════════════
# TestScheduler_R2 — from test_coverage_round2.py
# ═══════════════════════════════════════════════════════


class TestScheduler_R2:
    def test_schedules_structure(self):
        from nuri.scheduler import SCHEDULES

        assert len(SCHEDULES) >= 17
        for s in SCHEDULES:
            assert "name" in s
            assert "func" in s
            assert "cron" in s

    def test_spy_benchmark_wired_to_daily_freshness(self):
        """Gotcha-Test Pair (#860): §3.11 벤치마크(SPY) 일일 수집 배선 lock.

        stock_us_night/dawn 은 source=portfolio(held)만 → SPY(universe-only 벤치마크)가
        주간 backfill 에만 의존해 최대 1주 stale → forward_outcome_tracker(매일) alpha
        부정확 + 레짐 분류 차단. daily freshness job 을 제거/변경하면 즉시 FAIL.
        """
        from nuri.collectors.stock import _load_freshness_tickers
        from nuri.core.rules import RULES
        from nuri.scheduler import SCHEDULES

        # (a) scheduler 에 매일(요일 2-6) source=freshness 수집 job 이 있어야 함
        fresh_jobs = [
            s for s in SCHEDULES if s.get("kwargs", {}).get("source") == "freshness" and s["args"] == ("stock",)
        ]
        assert fresh_jobs, "source=freshness daily job 미배선 (#860 회귀)"
        assert any("* * 2-6" in s["cron"] or "* * 1-5" in s["cron"] for s in fresh_jobs), (
            "freshness job 이 주중 일일 cron 이 아님"
        )

        # (b) 측정 모드 벤치마크가 freshness 수집 대상에 실제로 포함되는지
        benchmark = RULES["measurement_mode"]["benchmark"]
        assert benchmark in _load_freshness_tickers(), f"{benchmark} 이 freshness 티커에 없음"

    def test_run_collector_unknown(self):
        """존재하지 않는 collector → 에러 로그만, 예외 없음."""
        from nuri.scheduler import _run_collector

        # 존재하지 않는 collector 이름 → 로그만 남기고 반환
        _run_collector("nonexistent_collector_xyz")

    def test_write_heartbeat(self, tmp_path, monkeypatch):
        from nuri.scheduler import _write_heartbeat

        hb_path = tmp_path / ".scheduler_heartbeat"
        monkeypatch.setattr("nuri.scheduler.HEARTBEAT_PATH", hb_path)
        _write_heartbeat()
        assert hb_path.exists()
        content = hb_path.read_text()
        assert len(content) > 0


# ═══════════════════════════════════════════════════════
# TestScheduler_R27 — from test_coverage_round27.py
# ═══════════════════════════════════════════════════════


class TestScheduler_R27:
    """Tests for nuri/scheduler.py."""

    def test_run_collector_unknown(self):
        """_run_collector with unknown name does nothing."""
        from nuri.scheduler import _run_collector

        # Should not raise
        _run_collector("totally_unknown_collector_name")

    def test_run_collector_stock_exception(self, monkeypatch):
        """_run_collector handles runtime errors."""
        from nuri.scheduler import _run_collector

        # Mock the actual collector to raise
        mock_collector = MagicMock()
        mock_collector.return_value.run.side_effect = Exception("test error")
        monkeypatch.setattr("nuri.collectors.stock.StockCollector", mock_collector)
        # Should not raise, just log error
        _run_collector("stock")

    def test_run_report_exception(self, monkeypatch):
        """_run_report handles exception."""
        from nuri.scheduler import _run_report

        # Should not raise
        _run_report()

    def test_run_backup_exception(self, monkeypatch):
        """_run_backup handles exception."""
        import subprocess

        from nuri.scheduler import _run_backup

        monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=Exception("no script")))
        _run_backup()

    def test_run_db_maintenance_exception(self):
        """_run_db_maintenance handles exception."""
        from nuri.scheduler import _run_db_maintenance

        _run_db_maintenance()  # Script likely doesn't exist in test env

    def test_write_heartbeat(self, tmp_path, monkeypatch):
        """_write_heartbeat writes file."""
        import nuri.scheduler as sched_mod
        from nuri.scheduler import _write_heartbeat

        monkeypatch.setattr(sched_mod, "HEARTBEAT_PATH", tmp_path / ".heartbeat")
        _write_heartbeat()
        assert (tmp_path / ".heartbeat").exists()

    def test_print_schedule(self, capsys):
        """print_schedule outputs schedule list."""
        from nuri.scheduler import print_schedule

        print_schedule()
        captured = capsys.readouterr()
        assert "Nuri-Quant Scheduler" in captured.out

    def test_create_scheduler(self):
        """create_scheduler creates and registers jobs."""
        from nuri.scheduler import SCHEDULES, create_scheduler

        scheduler = create_scheduler()
        jobs = scheduler.get_jobs()
        # Should have SCHEDULES + heartbeat
        assert len(jobs) == len(SCHEDULES) + 1


# ═══════════════════════════════════════════════════════
# TestScheduler_R26 — from test_coverage_round26.py
# ═══════════════════════════════════════════════════════


class TestScheduler_R26:
    def test_create_scheduler(self, monkeypatch):
        from nuri.scheduler import SCHEDULES, create_scheduler

        scheduler = create_scheduler()
        # Should have all schedules + heartbeat
        jobs = scheduler.get_jobs()
        assert len(jobs) == len(SCHEDULES) + 1  # +1 heartbeat

    def test_print_schedule(self, capsys):
        from nuri.scheduler import print_schedule

        print_schedule()
        out = capsys.readouterr().out
        assert "Nuri-Quant Scheduler" in out

    def test_main_dry_run(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["scheduler", "--dry-run"])
        from nuri.scheduler import main

        main()
        out = capsys.readouterr().out
        assert "Scheduler" in out

    def test_main_signal_handler(self, monkeypatch, capsys):
        """Cover signal handler setup + scheduler.start() (lines 237-247)."""
        monkeypatch.setattr("sys.argv", ["scheduler"])

        mock_scheduler = MagicMock()
        mock_scheduler.get_jobs.return_value = []
        # Simulate scheduler.start() then stop
        mock_scheduler.start.return_value = None

        monkeypatch.setattr(
            "nuri.scheduler.create_scheduler",
            lambda: mock_scheduler,
        )

        from nuri.scheduler import main

        main()
        mock_scheduler.start.assert_called_once()

    def test_shutdown_handler(self, monkeypatch):
        """Directly test the shutdown signal handler."""
        mock_scheduler = MagicMock()
        monkeypatch.setattr("sys.argv", ["scheduler"])
        monkeypatch.setattr("nuri.scheduler.create_scheduler", lambda: mock_scheduler)
        # We can't easily test signal handlers, so just verify create_scheduler works
        from nuri.scheduler import create_scheduler

        sched = create_scheduler()
        assert sched is not None

    def test_run_collector_unknown(self):
        from nuri.scheduler import _run_collector

        _run_collector("unknown_name")  # Should not raise

    def test_run_collector_error(self, monkeypatch):
        """Cover error handling in _run_collector."""
        monkeypatch.setattr(
            "nuri.collectors.stock.StockCollector",
            MagicMock(side_effect=Exception("import fail")),
        )
        from nuri.scheduler import _run_collector

        _run_collector("stock")  # Should log error, not raise

    def test_run_report_error(self, monkeypatch):
        monkeypatch.setattr(
            "nuri.alerts.daily_report.main",
            MagicMock(side_effect=Exception("fail")),
        )
        from nuri.scheduler import _run_report

        _run_report()  # Should not raise

    def test_run_backup_error(self, monkeypatch):
        monkeypatch.setattr("subprocess.run", MagicMock(side_effect=Exception("fail")))
        from nuri.scheduler import _run_backup

        _run_backup()  # Should not raise

    def test_write_heartbeat(self, tmp_path, monkeypatch):
        import nuri.scheduler as sched_mod

        monkeypatch.setattr(sched_mod, "HEARTBEAT_PATH", tmp_path / ".scheduler_heartbeat")
        from nuri.scheduler import _write_heartbeat

        _write_heartbeat()
        assert (tmp_path / ".scheduler_heartbeat").exists()

    def test_run_db_maintenance_error(self, monkeypatch):
        """Cover _run_db_maintenance error path."""
        # The import happens inside the function, so mock the module
        mock_mod = MagicMock()
        mock_mod.run_maintenance = MagicMock(side_effect=Exception("fail"))
        monkeypatch.setitem(sys.modules, "scripts.db.maintenance", mock_mod)
        from nuri.scheduler import _run_db_maintenance

        _run_db_maintenance()  # Should not raise


# ═══════════════════════════════════════════════════════
# TestScheduler_Final — from test_coverage_final.py
# ═══════════════════════════════════════════════════════


class TestScheduler_Final:
    def test_schedules_list(self):
        from nuri.scheduler import SCHEDULES

        assert len(SCHEDULES) > 0
        for s in SCHEDULES:
            assert "name" in s or "job" in s or len(s) >= 2


# ═══════════════════════════════════════════════════════
# TestSchedulerLazy — from test_coverage_round5.py
# ═══════════════════════════════════════════════════════


class TestSchedulerLazy:
    def test_run_collector_all_names(self):
        """모든 collector name에 대해 _run_collector 호출."""
        from nuri.scheduler import SCHEDULES, _run_collector

        collector_names = [s["name"] for s in SCHEDULES if s["func"] == _run_collector]
        for name in collector_names[:5]:  # 처음 5개만 테스트 (속도)
            _run_collector(name)

    def test_main_signal_handler(self):
        """main()의 시그널 핸들러 등록."""
        from nuri.scheduler import SCHEDULES

        # SCHEDULES가 올바른 구조인지만 확인
        assert all("func" in s for s in SCHEDULES)


# ═══════════════════════════════════════════════════════
# TestSchedulerLazy_R6 — from test_coverage_round6.py
# ═══════════════════════════════════════════════════════


class TestSchedulerLazy_R6:
    @pytest.mark.slow
    def test_run_collector_known_names(self):
        """실제 collector 이름 호출 — conftest mock 덕분에 네트워크 안 탐."""
        from nuri.scheduler import _run_collector

        names = [
            "stock",
            "stock_kr",
            "macro",
            "technical",
            "fear_greed",
            "ark",
            "news",
            "fundamental",
            "estimates",
            "wallstreet",
            "cboe",
            "finviz",
            "etf_flows",
        ]
        for name in names:
            _run_collector(name)  # lazy import + run() 호출

    def test_run_collector_reddit(self):
        from nuri.scheduler import _run_collector

        _run_collector("reddit")

    def test_run_collector_events(self):
        from nuri.scheduler import _run_collector

        _run_collector("events")


# ═══════════════════════════════════════════════════════
# TestSchedulerDispatch — from test_coverage_round3.py
# ═══════════════════════════════════════════════════════


class TestSchedulerDispatch:
    def test_run_collector_memory_snapshot(self):
        from nuri.scheduler import _run_collector

        _run_collector("memory_snapshot")

    def test_run_backup(self):
        from nuri.scheduler import _run_backup

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _run_backup()

    def test_run_db_maintenance(self):
        from nuri.scheduler import _run_db_maintenance

        with patch("scripts.db.maintenance.run_maintenance"):
            _run_db_maintenance()

    def test_schedules_cron_format(self):
        from nuri.scheduler import SCHEDULES

        for s in SCHEDULES:
            cron = s["cron"]
            assert isinstance(cron, str), f"{s['name']}: cron should be str"
            parts = cron.split()
            assert len(parts) == 5, f"{s['name']}: cron should have 5 parts"

    def test_print_schedule(self, capsys):
        from nuri.scheduler import print_schedule

        print_schedule()
        output = capsys.readouterr().out
        assert "stock" in output.lower() or "schedule" in output.lower() or len(output) > 0


# ═══════════════════════════════════════════════════════
# TestSchedulerExtended — from test_coverage_push.py
# ═══════════════════════════════════════════════════════


class TestSchedulerExtended:
    def test_schedules_structure(self):
        from nuri.scheduler import SCHEDULES

        for s in SCHEDULES:
            assert isinstance(s, dict)
            # 각 스케줄에 cron과 job이 있어야 함
            assert "name" in s

    def test_run_collector_import(self):
        """_run_collector 함수가 존재하는지."""
        from nuri.scheduler import _run_collector

        assert callable(_run_collector)


# ═══════════════════════════════════════════════════════
# TestWriteHeartbeat_PipelineApi — from test_pipeline_api.py
# ═══════════════════════════════════════════════════════


class TestWriteHeartbeat_PipelineApi:
    def test_creates_file(self, tmp_path, monkeypatch):
        """_write_heartbeat가 파일 생성."""
        import nuri.scheduler as sched

        monkeypatch.setattr(sched, "HEARTBEAT_PATH", tmp_path / ".hb")
        sched._write_heartbeat()
        assert (tmp_path / ".hb").exists()


# ═══════════════════════════════════════════════════════
# TestSchedulerDbMaintenance_Db — from test_db.py
# ═══════════════════════════════════════════════════════


class TestSchedulerDecisions:
    """Tests for decision_outcomes and agent_accuracy schedule entries."""

    def test_decision_pnl_and_alpha_in_schedules(self):
        """SCHEDULES에 decision_pnl(raw P&L) + alpha_tracking(realized alpha) 엔트리 존재."""
        from nuri.scheduler import SCHEDULES

        names = [s["name"] for s in SCHEDULES]
        assert "decision_pnl" in names
        assert "alpha_tracking" in names  # ForwardOutcomeTracker → decision_outcomes 테이블

    def test_agent_accuracy_in_schedules(self):
        """SCHEDULES에 agent_accuracy 엔트리 존재."""
        from nuri.scheduler import SCHEDULES

        names = [s["name"] for s in SCHEDULES]
        assert "agent_accuracy" in names

    def test_decision_pnl_cron(self):
        """decision_pnl: 매일 07:00 KST."""
        from nuri.scheduler import SCHEDULES

        entry = next(s for s in SCHEDULES if s["name"] == "decision_pnl")
        assert entry["cron"] == "0 7 * * *"

    def test_alpha_tracking_cron(self):
        """alpha_tracking: 매일 17:00 KST (한국장 마감 후, 흡수된 launchd track-forward timing)."""
        from nuri.scheduler import SCHEDULES

        entry = next(s for s in SCHEDULES if s["name"] == "alpha_tracking")
        assert entry["cron"] == "0 17 * * *"

    def test_no_launchd_plist_duplicates_alpha_tracking(self):
        """#762: ForwardOutcomeTracker 17:00 scan 은 scheduler(alpha_tracking)가 canonical.

        어떤 launchd plist 도 이를 중복 스케줄하면 안 된다 — 과거 track-forward.plist 가
        install_crons 자동발견으로 기본 설치되어 scheduler job 과 17:00 이중 발화했다.
        """
        from pathlib import Path

        plist_dir = Path(__file__).resolve().parent.parent / "scripts" / "launchd"
        for p in plist_dir.glob("com.nuri-quant.*.plist"):
            assert "forward_outcome_tracker" not in p.read_text(), (
                f"{p.name} 가 forward_outcome_tracker scan 을 중복 스케줄 (scheduler alpha_tracking 와 17:00 충돌)"
            )

        from nuri.scheduler import SCHEDULES

        assert any(s["name"] == "alpha_tracking" for s in SCHEDULES), "scheduler canonical alpha_tracking job 부재"

    def test_agent_accuracy_cron(self):
        """agent_accuracy: 일요일 08:00 KST."""
        from nuri.scheduler import SCHEDULES

        entry = next(s for s in SCHEDULES if s["name"] == "agent_accuracy")
        assert entry["cron"] == "0 8 * * 0"

    def test_run_collector_decision_pnl(self):
        """_run_collector('decision_pnl') dispatches to track_decision_outcomes (raw P&L)."""
        from nuri.scheduler import _run_collector

        with patch("nuri.trading.engine.decisions.track_decision_outcomes", return_value=3) as mock_fn:
            _run_collector("decision_pnl")
        mock_fn.assert_called_once()

    def test_run_collector_alpha_tracking(self):
        """_run_collector('alpha_tracking') dispatches to ForwardOutcomeTracker.scan (realized alpha)."""
        from unittest.mock import MagicMock

        from nuri.scheduler import _run_collector

        with patch("nuri.agents.actors.forward_outcome_tracker.ForwardOutcomeTracker") as mock_cls:
            mock_cls.return_value.run.return_value = MagicMock(
                output={"synced_from_recommendations": 2, "n_measurements": 6}
            )
            _run_collector("alpha_tracking")
        mock_cls.return_value.run.assert_called_once()
        # scan action 으로 호출됐는지
        assert mock_cls.return_value.run.call_args[0][0]["action"] == "scan"

    def test_run_collector_agent_accuracy(self):
        """_run_collector dispatches to save_agent_accuracy_snapshot."""
        from nuri.scheduler import _run_collector

        with patch("nuri.trading.engine.decisions.save_agent_accuracy_snapshot", return_value=5) as mock_fn:
            _run_collector("agent_accuracy")
        mock_fn.assert_called_once()

    def test_run_collector_recommendation_outcomes(self):
        """_run_collector dispatches to tracker.track_outcomes (#899)."""
        from nuri.scheduler import _run_collector

        with patch("nuri.trading.recommend.tracker.track_outcomes", return_value=12) as mock_fn:
            _run_collector("recommendation_outcomes")
        mock_fn.assert_called_once_with()

    def test_recommendation_outcomes_runs_before_consensus(self):
        """`recommendation_outcomes` 는 반드시 `consensus` **보다 먼저** 돈다.

        Gotcha-Test Pair: consensus 의 learning_memory 가 `recommendations.outcome_30d`
        (canonical) / `outcome_21d` (provisional) 를 읽어 에이전트 가중치를 만든다.
        순서가 뒤집히면 매일 하루 묵은 outcome 으로 가중치를 계산하게 되는데, 값이
        그럴듯해서 **틀린 걸 알아차릴 방법이 없다**. 순서 자체가 계약이라 잠근다.

        원 결함(#899)은 이 job 이 `make recommend` CLI 에만 있고 SCHEDULES 에는 아예
        없어서, 프로덕션 outcome_* 1,170행이 전부 NULL → 가중치가 DEFAULT 로 영구
        고정된 것이었다. dev 는 사람이 CLI 를 돌려 채워지므로 정상으로 보였다.
        """
        from nuri.scheduler import SCHEDULES

        jobs = {j["name"]: j for j in SCHEDULES}
        assert "recommendation_outcomes" in jobs, "SCHEDULES 에 recommendation_outcomes 미등록"

        def _minute_of_day(cron: str) -> int:
            minute, hour = cron.split()[0], cron.split()[1]
            return int(hour) * 60 + int(minute)

        outcomes_at = _minute_of_day(jobs["recommendation_outcomes"]["cron"])
        consensus_at = _minute_of_day(jobs["consensus"]["cron"])
        assert outcomes_at < consensus_at, (
            f"recommendation_outcomes({jobs['recommendation_outcomes']['cron']}) 가 "
            f"consensus({jobs['consensus']['cron']}) 보다 먼저 돌아야 한다"
        )
        # 미국 종가가 들어온 뒤여야 한다 — stock_us_dawn 은 06:59 에 끝난다.
        assert outcomes_at >= 7 * 60, "미국 종가 수집(00~06:59) 완료 후여야 함"

    def test_run_collector_consensus(self):
        """_run_collector dispatches to analyze_portfolio + save_to_recommendations + record_decisions.

        Phase 2 A-1a 의 read path fix 가 의미 있으려면 input 이 꾸준히 쌓여야 함 —
        이 job 이 매일 07:05 에 agent_verdicts 를 recommendations 테이블에 저장.
        Revert (dispatch 제거) 시 이 테스트 fail.
        """
        from nuri.scheduler import _run_collector

        # 비어있지 않은 sentinel — `return_value=[]` 로 두면 `record_decisions([])`,
        # `record_decisions(saved)` 같은 인자 변이가 전부 green 으로 통과한다.
        # `saved` 는 바로 윗줄 변수라 실제로 있을 법한 오타이고, 그 경우 production
        # 에서 `for r in 0` → TypeError 를 blanket except 가 삼켜 #897 과 **같은
        # 방식**으로 다시 동결된다. 그래서 호출 여부가 아니라 payload 를 잠근다.
        results = [object()]
        with (
            patch("nuri.trading.agents.consensus.analyze_portfolio", return_value=results) as m_analyze,
            patch("nuri.trading.agents.consensus.save_to_recommendations", return_value=0) as m_save,
            patch("nuri.trading.engine.decisions.record_decisions", return_value=0) as m_record,
        ):
            _run_collector("consensus")
        m_analyze.assert_called_once()
        m_save.assert_called_once_with(results)
        m_record.assert_called_once_with(results)

    def test_scheduler_and_cli_persist_to_the_same_tables(self):
        """자동(scheduler) 경로와 수동(CLI) 경로가 **같은 테이블 집합**에 쓴다.

        Gotcha-Test Pair (§5.3.1): PR #363 이 consensus 를 스케줄러로 자동화하면서
        CLI 에만 있던 `record_decisions()` 를 빠뜨렸다. 마지막 수동 실행(2026-04-14)
        이후 3.5 개월간 `decisions` 가 80 행에 동결됐고 /decisions 대시보드는 계속
        4 월 데이터를 서빙했다 — 헬스 지표는 전부 초록 (#897).

        위 `test_run_collector_consensus` 는 당시 두 함수만 단언해서 **불완전한
        동작을 lock-in** 했다. 그래서 개별 호출이 아니라 두 경로의 **동등성**을
        잠근다. 어느 한쪽에서 persistence 를 빼면 집합이 갈라지며 fail.

        기록하는 값은 호출 여부가 아니라 **전달된 payload** 다 — 호출 여부만 보면
        `record_decisions(saved)` 같은 인자 변이가 통과해버린다 (production 에서는
        TypeError 가 blanket except 에 삼켜져 같은 동결로 되돌아간다).
        """
        from nuri.scheduler import _run_collector
        from nuri.trading.agents.consensus import __main__ as cli

        results = [object()]

        # CLI 는 `from . import analyze_portfolio` 로 이름을 미리 바인딩하므로
        # 패키지 속성 patch 가 안 먹는다 → 모듈 속성을 직접 patch (tests/CLAUDE.md mock 함정).
        def _scheduler_path() -> dict[str, object]:
            seen: dict[str, object] = {}
            with (
                patch("nuri.trading.agents.consensus.analyze_portfolio", return_value=results),
                patch(
                    "nuri.trading.agents.consensus.save_to_recommendations",
                    side_effect=lambda r, *a, **k: seen.__setitem__("recommendations", r) or 0,
                ),
                patch(
                    "nuri.trading.engine.decisions.record_decisions",
                    side_effect=lambda r, *a, **k: seen.__setitem__("decisions", r) or 0,
                ),
            ):
                _run_collector("consensus")
            return seen

        def _cli_path() -> dict[str, object]:
            seen: dict[str, object] = {}
            with (
                patch.object(cli, "analyze_portfolio", return_value=results),
                patch.object(cli, "print_consensus"),
                patch.object(
                    cli,
                    "save_to_recommendations",
                    side_effect=lambda r, *a, **k: seen.__setitem__("recommendations", r) or 0,
                ),
                patch(
                    "nuri.trading.engine.decisions.record_decisions",
                    side_effect=lambda r, *a, **k: seen.__setitem__("decisions", r) or 0,
                ),
                patch("sys.argv", ["consensus"]),
            ):
                cli.main()
            return seen

        scheduler_writes, cli_writes = _scheduler_path(), _cli_path()
        assert scheduler_writes == cli_writes, (
            f"자동/수동 경로 persistence 불일치 — scheduler={sorted(scheduler_writes)} cli={sorted(cli_writes)}"
        )
        # 두 경로 모두 두 테이블에 **consensus 결과 그 자체**를 전달해야 한다.
        assert scheduler_writes == {"recommendations": results, "decisions": results}

    def test_schedules_include_consensus_job(self):
        """SCHEDULES 리스트에 consensus job entry 존재 — cron 스펙 lock-in."""
        from nuri.scheduler import SCHEDULES

        consensus_jobs = [j for j in SCHEDULES if j["name"] == "consensus"]
        assert len(consensus_jobs) == 1, "consensus job 정확히 1 개 필요"
        assert consensus_jobs[0]["args"] == ("consensus",)
        # 07:05 — technical 07:00 완료 후, daily_report 08:00 전
        assert consensus_jobs[0]["cron"] == "5 7 * * *"


class TestSchedulerDbMaintenance_Db:
    def test_scheduler_db_maintenance_runs(self, db_path, monkeypatch):
        """스케줄러 _run_db_maintenance가 정상 실행."""
        from nuri.scheduler import _run_db_maintenance

        _run_db_maintenance()  # 빈 DB에서도 에러 없이 실행


# ═══════════════════════════════════════════════════════
# TestUniverseBackfill — weekly 1y refresh for universe coverage
# ═══════════════════════════════════════════════════════


class TestUniverseBackfill:
    """Weekly 1y backfill SCHEDULE entries.

    실제 문제: 기존 stock_us_night/dawn/stock_kr 는 source="portfolio" 기본으로
    돌아 universe-only ticker (config/universe.yaml 만 등재) 는 일일 수집조차
    되지 않음. 실측 시 730/752 ticker 가 1-7일 stale.

    Fix: `stock_us_backfill` + `stock_kr_backfill` 주 1회 + source="all" + 1y
    window 로 gap 을 메운다. 기존 데일리 job 은 그대로 (rate-limit 고려).
    """

    def test_stock_us_backfill_entry_exists_with_correct_cron(self):
        """SCHEDULES 에 `stock_us_backfill` 항목이 있고 cron 이 일요일 05:00."""
        from nuri.scheduler import SCHEDULES

        entries = [s for s in SCHEDULES if s.get("name") == "stock_us_backfill"]
        assert len(entries) == 1, "stock_us_backfill 엔트리가 정확히 1개 존재해야 함"
        assert entries[0]["cron"] == "0 5 * * 0", "일요일 05:00 KST 실행"
        assert entries[0]["args"] == ("stock",), "_run_collector('stock', ...) 로 dispatch"

    def test_stock_us_backfill_kwargs_period_1y_source_all(self):
        """Backfill 은 `period='1y'` + `source='all'` 로 universe 전체 1년치 수집."""
        from nuri.scheduler import SCHEDULES

        entry = next(s for s in SCHEDULES if s.get("name") == "stock_us_backfill")
        assert entry.get("kwargs") == {"period": "1y", "source": "all"}, (
            "kwargs 는 period/source 를 명시적으로 전달. "
            "source='portfolio' 기본값으로 universe-only ticker 수집 누락 방지."
        )

    def test_stock_kr_backfill_entry_exists_with_correct_kwargs(self):
        """SCHEDULES 에 `stock_kr_backfill` 항목이 있고 days=365 + source=all."""
        from nuri.scheduler import SCHEDULES

        entries = [s for s in SCHEDULES if s.get("name") == "stock_kr_backfill"]
        assert len(entries) == 1
        assert entries[0]["cron"] == "30 5 * * 0", "일요일 05:30 KST (US 직후)"
        assert entries[0]["args"] == ("stock_kr",)
        assert entries[0].get("kwargs") == {"days": 365, "source": "all"}, (
            "stock_kr 는 `days=` 파라미터 사용. 1년치 = 365일."
        )

    def test_run_collector_stock_forwards_kwargs(self):
        """_run_collector('stock', period='1y', source='all') 이 StockCollector.run 에 그대로 전달."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.stock.StockCollector", return_value=mock_collector):
            _run_collector("stock", period="1y", source="all")
        mock_collector.run.assert_called_once_with(period="1y", source="all")

    def test_run_collector_stock_kr_forwards_kwargs(self):
        """_run_collector('stock_kr', days=365, source='all') 이 StockKRCollector.run 에 전달."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.stock_kr.StockKRCollector", return_value=mock_collector):
            _run_collector("stock_kr", days=365, source="all")
        mock_collector.run.assert_called_once_with(days=365, source="all")

    def test_estimates_entry_uses_universe_source(self):
        """SCHEDULES estimates 항목이 source='universe' kwargs 로 등록 (#420)."""
        from nuri.scheduler import SCHEDULES

        entries = [s for s in SCHEDULES if s.get("name") == "estimates"]
        assert len(entries) == 1, "estimates 엔트리 정확히 1개"
        assert entries[0]["cron"] == "0 2 * * 0", "일요일 02:00 KST"
        assert entries[0]["args"] == ("estimates",)
        assert entries[0].get("kwargs") == {"source": "universe"}, (
            "kwargs 누락 → portfolio 기본값으로 떨어져 universe 543 종목 수집 누락 (#420). "
            "이 lock 이 깨지면 estimates 테이블이 portfolio 8 종목만 누적."
        )

    def test_run_collector_estimates_forwards_kwargs(self):
        """_run_collector('estimates', source='universe') 이 EstimatesCollector.run 에 전달 (#420)."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.estimates.EstimatesCollector", return_value=mock_collector):
            _run_collector("estimates", source="universe")
        mock_collector.run.assert_called_once_with(source="universe")

    def test_create_scheduler_estimates_universe_kwargs(self):
        """create_scheduler 가 estimates universe kwargs 를 apscheduler 에 전달 (#420)."""
        from nuri.scheduler import create_scheduler

        scheduler = create_scheduler()
        job = scheduler.get_job("estimates")
        assert job is not None, "estimates job 이 등록돼야 함"
        assert job.kwargs == {"source": "universe"}, (
            "create_scheduler 가 SCHEDULES['kwargs'] 를 apscheduler 로 전달 누락 시 "
            "default portfolio 모드로 fallback — universe 자동 수집 silently 차단."
        )

    def test_create_scheduler_passes_kwargs_to_apscheduler(self):
        """create_scheduler 가 SCHEDULES 의 kwargs 를 apscheduler add_job 에 전달."""
        from nuri.scheduler import create_scheduler

        scheduler = create_scheduler()
        job = scheduler.get_job("stock_us_backfill")
        assert job is not None, "stock_us_backfill job 이 등록돼야 함"
        # apscheduler Job 에서 kwargs 는 job.kwargs 로 접근
        assert job.kwargs == {"period": "1y", "source": "all"}, (
            "create_scheduler 가 job.get('kwargs', {}) 를 add_job 으로 전달 해야 함. "
            "이 한 줄이 누락되면 period/source 가 무시되고 기본값 (5d/portfolio) 로 돌아감."
        )


# ═══════════════════════════════════════════════════════
# TestSchedulerLogRotation — RotatingFileHandler (PR #498)
# ═══════════════════════════════════════════════════════


class TestSchedulerLogRotation:
    """Mac mini 24/7 receiver runs the scheduler indefinitely; without
    rotation `data/logs/scheduler.log` grows unbounded. PR #498 adds a
    RotatingFileHandler with env-var tunable path.

    Per STRATEGY §5.3.1 Gotcha-Test Pair: this lock-test catches if the
    rotating handler is silently removed in a future refactor (the file
    would still get written via the basicConfig stream, but rotation
    would stop and the disk would fill).
    """

    def test_configure_logging_creates_rotating_handler(self, tmp_path, monkeypatch):
        """`_configure_logging` adds a RotatingFileHandler when env var is set."""
        import logging.handlers

        monkeypatch.setenv("NURI_SCHEDULER_LOG_DIR", str(tmp_path))
        monkeypatch.delenv("NURI_SCHEDULER_LOG_DISABLE_FILE", raising=False)
        # Re-import to re-run the module-level _configure_logging() with the
        # patched env var.
        import importlib

        import nuri.scheduler

        importlib.reload(nuri.scheduler)
        try:
            handlers = logging.getLogger().handlers
            rotating = [h for h in handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
            assert len(rotating) >= 1, "RotatingFileHandler must be attached"
            # Verify path + size cap match the documented contract
            h = rotating[-1]
            assert str(tmp_path) in str(h.baseFilename)
            assert h.maxBytes == 5 * 1024 * 1024
            assert h.backupCount == 3
        finally:
            # Clean up — the reload registered a real file handler. Detach so
            # subsequent tests don't accumulate handlers.
            for h in list(logging.getLogger().handlers):
                if isinstance(h, logging.handlers.RotatingFileHandler):
                    h.close()
                    logging.getLogger().removeHandler(h)

    def test_console_handler_warning_only_file_gets_info(self, tmp_path, monkeypatch):
        """Gotcha-Test Pair (#859): console(stderr)=WARNING+, file=INFO.

        basicConfig(INFO) 가 모든 INFO 를 stderr 로 보내 launchd scheduler.err 가
        로테이션 없이 무한 성장했음(189MB 실측). console 을 WARNING+ 로 되돌리면
        (또는 file 을 stderr 로 바꾸면) 이 테스트가 FAIL.
        """
        import importlib
        import logging as _logging
        import logging.handlers

        monkeypatch.setenv("NURI_SCHEDULER_LOG_DIR", str(tmp_path))
        monkeypatch.delenv("NURI_SCHEDULER_LOG_DISABLE_FILE", raising=False)
        import nuri.scheduler

        importlib.reload(nuri.scheduler)
        try:
            handlers = _logging.getLogger().handlers
            # console = StreamHandler 이지만 FileHandler(=RotatingFileHandler 부모) 아님
            console = [h for h in handlers if type(h) is _logging.StreamHandler]
            assert console, "console(stderr) handler 존재해야"
            assert all(h.level >= _logging.WARNING for h in console), (
                "console 은 WARNING+ 만 — INFO stderr 홍수 차단 (#859)"
            )
            rotating = [
                h
                for h in handlers
                if isinstance(h, logging.handlers.RotatingFileHandler) and str(tmp_path) in str(h.baseFilename)
            ]
            assert rotating and rotating[-1].level == _logging.INFO, "전체 INFO 스트림은 로테이션 파일로"
        finally:
            for h in list(_logging.getLogger().handlers):
                if isinstance(h, logging.handlers.RotatingFileHandler):
                    h.close()
                    _logging.getLogger().removeHandler(h)

    def test_reload_preserves_foreign_handlers(self, tmp_path, monkeypatch):
        """#859 회귀 lock: _configure_logging 재실행이 외부(pytest caplog 등) 핸들러를
        죽이지 않는다. root.handlers 전체 clear 시 caplog 가 shard 순서로 깨져
        CI Fast-1 이 실패했음 (test_postmarket_brief caplog 미포착, 2026-07-08).
        본 함수가 붙인 (_nuri_scheduler 마커) 핸들러만 교체해야 한다.
        """
        import importlib
        import logging as _logging

        monkeypatch.setenv("NURI_SCHEDULER_LOG_DIR", str(tmp_path))
        monkeypatch.delenv("NURI_SCHEDULER_LOG_DISABLE_FILE", raising=False)
        foreign = _logging.StreamHandler()  # caplog 모사 (마커 없음)
        _logging.getLogger().addHandler(foreign)
        try:
            import nuri.scheduler

            importlib.reload(nuri.scheduler)  # _configure_logging 재실행
            assert foreign in _logging.getLogger().handlers, "외부 handler 가 제거됨 (#859 회귀)"
        finally:
            _logging.getLogger().removeHandler(foreign)
            for h in list(_logging.getLogger().handlers):
                if getattr(h, "_nuri_scheduler", False):
                    h.close()
                    _logging.getLogger().removeHandler(h)

    def test_disable_env_var_skips_file_handler(self, tmp_path, monkeypatch):
        """`NURI_SCHEDULER_LOG_DISABLE_FILE=1` opt-out for CI / read-only FS."""
        import logging.handlers

        monkeypatch.setenv("NURI_SCHEDULER_LOG_DISABLE_FILE", "1")
        monkeypatch.setenv("NURI_SCHEDULER_LOG_DIR", str(tmp_path))
        import importlib

        import nuri.scheduler

        importlib.reload(nuri.scheduler)
        try:
            handlers = logging.getLogger().handlers
            rotating = [
                h
                for h in handlers
                if isinstance(h, logging.handlers.RotatingFileHandler) and str(tmp_path) in str(h.baseFilename)
            ]
            assert rotating == [], "disable env var must suppress file handler"
        finally:
            for h in list(logging.getLogger().handlers):
                if isinstance(h, logging.handlers.RotatingFileHandler):
                    h.close()
                    logging.getLogger().removeHandler(h)

    def test_yfinance_logger_silenced_to_warning(self, tmp_path, monkeypatch):
        """`_configure_logging` raises yfinance logger to WARNING.

        Lock-tests TODO Tier 2 P2 #10 (a) — ETF 404 / 401 Crumb noise must be
        suppressed at the global yfinance logger so scheduler.log doesn't flood
        on universe runs (746 tickers × routine 4xx). If a future refactor
        accidentally drops the line, this test catches the regression.
        """
        import logging as _logging

        monkeypatch.setenv("NURI_SCHEDULER_LOG_DISABLE_FILE", "1")
        import importlib

        import nuri.scheduler

        importlib.reload(nuri.scheduler)
        try:
            yflog = _logging.getLogger("yfinance")
            assert yflog.level == _logging.WARNING, (
                f"yfinance logger must be WARNING (got {yflog.level}) — "
                "scheduler.py::_configure_logging silenced INFO/ERROR noise"
            )
        finally:
            # Restore default for downstream tests that might assert on it.
            _logging.getLogger("yfinance").setLevel(_logging.NOTSET)


# ═══════════════════════════════════════════════════════
# TestSchedulerBootstrap — #575 init_db on startup
# ═══════════════════════════════════════════════════════


class TestSchedulerBootstrap:
    """`main()` 진입 시 `init_db()` 가 `create_scheduler()` 보다 먼저 호출되어야 함.

    배경: 신규 머신 / migration drift 누적 상태에서 scheduler 가 init_db() 없이
    부팅하면 첫 cron job 이 미적용 schema 로 실행되어 IntegrityError. #575 의 root
    cause 였고 직전 세션 (2026-05-02) 에 22→41 수동 catch-up 으로 워크어라운드.

    Gotcha-Test Pair (STRATEGY §5.3.1) — 본 테스트는 fix revert 시 fail.
    """

    def test_main_calls_init_db_before_scheduler_start(self, monkeypatch):
        """main() 이 scheduler.start() 이전에 init_db() 를 호출.

        실제 correctness boundary 는 "start() 이전" — create_scheduler() 는 job
        등록만 하므로 그 이전/이후는 무관. Codex review (PR #583) 후 의도적으로
        order assertion 을 완화 (init_db.index < start.index).
        """
        from nuri import scheduler as sched_mod

        call_order: list[str] = []

        mock_init_db = MagicMock(side_effect=lambda *a, **kw: call_order.append("init_db"))
        mock_scheduler = MagicMock()
        mock_scheduler.start.side_effect = lambda: call_order.append("start")

        monkeypatch.setattr(sched_mod, "init_db", mock_init_db)
        monkeypatch.setattr(sched_mod, "create_scheduler", MagicMock(return_value=mock_scheduler))
        # signal.signal 은 main 스레드 외에서 호출 시 ValueError — 우회.
        monkeypatch.setattr(sched_mod.signal, "signal", lambda *_a, **_kw: None)
        monkeypatch.setattr(sys, "argv", ["nuri.scheduler"])

        sched_mod.main()

        mock_init_db.assert_called_once()
        assert "init_db" in call_order and "start" in call_order, call_order
        assert call_order.index("init_db") < call_order.index("start"), (
            f"순서 어긋남: {call_order} — init_db 가 scheduler.start() 이전이어야 함 (#575)"
        )

    def test_dry_run_does_not_call_init_db(self, monkeypatch):
        """--dry-run 은 schedule 출력만 — DB 쓰기 회피 (CI / 검증용)."""
        from nuri import scheduler as sched_mod

        mock_init_db = MagicMock()
        monkeypatch.setattr(sched_mod, "init_db", mock_init_db)
        monkeypatch.setattr(sys, "argv", ["nuri.scheduler", "--dry-run"])

        sched_mod.main()

        mock_init_db.assert_not_called()


# ═══════════════════════════════════════════════════════
# TestOrphanCollectorsWired — #900
# ═══════════════════════════════════════════════════════


class TestOrphanCollectorsWired:
    """`make collect` 에만 있고 SCHEDULES 에 없던 collector 4종 (#900).

    2026-04-14 이후 프로덕션에 한 행도 안 쌓였다 — 그날이 마지막 수동 `make collect`
    이고 자동화가 이 넷을 안 가져갔다. `decisions` 동결(#897)·outcome 미기록(#899)과
    같은 날짜, 같은 drift 클래스.
    """

    ORPHANS = {
        "cboe": "nuri.collectors.cboe.CBOECollector",
        "coingecko": "nuri.collectors.coingecko.CoinGeckoCollector",
        "reddit": "nuri.collectors.reddit.RedditCollector",
        "fred_calendar": "nuri.collectors.fred_calendar.FREDCalendarCollector",
    }

    @pytest.mark.parametrize("job_name", sorted(ORPHANS))
    def test_dispatch_reaches_the_collector(self, job_name):
        """`_run_collector(name)` 이 해당 Collector.run() 을 부른다."""
        from nuri.scheduler import _run_collector

        mock = MagicMock()
        with patch(self.ORPHANS[job_name], return_value=mock):
            _run_collector(job_name)
        mock.run.assert_called_once()

    @pytest.mark.parametrize("job_name", sorted(ORPHANS))
    def test_registered_in_schedules(self, job_name):
        from nuri.scheduler import SCHEDULES

        jobs = [j for j in SCHEDULES if j["name"] == job_name]
        assert len(jobs) == 1, f"{job_name} job 이 정확히 1개여야 함"
        assert jobs[0]["args"] == (job_name,)

    def test_all_run_before_consensus(self):
        """네 job 모두 consensus(07:05) **보다 먼저** 돈다.

        Gotcha-Test Pair: reddit 은 `retail_agent` 의 유일한 입력이다
        (`retail_agent.py` 가 `macro.wsb_mention_<ticker>` / `wsb_post_count` 를 읽는다).
        consensus 뒤로 밀리면 10-agent 중 하나가 매일 하루 묵은 값으로 표를 던지는데,
        값이 그럴듯해서 틀린 걸 알아차릴 방법이 없다. 나머지 셋도 같은 이유로 선행.
        """
        from nuri.scheduler import SCHEDULES

        jobs = {j["name"]: j["cron"] for j in SCHEDULES}

        def _minute_of_day(cron: str) -> int:
            minute, hour = cron.split()[0], cron.split()[1]
            return int(hour) * 60 + int(minute)

        consensus_at = _minute_of_day(jobs["consensus"])
        for name in self.ORPHANS:
            assert _minute_of_day(jobs[name]) < consensus_at, (
                f"{name}({jobs[name]}) 가 consensus({jobs['consensus']}) 보다 늦다"
            )
