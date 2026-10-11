"""Maintenance-Auditor 분기 잠금 — 캡 · 스캔 축 · 액션 · CLI 의 나머지 경로.

줄 실행이 아니라 결과를 본다: 원장 상태, output 카운터, 후보 title/detail, 그리고
subprocess 경계의 argv. 스캐너는 `ctx.run`(또는 `ma.subprocess.run`)에서 대역을 쓰므로
실 `uv`/`bash` 는 뜨지 않는다.
"""

from __future__ import annotations

import io
import json
import logging
import runpy
import subprocess as real_subprocess
import sys
from datetime import datetime, timedelta

import pytest

from nuri.agents.actors import maintenance_auditor as ma
from nuri.core.db import (
    get_db,
    init_db,
    list_maintenance_candidates,
    log_collector_run,
    maintenance_review_stats,
    review_maintenance_candidate,
    stage_maintenance_candidate,
)
from nuri.core.timezone import KST


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "audit.db"
    init_db(path)
    return path


@pytest.fixture()
def quiet_ops(monkeypatch):
    """#ops 표면화를 끈다 — 스캔 테스트가 outbox 를 건드리지 않게."""
    monkeypatch.setattr(ma.MaintenanceAuditor, "_surface_summary", lambda self, output: None)


@pytest.fixture()
def default_db(tmp_path, monkeypatch):
    """CLI 는 db_path 를 받지 않는다 — 기본 DB 를 격리 사본으로 돌린다."""
    import nuri.core.db as dbmod

    path = tmp_path / "cli.db"
    init_db(path)
    monkeypatch.setattr(dbmod, "DB_PATH", path)
    return path


@pytest.fixture()
def restore_actor_registry():
    """runpy 재실행은 `@REGISTRY.register` 를 다시 돌려 `__main__` 사본으로 덮어쓴다 —
    `REGISTRY.get(name) is MaintenanceAuditor` 를 보는 다른 테스트를 오염시키지 않게 되돌린다."""
    from nuri.agents.base import REGISTRY

    snapshot = dict(REGISTRY._registry)
    yield
    REGISTRY._registry.clear()
    REGISTRY._registry.update(snapshot)


def _ctx(repo_root, db_path=None):
    return ma.ScanContext(repo_root=repo_root, tracker=ma._CapTracker(caps=ma.AuditCaps()), db_path=db_path)


def _scan(db_path, caps=None):
    input_data = {"action": "scan", "db_path": db_path}
    if caps:
        input_data["caps"] = caps
    return ma.MaintenanceAuditor().run(input_data)


def _completed(argv, rc=0, stdout="", stderr=""):
    return real_subprocess.CompletedProcess(argv, rc, stdout, stderr)


def _finding(title, detail="d"):
    return {"axis": "doc_drift", "title": title, "detail": detail}


class TestCapsInsideTheScanLoop:
    def test_a_budget_spent_inside_a_scanner_stops_before_its_findings_are_staged(
        self, db_path, quiet_ops, monkeypatch
    ):
        """wall-clock 은 subprocess 앞에서만이 아니라 **후보마다** 다시 본다 — 스캐너가 예산을 다
        태우면 그 스캐너가 낸 후보도 원장에 들어가지 않는다."""

        def slow_scanner(ctx):
            ctx.tracker.started -= 999  # 스캐너가 예산을 다 쓴 상태
            return [_finding("late")]

        monkeypatch.setattr(ma, "SCANNERS", (slow_scanner,))
        result = _scan(db_path)

        assert result.output["aborted_by_cap"] == "wall_clock"
        assert result.outcome == ma.Outcome.WARN
        assert list_maintenance_candidates(db_path=db_path) == []

    def test_spend_inside_the_usd_cap_is_counted_not_aborted(self, db_path, quiet_ops, monkeypatch):
        """캡 안의 지출은 계속 가되 output 에 그대로 적힌다 — Phase 1 LLM 이 붙을 자리다."""

        def spender(ctx):
            ctx.tracker.charge_usd(0.25)
            ctx.tracker.charge_usd(0.25)
            return [_finding("after spend")]

        monkeypatch.setattr(ma, "SCANNERS", (spender,))
        result = _scan(db_path, caps={"usd": 1.0})

        assert result.output["aborted_by_cap"] is None
        assert result.output["usd_spent"] == 0.5
        assert result.output["staged"] == 1

    def test_a_subprocess_timeout_is_charged_and_ends_the_scan_as_wall_clock(self, db_path, quiet_ops, monkeypatch):
        """subprocess 하나가 남은 예산을 넘기면 `wall_clock` 중단이다 — 일반 스캐너 오류로 흘러가면
        예산을 넘긴 스캔이 다음 축을 계속 돈다."""
        calls = []

        def hang(argv, **kwargs):
            calls.append((argv, kwargs))
            raise real_subprocess.TimeoutExpired(argv, kwargs["timeout"])

        def probe(ctx):
            ctx.run(["bash", "-n", "hook"], timeout=30.0)
            return []

        later = []
        monkeypatch.setattr(ma.subprocess, "run", hang)
        monkeypatch.setattr(ma, "SCANNERS", (probe, lambda ctx: later.append("ran") or []))
        result = _scan(db_path)

        assert result.output["aborted_by_cap"] == "wall_clock"
        assert result.output["subprocess_used"] == 1  # 실행 전에 계상된다
        assert later == []
        ((argv, kwargs),) = calls
        assert argv == ["bash", "-n", "hook"]
        assert (kwargs["cwd"], kwargs["timeout"], kwargs["check"]) == (ma.REPO_ROOT, 30.0, False)


def _repo(tmp_path, *, hooks=("pre-push", "pre-commit"), gate=True):
    repo = tmp_path / "repo"
    (repo / "scripts" / "hooks").mkdir(parents=True)
    (repo / "scripts" / "verify").mkdir(parents=True)
    (repo / ".git" / "hooks").mkdir(parents=True)
    if gate:
        (repo / "scripts" / "verify" / "pre_push_check.sh").write_text("#!/bin/sh\nexit 0\n")
    for hook in hooks:
        (repo / "scripts" / "hooks" / hook).write_text("#!/bin/sh\nexit 0\n")
        installed = repo / ".git" / "hooks" / hook
        installed.write_text("#!/bin/sh\nexit 0\n")
        installed.chmod(0o755)
    return repo


class TestGateLiveness:
    def test_a_missing_hook_source_is_reported_once_and_never_probed(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path, hooks=())
        ctx = _ctx(repo)
        spawned = []
        monkeypatch.setattr(ctx, "run", lambda argv, **kwargs: spawned.append(argv))

        titles = [f["title"] for f in ma.scan_gate_liveness(ctx)]

        assert titles == ["훅 소스 부재: scripts/hooks/pre-push", "훅 소스 부재: scripts/hooks/pre-commit"]
        assert spawned == []

    def test_a_hook_that_fails_bash_n_is_reported_with_its_stderr(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        ctx = _ctx(repo)
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            broken = argv[-1].endswith("pre-push")
            return _completed(argv, 2 if broken else 0, "", "line 3: syntax error near `fi'" if broken else "")

        monkeypatch.setattr(ctx, "run", run)
        findings = ma.scan_gate_liveness(ctx)

        assert calls == [["bash", "-n", str(repo / "scripts" / "hooks" / hook)] for hook in ("pre-push", "pre-commit")]
        assert findings == [
            {
                "axis": "gate_liveness",
                "title": "훅 문법 오류: scripts/hooks/pre-push",
                "detail": "bash -n rc=2: line 3: syntax error near `fi'",
            }
        ]

    def test_a_missing_gate_script_is_reported(self, tmp_path, monkeypatch):
        ctx = _ctx(_repo(tmp_path, gate=False))
        monkeypatch.setattr(ctx, "run", lambda argv, **kwargs: _completed(argv))

        titles = [f["title"] for f in ma.scan_gate_liveness(ctx)]

        assert titles == ["게이트 스크립트 부재: scripts/verify/pre_push_check.sh"]


class TestDocDrift:
    def test_a_failing_count_check_carries_the_tail_of_its_output(self, tmp_path, monkeypatch):
        ctx = _ctx(tmp_path)
        output = "x" * 600 + "\nFAIL tests_be: README says 1, collected 2"
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return _completed(argv, 1, output, "")

        monkeypatch.setattr(ctx, "run", run)
        findings = ma.scan_doc_drift(ctx)

        assert calls == [(["bash", "scripts/verify/verify_doc_counts.sh"], {"timeout": 60.0})]
        assert findings == [{"axis": "doc_drift", "title": "verify-doc-counts FAIL", "detail": output[-500:]}]

    def test_a_green_run_with_dead_checks_is_still_a_candidate(self, tmp_path, monkeypatch):
        """exit 0 이어도 `pattern not found` / `missing` warn 은 검증 공백이다 (#1288) — benign warn 과
        통과 줄은 빼고 앞 5줄만 싣는다."""
        ctx = _ctx(tmp_path)
        dead = [f"warn: pattern not found in docs/F{i}.md" for i in range(6)]
        lines = ["✓ tests_be 8,580", "WARN: target missing docs/GONE.md", "warn: count drift within tolerance", *dead]
        monkeypatch.setattr(ctx, "run", lambda argv, **kwargs: _completed(argv, 0, "\n".join(lines), ""))

        findings = ma.scan_doc_drift(ctx)

        assert [f["title"] for f in findings] == ["verify-doc-counts 죽은 검사 (warn + exit 0)"]
        assert findings[0]["detail"].splitlines()[1:] == ["WARN: target missing docs/GONE.md", *dead[:4]]

    def test_a_green_run_with_only_benign_warnings_is_no_candidate(self, tmp_path, monkeypatch):
        ctx = _ctx(tmp_path)
        lines = ["✓ tests_be 8,580", "warn: count drift within tolerance"]
        monkeypatch.setattr(ctx, "run", lambda argv, **kwargs: _completed(argv, 0, "\n".join(lines), ""))

        assert ma.scan_doc_drift(ctx) == []


class TestSchedulerWiring:
    def test_a_makefile_without_a_collect_target_is_one_premise_candidate(self, tmp_path):
        (tmp_path / "Makefile").write_text("lint:\n\truff check .\n", encoding="utf-8")

        titles = [f["title"] for f in ma.scan_scheduler_wiring(_ctx(tmp_path))]

        assert titles == ["Makefile collect: 타깃을 찾을 수 없음"]

    def test_a_stale_alias_reports_itself_and_does_not_cover_its_module(self, tmp_path, monkeypatch):
        """별칭이 가리키는 슬롯이 SCHEDULES 에서 사라지면 별칭 자체가 후보가 되고, 그 모듈도
        '배선 없음' 으로 드러난다 — 낡은 별칭이 무배선을 덮어 주면 안 된다."""
        import nuri.scheduler as sched

        (tmp_path / "Makefile").write_text(
            "collect:\n\t$(PY) -m nuri.collectors.macro\n\t$(PY) -m nuri.collectors.stock\n", encoding="utf-8"
        )
        monkeypatch.setattr(sched, "SCHEDULES", [{"func": sched._run_collector, "args": ["macro"]}])

        titles = [f["title"] for f in ma.scan_scheduler_wiring(_ctx(tmp_path))]

        assert titles == ["수집기 별칭 낡음: stock", "collect CLI 에만 있는 수집기: stock"]


class TestStaleCollectors:
    NOW = datetime(2026, 10, 7, 9, 0, tzinfo=KST)

    def test_wired_collectors_without_a_finish_in_14_days_are_reported(self, db_path, monkeypatch):
        """완주 이력이 없거나 14일보다 오래된 배선 수집기만 — 최근 완주와 배선 밖 수집기는 조용하다."""
        import nuri.scheduler as sched

        monkeypatch.setattr("nuri.core.timezone.kst_now", lambda: self.NOW)
        monkeypatch.setattr(
            sched,
            "SCHEDULES",
            [{"func": sched._run_collector, "args": [name]} for name in ("macro", "stock_us_night", "fear_greed")],
        )
        stale_at = (self.NOW - timedelta(days=20)).isoformat()
        for name, status, days in (
            ("macro", "finished", 3),
            ("stock_us_night", "finished", 20),
            ("fear_greed", "failed", 1),  # 실패만 있다 = 완주 기록 없음
            ("unwired", "finished", 30),
        ):
            log_collector_run(name, status, started_at=(self.NOW - timedelta(days=days)).isoformat(), db_path=db_path)

        findings = ma.scan_stale_collectors(_ctx(ma.REPO_ROOT, db_path))

        assert [f["title"] for f in findings] == [
            "수집기 14일 무완주: fear_greed",
            "수집기 14일 무완주: stock_us_night",
        ]
        assert "마지막 finished: 기록 없음" in findings[0]["detail"]
        assert f"마지막 finished: {stale_at}" in findings[1]["detail"]


class TestDependency:
    def test_without_uv_the_lock_check_is_unconfirmed_not_clean(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ma, "_uv_binary", lambda: None)
        ctx = _ctx(tmp_path)
        monkeypatch.setattr(ctx, "run", lambda *args, **kwargs: pytest.fail("uv 없이 subprocess 를 띄웠다"))

        findings = ma.scan_dependency(ctx)

        assert [f["title"] for f in findings] == ["uv 부재 — lock 드리프트 검사 미실행"]
        assert "미확인" in findings[0]["detail"]

    def test_lock_drift_is_reported_with_the_check_output(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ma, "_uv_binary", lambda: "/opt/uv")
        ctx = _ctx(tmp_path)
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return _completed(argv, 1, "", "error: The lockfile at `uv.lock` needs to be updated")

        monkeypatch.setattr(ctx, "run", run)
        findings = ma.scan_dependency(ctx)

        assert calls == [(["/opt/uv", "lock", "--check"], {"timeout": 60.0})]
        assert [f["title"] for f in findings] == ["uv.lock 이 pyproject 와 어긋남"]
        assert findings[0]["detail"].endswith("error: The lockfile at `uv.lock` needs to be updated")

    def test_requirement_strings_without_a_name_are_skipped(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\ndependencies = ["pandas>=2.0", "", "  ", "Foo_Bar.baz==1"]\n', encoding="utf-8"
        )

        assert ma._runtime_dependency_names(tmp_path) == {"pandas", "foo-bar-baz"}


class TestActions:
    @staticmethod
    def _run(db_path, **input_data):
        return ma.MaintenanceAuditor().run({"db_path": db_path, **input_data})

    def test_list_filters_by_status(self, db_path):
        stage_maintenance_candidate("doc_drift", "kept", "d", "fp-kept", "run-1", db_path=db_path)
        _, done = stage_maintenance_candidate("doc_drift", "done", "d", "fp-done", "run-1", db_path=db_path)
        review_maintenance_candidate(done, "rejected", db_path=db_path)

        staged = self._run(db_path, action="list", status="staged")
        everything = self._run(db_path, action="list")

        assert [r["title"] for r in staged.output["candidates"]] == ["kept"]
        assert (staged.sample_n, staged.outcome) == (1, ma.Outcome.PASS)
        assert sorted(r["title"] for r in everything.output["candidates"]) == ["done", "kept"]

    def test_review_says_whether_the_id_existed(self, db_path):
        _, cid = stage_maintenance_candidate("doc_drift", "t", "d", "fp", "run-1", db_path=db_path)

        ok = self._run(db_path, action="review", id=cid, verdict="approved", note="real gap")
        missing = self._run(db_path, action="review", id=cid + 99, verdict="approved")

        assert ok.output == {"reviewed": True, "id": cid, "verdict": "approved"}
        assert ok.outcome == ma.Outcome.PASS
        assert missing.output["reviewed"] is False and missing.outcome == ma.Outcome.WARN
        (row,) = list_maintenance_candidates(db_path=db_path)
        assert (row["status"], row["review_note"]) == ("approved", "real gap")

    def test_stats_returns_the_ledger_metrics(self, db_path):
        _, cid = stage_maintenance_candidate("doc_drift", "t", "d", "fp", "run-1", db_path=db_path)
        review_maintenance_candidate(cid, "approved", db_path=db_path)

        result = self._run(db_path, action="stats")

        assert result.output == maintenance_review_stats(db_path=db_path)
        assert (result.output["reviewed"], result.output["precision"]) == (1, 1.0)
        assert result.outcome == ma.Outcome.PASS

    def test_an_unknown_action_is_an_error_result_not_an_exception(self, db_path):
        result = self._run(db_path, action="publish")

        assert result.outcome == ma.Outcome.ERROR
        assert result.output == {"error": "unknown action 'publish'"}

    def test_a_review_without_a_timestamp_counts_for_precision_but_not_latency(self, db_path):
        """reviewed_at 이 빈 리뷰 행(수동 정정 등)은 precision 에는 들어가되 지연 중앙값에는 안 들어간다."""
        _, timed = stage_maintenance_candidate("doc_drift", "a", "d", "fp-a", "run-1", db_path=db_path)
        _, untimed = stage_maintenance_candidate("doc_drift", "b", "d", "fp-b", "run-1", db_path=db_path)
        review_maintenance_candidate(timed, "approved", db_path=db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "UPDATE maintenance_candidates SET status = 'rejected', reviewed_at = NULL WHERE id = ?", (untimed,)
            )

        stats = maintenance_review_stats(db_path=db_path)

        (row,) = [r for r in list_maintenance_candidates(db_path=db_path) if r["id"] == timed]
        latency = datetime.fromisoformat(row["reviewed_at"]) - datetime.fromisoformat(row["created_at"])
        assert (stats["reviewed"], stats["precision"]) == (2, 0.5)
        assert stats["review_latency_h_median"] == latency.total_seconds() / 3600


class TestScanLoop:
    def test_a_finding_already_in_the_ledger_counts_as_seen_again(self, db_path, quiet_ops, monkeypatch):
        fingerprint = ma._fingerprint("doc_drift", "repeat")
        stage_maintenance_candidate("doc_drift", "repeat", "old", fingerprint, "run-0", db_path=db_path)
        monkeypatch.setattr(ma, "SCANNERS", (lambda ctx: [_finding("repeat", "new")],))

        result = _scan(db_path)

        assert (result.output["staged"], result.output["seen_again"], result.sample_n) == (0, 1, 1)
        (row,) = list_maintenance_candidates(db_path=db_path)
        assert row["seen_count"] == 2

    def test_a_crashing_scanner_is_recorded_and_the_next_one_still_runs(self, db_path, quiet_ops, monkeypatch):
        def broken(ctx):
            raise RuntimeError("parse error in Makefile")

        monkeypatch.setattr(ma, "SCANNERS", (broken, lambda ctx: [_finding("after")]))
        result = _scan(db_path)

        assert result.output["scanner_errors"] == ["broken: parse error in Makefile"]
        assert result.output["staged"] == 1
        assert result.outcome == ma.Outcome.WARN

    def test_an_ops_staging_failure_leaves_the_scan_result_intact(self, db_path, monkeypatch, caplog):
        """표면화는 관측이다 — outbox 가 죽어도 스캔 결과와 원장은 그대로 남는다 (#894)."""

        def outbox_down(**kwargs):
            raise RuntimeError("outbox locked")

        monkeypatch.setattr("nuri.agents.discord.outbox.stage_ops", outbox_down)
        monkeypatch.setattr(ma, "SCANNERS", (lambda ctx: [_finding("t")],))
        with caplog.at_level(logging.WARNING, logger=ma.logger.name):
            result = _scan(db_path)

        assert result.outcome == ma.Outcome.PASS and result.output["staged"] == 1
        assert "#ops 표면화 실패 (본 작업은 완료): outbox locked" in caplog.text


class TestCli:
    def test_list_review_and_stats_print_json_and_exit_0(self, default_db, capsys):
        _, cid = stage_maintenance_candidate("doc_drift", "cli title", "d", "fp-cli", "run-1")
        _, old = stage_maintenance_candidate("doc_drift", "already rejected", "d", "fp-old", "run-0")
        review_maintenance_candidate(old, "rejected")

        assert ma.main(["list", "staged"]) == 0
        assert [r["title"] for r in json.loads(capsys.readouterr().out)["candidates"]] == ["cli title"]

        assert ma.main(["review", str(cid), "approved", "looks right"]) == 0
        assert json.loads(capsys.readouterr().out) == {"reviewed": True, "id": cid, "verdict": "approved"}

        assert ma.main(["stats"]) == 0
        assert json.loads(capsys.readouterr().out)["precision"] == 0.5
        (row,) = [r for r in list_maintenance_candidates() if r["id"] == cid]
        assert row["review_note"] == "looks right"

    def test_scan_prints_its_counters(self, default_db, capsys, monkeypatch):
        monkeypatch.setattr(ma.MaintenanceAuditor, "_surface_summary", lambda self, output: None)
        monkeypatch.setattr(ma, "SCANNERS", (lambda ctx: [_finding("cli scan")],))

        assert ma.main(["scan"]) == 0

        out = json.loads(capsys.readouterr().out)
        assert (out["staged"], out["aborted_by_cap"]) == (1, None)
        assert [r["title"] for r in list_maintenance_candidates()] == ["cli scan"]

    def test_the_module_entry_point_exits_with_the_cli_code(self, default_db, monkeypatch, restore_actor_registry):
        stage_maintenance_candidate("doc_drift", "via -m", "d", "fp-m", "run-1")
        stdout = io.StringIO()
        monkeypatch.setattr(sys, "argv", ["maintenance_auditor", "list"])
        monkeypatch.setattr(sys, "stdout", stdout)

        with pytest.raises(SystemExit) as exc:
            runpy.run_module("nuri.agents.actors.maintenance_auditor", run_name="__main__")

        assert exc.value.code == 0
        assert [r["title"] for r in json.loads(stdout.getvalue())["candidates"]] == ["via -m"]
