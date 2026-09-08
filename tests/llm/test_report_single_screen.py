"""#1496 — `gather_context()` 는 스크리너를 한 번만 돌린다.

후보 섹션이 얻은 `screen_candidates()` 결과를 conflicts 섹션에 넘긴다. 전에는 `detect_conflicts(db_path=...)` 가
`candidates=None` 으로 다시 스크린해 signal backtest(#1475 프로파일: 160회, 3,992 bar)를 브리프마다 두 번 지불했다.
"""

from __future__ import annotations

import pytest

from nuri.core.db import init_db
from nuri.trading.recommend import candidates as cand_mod


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "t.db"
    init_db(path)
    return path


def _fake_candidates():
    return [
        cand_mod.Candidate(
            ticker="AAPL",
            signal_id="rsi_oversold",
            signal_date="2025-01-10",
            direction="BUY",
            confidence=70.0,
            win_rate=0.6,
            profit_factor=1.5,
            regime_fit=True,
            price=190.0,
            notes="",
        ),
        cand_mod.Candidate(
            ticker="AAPL",
            signal_id="macd_cross",
            signal_date="2025-01-10",
            direction="SELL",
            confidence=55.0,
            win_rate=0.5,
            profit_factor=1.1,
            regime_fit=True,
            price=190.0,
            notes="",
        ),
    ]


class TestGatherContextScreensOnce:
    def test_screen_candidates_is_called_once_per_gather(self, db_path, monkeypatch):
        from nuri.llm.report import gather_context

        calls = {"n": 0}

        def counting(*a, **k):
            calls["n"] += 1
            return _fake_candidates()

        monkeypatch.setattr(cand_mod, "screen_candidates", counting)
        ctx = gather_context(db_path=db_path)
        assert calls["n"] == 1, f"screen_candidates 가 {calls['n']}회 — conflicts 섹션이 다시 스크린한다"
        # 넘긴 후보로 충돌을 실제로 계산했는지 — 같은 종목 BUY vs SELL 이면 충돌 1건
        assert "충돌" in ctx.conflicts_section and "AAPL" in ctx.conflicts_section

    def test_conflicts_still_screen_when_candidates_section_failed(self, db_path, monkeypatch):
        """섹션 5 가 예외로 죽어 candidates 가 None 이면 conflicts 는 예전처럼 스스로 스크린한다 (재사용 실패 ≠ 기능 상실)."""
        from nuri.llm import report as mod

        calls = {"n": 0}

        def counting(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("screener down for the candidates section only")
            return _fake_candidates()

        monkeypatch.setattr(cand_mod, "screen_candidates", counting)
        ctx = mod.gather_context(db_path=db_path)
        assert calls["n"] == 2
        assert "충돌" in ctx.conflicts_section
