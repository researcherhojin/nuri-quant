"""Lock-tests for the leader-exit rule (8주 룰 운영화) — growth-type 기준.

Source of truth: `config/rules.yaml take_profit.leader` -> `nuri.core.rules.TAKE_PROFIT_LEADER`.
리더 = 성장주(classify_stock_type==growth) + 50일선 계산가능. 고정 익절 대신 50일선 트레일.
Reverting is_leader / TP skip / check_leader_trail_signals / actions wiring fails these.

**#715 (2026-06-22): config 기본값 enabled=false 로 DISABLED.** growth 197종목 walk-forward
(random entries·permutation null·holdout) 에서 leader-exit 가 ladder 대비 열위(Δ−0.318,
p=0.55) → 라이브 정당화 실패, O'Neil ladder 복원. **코드는 보존**(validated leader-entry
조건부 재검증 대비). 따라서 이 파일의 behavior lock-test 는 `_enable_leader` autouse
fixture 로 enabled=true 를 명시 주입해 동작 자체를 잠근다 (config 정책값과 분리).
"""

from datetime import date, timedelta

import pytest

from nuri.core.db import get_db
from nuri.trading.recommend.price_targets import (
    calculate_targets,
    check_leader_trail_signals,
    check_take_profit_signals,
    format_target_tree,
    is_leader,
)


@pytest.fixture(autouse=True)
def _enable_leader(monkeypatch):
    """leader-exit 는 #715 로 config 기본값 disabled — behavior lock-test 는 enabled=true
    를 명시 주입해 코드 경로를 잠근다. `test_disabled*` 는 본문에서 다시 false 로 override."""
    import nuri.trading.recommend.price_targets as pt

    monkeypatch.setattr(pt, "TAKE_PROFIT_LEADER", {"enabled": True, "trail_ma": 50})


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

    def test_disabled_returns_empty(self, db_path, monkeypatch):
        """take_profit.leader.enabled=False → 리더-트레일 비활성 (빈 리스트)."""
        import nuri.trading.recommend.price_targets as pt

        monkeypatch.setattr(pt, "TAKE_PROFIT_LEADER", {"enabled": False, "trail_ma": 50})
        _seed(db_path, "GRW", 100.0, [140.0] * 49 + [125.0], sector="AI")
        assert check_leader_trail_signals(db_path=db_path) == []

    def test_empty_portfolio_returns_empty(self, db_path):
        """라인 507-508: 보유가 없으면 조회할 대상도 없다 — 빈 리스트.

        `enabled=True` 인데 portfolio 가 비어 있는 조합은 신규 배포/빈 DB 에서
        그대로 나온다. 아래 루프가 빈 DataFrame 을 만나면 iterrows 는 무해하지만,
        이 early return 이 사라져도 아무도 모르므로 계약으로 고정한다.
        """
        assert check_leader_trail_signals(db_path=db_path) == []

    def test_skips_zero_entry_price(self, db_path):
        """avg_price=0 보유는 손익 계산 불가 → skip (크래시 없음)."""
        _seed(db_path, "ZERO", 0.0, [140.0] * 49 + [125.0], sector="AI")
        assert "ZERO" not in {s["ticker"] for s in check_leader_trail_signals(db_path=db_path)}

    def test_skips_when_current_price_missing(self, db_path, monkeypatch):
        """리더여도 현재가 조회 실패 시 시그널 침묵 (방어)."""
        import nuri.trading.recommend.price_targets as pt

        _seed(db_path, "GRW", 100.0, [140.0] * 49 + [125.0], sector="AI")
        monkeypatch.setattr(pt, "_get_current_price", lambda *a, **k: None)
        assert "GRW" not in {s["ticker"] for s in check_leader_trail_signals(db_path=db_path)}


class TestLeaderTargets:
    def test_leader_targets_numeric_kept_with_flag(self, db_path):
        """codex R4-P2: 리더라도 target_1/2 numeric 유지 (참고용) + is_leader/leader_ma 플래그."""
        _seed(db_path, "GRW", 100.0, [130.0] * 50, sector="AI")
        t = calculate_targets("GRW", entry_price=100.0, db_path=db_path)
        assert t["is_leader"] is True
        assert t["target_1"] is not None and t["target_2"] is not None  # price-level 의무 유지 (참고용)
        assert t["leader_ma"] is not None

    def test_format_target_tree_shows_leader_line(self, db_path):
        """리더 target 트리는 '⭐ 리더 (성장주) … N일선 … 이탈 시 청산' 줄을 포함."""
        _seed(db_path, "GRW", 100.0, [130.0] * 50, sector="AI")
        t = calculate_targets("GRW", entry_price=100.0, db_path=db_path)
        tree = format_target_tree(t)
        assert "리더" in tree
        assert "일선" in tree


class TestConfigDefaultDisabled715:
    """#715 정책 결정 lock — config 기본값이 disabled 임을 고정.

    leader-exit 가 growth walk-forward(#715)에서 ladder 대비 열위(Δ−0.318, p=0.55)로
    FAIL → enabled=false 가 데이터 기반 디폴트. 무근거 재활성(true 복귀)이 이 테스트를
    깬다 — 재활성은 STRATEGY PR + 재검증 PASS 가 선결. (autouse _enable_leader 는 모듈
    상수만 패치하므로 YAML 직접 read 는 영향 없음.)
    """

    def test_rules_yaml_leader_disabled(self):
        from pathlib import Path

        import yaml

        cfg = yaml.safe_load((Path(__file__).resolve().parents[3] / "config" / "rules.yaml").read_text())
        leader = cfg["take_profit"]["leader"]
        assert leader["enabled"] is False, "leader-exit 재활성은 #715 재검증 PASS 선결 (STRATEGY PR)"
