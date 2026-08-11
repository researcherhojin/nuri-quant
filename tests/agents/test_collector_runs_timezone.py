"""`collector_runs` 시간대 일관성 (#1031).

`started_at` 은 스키마 기본값 `datetime('now')` 라 **UTC**, `finished_at` 은 호출자가
`kst_now()` 로 넣어 **KST** 였다 — 한 행 안에 9시간 어긋난 두 표현. #1030 이 이 테이블에
사상 첫 행을 넣으면서 드러났다.

**조회는 안 고쳤다 — 뮤테이션이 내 전제를 반증했다.** 처음엔 "`started_at` 만 KST 로
돌리면 `scan_health` 창이 33시간으로 늘어난다" 고 보고 쿼리도 같이 바꿨는데, 그 변경을
되돌리는 뮤테이션이 **잡히지 않았다**. 실측하니 SQLite `datetime()` 이 ISO 오프셋을 UTC 로
정규화한다 — `datetime('2026-08-11T05:30:00+09:00')` → `2026-08-10 20:30:00`. 즉 원래 쿼리는
양쪽을 UTC 로 맞춰 **애초에 정확했고**, 내가 넣었던 raw 문자열 비교가 오히려 형식 혼재에
취약했다. 그래서 쓰기만 고친다.

아래 창 테스트 2개는 이번 변경을 잠그지 않는다(수정 전에도 통과했다). 창 정확성 자체를
지키는 회귀 방어로 남긴다 — 잠금은 위 두 테스트다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from nuri.core.db import init_db, log_collector_run, query
from nuri.core.timezone import kst_now


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "t.db"
    init_db(p)
    return p


class TestBothTimestampsAreKst:
    def test_started_at_is_kst_not_the_utc_default(self, db_path):
        log_collector_run(collector_name="macro", status="finished", db_path=db_path)
        row = query("SELECT started_at FROM collector_runs", db_path=db_path)[0]
        delta = abs((kst_now() - _parse(row["started_at"])).total_seconds())
        assert delta < 120, f"started_at 이 현재 KST 와 {delta / 3600:.1f}시간 어긋난다 — 스키마 기본값(UTC)이 발화했다"

    def test_started_and_finished_agree(self, db_path):
        """한 행 안에서 두 컬럼이 같은 시계를 써야 한다 — duration 을 재는 쪽이 있다."""
        log_collector_run(collector_name="macro", status="finished", finished_at=kst_now().isoformat(), db_path=db_path)
        r = query("SELECT started_at, finished_at FROM collector_runs", db_path=db_path)[0]
        gap = abs((_parse(r["finished_at"]) - _parse(r["started_at"])).total_seconds())
        assert gap < 120, f"started_at 과 finished_at 이 {gap / 3600:.1f}시간 어긋난다"


class TestHealthWindowIsHonest:
    def _seed(self, db_path, name, hours_ago):
        log_collector_run(
            collector_name=name,
            status="finished",
            started_at=(kst_now() - timedelta(hours=hours_ago)).isoformat(),
            db_path=db_path,
        )

    def test_window_includes_recent_and_excludes_old(self, db_path, monkeypatch):
        import nuri.agents.actors.collector_orchestrator as mod

        self._seed(db_path, "recent", 1)
        self._seed(db_path, "stale", 30)
        monkeypatch.setattr(mod, "query", lambda *a, **k: query(*a, db_path=db_path, **k))
        out = mod.CollectorOrchestrator()._scan_health({"hours": 24}, _ctx()).output
        names = {s["collector_name"] for s in out["summaries"]}
        assert "recent" in names
        assert "stale" not in names, "24시간 창이 30시간 전 행을 긁어왔다"

    def test_a_25h_old_row_is_outside_a_24h_window(self, db_path, monkeypatch):
        """정확히 이 지점이 UTC/KST 혼재의 증상이었다.

        `started_at` 이 KST 인데 `datetime('now')`(UTC) 와 비교하면 창이 ~33시간으로
        늘어나 25시간 전 행이 들어온다. 그러면서 '24시간' 이라고 보고한다.
        """
        import nuri.agents.actors.collector_orchestrator as mod

        self._seed(db_path, "just_outside", 25)
        monkeypatch.setattr(mod, "query", lambda *a, **k: query(*a, db_path=db_path, **k))
        out = mod.CollectorOrchestrator()._scan_health({"hours": 24}, _ctx()).output
        assert out["collector_count"] == 0, (
            f"25시간 전 행이 24시간 창에 들어왔다 — 창이 조용히 넓어졌다: {out['summaries']}"
        )


def _parse(s):
    from datetime import datetime

    return datetime.fromisoformat(str(s).replace(" ", "T"))


def _ctx():
    from nuri.agents.base import RunContext

    return RunContext(run_id="test-run")
