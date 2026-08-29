"""Maintenance-Auditor shadow mode 잠금 (#1308 Phase 0).

수용 기준 세 축이 각자 실행형 잠금을 갖는다:
- **GitHub 쓰기 0건** — 구조 스윕(금지 import/문자열) + 행동 spy(subprocess argv
  바이너리 allowlist — denylist 는 새 우회를 못 잡는다).
- **하드 캡 초과 시 중단** — 캡 4종 각각: 초과 시 스캔이 멎고 어느 캡인지 기록.
- **staging 전 privacy 스캔** — 전 범주 `gate_text` (broker명·금액·ticker+PnL).
  걸린 후보는 원장에 흔적 없이 드롭, 사건은 output 카운터로만 (가짜 후보는
  precision/novelty 를 오염시킨다 — codex plan 리뷰 반영).
"""

from __future__ import annotations

import ast
import subprocess as real_subprocess
from pathlib import Path

import pytest

from nuri.agents.actors import maintenance_auditor as ma
from nuri.core.db import (
    init_db,
    list_maintenance_candidates,
    maintenance_review_stats,
    review_maintenance_candidate,
    stage_maintenance_candidate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_FILES = [REPO_ROOT / "nuri" / "agents" / "actors" / "maintenance_auditor.py"]


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "audit.db"
    init_db(path)
    return path


@pytest.fixture()
def quiet_ops(monkeypatch):
    """#ops 표면화를 캡처 — 테스트가 outbox 를 건드리지 않게 + payload 잠금용."""
    lines: list[str] = []
    monkeypatch.setattr(
        ma.MaintenanceAuditor,
        "_surface_summary",
        lambda self, output: lines.append(str(output)),
    )
    return lines


def _scan(db_path, caps=None, extra=None):
    input_data = {"action": "scan", "db_path": db_path}
    if caps:
        input_data["caps"] = caps
    if extra:
        input_data.update(extra)
    return ma.MaintenanceAuditor().run(input_data)


# ─────────────────────────────────────────────────────────────────────────────
# 수용 기준 1 — GitHub 쓰기 0건
# ─────────────────────────────────────────────────────────────────────────────


class TestGitHubWriteZero:
    def test_module_has_no_network_or_gh_surface(self):
        """구조 스윕 — gh/git push/HTTP 클라이언트가 import 표면에 존재하지 않는다."""
        banned_imports = ("requests", "httpx", "urllib", "aiohttp", "http.client")
        for py in MODULE_FILES + [REPO_ROOT / "nuri" / "core" / "db" / "maintenance_ops.py"]:
            src = py.read_text(encoding="utf-8")
            tree = ast.parse(src)
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for name in names:
                    assert not name.startswith(banned_imports), f"{py.name}: 금지 import {name}"
            assert "github.com" not in src and "api.github" not in src, f"{py.name}: GitHub 참조"

    def test_scan_spawns_only_allowlisted_binaries(self, db_path, quiet_ops, monkeypatch):
        """행동 잠금 — 스캔 중 모든 subprocess argv[0] 이 allowlist 안이고, gh/git-push
        형태가 어디에도 없다. denylist 가 아니라 **binary allowlist** 다."""
        import sys

        spawned: list[list[str]] = []
        orig_run = real_subprocess.run

        def spy(argv, *args, **kwargs):
            if isinstance(argv, (list, tuple)):
                spawned.append([str(a) for a in argv])
            return orig_run(argv, *args, **kwargs)

        monkeypatch.setattr(ma.subprocess, "run", spy)
        _scan(db_path)

        for argv in spawned:
            binary = Path(argv[0]).name if "/" in argv[0] else argv[0]
            assert binary in {"bash", "uv", "python", Path(sys.executable).name}, f"allowlist 밖 바이너리 실행: {argv}"
            joined = " ".join(argv)
            assert "gh" != binary and " push" not in joined and "github" not in joined, f"GitHub 쓰기 의심 argv: {argv}"


# ─────────────────────────────────────────────────────────────────────────────
# 수용 기준 2 — 하드 캡 초과 시 중단
# ─────────────────────────────────────────────────────────────────────────────


class TestHardCaps:
    def test_candidate_cap_stops_the_scan(self, db_path, quiet_ops, monkeypatch):
        flood = [{"axis": "doc_drift", "title": f"t{i}", "detail": "d"} for i in range(50)]
        monkeypatch.setattr(ma, "SCANNERS", (lambda ctx: flood,))

        result = _scan(db_path, caps={"candidates": 5})

        assert result.output["aborted_by_cap"] == "candidates"
        assert result.outcome == ma.Outcome.WARN
        assert len(list_maintenance_candidates(db_path=db_path)) == 5, "캡 초과분이 staging 됐다"

    def test_wall_clock_cap_cuts_before_subprocess_launch(self, db_path, quiet_ops, monkeypatch):
        """예산 소진 후 subprocess 는 **실행 자체가 안 된다** — 사후 검사가 아니다."""

        def slow_then_spawn(ctx):
            ctx.tracker.started -= 999  # 예산을 이미 다 쓴 상태를 주입
            ctx.run(["bash", "-c", "echo never"])
            return []

        monkeypatch.setattr(ma, "SCANNERS", (slow_then_spawn,))
        result = _scan(db_path)
        assert result.output["aborted_by_cap"] == "wall_clock"
        assert result.output["subprocess_used"] == 0, "예산 소진 뒤에도 subprocess 가 떴다"

    def test_subprocess_cap(self, db_path, quiet_ops, monkeypatch):
        def spawn_many(ctx):
            for _ in range(10):
                ctx.run(["bash", "-c", "true"])
            return []

        monkeypatch.setattr(ma, "SCANNERS", (spawn_many,))
        result = _scan(db_path, caps={"subprocess_calls": 3})
        assert result.output["aborted_by_cap"] == "subprocess_calls"
        assert result.output["subprocess_used"] == 4  # 4번째 시도가 초과를 발화

    def test_usd_cap_is_zero_and_any_spend_aborts(self, db_path, quiet_ops, monkeypatch):
        """Phase 0 은 LLM 0 — USD 를 1센트라도 쓰는 경로가 생기면 그 자리에서 중단."""

        def spender(ctx):
            ctx.tracker.charge_usd(0.01)
            return []

        monkeypatch.setattr(ma, "SCANNERS", (spender,))
        result = _scan(db_path)
        assert result.output["aborted_by_cap"] == "usd"


# ─────────────────────────────────────────────────────────────────────────────
# 수용 기준 3 — staging 전 privacy 스캔 (전 범주)
# ─────────────────────────────────────────────────────────────────────────────


class TestPrivacyGateBeforeStaging:
    def test_ticker_pnl_candidate_never_reaches_the_ledger(self, db_path, quiet_ops, monkeypatch):
        """ticker+PnL 조합(PR #202 시그니처) — 리터럴 금지 규칙에 따라 런타임 조립."""
        leaky_detail = "winner momentum — pnl +23.4% (" + "TS" + "LA)"
        monkeypatch.setattr(
            ma,
            "SCANNERS",
            (lambda ctx: [{"axis": "doc_drift", "title": "정상 제목", "detail": leaky_detail}],),
        )

        result = _scan(db_path)

        assert result.output["privacy_blocked"] == 1
        rows = list_maintenance_candidates(db_path=db_path)
        assert rows == [], "privacy 차단 후보가 원장에 남았다 (stub 도 금지 — 지표 오염)"

    def test_broker_name_is_blocked_too(self, db_path, quiet_ops, monkeypatch):
        """`--message` 모드였다면 통과했을 범주 — 전 범주 gate_text 를 쓰는지가 관건."""
        broker = "토스" + "증권"  # 리터럴 조립 (privacy 픽스처 규칙)
        monkeypatch.setattr(
            ma,
            "SCANNERS",
            (lambda ctx: [{"axis": "doc_drift", "title": "수집 경로", "detail": f"{broker} 계좌 경로에서 발견"}],),
        )

        result = _scan(db_path)

        assert result.output["privacy_blocked"] == 1, "broker명 범주가 스캔되지 않았다 — gate_text 미사용?"
        assert list_maintenance_candidates(db_path=db_path) == []

    def test_clean_candidate_passes(self, db_path, quiet_ops, monkeypatch):
        """대조군 — 게이트가 전부 떨구는 가짜 구현을 막는다."""
        monkeypatch.setattr(
            ma,
            "SCANNERS",
            (lambda ctx: [{"axis": "doc_drift", "title": "깨끗한 제목", "detail": "카운트 드리프트 3건"}],),
        )
        result = _scan(db_path)
        assert result.output["staged"] == 1 and result.output["privacy_blocked"] == 0

    def test_gate_failure_is_fail_closed(self, db_path, quiet_ops, monkeypatch):
        """스캔을 못 하면 깨끗한 게 아니다 — gate import 불능 시 후보는 차단된다.

        `sys.modules["check_privacy_leak"] = None` 은 이미 로드돼 있어도 다음
        `from ... import` 를 ImportError 로 만든다 — sys.path 상태와 무관하게 결정론.
        """
        import sys as _sys

        monkeypatch.setitem(_sys.modules, "check_privacy_leak", None)
        monkeypatch.setattr(
            ma,
            "SCANNERS",
            (lambda ctx: [{"axis": "doc_drift", "title": "t", "detail": "d"}],),
        )
        result = _scan(db_path)
        assert result.output["privacy_blocked"] == 1, "게이트 불능이 통과로 처리됐다 (fail-open)"
        assert list_maintenance_candidates(db_path=db_path) == []


# ─────────────────────────────────────────────────────────────────────────────
# 원장 시맨틱스 + 지표
# ─────────────────────────────────────────────────────────────────────────────


class TestLedgerSemantics:
    def test_redetection_updates_not_duplicates(self, db_path):
        v1, id1 = stage_maintenance_candidate("doc_drift", "t", "d", "fp1", "run-a", db_path=db_path)
        v2, id2 = stage_maintenance_candidate("doc_drift", "t", "d2", "fp1", "run-b", db_path=db_path)
        assert (v1, v2) == ("staged", "seen") and id1 == id2
        rows = list_maintenance_candidates(db_path=db_path)
        assert len(rows) == 1 and rows[0]["seen_count"] == 2

    def test_review_lifecycle_and_stats(self, db_path):
        _, cid = stage_maintenance_candidate("doc_drift", "a", "d", "fp-a", "r", db_path=db_path)
        stage_maintenance_candidate("dependency", "b", "d", "fp-b", "r", db_path=db_path)
        assert review_maintenance_candidate(cid, "approved", "실제 결함", db_path=db_path)
        assert not review_maintenance_candidate(99999, "rejected", db_path=db_path), "미존재 id 가 성공 처리됐다"

        stats = maintenance_review_stats(db_path=db_path)
        assert stats["candidates"] == 2 and stats["reviewed"] == 1
        assert stats["precision"] == 1.0
        assert stats["staged_pending"] == 1

    def test_stats_with_no_reviews_is_none_not_zero(self, db_path):
        stage_maintenance_candidate("doc_drift", "a", "d", "fp", "r", db_path=db_path)
        stats = maintenance_review_stats(db_path=db_path)
        assert stats["precision"] is None, "'리뷰 0건' 과 '전부 기각' 이 구분돼야 한다"

    def test_invalid_verdict_raises(self, db_path):
        with pytest.raises(ValueError):
            review_maintenance_candidate(1, "auto-merged", db_path=db_path)


class TestSummaryPayloadIsCountsOnly:
    def test_ops_line_never_carries_candidate_text(self, db_path, monkeypatch):
        """#ops 요약은 카운트만 — 후보 title/detail 이 Discord 로 새면 원장 격리가 무의미.

        `_surface_summary` 의 lazy import 는 호출 시점에 모듈 속성을 읽으므로
        `outbox_mod.stage_ops` monkeypatch 가 그대로 먹는다.
        """
        import nuri.agents.discord.outbox as outbox_mod

        secret_title = "아주 구체적인 내부 발견 제목 XYZTITLE"
        monkeypatch.setattr(
            ma,
            "SCANNERS",
            (lambda ctx: [{"axis": "doc_drift", "title": secret_title, "detail": "detail"}],),
        )
        import json as _json

        captured: list[str] = []
        monkeypatch.setattr(
            outbox_mod,
            "stage_ops",
            lambda payload, **kw: captured.append(_json.dumps(payload, ensure_ascii=False)),
        )

        _scan(db_path)

        assert captured, "요약이 표면화되지 않았다 — quiet-by-design 금지"
        assert secret_title not in captured[0], "후보 내용이 Discord 요약으로 샜다"
        assert "신규 1" in captured[0]


class TestWiringAndRoster:
    def test_scheduler_registers_the_weekly_job(self):
        from nuri.scheduler import SCHEDULES, _run_maintenance_audit

        entries = [s for s in SCHEDULES if s["name"] == "maintenance_audit"]
        assert len(entries) == 1
        assert entries[0]["func"] is _run_maintenance_audit
        assert entries[0]["cron"] == "0 3 * * 0"

    def test_actor_is_canonical_and_registered(self):
        from nuri.agents.base import REGISTRY, ActorRegistry

        assert "maintenance-auditor" in ActorRegistry.CANONICAL_ACTORS
        assert REGISTRY.get("maintenance-auditor") is ma.MaintenanceAuditor

    def test_strategy_rules_are_out_of_scope(self):
        """경계 불변 — config/rules.yaml 계열은 #1307 전용 경로다. 참조 자체가 없다."""
        src = MODULE_FILES[0].read_text(encoding="utf-8")
        assert "rules.yaml" not in src and "agents.yaml" not in src and "signals.yaml" not in src

    def test_stale_collector_reads_readonly(self):
        """감사가 감사 대상을 변형하지 않는다 — 모든 query() 호출이 readonly=True."""
        tree = ast.parse(MODULE_FILES[0].read_text(encoding="utf-8"))
        query_calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "query"
        ]
        assert query_calls, "query() 호출이 없다 — 스윕이 공허하다 (canary)"
        for call in query_calls:
            kw = {k.arg: k.value for k in call.keywords}
            assert "readonly" in kw and isinstance(kw["readonly"], ast.Constant) and kw["readonly"].value is True, (
                f"line {call.lineno}: query() 에 readonly=True 가 없다"
            )


class TestEmptyDbDoesNotFlood:
    def test_no_collector_runs_yields_one_summary_candidate(self, db_path, quiet_ops):
        """빈 DB = 수집기별 N건이 아니라 전면 침묵 1건 (실측 후 수정된 동작)."""
        ctx = ma.ScanContext(repo_root=ma.REPO_ROOT, tracker=ma._CapTracker(caps=ma.AuditCaps()), db_path=db_path)
        findings = ma.scan_stale_collectors(ctx)
        assert len(findings) == 1
        assert "전혀 없음" in findings[0]["title"]
