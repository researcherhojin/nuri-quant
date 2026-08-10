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
    """`_get_regime` 는 조회가 죽어도 값을 돌려준다 — 다만 **VIX 는 지어내지 않는다.**

    2026-08-10 이전에는 부재·실패·노후를 전부 `20.0` 으로 메웠고, 이 클래스의 옛 주석은
    *"20.0 은 어느 게이트도 건드리지 않는 중립값이라 '모름' 을 가장 정직하게 표현한다"*
    고 적고 있었다. 그 전제가 틀렸다 — 어느 게이트도 건드리지 않는다는 건 **측정 불가가
    조용히 통과권을 얻는다**는 뜻이고, 브리핑에는 `VIX=20.0` 이 측정값처럼 찍혔다.
    이제 `None` 이고, 부르는 쪽이 caution 과 동일하게 절반 포지션으로 처리한다
    (STRATEGY §2.6 Soft penalty).
    """

    def test_vix_query_failure_yields_unknown_not_a_fabricated_number(self, monkeypatch):
        """VIX 조회 실패 → `None`. 20.0 으로 되돌리면 FAIL.

        Gotcha-Test Pair: `_get_regime` 의 VIX 실패 경로가 숫자를 돌려주면 두 번째
        assert 가 FAIL — 그게 '측정 불가를 평온으로 둔갑' 시키던 회귀다.
        """
        from nuri.core.db import OperationalError
        from nuri.trading.recommend import buy_candidate_emitter as bce
        from nuri.trading.recommend import vix_gate as vg

        calls = []

        def _selective_boom(sql, *a, **kw):
            calls.append(sql)
            if "macro" in sql:
                raise OperationalError("simulated DB failure")
            import pandas as pd

            return pd.DataFrame()

        monkeypatch.setattr(bce, "query_df", _selective_boom)
        monkeypatch.setattr(vg, "query_df", _selective_boom)

        regime, vix = bce._get_regime()

        assert vix is None, "조회 실패인데 숫자를 지어냈다"
        assert regime == "neutral"
        assert any("macro" in s for s in calls), "VIX 조회 자체가 일어나지 않았다"

    def test_a_coding_error_is_not_disguised_as_unknown_vix(self, monkeypatch):
        """DB 오류가 아닌 예외는 삼키지 않는다.

        넓은 `except Exception` 이면 이 블록의 **코딩 오류**가 "VIX 미상" 으로 위장해
        영구 반포지션이 된다. 실제로 초안에서 `today_kst()`(str)에 timedelta 를 빼다
        TypeError 가 났고 넓은 except 가 그걸 삼켰다.

        Gotcha-Test Pair: `except (OperationalError, DatabaseError)` 를
        `except Exception` 으로 넓히면 이 테스트가 FAIL.
        """
        import pytest as _pytest

        from nuri.trading.recommend import buy_candidate_emitter as bce
        from nuri.trading.recommend import vix_gate as vg

        def _type_error(sql, *a, **kw):
            if "macro" in sql:
                raise TypeError("simulated coding error")
            import pandas as pd

            return pd.DataFrame()

        monkeypatch.setattr(bce, "query_df", _type_error)
        monkeypatch.setattr(vg, "query_df", _type_error)

        with _pytest.raises(TypeError):
            bce._get_regime()
