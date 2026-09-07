"""nuri/trading/agents/smart_money.py 의 partial branches 닫기 (#616 Phase 3-A).

Branches:
- 67→71: rec 가 buy/sell 그룹 아님 (e.g. 'hold') → 둘 다 False → target 검사로 fallthrough
- 71→81: target=None or current=None or current<=0 → False → ARK 단계로
- 76→81: 0 < upside < upside_th (양수지만 임계 미만) → 둘 다 False → ARK 단계로
- lines 91-93: ARK direction 에서 sells > buys → score -= 1, "ARK 최근 매도" 추가

`# pragma: no cover` 미사용 (CLAUDE.md ★).
"""

from __future__ import annotations

from datetime import timedelta

from nuri.core.db import get_db
from nuri.core.timezone import kst_now
from nuri.trading.agents.base import QueryRows
from nuri.trading.agents.smart_money import SmartMoneyAgent


def _d(days_ago: int) -> str:
    """오늘 앵커 날짜 — 고정 리터럴은 시한폭탄 (tests/CLAUDE.md Time-bomb seed dates, #1187)."""
    return (kst_now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


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
                ("TESTHO", _d(5), "hold", 105.0, 100.0, 8),  # upside +5% < 20%
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
                ("NOPX", _d(5), "buy", None, 100.0, 5),
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
                ("MIDUP", _d(5), "buy", 110.0, 100.0, 5),  # upside +10% (between -10/+20)
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
                    ("ARKSL", _d(4 - i), direction, 1000),
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
                ("EQAR", _d(5), "buy", 130.0, 100.0, 5),
            )
            for i, direction in enumerate(["Buy", "Sell"]):  # 1:1
                conn.execute(
                    "INSERT INTO ark (ticker, date, direction, shares) VALUES (?, ?, ?, ?)",
                    ("EQAR", _d(4 - i), direction, 1000),
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
                ("HOLDONLY", _d(5), "buy", 130.0, 100.0, 5),
            )
            for i in range(5):
                conn.execute(
                    "INSERT INTO ark (ticker, date, direction, shares, fund) VALUES (?, ?, ?, ?, ?)",
                    ("HOLDONLY", _d(4 - i), "Hold", 0.0, f"ARK{i}"),
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
                ("RAWHOLD", _d(5), "buy", 130.0, 100.0, 5),
            )

        agent = SmartMoneyAgent()
        real_safe_query = agent._safe_query

        def _leak_hold_rows(sql, params=(), db_path=None):
            if "FROM ark" in sql:
                return QueryRows([{"direction": "Hold", "shares": 0.0} for _ in range(5)])
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
                    ("CROWD", _d(10 - i), "Buy", 1000.0, f"ARK{i}"),
                )
            for i in range(5):  # 그 위를 덮는 최신 Hold 스냅샷
                conn.execute(
                    "INSERT INTO ark (ticker, date, direction, shares, fund) VALUES (?, ?, ?, ?, ?)",
                    ("CROWD", _d(4 - i), "Hold", 0.0, f"ARK{i}"),
                )
        v = SmartMoneyAgent().analyze("CROWD", db_path=db_path)
        assert "ARK 최근 매수 3건" in v.reasoning


class TestSourceFreshnessSuppression:
    """#1187: source 별 신선도 억제 — 낡은 소스는 점수 0 + '낡음 — 제외' 명시.

    축별로 따로 잠근다 (mutation-axes 규칙): 한 소스의 컷오프를 지워도
    다른 소스 테스트는 초록이므로 축마다 전용 테스트가 있어야 한다.
    """

    def test_stale_superinvestors_are_excluded_with_note(self, db_path):
        """13F 가 컷오프(200d)보다 낡으면 보유·신규매수 점수 모두 0 + 명시."""
        with get_db(db_path) as conn:
            for inv in ("Buffett", "Dalio", "Gates"):
                conn.execute(
                    "INSERT INTO superinvestors (investor, ticker, portfolio_pct, filing_date, investor_class) "
                    "VALUES (?, ?, ?, ?, 'conviction')",
                    (inv, "STALE13F", 8.0, _d(300)),
                )
        v = SmartMoneyAgent().analyze("STALE13F", db_path=db_path)
        assert "슈퍼투자자 13F 낡음" in v.reasoning
        assert "슈퍼투자자 3명 보유" not in v.reasoning
        assert "최근 신규 매수" not in v.reasoning
        assert v.data_points["score"] == 0
        assert "superinvestors" in v.data_points["stale_sources"]

    def test_fresh_superinvestors_still_score(self, db_path):
        with get_db(db_path) as conn:
            for inv in ("Buffett", "Dalio"):
                conn.execute(
                    "INSERT INTO superinvestors (investor, ticker, portfolio_pct, filing_date, investor_class) "
                    "VALUES (?, ?, ?, ?, 'conviction')",
                    (inv, "FRESH13F", 8.0, _d(30)),
                )
        v = SmartMoneyAgent().analyze("FRESH13F", db_path=db_path)
        assert "슈퍼투자자 2명 보유" in v.reasoning
        assert v.data_points["stale_sources"] == []

    def test_stale_estimates_are_excluded_with_note(self, db_path):
        """estimates 최신 행이 45d 컷오프보다 낡으면 등급/목표가 점수 제외 + 명시."""
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("STALEEST", _d(90), "strong_buy", 200.0, 100.0, 10),
            )
        v = SmartMoneyAgent().analyze("STALEEST", db_path=db_path)
        assert "애널리스트 컨센서스 낡음" in v.reasoning
        assert "애널리스트: strong_buy" not in v.reasoning
        assert "목표가" not in v.reasoning
        assert v.data_points["score"] == 0
        assert "estimates" in v.data_points["stale_sources"]

    def test_stale_ark_trades_are_excluded_with_note(self, db_path):
        """ARK 매매가 14d 컷오프보다 낡으면 ± 점수 제외 + 명시 — 235d stale ±1 사고의 재발 방지."""
        with get_db(db_path) as conn:
            for i in range(3):
                conn.execute(
                    "INSERT INTO ark (ticker, date, direction, shares) VALUES (?, ?, ?, ?)",
                    ("STALEARK", _d(235 + i), "Buy", 1000),
                )
        v = SmartMoneyAgent().analyze("STALEARK", db_path=db_path)
        assert "ARK 매매 낡음" in v.reasoning
        assert "ARK 최근 매수" not in v.reasoning
        assert v.data_points["score"] == 0
        assert "ark" in v.data_points["stale_sources"]

    def test_mixed_ark_counts_only_fresh_rows(self, db_path):
        """창 안에 낡은 Sell + 신선한 Buy 가 섞이면 신선한 것만 센다."""
        with get_db(db_path) as conn:
            for i in range(2):  # 낡은 Sell
                conn.execute(
                    "INSERT INTO ark (ticker, date, direction, shares) VALUES (?, ?, ?, ?)",
                    ("MIXARK", _d(60 + i), "Sell", 1000),
                )
            for i in range(2):  # 신선한 Buy
                conn.execute(
                    "INSERT INTO ark (ticker, date, direction, shares) VALUES (?, ?, ?, ?)",
                    ("MIXARK", _d(1 + i), "Buy", 1000),
                )
        v = SmartMoneyAgent().analyze("MIXARK", db_path=db_path)
        assert "ARK 최근 매수 2건" in v.reasoning
        assert "ARK 매매 낡음" not in v.reasoning

    def test_all_sources_stale_returns_hold_with_exclusion_notes(self, db_path):
        """전 소스 낡음 → '데이터 없음' 이 아니라 제외 사유가 나열된 HOLD."""
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, portfolio_pct, filing_date, investor_class) "
                "VALUES ('Buffett', 'ALLSTALE', 8.0, ?, 'conviction')",
                (_d(300),),
            )
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES ('ALLSTALE', ?, 'buy', 200.0, 100.0, 10)",
                (_d(90),),
            )
            conn.execute(
                "INSERT INTO ark (ticker, date, direction, shares) VALUES ('ALLSTALE', ?, 'Buy', 1000)",
                (_d(235),),
            )
        v = SmartMoneyAgent().analyze("ALLSTALE", db_path=db_path)
        assert v.action == "HOLD"
        assert "스마트머니 데이터 없음" not in v.reasoning
        assert "낡음" in v.reasoning
        assert set(v.data_points["stale_sources"]) == {"superinvestors", "estimates", "ark"}
        # #1436 (codex R7): 증거를 하나도 못 썼으므로 **의견이 아니라 기권**이다. 제외 노트가
        # `reasons` 에 섞여 있던 동안에는 살아 있는 HOLD 로 집계돼 동의율·커버리지를 부풀렸다.
        assert v.abstained is True and v.degraded is False

    def test_a_stale_note_does_not_mask_a_failed_sibling_read(self, db_path, monkeypatch):
        """검증된 낡음 + 형제 조회 실패 → degraded 다 (#1436, codex R7 P1).

        `reasons` 가 점수 근거와 제외 노트를 섞고 있던 동안, "13F 낡음 — 제외" 하나가
        `not reasons` 를 거짓으로 만들어 **estimates 조회 실패를 살아 있는 HOLD/43.8 로**
        내보냈다. 실패한 조회가 표를 얻고 패널 커버리지까지 부풀린다.
        `risk_agent` 에서 고친 것과 같은 형태 — 실패를 가리는 근거가 실패 자신이 만든 근거다.
        """
        with get_db(db_path) as conn:
            conn.execute(  # 소스 자체가 낡음 → 검증된 제외 노트가 난다
                "INSERT INTO superinvestors (investor, ticker, portfolio_pct, filing_date, investor_class) "
                "VALUES ('Buffett', 'STALEMASK', 8.0, ?, 'conviction')",
                (_d(300),),
            )
        agent = SmartMoneyAgent()
        real = agent._safe_query

        def _stub(sql, params, dbp):
            if "FROM estimates WHERE ticker" in sql:
                return QueryRows(failed=True)
            return real(sql, params, dbp)

        monkeypatch.setattr(agent, "_safe_query", _stub)
        v = agent.analyze("STALEMASK", db_path=db_path)
        assert v.degraded is True and v.abstained is False, f"실패가 노트에 가려졌다: {v.reasoning!r}"
        assert v.confidence == 0


class TestStaleRowsVsFreshSource:
    """#1187 Codex P2 ×2: 티커 행만 낡은 것(정상 부재)과 소스 staleness 를 구분한다.

    - 13F 에서 팔린 종목: 소스는 매 분기 갱신 중인데 그 티커의 마지막 보유 행만 늙는다
    - ARK 보유 유지 종목: Hold 스냅샷은 매일 오는데 마지막 Buy/Sell 행만 늙는다
    둘 다 "낡음 — 제외" 노트 없이 조용히 제외돼야 한다. 소스 프로브는 ark 의 경우
    `ark_source_dates` (#1147 — ark 테이블은 보유 교집합이라 소스 신선도의 정본이 아님).
    """

    def test_sold_out_13f_name_is_silent_absence_not_stale_note(self, db_path):
        with get_db(db_path) as conn:
            # 이 티커의 마지막 보유는 300일 전 (매도 종결)
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, portfolio_pct, filing_date, investor_class) "
                "VALUES ('Buffett', 'SOLDOUT', 8.0, ?, 'conviction')",
                (_d(300),),
            )
            # 소스는 살아 있다 — 다른 티커에 신선한 제출분
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, portfolio_pct, filing_date, investor_class) "
                "VALUES ('Buffett', 'OTHER', 5.0, ?, 'conviction')",
                (_d(30),),
            )
        v = SmartMoneyAgent().analyze("SOLDOUT", db_path=db_path)
        assert "낡음" not in v.reasoning
        assert "슈퍼투자자" not in v.reasoning  # 점수 기여도 없음 (조용한 부재)
        assert "superinvestors" not in v.data_points.get("stale_sources", [])

    def test_stale_estimates_with_fresh_source_is_silent(self, db_path):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES ('DROPPED', ?, 'buy', 200.0, 100.0, 10)",
                (_d(90),),
            )
            conn.execute(
                "INSERT INTO estimates (ticker, date, recommendation, target_mean, current_price, num_analysts) "
                "VALUES ('COVERED', ?, 'buy', 300.0, 200.0, 12)",
                (_d(3),),
            )
        v = SmartMoneyAgent().analyze("DROPPED", db_path=db_path)
        assert "낡음" not in v.reasoning
        assert "애널리스트" not in v.reasoning

    def test_ark_held_steady_with_fresh_snapshots_is_silent(self, db_path):
        with get_db(db_path) as conn:
            # 마지막 매매는 60일 전이지만, 소스(ark_source_dates)는 매일 갱신 중
            conn.execute(
                "INSERT INTO ark (ticker, date, direction, shares) VALUES ('HELD', ?, 'Buy', 1000)",
                (_d(60),),
            )
            conn.execute(
                "INSERT INTO ark_source_dates (fund, csv_date, observed_at) VALUES ('ARKK', ?, ?)",
                (_d(1), _d(1)),
            )
        v = SmartMoneyAgent().analyze("HELD", db_path=db_path)
        assert "ARK 매매 낡음" not in v.reasoning
        assert "ARK 최근 매수" not in v.reasoning  # 낡은 매매는 점수에도 안 들어감
        assert "ark" not in v.data_points.get("stale_sources", [])

    def _seed_stale_ark(self, db_path):
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO ark (ticker, date, direction, shares) VALUES ('NOPROBE', ?, 'Buy', 1000)",
                (_d(60),),
            )

    def _with_probe(self, agent, monkeypatch, probe_result):
        real = agent._safe_query

        def _stub(sql, params, dbp):
            return probe_result if "ark_source_dates" in sql else real(sql, params, dbp)

        monkeypatch.setattr(agent, "_safe_query", _stub)

    def test_probe_empty_result_counts_as_not_fresh(self, db_path, monkeypatch):
        """프로브가 **빈 결과**면 미상 = 신선 아님 → 낡은 행만 있으면 노트가 난다.
        부재를 신선으로 치면 '진짜 낡았는데 침묵' 이 된다.

        빈 결과는 수집기가 한 번도 기록을 안 남겼다는 뜻이라 낡음 주장이 성립한다.
        조회 **실패**는 다르다 — 아래 짝 테스트 참조."""
        self._seed_stale_ark(db_path)
        agent = SmartMoneyAgent()
        self._with_probe(agent, monkeypatch, QueryRows())
        v = agent.analyze("NOPROBE", db_path=db_path)
        assert "ARK 매매 낡음" in v.reasoning
        assert "ark" in v.data_points["stale_sources"]

    def test_superinvestor_probe_failure_makes_no_staleness_claim(self, db_path, monkeypatch):
        """축마다 따로 잠근다 — 세 프로브(13F · estimates · ark)는 호출부가 각각이다.

        실측으로 확인한 구멍이다: ark 축만 잠갔을 때 13F 축의 `not si_probe_failed` 를
        지우는 뮤테이션이 **통과했다.** 한 규칙에 잠금이 한 경로만 걸리면 나머지는 무방비다.
        """
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, portfolio_pct, filing_date, investor_class) "
                "VALUES ('Buffett', 'SIPROBE', 8.0, ?, 'conviction')",
                (_d(300),),  # 컷오프(200일)보다 낡음 → 소스-레벨 프로브를 태운다
            )
        agent = SmartMoneyAgent()
        real = agent._safe_query

        def _stub(sql, params, dbp):
            if "MAX(filing_date) FROM superinvestors" in sql:
                return QueryRows(failed=True)
            return real(sql, params, dbp)

        monkeypatch.setattr(agent, "_safe_query", _stub)
        v = agent.analyze("SIPROBE", db_path=db_path)
        assert "13F 낡음" not in v.reasoning, f"검증 못 한 staleness 를 사실로 주장했다: {v.reasoning!r}"
        assert "superinvestors" not in v.data_points.get("stale_sources", [])
        assert v.degraded is True and v.abstained is False

    def test_probe_failure_makes_no_staleness_claim(self, db_path, monkeypatch):
        """짝 (#1436, codex R6 P1) — 프로브가 **실패**하면 낡았는지 모른다.

        빈 결과와 뭉뚱그려 "낡음 — 제외" 를 적으면 검증한 적 없는 사실 주장이 되고, 그
        문구가 `reasons` 를 채워 `_no_data` 의 실패 분기까지 우회한다. 억제는 그대로 하되
        말은 하지 않고, verdict 는 degraded 로 낸다."""
        self._seed_stale_ark(db_path)
        agent = SmartMoneyAgent()
        self._with_probe(agent, monkeypatch, QueryRows(failed=True))
        v = agent.analyze("NOPROBE", db_path=db_path)
        assert "ARK 매매 낡음" not in v.reasoning
        assert "ark" not in v.data_points.get("stale_sources", [])
        assert v.degraded is True and v.abstained is False
