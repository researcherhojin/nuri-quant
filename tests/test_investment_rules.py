"""투자 규칙 강제 적용 테스트 — 익절/트레일링 스톱/VIX 반포지션/매도 우선순위.

GitHub Issue #1: feat: enforce investment rules in code
"""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, query, upsert_prices


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _insert_position(db_path, ticker="AAPL", entry_price=100.0, direction="long",
                     portfolio_type="tactical", status="open",
                     target_1_price=None, target_2_price=None, high_water_mark=None):
    """테스트용 포지션 삽입 헬퍼."""
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO positions
               (portfolio_type, ticker, direction, entry_date, entry_price,
                quantity, status, target_1_price, target_2_price, high_water_mark)
               VALUES (?, ?, ?, '2025-01-01', ?, 100, ?, ?, ?, ?)""",
            (portfolio_type, ticker, direction, entry_price, status,
             target_1_price, target_2_price, high_water_mark),
        )


def _insert_price(db_path, ticker="AAPL", close=100.0, date="2025-03-20"):
    """테스트용 가격 삽입 헬퍼."""
    df = pd.DataFrame([{
        "ticker": ticker, "date": date,
        "open": close * 0.99, "high": close * 1.01,
        "low": close * 0.98, "close": close,
        "volume": 1000000, "adj_close": close,
    }])
    upsert_prices(df, db_path)


# ═══════════════════════════════════════════════════════
# DB 마이그레이션 테스트
# ═══════════════════════════════════════════════════════

class TestDBMigrations:
    """positions 테이블에 target_1_price, target_2_price, high_water_mark 컬럼 추가 확인."""

    def test_target_1_price_column_exists(self, db_path):
        """target_1_price 컬럼이 positions 테이블에 존재."""
        rows = query("PRAGMA table_info(positions)", db_path=db_path)
        columns = {row["name"] for row in rows}
        assert "target_1_price" in columns

    def test_target_2_price_column_exists(self, db_path):
        """target_2_price 컬럼이 positions 테이블에 존재."""
        rows = query("PRAGMA table_info(positions)", db_path=db_path)
        columns = {row["name"] for row in rows}
        assert "target_2_price" in columns

    def test_high_water_mark_column_exists(self, db_path):
        """high_water_mark 컬럼이 positions 테이블에 존재."""
        rows = query("PRAGMA table_info(positions)", db_path=db_path)
        columns = {row["name"] for row in rows}
        assert "high_water_mark" in columns

    def test_migration_versions(self, db_path):
        """마이그레이션 버전 3, 4, 5가 적용됨."""
        from nuri.core.db import get_schema_version
        version = get_schema_version(db_path)
        assert version >= 5

    def test_insert_with_new_columns(self, db_path):
        """새 컬럼에 값을 넣고 조회."""
        _insert_position(
            db_path, ticker="TEST", entry_price=100.0,
            target_1_price=120.0, target_2_price=140.0, high_water_mark=115.0,
        )
        rows = query(
            "SELECT target_1_price, target_2_price, high_water_mark "
            "FROM positions WHERE ticker = 'TEST'",
            db_path=db_path,
        )
        assert len(rows) == 1
        assert rows[0]["target_1_price"] == 120.0
        assert rows[0]["target_2_price"] == 140.0
        assert rows[0]["high_water_mark"] == 115.0


# ═══════════════════════════════════════════════════════
# Task 1: Take-Profit 자동 실행
# ═══════════════════════════════════════════════════════

class TestTakeProfitSignals:
    """익절 도달 시 SELL 시그널 자동 생성 테스트."""

    def test_no_signals_when_no_positions(self, db_path):
        """오픈 포지션 없으면 시그널 없음."""
        from nuri.trading.recommend.price_targets import check_take_profit_signals
        signals = check_take_profit_signals(db_path=db_path)
        assert signals == []

    def test_no_signals_below_target(self, db_path):
        """현재가가 익절가 미달이면 시그널 없음."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         target_1_price=120.0, target_2_price=140.0)
        _insert_price(db_path, ticker="AAPL", close=110.0)

        from nuri.trading.recommend.price_targets import check_take_profit_signals
        signals = check_take_profit_signals(db_path=db_path)
        assert signals == []

    def test_target_1_signal(self, db_path):
        """1차 익절 도달 시 SELL 시그널 (50% 매도)."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         target_1_price=120.0, target_2_price=140.0)
        _insert_price(db_path, ticker="AAPL", close=125.0)

        from nuri.trading.recommend.price_targets import check_take_profit_signals
        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) == 1
        sig = signals[0]
        assert sig.ticker == "AAPL"
        assert sig.direction == "SELL"
        assert sig.level == "target_1"
        assert sig.sell_pct == 50
        assert sig.current_price == 125.0
        assert sig.target_price == 120.0

    def test_target_2_signal(self, db_path):
        """2차 익절 도달 시 SELL 시그널 (25% 매도)."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         target_1_price=120.0, target_2_price=140.0)
        _insert_price(db_path, ticker="AAPL", close=145.0)

        from nuri.trading.recommend.price_targets import check_take_profit_signals
        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) == 1
        sig = signals[0]
        assert sig.level == "target_2"
        assert sig.sell_pct == 25

    def test_target_2_takes_priority_over_target_1(self, db_path):
        """현재가가 2차 익절 이상이면 target_2 시그널만 발생."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         target_1_price=120.0, target_2_price=140.0)
        _insert_price(db_path, ticker="AAPL", close=150.0)

        from nuri.trading.recommend.price_targets import check_take_profit_signals
        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) == 1
        assert signals[0].level == "target_2"

    def test_no_signal_for_closed_position(self, db_path):
        """청산된 포지션은 체크하지 않음."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         target_1_price=120.0, target_2_price=140.0, status="closed")
        _insert_price(db_path, ticker="AAPL", close=150.0)

        from nuri.trading.recommend.price_targets import check_take_profit_signals
        signals = check_take_profit_signals(db_path=db_path)
        assert signals == []

    def test_no_signal_for_short_position(self, db_path):
        """short 포지션은 체크하지 않음 (별도 로직)."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         direction="short",
                         target_1_price=120.0, target_2_price=140.0)
        _insert_price(db_path, ticker="AAPL", close=150.0)

        from nuri.trading.recommend.price_targets import check_take_profit_signals
        signals = check_take_profit_signals(db_path=db_path)
        assert signals == []

    def test_no_signal_when_targets_not_set(self, db_path):
        """익절가가 설정되지 않은 포지션은 건너뜀."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0)
        _insert_price(db_path, ticker="AAPL", close=150.0)

        from nuri.trading.recommend.price_targets import check_take_profit_signals
        signals = check_take_profit_signals(db_path=db_path)
        assert signals == []

    def test_multiple_positions(self, db_path):
        """여러 포지션 중 익절 도달한 것만 시그널."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         target_1_price=120.0, target_2_price=140.0)
        _insert_price(db_path, ticker="AAPL", close=125.0)

        # MSFT는 목표 미달
        with get_db(db_path) as conn:
            conn.execute(
                """INSERT INTO positions
                   (portfolio_type, ticker, direction, entry_date, entry_price,
                    quantity, status, target_1_price, target_2_price)
                   VALUES ('tactical', 'MSFT', 'long', '2025-01-02', 200.0,
                           50, 'open', 240.0, 280.0)""",
            )
        _insert_price(db_path, ticker="MSFT", close=210.0)

        from nuri.trading.recommend.price_targets import check_take_profit_signals
        signals = check_take_profit_signals(db_path=db_path)
        assert len(signals) == 1
        assert signals[0].ticker == "AAPL"

    def test_signal_return_pct(self, db_path):
        """수익률 계산 정확성."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         target_1_price=120.0, target_2_price=140.0)
        _insert_price(db_path, ticker="AAPL", close=125.0)

        from nuri.trading.recommend.price_targets import check_take_profit_signals
        signals = check_take_profit_signals(db_path=db_path)
        assert signals[0].return_pct == 25.0


class TestSetPositionTargets:
    """포지션 익절가 설정 테스트."""

    def test_set_growth_targets(self, db_path):
        """성장주: +20% / +40% 익절가 설정."""
        _insert_position(db_path, ticker="NVDA", entry_price=100.0)

        from nuri.trading.recommend.price_targets import set_position_targets
        result = set_position_targets(
            position_id=1, entry_price=100.0,
            stock_type="growth", db_path=db_path,
        )
        assert result["target_1_price"] == 120.0
        assert result["target_2_price"] == 140.0
        assert result["target_1_pct"] == 20
        assert result["target_2_pct"] == 40

        # DB에 저장 확인
        rows = query(
            "SELECT target_1_price, target_2_price FROM positions WHERE id = 1",
            db_path=db_path,
        )
        assert rows[0]["target_1_price"] == 120.0
        assert rows[0]["target_2_price"] == 140.0

    def test_set_value_targets(self, db_path):
        """가치주: +15% / +30% 익절가 설정."""
        _insert_position(db_path, ticker="BRK", entry_price=200.0)

        from nuri.trading.recommend.price_targets import set_position_targets
        result = set_position_targets(
            position_id=1, entry_price=200.0,
            stock_type="value", db_path=db_path,
        )
        assert result["target_1_price"] == 230.0
        assert result["target_2_price"] == 260.0

    def test_set_swing_targets(self, db_path):
        """스윙: +5% / +10% 익절가 설정."""
        _insert_position(db_path, ticker="SPY", entry_price=500.0)

        from nuri.trading.recommend.price_targets import set_position_targets
        result = set_position_targets(
            position_id=1, entry_price=500.0,
            stock_type="swing", db_path=db_path,
        )
        assert result["target_1_price"] == 525.0
        assert result["target_2_price"] == 550.0

    def test_auto_classify_with_ticker(self, db_path):
        """ticker만 주면 자동 분류."""
        _insert_position(db_path, ticker="TEST", entry_price=50.0)

        from nuri.trading.recommend.price_targets import set_position_targets
        result = set_position_targets(
            position_id=1, entry_price=50.0,
            ticker="TEST", db_path=db_path,
        )
        # stock_type이 자동 분류됨 (PE 데이터 없으면 value)
        assert result["stock_type"] in ("growth", "value", "swing")
        assert result["target_1_price"] > 50.0
        assert result["target_2_price"] > result["target_1_price"]


class TestPrintTakeProfitSignals:
    """익절 시그널 출력 테스트."""

    def test_empty(self, capsys):
        from nuri.trading.recommend.price_targets import print_take_profit_signals
        print_take_profit_signals([])
        output = capsys.readouterr().out
        assert "없음" in output

    def test_with_signals(self, capsys):
        from nuri.trading.recommend.price_targets import TakeProfitSignal, print_take_profit_signals
        signals = [
            TakeProfitSignal(
                ticker="AAPL", position_id=1, stock_type="growth",
                direction="SELL", level="target_1",
                entry_price=100.0, target_price=120.0, current_price=125.0,
                sell_pct=50, return_pct=25.0, note="1차 익절 도달",
            ),
        ]
        print_take_profit_signals(signals)
        output = capsys.readouterr().out
        assert "AAPL" in output
        assert "50%" in output
        assert "Take-Profit" in output


# ═══════════════════════════════════════════════════════
# Task 2: Trailing Stop 자동 추적
# ═══════════════════════════════════════════════════════

class TestUpdateHighWaterMarks:
    """고점(HWM) 갱신 테스트."""

    def test_no_positions(self, db_path):
        """오픈 포지션 없으면 갱신 0건."""
        from nuri.trading.execution.trailing import update_high_water_marks
        count = update_high_water_marks(db_path=db_path)
        assert count == 0

    def test_initialize_hwm(self, db_path):
        """HWM NULL이면 진입가와 현재가 중 높은 값으로 초기화."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0)
        _insert_price(db_path, ticker="AAPL", close=110.0)

        from nuri.trading.execution.trailing import update_high_water_marks
        count = update_high_water_marks(db_path=db_path)
        assert count == 1

        rows = query(
            "SELECT high_water_mark FROM positions WHERE ticker = 'AAPL'",
            db_path=db_path,
        )
        assert rows[0]["high_water_mark"] == 110.0

    def test_initialize_hwm_below_entry(self, db_path):
        """현재가가 진입가보다 낮으면 진입가로 초기화."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0)
        _insert_price(db_path, ticker="AAPL", close=90.0)

        from nuri.trading.execution.trailing import update_high_water_marks
        update_high_water_marks(db_path=db_path)

        rows = query(
            "SELECT high_water_mark FROM positions WHERE ticker = 'AAPL'",
            db_path=db_path,
        )
        assert rows[0]["high_water_mark"] == 100.0

    def test_update_hwm_higher(self, db_path):
        """현재가가 기존 HWM보다 높으면 갱신."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         high_water_mark=110.0)
        _insert_price(db_path, ticker="AAPL", close=120.0)

        from nuri.trading.execution.trailing import update_high_water_marks
        count = update_high_water_marks(db_path=db_path)
        assert count == 1

        rows = query(
            "SELECT high_water_mark FROM positions WHERE ticker = 'AAPL'",
            db_path=db_path,
        )
        assert rows[0]["high_water_mark"] == 120.0

    def test_no_update_hwm_lower(self, db_path):
        """현재가가 기존 HWM보다 낮으면 갱신하지 않음."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         high_water_mark=120.0)
        _insert_price(db_path, ticker="AAPL", close=110.0)

        from nuri.trading.execution.trailing import update_high_water_marks
        count = update_high_water_marks(db_path=db_path)
        assert count == 0

        rows = query(
            "SELECT high_water_mark FROM positions WHERE ticker = 'AAPL'",
            db_path=db_path,
        )
        assert rows[0]["high_water_mark"] == 120.0

    def test_skip_closed_positions(self, db_path):
        """청산된 포지션은 HWM 갱신하지 않음."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0, status="closed")
        _insert_price(db_path, ticker="AAPL", close=200.0)

        from nuri.trading.execution.trailing import update_high_water_marks
        count = update_high_water_marks(db_path=db_path)
        assert count == 0


class TestTrailingStopSignals:
    """트레일링 스톱 발동 테스트."""

    def test_no_signals_within_threshold(self, db_path):
        """고점 대비 하락이 임계값 내이면 시그널 없음."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         high_water_mark=120.0)
        # 120 * 0.9 = 108 → -10%로 -15% 내
        _insert_price(db_path, ticker="AAPL", close=108.0)

        from nuri.trading.execution.trailing import check_trailing_stop_signals
        signals = check_trailing_stop_signals(db_path=db_path)
        assert signals == []

    def test_signal_at_threshold(self, db_path):
        """고점 대비 -15% 이하 → SELL 시그널 발생."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         high_water_mark=120.0)
        # 120 * 0.85 = 102 → 정확히 -15%
        _insert_price(db_path, ticker="AAPL", close=102.0)

        from nuri.trading.execution.trailing import check_trailing_stop_signals
        signals = check_trailing_stop_signals(db_path=db_path)
        assert len(signals) == 1
        sig = signals[0]
        assert sig.ticker == "AAPL"
        assert sig.direction == "SELL"
        assert sig.high_water_mark == 120.0
        assert sig.current_price == 102.0
        assert sig.drop_pct == -15.0

    def test_signal_below_threshold(self, db_path):
        """고점 대비 -20% → SELL 시그널 발생."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         high_water_mark=120.0)
        # 120 * 0.80 = 96 → -20%
        _insert_price(db_path, ticker="AAPL", close=96.0)

        from nuri.trading.execution.trailing import check_trailing_stop_signals
        signals = check_trailing_stop_signals(db_path=db_path)
        assert len(signals) == 1
        assert signals[0].drop_pct == -20.0

    def test_no_signal_for_short(self, db_path):
        """short 포지션은 트레일링 스톱 체크하지 않음."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         direction="short", high_water_mark=120.0)
        _insert_price(db_path, ticker="AAPL", close=96.0)

        from nuri.trading.execution.trailing import check_trailing_stop_signals
        signals = check_trailing_stop_signals(db_path=db_path)
        assert signals == []

    def test_no_signal_without_hwm(self, db_path):
        """HWM 없으면 시그널 발생하지 않음 (HWM 갱신 후에도)."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0)
        # 현재가 = 진입가 → HWM 100, drop 0% → 시그널 없음
        _insert_price(db_path, ticker="AAPL", close=100.0)

        from nuri.trading.execution.trailing import check_trailing_stop_signals
        signals = check_trailing_stop_signals(db_path=db_path)
        assert signals == []

    def test_threshold_varies_by_stock_type(self, db_path):
        """종목 유형별 트레일링 스톱 임계값 확인."""
        from nuri.trading.execution.trailing import _get_trailing_threshold
        assert _get_trailing_threshold("growth") == -15
        assert _get_trailing_threshold("value") == -15
        assert _get_trailing_threshold("swing") == -20


class TestRunTrailingStopCheck:
    """일일 트레일링 스톱 파이프라인 테스트."""

    def test_empty_result(self, db_path):
        from nuri.trading.execution.trailing import run_trailing_stop_check
        result = run_trailing_stop_check(db_path=db_path)
        assert result["hwm_updated"] == 0
        assert result["signals"] == []
        assert result["total_checked"] == 0

    def test_full_pipeline(self, db_path):
        """HWM 갱신 + 트레일링 스톱 체크 통합."""
        _insert_position(db_path, ticker="AAPL", entry_price=100.0,
                         high_water_mark=120.0)
        _insert_price(db_path, ticker="AAPL", close=95.0)  # -20.8% from HWM

        from nuri.trading.execution.trailing import run_trailing_stop_check
        result = run_trailing_stop_check(db_path=db_path)
        assert result["total_checked"] == 1
        assert len(result["signals"]) == 1

    def test_print_signals(self, db_path, capsys):
        """출력 포맷 확인."""
        from nuri.trading.execution.trailing import (
            TrailingStopSignal,
            print_trailing_stop_signals,
        )
        signals = [
            TrailingStopSignal(
                ticker="AAPL", position_id=1, direction="SELL",
                high_water_mark=120.0, current_price=100.0,
                drop_pct=-16.7, threshold_pct=-15,
                stock_type="growth", note="트레일링 스톱 발동",
            ),
        ]
        print_trailing_stop_signals(signals)
        output = capsys.readouterr().out
        assert "AAPL" in output
        assert "Trailing" in output

    def test_print_empty_signals(self, capsys):
        from nuri.trading.execution.trailing import print_trailing_stop_signals
        print_trailing_stop_signals([])
        output = capsys.readouterr().out
        assert "없음" in output


# ═══════════════════════════════════════════════════════
# Task 3: VIX 25-30 반포지션
# ═══════════════════════════════════════════════════════

class TestVixHalfPosition:
    """VIX 25-30 구간에서 BUY 후보 반포지션 처리."""

    @pytest.fixture
    def market_data(self, db_path):
        """시장 데이터 + 포트폴리오 설정."""
        with get_db(db_path) as conn:
            conn.executemany(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [("test", "TEST1", 100, 50.0, "USD", "Technology")],
            )

        # 60일 가격 데이터 (충분한 기간)
        dates = pd.bdate_range("2025-01-01", periods=60)
        close = np.linspace(100, 70, 30).tolist() + np.linspace(70, 110, 30).tolist()

        df = pd.DataFrame({
            "ticker": "TEST1",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": [c * 0.99 for c in close],
            "high": [c * 1.02 for c in close],
            "low": [c * 0.98 for c in close],
            "close": close,
            "volume": [1000000] * 60,
            "adj_close": close,
        })
        upsert_prices(df, db_path)
        return db_path

    def test_half_position_flag_on_caution(self, market_data):
        """VIX 25-30이면 BUY 후보에 half_position=True 설정."""
        from nuri.core.db import upsert_macro
        # VIX를 27로 설정
        upsert_macro([{"indicator": "vix", "date": "2025-03-20", "value": 27.0, "source": "test"}],
                     db_path=market_data)

        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=30, db_path=market_data)

        buy_candidates = [c for c in candidates if c.direction == "BUY"]
        for c in buy_candidates:
            assert c.half_position is True
            assert "반포지션" in c.notes

    def test_no_half_position_normal(self, market_data):
        """VIX < 25이면 half_position=False."""
        from nuri.core.db import upsert_macro
        upsert_macro([{"indicator": "vix", "date": "2025-03-20", "value": 18.0, "source": "test"}],
                     db_path=market_data)

        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=30, db_path=market_data)

        buy_candidates = [c for c in candidates if c.direction == "BUY"]
        for c in buy_candidates:
            assert c.half_position is False

    def test_confidence_halved_on_caution(self, market_data):
        """VIX 25-30이면 BUY 후보 confidence 절반."""
        from nuri.core.db import upsert_macro

        # 정상 VIX에서 confidence 측정
        upsert_macro([{"indicator": "vix", "date": "2025-03-20", "value": 18.0, "source": "test"}],
                     db_path=market_data)
        from nuri.trading.recommend.candidates import screen_candidates
        normal = screen_candidates(lookback_days=30, db_path=market_data)
        normal_buys = {c.signal_id: c.confidence for c in normal
                       if c.direction == "BUY" and c.ticker == "TEST1"}

        # VIX 27에서 confidence 측정
        upsert_macro([{"indicator": "vix", "date": "2025-03-20", "value": 27.0, "source": "test"}],
                     db_path=market_data)
        caution = screen_candidates(lookback_days=30, db_path=market_data)
        caution_buys = {c.signal_id: c.confidence for c in caution
                        if c.direction == "BUY" and c.ticker == "TEST1"}

        # 겹치는 시그널에서 confidence 비교
        for sig_id in set(normal_buys) & set(caution_buys):
            if normal_buys[sig_id] > 0:
                ratio = caution_buys[sig_id] / normal_buys[sig_id]
                assert abs(ratio - 0.5) < 0.01, (
                    f"{sig_id}: normal={normal_buys[sig_id]}, caution={caution_buys[sig_id]}"
                )

    def test_sell_not_affected(self, market_data):
        """VIX 25-30이어도 SELL 후보는 영향 없음."""
        from nuri.core.db import upsert_macro
        upsert_macro([{"indicator": "vix", "date": "2025-03-20", "value": 27.0, "source": "test"}],
                     db_path=market_data)

        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=30, db_path=market_data)

        sell_candidates = [c for c in candidates if c.direction == "SELL"]
        for c in sell_candidates:
            assert c.half_position is False

    def test_candidate_has_half_position_field(self):
        """Candidate 데이터클래스에 half_position 필드 존재."""
        from nuri.trading.recommend.candidates import Candidate
        c = Candidate(
            ticker="TEST", signal_id="rsi_oversold", signal_date="2025-01-01",
            direction="BUY", confidence=50, win_rate=0.5, profit_factor=1.5,
            regime_fit=True, price=100.0, notes="test",
        )
        assert c.half_position is False  # 기본값


# ═══════════════════════════════════════════════════════
# Task 4: 매도 우선순위 자동 정렬
# ═══════════════════════════════════════════════════════

class TestSellPrioritySort:
    """rebalance_advisor 출력이 rules.yaml 매도 우선순위를 따르는지 검증."""

    def test_priority_order_from_rules(self):
        """SELL_PRIORITY 순서 확인."""
        from nuri.core.rules import SELL_PRIORITY
        assert SELL_PRIORITY == [
            "leverage_etf",
            "stop_loss_exceeded",
            "no_superinvestor",
            "position_limit_exceeded",
            "sector_limit_exceeded",
        ]

    def test_priority_map_values(self):
        """_PRIORITY_MAP이 올바른 우선순위 번호를 가짐."""
        from nuri.analysis.rebalance_advisor import _PRIORITY_MAP
        assert _PRIORITY_MAP["leverage_etf"] == 1
        assert _PRIORITY_MAP["stop_loss_exceeded"] == 2
        assert _PRIORITY_MAP["no_superinvestor"] == 3
        assert _PRIORITY_MAP["position_limit_exceeded"] == 4
        assert _PRIORITY_MAP["sector_limit_exceeded"] == 5

    def test_violations_have_priority_field(self, db_path, monkeypatch):
        """detect_violations 결과에 priority 필드 존재."""
        # 분석 함수 mock
        import nuri.analysis.rebalance_advisor as ra

        mock_df = pd.DataFrame([{
            "ticker": "TQQQ", "account": "test", "quantity": 10,
            "current_price": 50.0, "pnl_pct": 5.0,
            "current_value_usd": 500.0, "sector": "ETF",
            "currency": "USD", "weight_pct": 5.0,
        }])
        mock_df.attrs["total_value_usd"] = 10000.0
        monkeypatch.setattr(ra, "analyze_portfolio", lambda: mock_df)

        violations = ra.detect_violations(db_path)
        for v in violations:
            assert "priority" in v
            assert isinstance(v["priority"], int)
            assert v["priority"] >= 1

    def test_leverage_etf_has_priority_1(self, db_path, monkeypatch):
        """레버리지 ETF 위반은 priority 1."""
        import nuri.analysis.rebalance_advisor as ra

        mock_df = pd.DataFrame([{
            "ticker": "TQQQ", "account": "test", "quantity": 10,
            "current_price": 50.0, "pnl_pct": 5.0,
            "current_value_usd": 500.0, "sector": "ETF",
            "currency": "USD", "weight_pct": 5.0,
        }])
        mock_df.attrs["total_value_usd"] = 10000.0
        monkeypatch.setattr(ra, "analyze_portfolio", lambda: mock_df)

        violations = ra.detect_violations(db_path)
        leverage_violations = [v for v in violations if v["violation_type"] == "leverage_etf"]
        assert len(leverage_violations) == 1
        assert leverage_violations[0]["priority"] == 1

    def test_stop_loss_has_priority_2(self, db_path, monkeypatch):
        """손절선 초과 위반은 priority 2."""
        import nuri.analysis.rebalance_advisor as ra

        mock_df = pd.DataFrame([{
            "ticker": "BAD_STOCK", "account": "test", "quantity": 100,
            "current_price": 50.0, "pnl_pct": -15.0,
            "current_value_usd": 5000.0, "sector": "Technology",
            "currency": "USD", "weight_pct": 10.0,
        }])
        mock_df.attrs["total_value_usd"] = 50000.0
        monkeypatch.setattr(ra, "analyze_portfolio", lambda: mock_df)

        violations = ra.detect_violations(db_path)
        sl_violations = [v for v in violations if v["violation_type"] == "stop_loss_exceeded"]
        assert len(sl_violations) == 1
        assert sl_violations[0]["priority"] == 2

    def test_violations_sorted_by_priority(self, db_path, monkeypatch):
        """calculate_rebalance_actions 결과가 SELL_PRIORITY 순서로 정렬."""
        import nuri.analysis.rebalance_advisor as ra

        # 레버리지 ETF + 손절선 위반 + 비중 초과
        mock_df = pd.DataFrame([
            {
                "ticker": "TQQQ", "account": "test", "quantity": 10,
                "current_price": 50.0, "pnl_pct": 5.0,
                "current_value_usd": 500.0, "sector": "ETF",
                "currency": "USD", "weight_pct": 5.0,
            },
            {
                "ticker": "BAD_STOCK", "account": "test", "quantity": 100,
                "current_price": 50.0, "pnl_pct": -15.0,
                "current_value_usd": 5000.0, "sector": "Technology",
                "currency": "USD", "weight_pct": 10.0,
            },
            {
                "ticker": "BIG_POS", "account": "test", "quantity": 500,
                "current_price": 100.0, "pnl_pct": 20.0,
                "current_value_usd": 50000.0, "sector": "Technology",
                "currency": "USD", "weight_pct": 50.0,
            },
        ])
        mock_df.attrs["total_value_usd"] = 55500.0
        monkeypatch.setattr(ra, "analyze_portfolio", lambda: mock_df)

        actions = ra.calculate_rebalance_actions(db_path)
        if len(actions) >= 2:
            for i in range(len(actions) - 1):
                # 같은 우선순위 내에서는 current_value 절대값으로 정렬
                a, b = actions[i], actions[i + 1]
                from nuri.core.rules import SELL_PRIORITY
                order = {cat: idx for idx, cat in enumerate(SELL_PRIORITY)}
                assert order.get(a["violation_type"], 99) <= order.get(b["violation_type"], 99)

    def test_print_shows_priority(self, capsys, monkeypatch):
        """print_rebalance_advisor 출력에 priority 표시."""
        from nuri.analysis.rebalance_advisor import print_rebalance_advisor
        actions = [
            {
                "ticker": "TQQQ",
                "violation_type": "leverage_etf",
                "priority": 1,
                "current_value": 5.0,
                "limit_value": 0,
                "severity": "critical",
                "action": "SELL_ALL",
                "sell_shares": 10,
                "sell_value_usd": 500.0,
                "reason": "레버리지 ETF 금지",
                "cumulative_recovery_usd": 500.0,
            },
            {
                "ticker": "BAD",
                "violation_type": "stop_loss_exceeded",
                "priority": 2,
                "current_value": -15.0,
                "limit_value": -7,
                "severity": "high",
                "action": "SELL_ALL",
                "sell_shares": 100,
                "sell_value_usd": 5000.0,
                "reason": "손절 -15% 초과 (한도 -7%)",
                "cumulative_recovery_usd": 5500.0,
            },
        ]
        print_rebalance_advisor(actions)
        output = capsys.readouterr().out
        # 우선순위 표시 확인
        assert "[P1]" in output
        assert "[P2]" in output
        assert "레버리지 ETF" in output
        assert "손절선 초과" in output
