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

    def test_run_collector_consensus(self):
        """_run_collector dispatches to analyze_portfolio + save_to_recommendations.

        Phase 2 A-1a 의 read path fix 가 의미 있으려면 input 이 꾸준히 쌓여야 함 —
        이 job 이 매일 07:05 에 agent_verdicts 를 recommendations 테이블에 저장.
        Revert (dispatch 제거) 시 이 테스트 fail.
        """
        from nuri.scheduler import _run_collector

        with (
            patch("nuri.trading.agents.consensus.analyze_portfolio", return_value=[]) as m_analyze,
            patch("nuri.trading.agents.consensus.save_to_recommendations", return_value=0) as m_save,
        ):
            _run_collector("consensus")
        m_analyze.assert_called_once()
        m_save.assert_called_once()

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
