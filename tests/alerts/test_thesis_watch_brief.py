"""brief 의 Thesis Watch 섹션 (#1167) — 판정이 돌아도 안 보이면 반증은 침묵한다.

잠금 축 3개: (1) breached 가 statement 로 표면화 (2) active 0건도 침묵하지 않음
(3) 수집 실패가 brief 를 죽이지 않음 (#894). ctx 수집 배선은 _collect_context
진입점을 통과해 잠근다 (wiring axis).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from nuri.core.db import init_db, upsert_portfolio
from nuri.core.db.thesis_ops import add_criteria, upsert_thesis
from nuri.core.timezone import today_kst


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    init_db(p)
    return p


def _thesis(db, ticker, status="active"):
    tid = upsert_thesis(
        ticker=ticker,
        author="user",
        stance="bullish",
        bull_case="상승 논지",
        bear_case="하락 논지",
        evidence=[{"side": "bull", "claim": "근거", "source_type": "measurement"}],
        status=status,
        db_path=db,
    )
    add_criteria(
        tid,
        [
            {
                "kind": "machine",
                "statement": "200일선 대비 -5% 이탈이면 추세 기각",
                "metric": "close",
                "op": "<",
                "threshold": 50,
            }
        ],
        db_path=db,
    )
    return tid


def _check(db, tid, result, observed=None):
    from nuri.core.db import get_db

    with get_db(db) as conn:
        cid = conn.execute("SELECT id FROM thesis_criteria WHERE thesis_id = ?", (tid,)).fetchone()[0]
        conn.execute(
            "INSERT INTO thesis_criteria_checks (criterion_id, check_date, result, observed) VALUES (?, ?, ?, ?)",
            (cid, today_kst(), result, observed),
        )


class TestThesisWatchSection:
    def test_breached_criterion_surfaces_with_statement(self, db):
        from nuri.alerts.premarket_brief import format_brief_markdown
        from nuri.core.db import get_thesis_watch

        tid = _thesis(db, "AAAA")
        _check(db, tid, "breached", observed=42.0)

        md = format_brief_markdown({"thesis_watch": get_thesis_watch(db_path=db)})
        assert "⚠ Thesis Watch — 반증 1건" in md
        assert "200일선 대비 -5% 이탈이면 추세 기각" in md

    def test_no_active_thesis_is_stated_not_silent(self, db):
        from nuri.alerts.premarket_brief import format_brief_markdown
        from nuri.core.db import get_thesis_watch

        _thesis(db, "AAAA", status="draft")
        md = format_brief_markdown({"thesis_watch": get_thesis_watch(db_path=db)})
        assert "active 논지 없음 (draft 1건" in md

    def test_held_without_thesis_counted(self, db):
        from nuri.alerts.premarket_brief import format_brief_markdown
        from nuri.core.db import get_thesis_watch

        upsert_portfolio(
            [
                {
                    "account": "Brokerage Alpha",
                    "ticker": "BBBB",
                    "quantity": 10,
                    "avg_price": 100.0,
                    "currency": "USD",
                    "sector": None,
                }
            ],
            db_path=db,
        )
        _thesis(db, "AAAA")
        md = format_brief_markdown({"thesis_watch": get_thesis_watch(db_path=db)})
        assert "논지 없는 보유: 1종목" in md

    def test_collect_context_wires_thesis_watch(self, db, monkeypatch):
        """_collect_context 진입점 통과 — 배선 잠금 (직접 호출 테스트는 배선 누락을 못 잡음)."""
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", db)
        _thesis(db, "AAAA")
        from nuri.alerts.premarket_brief import _collect_context

        ctx = _collect_context(db_path=db)
        assert ctx["thesis_watch"] is not None
        assert ctx["thesis_watch"]["active"][0]["ticker"] == "AAAA"

    def test_reader_failure_does_not_kill_brief(self, db):
        """수집 실패는 섹션 None + brief 계속 (#894)."""
        from nuri.alerts import premarket_brief as pb

        with patch("nuri.core.db.get_thesis_watch", side_effect=RuntimeError("boom")):
            ctx = pb._collect_context(db_path=db)
        assert ctx["thesis_watch"] is None
