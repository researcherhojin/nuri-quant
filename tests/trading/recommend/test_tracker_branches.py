"""tracker.py branch coverage — Issue #616 Phase 3-C1.

353→364: `if report["by_action"]:` False (빈 list) → 표 출력 skip.
"""

from __future__ import annotations


class TestTrackerEmptyByAction:
    def test_print_report_with_zero_by_action_skips_table(self, tmp_path, capsys, monkeypatch):
        """353→364: report['by_action']==[] → 표 출력 skip → recent 쿼리로 fall through."""
        from nuri.core.db import init_db
        from nuri.trading.recommend import tracker as tracker_mod

        p = tmp_path / "tr.db"
        init_db(p)

        # tracked>0 이지만 by_action 빈 list 인 report 주입.
        fake_report = {
            "total_recommendations": 5,
            "tracked": 3,
            "hit_count": 2,
            "hit_rate": 0.67,
            "by_action": [],  # 빈 list → 353 False
        }
        monkeypatch.setattr(
            tracker_mod,
            "get_tracking_report",
            lambda *a, **kw: fake_report,
        )
        monkeypatch.setattr(tracker_mod, "query", lambda *a, **kw: [])

        tracker_mod.print_tracking_report(db_path=p)
        out = capsys.readouterr().out
        # tracked > 0 → "Hit rate" 출력. by_action 빈 → "Action" 헤더 미출력.
        assert "Hit rate" in out
        assert "Action" not in out
