"""`gather_context(db_path=X)` / `generate_brief(db_path=X)` 는 X 만 읽어야 한다.

왜 이게 필요한가
----------------
`gather_context` 는 10개 섹션에 db_path 를 제대로 넘기면서 **risk 섹션 한 줄만**
빠뜨렸다 (`analyze_risk()`). `analyze_risk` 가 애초에 db_path 를 안 받았기
때문인데, 그 한 줄 때문에 테스트가 tmp DB 를 지정해도 그 경로만 기본 DB 로
샜다 — 2026-08-14 실측으로 `test_report_branch_coverage.py` 17개 테스트가
각 60 커넥션씩 프로덕션 DB 를 열고 있었다.

`premarket_brief` 는 db_path 배선이 **아예 없었다**.

전역 격리(#1049)가 이제 프로덕션 접근 자체를 막지만, 그건 백스톱이지 배선이
아니다. 호출자가 DB 를 지정할 수 있어야 replay/backtest 처럼 **의도적으로 다른
DB 를 겨누는** 용도가 성립한다. 이 테스트는 값이 아니라 **접근 경로**를 잠근다.
"""

from __future__ import annotations

import inspect

import pytest


@pytest.fixture
def db_path(tmp_path):
    """스키마만 있는 tmp DB. `tests/quant/conftest.py` 의 동명 픽스처는 그쪽 전용이다."""
    from nuri.core.db import init_db

    path = tmp_path / "test.db"
    init_db(path)
    return path


def _spy_connect(monkeypatch) -> list[str]:
    import nuri.core.db.connection as conn_mod

    opened: list[str] = []
    original = conn_mod.sqlite3.connect

    def spy(path, *args, **kwargs):
        opened.append(str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(conn_mod.sqlite3, "connect", spy)
    return opened


class TestSignaturesAcceptDbPath:
    @pytest.mark.parametrize(
        "module,name",
        [
            ("nuri.analysis.risk", "analyze_risk"),
            ("nuri.analysis.risk", "_get_portfolio_returns"),
            ("nuri.alerts.premarket_brief", "_collect_context"),
            ("nuri.alerts.premarket_brief", "generate_brief"),
        ],
    )
    def test_accepts_db_path(self, module: str, name: str) -> None:
        """시그니처가 좁아지면 호출부 배선이 조용히 끊긴다."""
        import importlib

        fn = getattr(importlib.import_module(module), name)
        assert "db_path" in inspect.signature(fn).parameters


class TestAnalyzeRiskReadsOnlyTheGivenDb:
    def test_no_other_database_is_opened(self, db_path, monkeypatch) -> None:
        from nuri.analysis.risk import analyze_risk
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "AAA", 10, 100.0, "USD", "Tech"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("AAA", "2026-08-14", 100.0, 101.0, 99.0, 100.5, 1000),
            )

        opened = _spy_connect(monkeypatch)
        analyze_risk(db_path=db_path)

        others = {p for p in opened if p != str(db_path)}
        assert not others, f"db_path 외의 DB 를 열었다: {sorted(others)}"
        assert opened, "아무 DB 도 안 열었다 — 스파이가 안 걸린 것"


class TestGatherContextThreadsToRisk:
    def test_risk_section_receives_db_path(self, db_path, monkeypatch) -> None:
        """`gather_context` 가 risk 섹션에도 db_path 를 넘기는지 — 그 한 줄이 빠져 있었다."""
        seen: dict = {}

        def fake_analyze_risk(db_path=None):
            seen["db_path"] = db_path
            return {}

        monkeypatch.setattr("nuri.analysis.risk.analyze_risk", fake_analyze_risk)
        from nuri.llm import report

        report.gather_context(db_path=db_path)
        assert seen.get("db_path") == db_path, "risk 섹션이 db_path 를 못 받았다"
