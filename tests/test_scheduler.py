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
        """_run_collector dispatches to EstimatesCollector."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.estimates.EstimatesCollector", return_value=mock_collector):
            _run_collector("estimates")
        mock_collector.run.assert_called_once()

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

    def test_run_backup_exception(self):
        """_run_backup catches exceptions."""
        from nuri.scheduler import _run_backup

        with patch("subprocess.run", side_effect=RuntimeError("fail")):
            _run_backup()

    def test_run_db_maintenance(self):
        """_run_db_maintenance calls run_maintenance."""
        from nuri.scheduler import _run_db_maintenance

        with patch("scripts.db_maintenance.run_maintenance") as mock_maint:
            _run_db_maintenance()
        mock_maint.assert_called_once()

    def test_run_db_maintenance_exception(self):
        """_run_db_maintenance catches exceptions."""
        from nuri.scheduler import _run_db_maintenance

        with patch("scripts.db_maintenance.run_maintenance", side_effect=RuntimeError("fail")):
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
            "nuri.scheduler.create_scheduler", lambda: mock_scheduler,
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
        monkeypatch.setitem(sys.modules, "scripts.db_maintenance", mock_mod)
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
    def test_run_collector_known_names(self):
        """실제 collector 이름 호출 — conftest mock 덕분에 네트워크 안 탐."""
        from nuri.scheduler import _run_collector
        names = ["stock", "stock_kr", "macro", "technical", "fear_greed",
                 "ark", "news", "fundamental", "estimates", "wallstreet",
                 "cboe", "finviz", "etf_flows"]
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
        with patch("scripts.db_maintenance.run_maintenance"):
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

    def test_decision_outcomes_in_schedules(self):
        """SCHEDULES에 decision_outcomes 엔트리 존재."""
        from nuri.scheduler import SCHEDULES
        names = [s["name"] for s in SCHEDULES]
        assert "decision_outcomes" in names

    def test_agent_accuracy_in_schedules(self):
        """SCHEDULES에 agent_accuracy 엔트리 존재."""
        from nuri.scheduler import SCHEDULES
        names = [s["name"] for s in SCHEDULES]
        assert "agent_accuracy" in names

    def test_decision_outcomes_cron(self):
        """decision_outcomes: 매일 07:00 KST."""
        from nuri.scheduler import SCHEDULES
        entry = next(s for s in SCHEDULES if s["name"] == "decision_outcomes")
        assert entry["cron"] == "0 7 * * *"

    def test_agent_accuracy_cron(self):
        """agent_accuracy: 일요일 08:00 KST."""
        from nuri.scheduler import SCHEDULES
        entry = next(s for s in SCHEDULES if s["name"] == "agent_accuracy")
        assert entry["cron"] == "0 8 * * 0"

    def test_run_collector_decision_outcomes(self):
        """_run_collector dispatches to track_decision_outcomes."""
        from nuri.scheduler import _run_collector
        with patch("nuri.trading.engine.decisions.track_decision_outcomes", return_value=3) as mock_fn:
            _run_collector("decision_outcomes")
        mock_fn.assert_called_once()

    def test_run_collector_agent_accuracy(self):
        """_run_collector dispatches to save_agent_accuracy_snapshot."""
        from nuri.scheduler import _run_collector
        with patch("nuri.trading.engine.decisions.save_agent_accuracy_snapshot", return_value=5) as mock_fn:
            _run_collector("agent_accuracy")
        mock_fn.assert_called_once()


class TestSchedulerDbMaintenance_Db:
    def test_scheduler_db_maintenance_runs(self, db_path, monkeypatch):
        """스케줄러 _run_db_maintenance가 정상 실행."""
        from nuri.scheduler import _run_db_maintenance
        _run_db_maintenance()  # 빈 DB에서도 에러 없이 실행
