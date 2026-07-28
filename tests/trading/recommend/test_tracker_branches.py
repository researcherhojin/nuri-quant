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


class TestRegimeClassifyDegradation:
    def test_classify_failure_leaves_regime_null_and_still_saves(self, tmp_path, monkeypatch):
        """라인 80-81: regime 분류가 죽어도 추천 저장은 계속되고 라벨은 NULL 로 남는다.

        두 가지를 동시에 지킨다:
        1. **저장이 막히면 안 된다.** regime 라벨은 사후 분석용 메타데이터지
           추천의 성립 조건이 아니다 ([[feedback_observability_must_not_gate]]).
        2. **'unknown' 같은 가짜 라벨을 쓰면 안 된다** (#832). 분류 실패와 실제
           regime 을 구분할 수 없게 되면 라벨 커버리지 통계 자체가 거짓이 된다.

        Gotcha-Test Pair: except 를 지우면 저장이 통째로 죽어 FAIL. NULL 대신
        'unknown' 을 넣어도 FAIL.
        """
        from nuri.core.db import init_db, query
        from nuri.trading.recommend.candidates import Candidate
        from nuri.trading.recommend.tracker import save_recommendations

        p = tmp_path / "tr_regime.db"
        init_db(p)

        import nuri.quant.regime.classifier as clf

        monkeypatch.setattr(clf, "classify_regime", lambda **kw: (_ for _ in ()).throw(RuntimeError("no price data")))

        candidates = [Candidate("TESTAA", "rsi_oversold", "2026-03-01", "BUY", 75.0, 0.6, 2.0, True, 100.0, "test")]
        assert save_recommendations(candidates, db_path=p) == 1

        rows = query("SELECT regime FROM recommendations WHERE ticker = 'TESTAA'", db_path=p)
        assert rows[0]["regime"] is None, "분류 실패가 가짜 라벨로 저장됐다"
