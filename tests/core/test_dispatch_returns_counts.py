"""`_dispatch_collector` 의 모든 분기는 수집량을 반환한다 (#1105).

## 왜 구조 스윕인가

`collector_runs`(#975)는 "collector health 관측이 통째로 없어 데이터 구멍 셋(#1025/#1020)을
손으로 DB 를 뒤져 찾았다" 는 이유로 만든 테이블이다. 그런데 분기가 `return` 을 빠뜨리면
`_record_collector_run` 에 `None` 이 넘어가 `rows_collected=0` 으로 기록된다 —
**실패가 아니라 성공으로, 다만 수집량 0 으로.**

프로덕션 실측(2026-08-18): `technical` 이 17건을 저장하고 로그에 "완료: 17건" 을 남겼는데
`collector_runs` 에는 `rows_collected=0 status=finished` 였다. 그 상태에서
`CollectorOrchestrator.scan_health` 의 under-fetch 검출(`rows < expected*0.9`)은 장식이고,
"0행 수집" 이라는 진짜 고장(#1043 클래스)과 구분이 불가능하다.

한 줄 빠뜨림이라 리뷰로는 반복해서 놓친다 — #1074 에서 봉투(`len(dict)==4`)를 고쳤을 때도
무반환 분기는 그대로 남았다. 그래서 **분기마다 잠그지 않고 구조로** 잠근다.

## 한계 (알고 쓴다)

이 스윕은 `return` 문의 **존재**만 본다. 반환값이 의미 있는 수인지는 못 본다 —
그건 동작 테스트의 몫이고, 대표 분기 몇 개는 `tests/test_scheduler.py` 가 실제 호출로 덮는다.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import nuri.scheduler as sch

#: 반환할 수집량이 **없는** 분기. 사유 필수. 양방향 검사라 해소된 항목도 FAIL.
ALLOWED_NO_RETURN: dict[str, str] = {}


def _dispatch_branches() -> list[tuple[str, list[ast.stmt]]]:
    """`_dispatch_collector` 의 `if/elif` 체인 → [(잡 이름, 본문 statements)]."""
    src = inspect.getsource(sch._dispatch_collector)
    fn = ast.parse(ast.unparse(ast.parse(src))).body[0]
    assert isinstance(fn, ast.FunctionDef)

    branches: list[tuple[str, list[ast.stmt]]] = []
    node: ast.stmt | None = next((n for n in fn.body if isinstance(n, ast.If)), None)
    while isinstance(node, ast.If):
        # `name == "<job>"` 에서 잡 이름을 뽑는다.
        job = None
        test = node.test
        if isinstance(test, ast.Compare) and test.comparators and isinstance(test.comparators[0], ast.Constant):
            job = test.comparators[0].value
        branches.append((job or "<unknown>", node.body))
        node = node.orelse[0] if len(node.orelse) == 1 else None
    return branches


class TestEveryBranchReturnsItsCount:
    def test_the_sweep_actually_finds_branches(self):
        """스윕이 0건을 찾고도 통과하면 이 파일 전체가 장식이다."""
        branches = _dispatch_branches()

        assert len(branches) >= 20, f"분기를 {len(branches)}개만 찾았다 — 파서가 눈이 멀었다"
        assert any(job == "stock" for job, _ in branches)

    @pytest.mark.parametrize("job,body", _dispatch_branches(), ids=lambda x: x if isinstance(x, str) else "")
    def test_branch_returns(self, job: str, body: list[ast.stmt]):
        has_return = any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(ast.Module(body, [])))
        if job in ALLOWED_NO_RETURN:
            assert not has_return, f"{job}: ALLOWED_NO_RETURN 에 있는데 return 이 생겼다 — 항목을 지울 것"
            return
        assert has_return, (
            f"{job} 분기가 수집량을 반환하지 않는다 — collector_runs 에 rows_collected=0 으로 "
            f"기록되어 이 잡이 매일 no-op 처럼 보인다. 돌려줄 수가 정말 없으면 "
            f"ALLOWED_NO_RETURN 에 사유와 함께 등재할 것."
        )

    def test_allowlist_has_no_stale_entries(self):
        """해소된 항목이 남아 있으면 다음 위반을 조용히 통과시킨다."""
        jobs = {job for job, _ in _dispatch_branches()}
        stale = sorted(set(ALLOWED_NO_RETURN) - jobs)

        assert not stale, f"ALLOWED_NO_RETURN 에 더 이상 존재하지 않는 분기: {stale}"


class TestTheRecorderUnderstandsAnInt:
    """분기가 int 를 돌려줘도 `rows_collected` 에 그대로 앉는지 — 반환이 헛되지 않게."""

    def test_an_int_result_lands_as_rows_collected(self, tmp_path, monkeypatch):
        from nuri.core.db import init_db, query

        db = tmp_path / "t.db"
        init_db(db)
        monkeypatch.setattr("nuri.core.db.DB_PATH", db)

        sch._record_collector_run("probe", "finished", 0.0, result=751)

        rows = query("SELECT collector_name, rows_collected FROM collector_runs", db_path=db)
        assert [(r["collector_name"], r["rows_collected"]) for r in rows] == [("probe", 751)]

    def test_none_result_is_recorded_as_zero(self, tmp_path, monkeypatch):
        """무반환이 0 으로 남는다는 사실 자체를 문서화 — 이게 이 파일의 존재 이유다."""
        from nuri.core.db import init_db, query

        db = tmp_path / "t.db"
        init_db(db)
        monkeypatch.setattr("nuri.core.db.DB_PATH", db)

        sch._record_collector_run("probe", "finished", 0.0, result=None)

        assert query("SELECT rows_collected FROM collector_runs", db_path=db)[0]["rows_collected"] == 0


class TestSourceHasNoBareCollectorRun:
    """`XCollector().run(...)` 이 `return` 없이 서 있으면 잡는다 — AST 분기 검사의 짝.

    분기 검사는 "본문 어딘가에 return 이 있는가" 만 보므로, 한 분기가 두 수집기를 부르고
    하나만 반환하면 통과한다. 이건 그 구멍을 문장 수준에서 막는다.
    """

    def test_no_collector_call_is_a_bare_statement(self):
        src = Path(sch.__file__).read_text(encoding="utf-8")
        fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_dispatch_collector")

        offenders = []
        for node in ast.walk(fn):
            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                continue
            call = node.value
            # `XCollector().run(...)` 형태만 — logger.info 등은 통과.
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "run"
                and isinstance(call.func.value, ast.Call)
                and isinstance(call.func.value.func, ast.Name)
                and call.func.value.func.id.endswith("Collector")
            ):
                offenders.append(f"line {node.lineno}: {call.func.value.func.id}().run(...)")

        assert not offenders, "return 없이 서 있는 수집기 호출:\n  " + "\n  ".join(offenders)


class TestBranchesReportPrimaryWorkNotSideChannels:
    """반환값은 그 잡이 **한 일**이어야 한다 — 부수 채널의 성공률이 아니라 (Codex 리뷰).

    `return` 존재만 잠그면 "값은 있는데 엉뚱한 걸 센다" 가 통과한다. 두 분기가 실제로 그랬고,
    둘 다 **관측이 가장 필요한 순간에** 0 을 기록하는 형태였다.
    """

    def test_holdings_monitor_reports_alerts_even_when_discord_is_down(self, monkeypatch):
        """`send_alerts` 는 best-effort 라 Discord 가 죽으면 0 을 반환한다.

        그 값을 기록하면 감시가 정상 동작한 날이 no-op 으로 남는다 — 하필 outage 때.
        """
        summary = type("S", (), {"n_holdings": 18, "n_alerted": 3, "alerts": [{}, {}, {}]})()
        monkeypatch.setattr("nuri.trading.recommend.holdings_monitor.run_monitor", lambda: summary)
        monkeypatch.setattr("nuri.trading.recommend.holdings_monitor.send_alerts", lambda s: 0)

        assert sch._dispatch_collector("holdings_monitor") == 3

    def test_alpha_tracking_counts_backfill_not_only_matured_windows(self, monkeypatch):
        """부트스트랩 구간: sync 수백 건 + measure 0 은 no-op 이 아니다.

        측정만 세면 백필 기간 전체가 `rows_collected=0` 으로 기록돼, 이 파일이 없애려는
        상태 그대로가 된다.
        """
        result = type("R", (), {"output": {"synced_from_recommendations": 262, "n_measurements": 0}})()
        monkeypatch.setattr(
            "nuri.agents.actors.forward_outcome_tracker.ForwardOutcomeTracker.run",
            lambda self, payload: result,
        )

        assert sch._dispatch_collector("alpha_tracking") == 262

    def test_consensus_reports_recommendations_not_a_sum_of_two_tables(self, monkeypatch):
        """두 테이블 수를 더하면 어느 쪽이 비었는지 못 읽는다."""
        monkeypatch.setattr("nuri.trading.agents.consensus.analyze_portfolio", lambda: [1, 2, 3])
        monkeypatch.setattr("nuri.trading.agents.consensus.save_to_recommendations", lambda r: 18)
        monkeypatch.setattr("nuri.trading.engine.decisions.record_decisions", lambda r: 18)

        assert sch._dispatch_collector("consensus") == 18
