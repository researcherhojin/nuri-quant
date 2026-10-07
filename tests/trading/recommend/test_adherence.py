"""추천 이행 여부 진단 (#1722) — 에피소드 묶기와 4분류.

보유 원장은 트리거가 채우지만, 여기서는 시각을 고정해야 하므로 `portfolio_changes` 에 직접 넣는다.
"""

from __future__ import annotations

import pytest

from nuri.core.db import get_db, init_db
from nuri.trading.recommend import adherence as adh


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "adherence.db"
    init_db(p)
    return p


def _recs(db_path, rows, source=None):
    with get_db(db_path) as conn:
        for day, ticker, action in rows:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, confidence, source) VALUES (?, ?, ?, 70.0, ?)",
                (day, ticker, action, source),
            )


def _change(db_path, at, ticker, old, new, account="Brokerage Alpha"):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio_changes (changed_at, account, ticker, old_quantity, new_quantity) VALUES (?, ?, ?, ?, ?)",
            (at, account, ticker, old, new),
        )


class TestEpisodes:
    def test_consecutive_same_action_is_one_episode_and_hold_breaks_it(self, db_path):
        _recs(
            db_path,
            [
                ("2026-10-01", "AAA", "SELL"),
                ("2026-10-02", "AAA", "SELL"),
                ("2026-10-03", "AAA", "SELL"),
                ("2026-10-04", "AAA", "HOLD"),
                ("2026-10-05", "AAA", "SELL"),
                ("2026-10-01", "BBB", "BUY"),
            ],
        )
        eps = adh.episodes(db_path=db_path)
        assert [(e.ticker, e.action, e.start, e.days) for e in eps] == [
            ("AAA", "SELL", "2026-10-01", 3),
            ("AAA", "SELL", "2026-10-05", 1),
            ("BBB", "BUY", "2026-10-01", 1),
        ]

    def test_only_consensus_rows_count(self, db_path):
        """emitter 행(source 있음)은 합의 추천이 아니다 — §3.11 표본과 같은 모집단만 본다."""
        _recs(db_path, [("2026-10-01", "CCC", "BUY")], source="emitter")
        assert adh.episodes(db_path=db_path) == []


class TestClassify:
    EP_BUY = adh.Episode("AAA", "BUY", "2026-10-01", "2026-10-01", 1)
    EP_SELL = adh.Episode("AAA", "SELL", "2026-10-01", "2026-10-01", 1)

    @pytest.fixture(autouse=True)
    def _log_started_before(self, db_path):
        _change(db_path, "2026-09-25 09:00:00", "ZZZ", None, 1)

    def test_buy_followed(self, db_path):
        _change(db_path, "2026-10-03 09:00:00", "AAA", 0, 10)
        assert adh.classify(self.EP_BUY, 7, db_path=db_path) == "followed"

    def test_sell_followed(self, db_path):
        _change(db_path, "2026-10-03 09:00:00", "AAA", 10, 4)
        assert adh.classify(self.EP_SELL, 7, db_path=db_path) == "followed"

    def test_contrary(self, db_path):
        _change(db_path, "2026-10-03 09:00:00", "AAA", 10, 4)
        assert adh.classify(self.EP_BUY, 7, db_path=db_path) == "contrary"

    def test_import_without_movement_is_not_followed(self, db_path):
        """가져오기(−q/+q 쌍)가 있었는데 그 종목이 그대로면 안 따른 것이다."""
        _change(db_path, "2026-10-03 09:00:00", "AAA", 10, None)
        _change(db_path, "2026-10-03 09:00:00", "AAA", None, 10)
        assert adh.classify(self.EP_BUY, 7, db_path=db_path) == "not_followed"

    def test_no_import_in_the_window_is_unknown(self, db_path):
        """원장에 아무 흔적이 없으면 '안 따름' 이 아니라 '모름' — 가져오기를 안 했을 뿐일 수 있다."""
        assert adh.classify(self.EP_BUY, 7, db_path=db_path) == "unknown"

    def test_same_day_change_is_outside_the_window(self, db_path):
        """창은 시작일 **다음 날**부터 — 추천 당일 07:05 이전의 변경은 그 추천의 결과가 아니다."""
        _change(db_path, "2026-10-01 06:00:00", "AAA", 0, 10)
        assert adh.classify(self.EP_BUY, 7, db_path=db_path) == "unknown"

    def test_change_after_the_window_does_not_count(self, db_path):
        _change(db_path, "2026-10-20 09:00:00", "AAA", 0, 10)
        assert adh.classify(self.EP_BUY, 7, db_path=db_path) == "unknown"


def test_episode_before_the_log_is_unknown(db_path):
    _change(db_path, "2026-10-10 09:00:00", "AAA", 0, 10)
    ep = adh.Episode("AAA", "BUY", "2026-10-01", "2026-10-01", 1)
    assert adh.classify(ep, 30, db_path=db_path) == "unknown"


def test_summary_reads_the_window_from_config(db_path, monkeypatch):
    from nuri.core import rules

    monkeypatch.setitem(rules.ADHERENCE, "window_days", 2)
    _change(db_path, "2026-09-25 09:00:00", "ZZZ", None, 1)
    _recs(db_path, [("2026-10-01", "AAA", "BUY")])
    _change(db_path, "2026-10-05 09:00:00", "AAA", 0, 10)  # 2일 창 밖, 7일 창 안
    assert adh.summarize(db_path=db_path)["counts"] == {"BUY:unknown": 1}
