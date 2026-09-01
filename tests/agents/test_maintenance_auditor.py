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

    def test_even_count_latency_is_the_true_median(self, db_path):
        """짝수 개 리뷰의 중앙값은 가운데 두 값의 평균 — `[len//2]` 상위 중앙값이면
        1h·9h 가 9h 로 과대 보고된다 (codex P3)."""
        from nuri.core.db import get_db

        for fp in ("fp-x", "fp-y"):
            _, cid = stage_maintenance_candidate("doc_drift", fp, "d", fp, "r", db_path=db_path)
            review_maintenance_candidate(cid, "approved", db_path=db_path)
        with get_db(db_path) as conn:
            conn.execute(
                "UPDATE maintenance_candidates SET created_at='2026-08-01T00:00:00',"
                " reviewed_at='2026-08-01T01:00:00' WHERE fingerprint='fp-x'"
            )
            conn.execute(
                "UPDATE maintenance_candidates SET created_at='2026-08-01T00:00:00',"
                " reviewed_at='2026-08-01T09:00:00' WHERE fingerprint='fp-y'"
            )

        stats = maintenance_review_stats(db_path=db_path)
        assert stats["review_latency_h_median"] == pytest.approx(5.0)

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
        assert entries[0]["cron"] == "30 4 * * 0"
        # db_maintenance(VACUUM/checkpoint) 와 같은 슬롯이면 매주 lock 경합 (codex P1).
        db_maint = next(s for s in SCHEDULES if s["name"] == "db_maintenance")
        assert entries[0]["cron"] != db_maint["cron"], "감사가 DB 유지보수와 같은 슬롯에서 돈다"

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


# 전이로도 설치되면서 `nuri/`·`tests/`·`scripts/` 어디서도 직접 import 하지 않는 직접 런타임
# 의존성 (2026-09-02 AST 실측 — 정규식 스윕은 함수 내부 deferred import 를 놓쳤다).
# 선언을 지워도 `uv lock` 재해석이 238 패키지 그대로라 눈으로는 잉여로 보이고, 실제로 #1399 가
# 그렇게 제안됐다. 아래 사유가 그 제안을 기각한 근거다. codex 2라운드 판정 archive:
# data/llm_consults/2026-09-02_sklearn-dep-lock-round2.md (gitignored).
ZERO_IMPORT_DIRECT_DEPS = {
    "scikit-learn": "hmmlearn(!=0.22.0,>=0.16)·riskfolio-lib(>=1.3.0)·vectorbt(무제약) 가 전이로 가져오지만 "
    "직접 선언의 >=1.4.0 이 그중 가장 강한 하한이다. GaussianHMM.fit(regime_posterior.py:137)·"
    "riskfolio 최적화(rebalance.py:73) 의 수치 바닥이라 버전 이동이 관측돼야 한다",
    "cvxpy": "riskfolio-lib 전이. 포트폴리오 최적화 solver",
    "pillow": "matplotlib 전이. 이 선언은 CVE 보안 하한도 겸한다 (선언 바로 위 주석 참조)",
    "vectorbt": "riskfolio-lib 전이. 0.x 라 minor 도 파괴적 — check_lock_major_bump 의 경계 대상",
}


class TestDependencyLag:
    def test_zero_import_direct_deps_stay_in_the_observation_set(self):
        """직접 import 0건인 선언이 관측 집합에서 빠지지 않는지 잠근다 (#1399).

        **이 테스트 도입 전에는** 선언을 지워도 해석이 그대로고 게이트가 전부 초록인 채로
        dependabot direct-scope 와 주간 lag 관측에서만 사라졌다. 침묵이 유일한 증상이라
        사람 눈으로는 반복해서 놓친다 — #1399 자체가 그 재발이다.

        **잠그는 범위는 이름의 관측집합 포함 여부뿐이다.** 버전 하한 자체는 잠그지 않는다 —
        `_runtime_dependency_names()` 가 이름만 파싱하므로 `"scikit-learn>=1.4.0"` 을
        `"scikit-learn"` 으로 바꿔 하한을 없애면 이 테스트는 통과한다. `[project.optional-dependencies]`
        로 옮기는 것은 잡힌다(그 함수는 `[project].dependencies` 만 읽는다).

        부분집합만 검사한다. 동등 비교로 잠그면 의존성을 새로 추가할 때마다 이 목록을
        갱신해야 해서, 잠금이 아니라 churn 이 된다.

        **Test:** tests/agents/test_maintenance_auditor.py::TestDependencyLag::test_zero_import_direct_deps_stay_in_the_observation_set
        """
        observed = ma._runtime_dependency_names(REPO_ROOT)

        missing = {name: why for name, why in ZERO_IMPORT_DIRECT_DEPS.items() if name not in observed}

        assert not missing, (
            "직접 의존성 선언이 빠졌다 — 주간 lag 관측과 dependabot direct-scope 에서 조용히 사라진다:\n"
            + "\n".join(f"  - {name}: {why}" for name, why in sorted(missing.items()))
        )

    def test_missing_uv_is_recorded_as_unobserved_not_clean(self, tmp_path, monkeypatch):
        """uv 부재를 '업데이트 0건'으로 읽으면 #1362의 silent failure 감지가 무의미하다."""
        monkeypatch.setattr(ma, "_uv_binary", lambda: None)
        ctx = ma.ScanContext(repo_root=tmp_path, tracker=ma._CapTracker(caps=ma.AuditCaps()))

        findings = ma.scan_dependency_lag(ctx)

        assert findings == [
            {
                "axis": "dependency_lag",
                "title": "직접 의존성 lag 관측 미실행",
                "detail": "uv를 찾지 못해 직접 의존성 lag을 측정하지 못했다. PATH를 확인할 것.",
            }
        ]

    def test_transitive_updates_are_excluded_from_runtime_lag_observation(self, tmp_path, monkeypatch):
        """직접 의존성만 관측 — 전이 업데이트를 섞으면 #1362의 baseline이 부풀어진다.

        **Test:** tests/agents/test_maintenance_auditor.py::TestDependencyLag::test_transitive_updates_are_excluded_from_runtime_lag_observation
        """
        (tmp_path / "pyproject.toml").write_text(
            "[project]\ndependencies = ['numpy>=1.26', 'discord.py>=2.0']\n", encoding="utf-8"
        )
        monkeypatch.setattr(ma, "_uv_binary", lambda: "uv")
        ctx = ma.ScanContext(repo_root=tmp_path, tracker=ma._CapTracker(caps=ma.AuditCaps()))
        monkeypatch.setattr(
            ctx,
            "run",
            lambda *args, **kwargs: real_subprocess.CompletedProcess(
                args[0], 0, "Update numpy v1.26.4 -> v2.5.2\nUpdate transitive-lib v1.0.0 -> v1.1.0\n", ""
            ),
        )

        findings = ma.scan_dependency_lag(ctx)

        assert len(findings) == 1
        assert "1건" in findings[0]["detail"]
        assert "numpy: v1.26.4 → v2.5.2" in findings[0]["detail"]
        assert "transitive-lib" not in findings[0]["detail"]

    def test_zero_direct_updates_are_recorded_as_an_observation(self, tmp_path, monkeypatch):
        """0건도 기록해야 Dependabot 무PR과 '정상적으로 최신'을 구분할 baseline이 생긴다."""
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = ['numpy>=1.26']\n", encoding="utf-8")
        monkeypatch.setattr(ma, "_uv_binary", lambda: "uv")
        ctx = ma.ScanContext(repo_root=tmp_path, tracker=ma._CapTracker(caps=ma.AuditCaps()))
        monkeypatch.setattr(
            ctx,
            "run",
            lambda *args, **kwargs: real_subprocess.CompletedProcess(
                args[0], 0, "Update transitive v1.0.0 -> v1.1.0\n", ""
            ),
        )

        findings = ma.scan_dependency_lag(ctx)

        assert findings == [
            {
                "axis": "dependency_lag",
                "title": "직접 의존성 lag 관측",
                "detail": "직접 런타임 의존성 업데이트 후보: 0건 (판정 임계값 없음).\n"
                "현재 lock은 모든 직접 런타임 의존성의 최신 resolver 결과와 일치한다.",
            }
        ]

    def test_failed_dry_run_is_not_reported_as_clean(self, tmp_path, monkeypatch):
        """resolver 오류를 0건 관측으로 읽으면 #1362가 막으려는 silent failure가 재발한다."""
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n", encoding="utf-8")
        monkeypatch.setattr(ma, "_uv_binary", lambda: "uv")
        ctx = ma.ScanContext(repo_root=tmp_path, tracker=ma._CapTracker(caps=ma.AuditCaps()))
        monkeypatch.setattr(
            ctx,
            "run",
            lambda *args, **kwargs: real_subprocess.CompletedProcess(args[0], 1, "", "resolution failed"),
        )

        findings = ma.scan_dependency_lag(ctx)

        assert findings[0]["title"] == "직접 의존성 lag 관측 실패"
        assert "resolution failed" in findings[0]["detail"]


class TestGateLiveness:
    def test_missing_exec_bit_is_reported_as_dead_gate(self, tmp_path):
        """실행비트 없는 설치 훅 = git 이 아예 안 부르는 green dead gate (codex P2).
        `bash -n` 초록만 보면 이 상태가 건강으로 보고된다."""
        repo = tmp_path / "repo"
        (repo / "scripts" / "hooks").mkdir(parents=True)
        (repo / "scripts" / "verify").mkdir(parents=True)
        (repo / ".git" / "hooks").mkdir(parents=True)
        (repo / "scripts" / "verify" / "pre_push_check.sh").write_text("#!/bin/sh\nexit 0\n")
        for hook in ("pre-push", "pre-commit"):
            (repo / "scripts" / "hooks" / hook).write_text("#!/bin/sh\nexit 0\n")
            installed = repo / ".git" / "hooks" / hook
            installed.write_text("#!/bin/sh\nexit 0\n")
            # pre-push 만 실행비트 제거 — pre-commit 은 건강한 대조군
            installed.chmod(0o755 if hook == "pre-commit" else 0o644)

        ctx = ma.ScanContext(repo_root=repo, tracker=ma._CapTracker(caps=ma.AuditCaps()))
        titles = [f["title"] for f in ma.scan_gate_liveness(ctx)]

        assert "훅 실행권 부재: .git/hooks/pre-push" in titles
        assert not any("실행권" in t and "pre-commit" in t for t in titles)
