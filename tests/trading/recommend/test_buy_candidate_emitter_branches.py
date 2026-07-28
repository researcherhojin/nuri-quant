"""buy_candidate_emitter.py branch coverage — Issue #616 Phase 3-C2.

158→176: `if fallback > 0:` False (cooldown_cfg.fallback_days = 0) → legacy block skip.
154, 174 (stmt): 각 query_df 결과 non-empty 일 때 ticker 누적.
"""

from __future__ import annotations

import json

from nuri.core.db import get_db, init_db


class TestCooldownFallbackZero:
    def test_fallback_zero_skips_legacy_block(self, tmp_path):
        """158→176: cooldown_cfg.fallback_days = 0 → legacy query skip → suppressed 그대로."""
        from nuri.trading.recommend.buy_candidate_emitter import _get_cooldown_tickers_by_type

        p = tmp_path / "ce.db"
        init_db(p)

        # fallback=0 + type_days 모두 0 → 모든 분기 skip → 빈 set.
        cfg = {
            "hard_sell_days": 0,
            "trim_days": 0,
            "reduce_days": 0,
            "divergence_days": 0,
            "fallback_days": 0,
        }
        result = _get_cooldown_tickers_by_type(cfg)
        # query_df 호출 자체 안 일어남 → DB 무관 → 빈 set.
        # patch DB_PATH 없이 호출되면 default db_path 사용해 query_df 호출. 차단 위해 monkeypatch 필요.
        # 하지만 모든 days==0 이라 query_df 호출 자체 skip → 빈 set 반환.
        assert result == set()


class TestCooldownTickerAccumulation:
    def test_type_aware_and_legacy_events_populate_suppressed(self, tmp_path, monkeypatch):
        """154 + 174: pipeline_events 에 action_type / legacy 이벤트 → suppressed update."""
        import nuri.core.db as db_mod
        from nuri.trading.recommend.buy_candidate_emitter import _get_cooldown_tickers_by_type

        p = tmp_path / "ce_full.db"
        init_db(p)
        monkeypatch.setattr(db_mod, "DB_PATH", p)

        # pipeline_events seed: type-aware (action_type=hard_sell) + legacy (action_type=NULL).
        with get_db(p) as conn:
            conn.execute(
                "INSERT INTO pipeline_events (event_type, payload, timestamp) VALUES (?, ?, datetime('now'))",
                ("holdings_monitor_alert", json.dumps({"ticker": "AAA", "action_type": "hard_sell"})),
            )
            conn.execute(
                "INSERT INTO pipeline_events (event_type, payload, timestamp) VALUES (?, ?, datetime('now'))",
                ("holdings_monitor_alert", json.dumps({"ticker": "BBB"})),  # action_type 누락 → legacy
            )

        cfg = {
            "hard_sell_days": 21,
            "trim_days": 0,
            "reduce_days": 7,
            "divergence_days": 3,
            "fallback_days": 5,
        }
        result = _get_cooldown_tickers_by_type(cfg)
        assert "AAA" in result  # type-aware path (line 154)
        assert "BBB" in result  # legacy fallback path (line 174)


class TestRegimeAndVixDegradation:
    """`_get_regime` 는 조회가 죽어도 값을 돌려줘야 한다 — 부르는 쪽이 게이트다."""

    def test_vix_query_failure_falls_back_to_neutral_reading(self, monkeypatch):
        """라인 251-252: VIX 조회 실패 → 20.0.

        VIX 는 신규 매수 차단(>30) / 반포지션(25-30) 게이트의 입력이다. 조회가
        실패했을 때 예외가 새면 후보 산출 전체가 멈추고, 반대로 30 같은 값으로
        떨어지면 조회 실패가 조용히 '공포장' 으로 둔갑해 매수가 전면 차단된다.
        20.0 은 어느 게이트도 건드리지 않는 중립값이라 '모름' 을 가장 정직하게
        표현한다.

        Gotcha-Test Pair: fallback 값을 25 이상으로 바꾸면 두 번째 assert 가 FAIL.
        """
        from nuri.core.rules import VIX_BLOCK_ABOVE, VIX_CAUTION_ABOVE
        from nuri.trading.recommend import buy_candidate_emitter as bce

        calls = []

        def _selective_boom(sql, *a, **kw):
            calls.append(sql)
            if "macro" in sql:
                raise RuntimeError("simulated DB failure")
            import pandas as pd

            return pd.DataFrame()

        monkeypatch.setattr(bce, "query_df", _selective_boom)

        regime, vix = bce._get_regime()

        assert vix == 20.0
        assert vix < VIX_CAUTION_ABOVE < VIX_BLOCK_ABOVE, "조회 실패가 공포장으로 둔갑하면 안 된다"
        assert regime == "neutral"
        assert any("macro" in s for s in calls), "VIX 조회 자체가 일어나지 않았다"
