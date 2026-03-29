"""확장 시그널 테스트 — volume_spike, gap_up, gap_down + 매크로/데이터 시그널."""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_prices


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


# ═══════════════════════════════════════════════════════
# Step 1: 가격 기반 시그널
# ═══════════════════════════════════════════════════════


@pytest.fixture
def volume_spike_prices(db_path):
    """거래량 급증 테스트용 데이터 — 40일째에 volume 4x spike."""
    dates = pd.date_range("2025-01-01", periods=60)
    close = np.linspace(100, 120, 60) + np.random.normal(0, 0.3, 60)
    volume = np.full(60, 1_000_000, dtype=float)
    # 40일째에 거래량 4배 급증
    volume[40] = 4_000_000

    df = pd.DataFrame({
        "ticker": "VSPK",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.999,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": volume,
        "adj_close": close,
    })
    upsert_prices(df, db_path)
    return db_path


@pytest.fixture
def gap_prices(db_path):
    """갭 상승/하락 테스트용 데이터.

    - 30일째: 갭 상승 (open = prev close * 1.05)
    - 45일째: 갭 하락 (open = prev close * 0.95)
    """
    dates = pd.date_range("2025-01-01", periods=80)
    close = np.linspace(100, 110, 80).copy()
    open_prices = close * 0.999  # 기본: open ≈ close

    # 30일째: 갭 상승
    open_prices[30] = close[29] * 1.05
    close[30] = close[29] * 1.04  # 갭 후 살짝 빠짐

    # 45일째: 갭 하락
    open_prices[45] = close[44] * 0.95
    close[45] = close[44] * 0.96  # 갭 후 추가 하락

    df = pd.DataFrame({
        "ticker": "GAPTEST",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": open_prices,
        "high": np.maximum(close, open_prices) * 1.01,
        "low": np.minimum(close, open_prices) * 0.99,
        "close": close,
        "volume": [1_000_000] * 80,
        "adj_close": close,
    })
    upsert_prices(df, db_path)
    return db_path


class TestVolumeSpikeSignal:

    def test_volume_spike_detection(self, volume_spike_prices):
        """거래량 3배 초과 시 volume_spike 시그널 감지."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(
            ticker="VSPK", signals=["volume_spike"], db_path=volume_spike_prices
        )
        assert len(results) >= 1, "volume_spike 시그널이 감지되어야 함"
        assert results[0].signal_id == "volume_spike"
        assert results[0].holding_days == 10

    def test_volume_spike_not_triggered_on_normal(self, volume_spike_prices):
        """일반 거래량에서는 volume_spike 미발생."""
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import (
            _compute_indicators,
            _detect_signal_entries,
        )

        df = query_df(
            "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ? ORDER BY date",
            ("VSPK",), db_path=volume_spike_prices,
        )
        df["date"] = pd.to_datetime(df["date"])
        df = df.reset_index(drop=True)
        df = _compute_indicators(df)
        entries = _detect_signal_entries(df, "volume_spike")
        # 40일째만 spike (volume=4M, avg=1M → 4x > 3x threshold)
        for idx in entries:
            vol = df["volume"].iloc[idx]
            vol_avg = df["volume_sma_20"].iloc[idx]
            assert vol > vol_avg * 3


class TestGapSignals:

    def test_gap_up_detection(self, gap_prices):
        """2%+ 갭 상승 감지."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(
            ticker="GAPTEST", signals=["gap_up"], db_path=gap_prices
        )
        assert len(results) >= 1, "gap_up 시그널이 감지되어야 함"
        assert results[0].signal_id == "gap_up"
        assert results[0].holding_days == 10

    def test_gap_down_detection(self, gap_prices):
        """2%+ 갭 하락 감지."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(
            ticker="GAPTEST", signals=["gap_down"], db_path=gap_prices
        )
        assert len(results) >= 1, "gap_down 시그널이 감지되어야 함"
        assert results[0].signal_id == "gap_down"
        assert results[0].holding_days == 10

    def test_gap_signals_no_false_positive(self, gap_prices):
        """1% 미만 갭에서는 시그널 미발생."""
        from nuri.core.db import query_df
        from nuri.quant.validation.signal_backtest import (
            _compute_indicators,
            _detect_signal_entries,
        )

        df = query_df(
            "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ? ORDER BY date",
            ("GAPTEST",), db_path=gap_prices,
        )
        df["date"] = pd.to_datetime(df["date"])
        df = df.reset_index(drop=True)
        df = _compute_indicators(df)

        gap_up_entries = _detect_signal_entries(df, "gap_up")
        gap_down_entries = _detect_signal_entries(df, "gap_down")
        # 갭 상승/하락은 각각 특정 날짜에서만 발동
        for idx in gap_up_entries:
            assert df["open"].iloc[idx] > df["close"].iloc[idx - 1] * 1.02
        for idx in gap_down_entries:
            assert df["open"].iloc[idx] < df["close"].iloc[idx - 1] * 0.98


class TestSignalDefinitions:

    def test_new_signals_in_definitions(self):
        """확장 시그널이 SIGNAL_DEFINITIONS에 등록됨."""
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        assert "volume_spike" in SIGNAL_DEFINITIONS
        assert "gap_up" in SIGNAL_DEFINITIONS
        assert "gap_down" in SIGNAL_DEFINITIONS
        assert SIGNAL_DEFINITIONS["volume_spike"]["hold_days"] == 10
        assert SIGNAL_DEFINITIONS["gap_up"]["hold_days"] == 10
        assert SIGNAL_DEFINITIONS["gap_down"]["hold_days"] == 10

    def test_buy_sell_classification(self):
        """BUY/SELL 분류 업데이트 확인."""
        from nuri.trading.recommend.candidates import BUY_SIGNALS, SELL_SIGNALS
        assert "volume_spike" in BUY_SIGNALS
        assert "gap_up" in BUY_SIGNALS
        assert "gap_down" in SELL_SIGNALS

    def test_original_7_signals_unchanged(self):
        """기존 7개 시그널 정의 무변경."""
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        original = ["rsi_oversold", "rsi_overbought", "macd_golden", "macd_dead",
                     "sma_golden", "sma_dead", "bb_bounce"]
        for sig_id in original:
            assert sig_id in SIGNAL_DEFINITIONS
        assert SIGNAL_DEFINITIONS["rsi_oversold"]["hold_days"] == 20
        assert SIGNAL_DEFINITIONS["macd_golden"]["hold_days"] is None
        assert SIGNAL_DEFINITIONS["sma_golden"]["hold_days"] is None

    def test_macro_signals_in_definitions(self):
        """매크로 시그널이 SIGNAL_DEFINITIONS에 등록됨."""
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        assert "vix_reversal" in SIGNAL_DEFINITIONS
        assert "pcr_reversal" in SIGNAL_DEFINITIONS
        assert "yield_curve_recovery" in SIGNAL_DEFINITIONS
        assert SIGNAL_DEFINITIONS["vix_reversal"]["hold_days"] == 20
        assert SIGNAL_DEFINITIONS["pcr_reversal"]["hold_days"] == 15
        assert SIGNAL_DEFINITIONS["yield_curve_recovery"]["hold_days"] is None

    def test_macro_signals_in_buy_classification(self):
        """매크로 시그널이 BUY_SIGNALS에 포함."""
        from nuri.trading.recommend.candidates import BUY_SIGNALS
        assert "vix_reversal" in BUY_SIGNALS
        assert "pcr_reversal" in BUY_SIGNALS
        assert "yield_curve_recovery" in BUY_SIGNALS


# ═══════════════════════════════════════════════════════
# Step 2: 매크로 기반 시그널
# ═══════════════════════════════════════════════════════


@pytest.fixture
def vix_reversal_data(db_path):
    """VIX 반전 테스트 데이터: 30+ 3일 → 25 이하."""
    dates = pd.date_range("2025-01-01", periods=60)
    close = np.linspace(100, 120, 60)
    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.999, "high": close * 1.01,
        "low": close * 0.99, "close": close,
        "volume": [1_000_000] * 60, "adj_close": close,
    })
    upsert_prices(df, db_path)

    # VIX: 20일까지 정상, 21-23일 35(3일 연속 30+), 24일 24(25 이하)
    macro_records = []
    for i, d in enumerate(dates):
        if 21 <= i <= 23:
            vix = 35.0
        elif i == 24:
            vix = 24.0
        else:
            vix = 18.0
        macro_records.append({"indicator": "vix", "date": d.strftime("%Y-%m-%d"), "value": vix, "source": "test"})
    upsert_macro(macro_records, db_path)
    return db_path


@pytest.fixture
def pcr_reversal_data(db_path):
    """PCR 반전 테스트 데이터: 1.2+ → 0.8 이하."""
    dates = pd.date_range("2025-01-01", periods=60)
    close = np.linspace(100, 115, 60)
    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.999, "high": close * 1.01,
        "low": close * 0.99, "close": close,
        "volume": [1_000_000] * 60, "adj_close": close,
    })
    upsert_prices(df, db_path)

    # PCR: 30일째 1.3(고점), 40일째 0.7(저점)
    macro_records = []
    for i, d in enumerate(dates):
        if i == 30:
            pcr = 1.3
        elif i == 40:
            pcr = 0.7
        elif i < 30:
            pcr = 0.9
        else:
            pcr = 0.9 - (i - 30) * 0.02  # 서서히 하락
        macro_records.append({"indicator": "put_call_ratio", "date": d.strftime("%Y-%m-%d"), "value": pcr, "source": "test"})
    upsert_macro(macro_records, db_path)
    return db_path


@pytest.fixture
def yield_curve_data(db_path):
    """수익률곡선 정상화 테스트: 역전(음수) → 정상(양수)."""
    dates = pd.date_range("2025-01-01", periods=60)
    close = np.linspace(100, 115, 60)
    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.999, "high": close * 1.01,
        "low": close * 0.99, "close": close,
        "volume": [1_000_000] * 60, "adj_close": close,
    })
    upsert_prices(df, db_path)

    macro_records = []
    for i, d in enumerate(dates):
        date_str = d.strftime("%Y-%m-%d")
        # 3M yield: 5.0% 고정
        macro_records.append({"indicator": "us_3m_yield", "date": date_str, "value": 5.0, "source": "test"})
        # 10Y yield: ~30일 4.5%(역전) → 31~49일 5.2%(정상화) → 50일~ 4.5%(재역전=청산)
        if i <= 30:
            yield_10y = 4.5
        elif i <= 49:
            yield_10y = 5.2
        else:
            yield_10y = 4.5
        macro_records.append({"indicator": "us_10y_yield", "date": date_str, "value": yield_10y, "source": "test"})
    upsert_macro(macro_records, db_path)
    return db_path


class TestVixReversal:

    def test_vix_reversal_detection(self, vix_reversal_data):
        """VIX 30+ 3일 연속 후 25 이하에서 시그널 발동."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(
            ticker="SPY", signals=["vix_reversal"], db_path=vix_reversal_data
        )
        assert len(results) >= 1, "vix_reversal 시그널이 감지되어야 함"
        assert results[0].signal_id == "vix_reversal"
        assert results[0].holding_days == 20

    def test_vix_reversal_no_false_positive_1day(self, db_path):
        """VIX 30+ 1일만이면 시그널 미발동 (3일 연속 필요)."""
        dates = pd.date_range("2025-01-01", periods=60)
        close = np.linspace(100, 120, 60)
        df = pd.DataFrame({
            "ticker": "TEST1D",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.01,
            "low": close * 0.99, "close": close,
            "volume": [1_000_000] * 60, "adj_close": close,
        })
        upsert_prices(df, db_path)

        # VIX: 21일만 35, 22일 24 (1일만 30+)
        macro_records = []
        for i, d in enumerate(dates):
            vix = 35.0 if i == 21 else (24.0 if i == 22 else 18.0)
            macro_records.append({"indicator": "vix", "date": d.strftime("%Y-%m-%d"), "value": vix, "source": "test"})
        upsert_macro(macro_records, db_path)

        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(ticker="TEST1D", signals=["vix_reversal"], db_path=db_path)
        assert len(results) == 0, "1일만 30+이면 vix_reversal 미발동"


class TestPcrReversal:

    def test_pcr_reversal_detection(self, pcr_reversal_data):
        """PCR 1.2+ → 0.8 이하 전환 시 시그널 발동."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(
            ticker="SPY", signals=["pcr_reversal"], db_path=pcr_reversal_data
        )
        assert len(results) >= 1, "pcr_reversal 시그널이 감지되어야 함"
        assert results[0].signal_id == "pcr_reversal"
        assert results[0].holding_days == 15


class TestYieldCurveRecovery:

    def test_yield_curve_recovery_detection(self, yield_curve_data):
        """수익률곡선 역전 → 정상화 시 시그널 발동."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(
            ticker="SPY", signals=["yield_curve_recovery"], db_path=yield_curve_data
        )
        assert len(results) >= 1, "yield_curve_recovery 시그널이 감지되어야 함"
        assert results[0].signal_id == "yield_curve_recovery"

    def test_graceful_skip_no_macro_data(self, db_path):
        """매크로 데이터 없으면 에러 없이 빈 결과."""
        dates = pd.date_range("2025-01-01", periods=60)
        close = np.linspace(100, 120, 60)
        df = pd.DataFrame({
            "ticker": "NOMACRO",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.01,
            "low": close * 0.99, "close": close,
            "volume": [1_000_000] * 60, "adj_close": close,
        })
        upsert_prices(df, db_path)

        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(
            ticker="NOMACRO", signals=["vix_reversal", "pcr_reversal", "yield_curve_recovery"],
            db_path=db_path,
        )
        assert results == [], "매크로 데이터 없으면 graceful skip"


# ═══════════════════════════════════════════════════════
# Step 3: 데이터 의존 시그널
# ═══════════════════════════════════════════════════════


@pytest.fixture
def insider_cluster_data(db_path):
    """내부자 집중 매수 테스트: 30~35일에 4건 매수 클러스터."""
    dates = pd.date_range("2025-01-01", periods=60)
    close = np.linspace(100, 115, 60)
    df = pd.DataFrame({
        "ticker": "INSD",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.999, "high": close * 1.01,
        "low": close * 0.99, "close": close,
        "volume": [1_000_000] * 60, "adj_close": close,
    })
    upsert_prices(df, db_path)

    # insider_trades: 30, 32, 33, 35일에 Purchase
    with get_db(db_path) as conn:
        for day_offset in [30, 32, 33, 35]:
            conn.execute(
                "INSERT OR REPLACE INTO insider_trades (ticker, date, insider_name, position, transaction_type, shares, value) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("INSD", dates[day_offset].strftime("%Y-%m-%d"), f"Insider{day_offset}", "CEO", "P-Purchase", 1000, 100000),
            )
    return db_path


@pytest.fixture
def short_squeeze_data(db_path):
    """숏 스퀴즈 테스트: short_interest 15% + 3일 연속 상승."""
    dates = pd.date_range("2025-01-01", periods=60)
    # 30일부터 가격 연속 상승
    close = np.concatenate([
        np.linspace(100, 95, 30),     # 하락
        np.linspace(95, 110, 30),     # 상승
    ])
    df = pd.DataFrame({
        "ticker": "SQZZ",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.999, "high": close * 1.01,
        "low": close * 0.99, "close": close,
        "volume": [1_000_000] * 60, "adj_close": close,
    })
    upsert_prices(df, db_path)

    # external_analysis: short_interest 15%
    with get_db(db_path) as conn:
        for i, d in enumerate(dates):
            conn.execute(
                "INSERT OR REPLACE INTO external_analysis (date, source, ticker, data_type, value, numeric_value, collected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (d.strftime("%Y-%m-%d"), "shortinterest", "SQZZ", "short_interest", "15%", 15.0, "2025-01-01"),
            )
    return db_path


class TestInsiderCluster:

    def test_insider_cluster_detection(self, insider_cluster_data):
        """10일 내 3건+ 매수 시 insider_cluster 시그널 발동."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(
            ticker="INSD", signals=["insider_cluster"], db_path=insider_cluster_data
        )
        assert len(results) >= 1, "insider_cluster 시그널이 감지되어야 함"
        assert results[0].signal_id == "insider_cluster"
        assert results[0].holding_days == 20

    def test_insider_cluster_no_data_graceful(self, db_path):
        """insider_trades 데이터 없으면 에러 없이 빈 결과."""
        dates = pd.date_range("2025-01-01", periods=60)
        close = np.linspace(100, 115, 60)
        df = pd.DataFrame({
            "ticker": "NOINSD",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.01,
            "low": close * 0.99, "close": close,
            "volume": [1_000_000] * 60, "adj_close": close,
        })
        upsert_prices(df, db_path)

        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(
            ticker="NOINSD", signals=["insider_cluster"], db_path=db_path
        )
        assert results == []


class TestShortSqueeze:

    def test_short_squeeze_detection(self, short_squeeze_data):
        """short_interest 10%+ AND 3일 연속 상승 시 시그널 발동."""
        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(
            ticker="SQZZ", signals=["short_squeeze"], db_path=short_squeeze_data
        )
        assert len(results) >= 1, "short_squeeze 시그널이 감지되어야 함"
        assert results[0].signal_id == "short_squeeze"
        assert results[0].holding_days == 15

    def test_short_squeeze_no_data_graceful(self, db_path):
        """short_interest 데이터 없으면 에러 없이 빈 결과."""
        dates = pd.date_range("2025-01-01", periods=60)
        close = np.linspace(100, 115, 60)
        df = pd.DataFrame({
            "ticker": "NOSI",
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.999, "high": close * 1.01,
            "low": close * 0.99, "close": close,
            "volume": [1_000_000] * 60, "adj_close": close,
        })
        upsert_prices(df, db_path)

        from nuri.quant.validation.signal_backtest import backtest_signals
        results = backtest_signals(
            ticker="NOSI", signals=["short_squeeze"], db_path=db_path
        )
        assert results == []


class TestAllSignalCount:

    def test_total_signal_count_is_15(self):
        """전체 시그널 수가 15개인지 확인."""
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        assert len(SIGNAL_DEFINITIONS) == 15
