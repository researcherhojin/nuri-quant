"""nuri/trading/agents/smart_money.py 의 partial branches 닫기 (#616 Phase 3-A).

Branches:
- 67→71: rec 가 buy/sell 그룹 아님 (e.g. 'hold') → 둘 다 False → target 검사로 fallthrough
- 71→81: target=None or current=None or current<=0 → False → ARK 단계로
- 76→81: 0 < upside < upside_th (양수지만 임계 미만) → 둘 다 False → ARK 단계로
- lines 91-93: ARK direction 에서 sells > buys → score -= 1, "ARK 최근 매도" 추가

`# pragma: no cover` 미사용 (CLAUDE.md ★).
"""

from __future__ import annotations

from nuri.core.db import get_db
from nuri.trading.agents.smart_money import SmartMoneyAgent


class TestSmartMoneyBranches:
    """4 partial branches in smart_money.py."""

    def test_recommendation_neutral_skips_buy_sell(self, db_path):
        """Branch 67→71: rec='hold' → buy/sell 분기 둘 다 False → target 검사 진입.
        target=upside_th 미만 양수 → 76→81 도 False → ARK 단계."""
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates "
                "(ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("TESTHO", "2026-01-01", "hold", 105.0, 100.0, 8),  # upside +5% < 20%
            )
        v = SmartMoneyAgent().analyze("TESTHO", db_path=db_path)
        # rec=hold 이라 buy/sell 분기 미진입; upside=5% (>0 but <20) → 76→81
        # → 결과는 reasons 비어있어 HOLD with 'no data' OR ARK 단계까지 가도 결과 동일
        assert v.action in ("BUY", "SELL", "HOLD")
        # 'buy' / 'sell' 키워드 미포함 (rec=hold)
        assert "애널리스트: buy" not in v.reasoning
        assert "애널리스트: sell" not in v.reasoning

    def test_target_or_current_missing_skips_upside_check(self, db_path):
        """Branch 71→81: target=None → if False → upside 평가 skip → ARK 단계."""
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates "
                "(ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("NOPX", "2026-01-01", "buy", None, 100.0, 5),
            )
        v = SmartMoneyAgent().analyze("NOPX", db_path=db_path)
        # rec=buy → score+=1, 그러나 target=None → 71→81 False → 목표가 reasons 미추가
        assert "목표가" not in v.reasoning

    def test_upside_between_thresholds_skips_score_adjust(self, db_path):
        """Branch 76→81: 0 < upside < upside_th(20) → if/elif 둘 다 False → ARK 단계."""
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates "
                "(ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("MIDUP", "2026-01-01", "buy", 110.0, 100.0, 5),  # upside +10% (between -10/+20)
            )
        v = SmartMoneyAgent().analyze("MIDUP", db_path=db_path)
        # upside=10% → 73(>20) False, 76(<-10) False → score 추가/감소 미발생
        assert "목표가 괴리" not in v.reasoning
        assert "목표가 하회" not in v.reasoning

    def test_ark_sells_dominate(self, db_path):
        """Lines 91-93: sells > buys → score -= 1, '매도' reason 추가."""
        with get_db(db_path) as conn:
            for i, direction in enumerate(["Sell", "Sell", "Sell", "Buy"]):
                conn.execute(
                    "INSERT INTO ark (ticker, date, direction, shares) VALUES (?, ?, ?, ?)",
                    ("ARKSL", f"2026-03-{20 + i:02d}", direction, 1000),
                )
        v = SmartMoneyAgent().analyze("ARKSL", db_path=db_path)
        assert "ARK 최근 매도" in v.reasoning

    def test_ark_buys_equals_sells_skips_score(self, db_path):
        """Branch 91→95: buys == sells → 88 False, 91 False → fallthrough to 95.
        ARK 카테고리에서 score 변화 없음, 'ARK 최근' reason 미추가."""
        # ARK 가 활성되려면 다른 score 트리거 필요 (no_data path 우회 위해 estimates 추가)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates "
                "(ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("EQAR", "2026-01-01", "buy", 130.0, 100.0, 5),
            )
            for i, direction in enumerate(["Buy", "Sell"]):  # 1:1
                conn.execute(
                    "INSERT INTO ark (ticker, date, direction, shares) VALUES (?, ?, ?, ?)",
                    ("EQAR", f"2026-03-{20 + i:02d}", direction, 1000),
                )
        v = SmartMoneyAgent().analyze("EQAR", db_path=db_path)
        assert "ARK 최근" not in v.reasoning

    def test_ark_hold_rows_are_not_counted_as_sells(self, db_path):
        """#1143 회귀 잠금: direction='Hold' 는 매도가 아니다.

        예전 코드는 `sells = len(rows) - buys` 로 세서 Hold 를 전부 매도로 집계했다.
        죽은 CSV 소스 때문에 ark 테이블이 Hold 만 담고 있던 기간 동안, 거기 있는
        티커는 예외 없이 score -1 과 "ARK 최근 매도 N건" 이라는 거짓 근거를 받았다.

        Hold 만 있을 때 ARK 는 아무 방향도 주장하지 않아야 한다. estimates 로 다른
        근거를 하나 깔아 no-data 경로를 우회하고, ARK 항목만 관찰한다.
        """
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates "
                "(ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("HOLDONLY", "2026-01-01", "buy", 130.0, 100.0, 5),
            )
            for i in range(5):
                conn.execute(
                    "INSERT INTO ark (ticker, date, direction, shares, fund) VALUES (?, ?, ?, ?, ?)",
                    ("HOLDONLY", f"2026-03-{20 + i:02d}", "Hold", 0.0, f"ARK{i}"),
                )
        v = SmartMoneyAgent().analyze("HOLDONLY", db_path=db_path)
        assert "ARK 최근 매도" not in v.reasoning
        assert "ARK 최근 매수" not in v.reasoning

    def test_ark_counting_is_safe_even_if_the_query_stops_filtering(self, db_path):
        """#1143 회귀 잠금 — 집계 그 자체.

        위 테스트는 SQL 의 `direction IN ('Buy','Sell')` 만으로도 통과한다. 즉 필터를
        지우면 잡히지만 **집계식을 되돌리면 안 잡힌다.** 두 방어선은 막는 게 서로 다르다:
        필터가 없으면 침묵(진짜 매매가 창 밖으로 밀림), 집계가 틀리면 거짓 매도다.
        후자를 잠그려고 `_safe_query` 를 가로채 Hold 행을 집계 코드에 직접 흘린다 —
        나중에 필터가 느슨해지거나 다른 호출자가 생겨도 집계는 안전해야 한다.
        """
        from nuri.trading.agents.smart_money import SmartMoneyAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates "
                "(ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("RAWHOLD", "2026-01-01", "buy", 130.0, 100.0, 5),
            )

        agent = SmartMoneyAgent()
        real_safe_query = agent._safe_query

        def _leak_hold_rows(sql, params=(), db_path=None):
            if "FROM ark" in sql:
                return [{"direction": "Hold", "shares": 0.0} for _ in range(5)]
            return real_safe_query(sql, params, db_path)

        agent._safe_query = _leak_hold_rows
        v = agent.analyze("RAWHOLD", db_path=db_path)
        assert "ARK 최근 매도" not in v.reasoning
        assert "ARK 최근 매수" not in v.reasoning

    def test_ark_hold_does_not_crowd_out_real_trades(self, db_path):
        """#1143: 쿼리가 Hold 를 거르지 않으면 최신 Hold 5건이 LIMIT 5 창을 잡아먹어
        그 아래 실제 Buy 가 영영 안 보인다 — 결손이 아니라 침묵이라 신호가 없다."""
        with get_db(db_path) as conn:
            for i in range(3):  # 오래된 진짜 매수
                conn.execute(
                    "INSERT INTO ark (ticker, date, direction, shares, fund) VALUES (?, ?, ?, ?, ?)",
                    ("CROWD", f"2026-03-0{1 + i}", "Buy", 1000.0, f"ARK{i}"),
                )
            for i in range(5):  # 그 위를 덮는 최신 Hold 스냅샷
                conn.execute(
                    "INSERT INTO ark (ticker, date, direction, shares, fund) VALUES (?, ?, ?, ?, ?)",
                    ("CROWD", f"2026-03-{20 + i:02d}", "Hold", 0.0, f"ARK{i}"),
                )
        v = SmartMoneyAgent().analyze("CROWD", db_path=db_path)
        assert "ARK 최근 매수 3건" in v.reasoning
