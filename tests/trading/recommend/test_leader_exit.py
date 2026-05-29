"""Lock-tests for the leader-exit rule (8주 룰 운영화) — growth-type 기준.

Source of truth: `config/rules.yaml take_profit.leader` -> `nuri.core.rules.TAKE_PROFIT_LEADER`.
리더 = 성장주(classify_stock_type==growth) + 50일선 계산가능. 고정 익절 대신 50일선 트레일.
Reverting is_leader / TP skip / check_leader_trail_signals / actions wiring fails these.

근거: 백테스트(17 성장주 2021~26, 비중첩·트레일동일·비용·연율화, skeptic 검증) —
무TP+MA50 트레일이 고정TP ladder 대비 CAGR 12.8% → 19.5%, 낙폭 더 얕음.
설계(codex 4-round review): growth-type 기준 (gain-threshold stickiness 문제 회피).
"""

from datetime import date, timedelta

from nuri.core.db import get_db
from nuri.trading.recommend.price_targets import (
    calculate_targets,
    check_leader_trail_signals,
    check_take_profit_signals,
    is_leader,
)


def _seed(db_path, ticker, avg_price, closes, sector="AI"):
    """portfolio 1종 + len(closes)일 가격 시드. sector 로 growth/value 제어."""
    d0 = date(2026, 1, 1)
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO portfolio "
            "(account, ticker, quantity, avg_price, currency, sector) VALUES (?, ?, ?, ?, ?, ?)",
            ("test", ticker, 10, avg_price, "USD", sector),
        )
        rows = [
            ((d0 + timedelta(days=i)).isoformat(), ticker, c, c * 1.01, c * 0.99, c, 1_000_000)
            for i, c in enumerate(closes)
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO prices (date, ticker, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


class TestIsLeader:
    def test_growth_with_ma_is_leader(self, db_path):
        _seed(db_path, "GRW", 100.0, [130.0] * 50, sector="AI")
        assert is_leader("GRW", db_path=db_path) is True

    def test_value_not_leader(self, db_path):
        _seed(db_path, "VAL", 100.0, [130.0] * 50, sector="Financials")
        assert is_leader("VAL", db_path=db_path) is False

    def test_growth_without_ma_not_leader(self, db_path):
        """codex R2-P2: 50일선 미계산(< trail_ma 종가) → 리더 아님 (고정 ladder 유지)."""
        _seed(db_path, "NEW", 100.0, [130.0] * 10, sector="AI")
        assert is_leader("NEW", db_path=db_path) is False

    def test_disabled(self, db_path, monkeypatch):
        import nuri.trading.recommend.price_targets as pt

        monkeypatch.setattr(pt, "TAKE_PROFIT_LEADER", {"enabled": False, "trail_ma": 50})
        _seed(db_path, "GRW", 100.0, [130.0] * 50, sector="AI")
        assert is_leader("GRW", db_path=db_path) is False


class TestTakeProfitSkipsLeader:
    def test_growth_leader_excluded_from_fixed_tp(self, db_path):
        _seed(db_path, "GRW", 100.0, [130.0] * 50, sector="AI")  # +30% 성장주
        assert "GRW" not in {s["ticker"] for s in check_take_profit_signals(db_path=db_path)}

    def test_value_still_fires_tp1(self, db_path):
        """가치주 +16% (>= value target_1 +15%) → 비리더 → 고정 익절 유지."""
        _seed(db_path, "VAL", 100.0, [116.0] * 50, sector="Financials")
        sigs = {s["ticker"]: s for s in check_take_profit_signals(db_path=db_path)}
        assert "VAL" in sigs
        assert sigs["VAL"]["level"] == "target_1"

    def test_growth_no_ma_keeps_fixed_tp(self, db_path):
        """codex R2-P2: 성장주여도 MA 미계산이면 고정 익절 유지 (트리거 공백 방지)."""
        _seed(db_path, "NEW", 100.0, [130.0] * 10, sector="AI")  # 성장주 +30% but 종가 10개
        assert "NEW" in {s["ticker"] for s in check_take_profit_signals(db_path=db_path)}


class TestLeaderTrail:
    def test_fires_when_growth_below_ma(self, db_path):
        closes = [140.0] * 49 + [125.0]  # MA50 ~= 139.7, current 125 < MA
        _seed(db_path, "BRK", 100.0, closes, sector="AI")
        sigs = {s["ticker"]: s for s in check_leader_trail_signals(db_path=db_path)}
        assert "BRK" in sigs
        assert sigs["BRK"]["status"] == "TREND_BREAK"
        assert sigs["BRK"]["ma_period"] == 50

    def test_silent_when_above_ma(self, db_path):
        closes = [125.0] * 49 + [130.0]  # MA50 ~= 125.1, current 130 > MA
        _seed(db_path, "RUN", 100.0, closes, sector="AI")
        assert "RUN" not in {s["ticker"] for s in check_leader_trail_signals(db_path=db_path)}

    def test_silent_for_value(self, db_path):
        """가치주는 50일선 아래여도 리더 아님 → 리더-트레일 침묵 (고정 ladder/일반 트레일 적용)."""
        closes = [140.0] * 49 + [125.0]
        _seed(db_path, "VLO", 100.0, closes, sector="Financials")
        assert "VLO" not in {s["ticker"] for s in check_leader_trail_signals(db_path=db_path)}


class TestLeaderTargets:
    def test_leader_targets_numeric_kept_with_flag(self, db_path):
        """codex R4-P2: 리더라도 target_1/2 numeric 유지 (참고용) + is_leader/leader_ma 플래그."""
        _seed(db_path, "GRW", 100.0, [130.0] * 50, sector="AI")
        t = calculate_targets("GRW", entry_price=100.0, db_path=db_path)
        assert t["is_leader"] is True
        assert t["target_1"] is not None and t["target_2"] is not None  # price-level 의무 유지 (참고용)
        assert t["leader_ma"] is not None
