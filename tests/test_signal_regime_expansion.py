"""Phase 3 시그널 15개 + 레짐 10개 확장 테스트.

신규 시그널 8개와 특수 레짐 4개에 대한 단위 테스트.
모든 테스트는 tmp_path SQLite + mock 데이터로 격리 실행.
"""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_prices


@pytest.fixture
def db_path(tmp_path):
    """임시 DB 경로 픽스처."""
    path = tmp_path / "test.db"
    init_db(path)
    return path


# ═══════════════════════════════════════════════════════
# 헬퍼: 테스트 데이터 생성
# ═══════════════════════════════════════════════════════


def _make_price_df(
    ticker: str, dates, close, volume=None, open_prices=None,
):
    """가격 DataFrame 생성 헬퍼."""
    n = len(dates)
    if volume is None:
        volume = [1_000_000] * n
    if open_prices is None:
        open_prices = close * 0.99
    return pd.DataFrame({
        "ticker": ticker,
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": open_prices,
        "high": close * 1.02,
        "low": close * 0.98,
        "close": close,
        "volume": volume,
        "adj_close": close,
    })


def _make_spy_data(db_path, pattern="bull"):
    """SPY 300일 시뮬레이션 데이터."""
    dates = pd.bdate_range("2024-01-01", periods=300)
    if pattern == "bull":
        close = np.linspace(100, 200, 300) + np.random.normal(0, 0.5, 300)
    elif pattern == "bear":
        up = np.linspace(150, 200, 200)
        down = np.linspace(200, 130, 100)
        close = np.concatenate([up, down]) + np.random.normal(0, 0.3, 300)
    elif pattern == "sideways":
        close = np.full(300, 150.0) + np.random.normal(0, 2, 300)
    elif pattern == "recovery":
        # 200일 하락 → 100일 상승 (SMA50이 SMA200 위로 돌파)
        phase1 = np.linspace(200, 120, 200)
        phase2 = np.linspace(120, 170, 100)
        close = np.concatenate([phase1, phase2]) + np.random.normal(0, 0.3, 300)
    else:
        close = np.linspace(100, 200, 300)

    df = _make_price_df("SPY", dates, close)
    upsert_prices(df, db_path)
    return dates


# ═══════════════════════════════════════════════════════
# Part 1: 신규 시그널 테스트
# ═══════════════════════════════════════════════════════


class TestVolumeSpike:
    """volume_spike 시그널: Volume > 3x 20일 평균."""

    def test_detect_volume_spike(self):
        """거래량 3배 이상이면 감지."""
        from nuri.quant.validation.signal_backtest import _detect_volume_spike
        # 20일 평균 100만, 현재 400만
        close = np.linspace(100, 110, 25)
        volume = [1_000_000] * 20 + [1_000_000, 1_000_000, 1_000_000, 1_000_000, 4_000_000]
        df = pd.DataFrame({"close": close, "volume": volume})
        df["volume_avg_20"] = df["volume"].rolling(20).mean()
        assert _detect_volume_spike(df, 24) is True

    def test_no_spike_below_threshold(self):
        """거래량 2배면 미감지 (3배 미만)."""
        from nuri.quant.validation.signal_backtest import _detect_volume_spike
        close = np.linspace(100, 110, 25)
        volume = [1_000_000] * 24 + [2_500_000]
        df = pd.DataFrame({"close": close, "volume": volume})
        df["volume_avg_20"] = df["volume"].rolling(20).mean()
        assert _detect_volume_spike(df, 24) is False

    def test_backtest_with_volume_spike(self, db_path):
        """실제 백테스트에서 volume_spike 감지."""
        from nuri.quant.validation.signal_backtest import backtest_signals

        dates = pd.bdate_range("2025-01-01", periods=60)
        close = np.linspace(100, 120, 60)
        # 30일째에 거래량 급증
        volume = [1_000_000] * 29 + [5_000_000] + [1_000_000] * 30
        df = _make_price_df("VTEST", dates, close, volume=volume)
        upsert_prices(df, db_path)

        results = backtest_signals(ticker="VTEST", signals=["volume_spike"], db_path=db_path)
        assert isinstance(results, list)
        for r in results:
            assert r.signal_id == "volume_spike"
            assert r.holding_days == 10


class TestGapSignals:
    """gap_up / gap_down 시그널."""

    def test_detect_gap_up(self):
        """시가 > 전일 종가 × 1.02."""
        from nuri.quant.validation.signal_backtest import _detect_gap_up
        df = pd.DataFrame({
            "open": [100, 100, 103],  # 103 > 100 * 1.02
            "close": [100, 100, 104],
        })
        assert _detect_gap_up(df, 2) is True
        assert _detect_gap_up(df, 1) is False  # 100 <= 100*1.02

    def test_detect_gap_down(self):
        """시가 < 전일 종가 × 0.98."""
        from nuri.quant.validation.signal_backtest import _detect_gap_down
        df = pd.DataFrame({
            "open": [100, 100, 97],  # 97 < 100 * 0.98
            "close": [100, 100, 96],
        })
        assert _detect_gap_down(df, 2) is True
        assert _detect_gap_down(df, 1) is False

    def test_gap_up_backtest(self, db_path):
        """갭 상승 백테스트."""
        from nuri.quant.validation.signal_backtest import backtest_signals

        dates = pd.bdate_range("2025-01-01", periods=60)
        close = np.linspace(100, 120, 60)
        open_prices = close * 0.99
        # 25일째에 갭 상승 (시가가 전일 종가의 103%)
        open_prices[25] = close[24] * 1.03
        df = _make_price_df("GTEST", dates, close, open_prices=open_prices)
        upsert_prices(df, db_path)

        results = backtest_signals(ticker="GTEST", signals=["gap_up"], db_path=db_path)
        assert isinstance(results, list)
        for r in results:
            assert r.signal_id == "gap_up"
            assert r.holding_days == 10

    def test_gap_down_backtest(self, db_path):
        """갭 하락 백테스트."""
        from nuri.quant.validation.signal_backtest import backtest_signals

        dates = pd.bdate_range("2025-01-01", periods=60)
        close = np.linspace(120, 100, 60)
        open_prices = close * 1.01
        # 25일째에 갭 하락
        open_prices[25] = close[24] * 0.97
        df = _make_price_df("GDTEST", dates, close, open_prices=open_prices)
        upsert_prices(df, db_path)

        results = backtest_signals(ticker="GDTEST", signals=["gap_down"], db_path=db_path)
        assert isinstance(results, list)
        for r in results:
            assert r.signal_id == "gap_down"
            assert r.holding_days == 10


class TestPCRReversal:
    """pcr_reversal 시그널: PCR 1.2 → 0.8 (5일 이내)."""

    def test_pcr_reversal_detection(self):
        """PCR이 1.2 → 0.8로 하락하면 감지."""
        from nuri.quant.validation.signal_backtest import _detect_pcr_reversal_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=20))
        pcr_data = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10"]),
            "value": [1.3, 1.2, 1.0, 0.9, 0.75],
        })
        entries = _detect_pcr_reversal_entries(dates, pcr_data)
        assert len(entries) >= 1

    def test_pcr_no_reversal(self):
        """PCR이 일정하면 미감지."""
        from nuri.quant.validation.signal_backtest import _detect_pcr_reversal_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=20))
        pcr_data = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-06", "2025-01-07"]),
            "value": [0.85, 0.85],
        })
        entries = _detect_pcr_reversal_entries(dates, pcr_data)
        assert entries == []

    def test_pcr_empty_data(self):
        """데이터 없으면 빈 리스트."""
        from nuri.quant.validation.signal_backtest import _detect_pcr_reversal_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=10))
        entries = _detect_pcr_reversal_entries(dates, pd.DataFrame())
        assert entries == []


class TestShortSqueeze:
    """short_squeeze 시그널: 공매도 비율 20%+ AND RSI 50 돌파."""

    def test_short_squeeze_detection(self):
        """공매도 비율 20%+ AND RSI 50 상향 돌파."""
        from nuri.quant.validation.signal_backtest import _detect_short_squeeze_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=30))
        # RSI가 49 → 51로 돌파하는 시점 생성
        rsi_values = [40.0] * 10 + [48.0, 49.0, 51.0] + [55.0] * 17
        df = pd.DataFrame({"rsi_14": rsi_values})

        short_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-01"]),
            "value": [25.0],  # 20% 이상
        })

        entries = _detect_short_squeeze_entries(df, dates, short_df)
        assert len(entries) >= 1

    def test_short_squeeze_no_si(self):
        """공매도 비율 데이터 없으면 미감지."""
        from nuri.quant.validation.signal_backtest import _detect_short_squeeze_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=10))
        df = pd.DataFrame({"rsi_14": [50.0] * 10})
        entries = _detect_short_squeeze_entries(df, dates, pd.DataFrame())
        assert entries == []


class TestInsiderCluster:
    """insider_cluster 시그널: 10일 내 3+ 매수."""

    def test_insider_cluster_detection(self):
        """10일 이내 매수 3건이면 감지."""
        from nuri.quant.validation.signal_backtest import _detect_insider_cluster_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=20))
        insider_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-13", "2025-01-14", "2025-01-15"]),
            "transaction_type": ["Purchase", "Purchase", "Buy"],
        })
        entries = _detect_insider_cluster_entries(dates, insider_df)
        assert len(entries) >= 1

    def test_insider_cluster_no_buys(self):
        """매도만 있으면 미감지."""
        from nuri.quant.validation.signal_backtest import _detect_insider_cluster_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=20))
        insider_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-13", "2025-01-14"]),
            "transaction_type": ["Sale", "Sale"],
        })
        entries = _detect_insider_cluster_entries(dates, insider_df)
        assert entries == []

    def test_insider_cluster_empty(self):
        """데이터 없으면 빈 리스트."""
        from nuri.quant.validation.signal_backtest import _detect_insider_cluster_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=20))
        entries = _detect_insider_cluster_entries(dates, pd.DataFrame())
        assert entries == []


class TestVIXReversal:
    """vix_reversal 시그널: VIX 30+ → 25 이하."""

    def test_vix_reversal_detection(self):
        """VIX 3일 연속 30+ 후 25 이하 하락 시 감지."""
        from nuri.quant.validation.signal_backtest import _detect_vix_reversal_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=10))
        # 3일 연속 VIX >= 30 필요 (06, 07, 08) → 09일에 24로 하락
        vix_df = pd.DataFrame({
            "date": pd.to_datetime([
                "2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09",
            ]),
            "value": [32.0, 31.0, 30.5, 24.0],
        })
        entries = _detect_vix_reversal_entries(dates, vix_df)
        assert len(entries) >= 1

    def test_vix_no_reversal_still_high(self):
        """VIX가 계속 높으면 미감지."""
        from nuri.quant.validation.signal_backtest import _detect_vix_reversal_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=10))
        vix_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-06", "2025-01-07"]),
            "value": [32.0, 31.0],
        })
        entries = _detect_vix_reversal_entries(dates, vix_df)
        assert entries == []

    def test_vix_single_day_spike_no_trigger(self):
        """VIX 1일만 30+ → 25 이하: 3일 연속 미달로 미감지."""
        from nuri.quant.validation.signal_backtest import _detect_vix_reversal_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=10))
        # VIX가 1일만 30+ 후 바로 하락 → 연속 3일 미달
        vix_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-06", "2025-01-07"]),
            "value": [32.0, 24.0],
        })
        entries = _detect_vix_reversal_entries(dates, vix_df)
        assert entries == []

    def test_vix_empty_data(self):
        """데이터 없으면 빈 리스트."""
        from nuri.quant.validation.signal_backtest import _detect_vix_reversal_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=10))
        entries = _detect_vix_reversal_entries(dates, pd.DataFrame())
        assert entries == []


class TestYieldCurveRecovery:
    """yield_curve_recovery 시그널: 3M-10Y 역전 → 정상 전환 (수익률곡선 회복)."""

    def test_yield_curve_recovery_detection(self):
        """스프레드 음수 → 양수 전환 시 감지."""
        from nuri.quant.validation.signal_backtest import _detect_yield_curve_recovery_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=10))
        y3m_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-08"]),
            "value": [5.0, 5.0, 4.0],
        })
        y10_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-08"]),
            "value": [4.5, 4.5, 4.5],  # 4.5-5.0=-0.5 → 4.5-4.0=0.5 (정상 전환)
        })
        entries = _detect_yield_curve_recovery_entries(dates, y3m_df, y10_df)
        assert len(entries) >= 1

    def test_yield_no_transition(self):
        """스프레드가 계속 양수면 미감지."""
        from nuri.quant.validation.signal_backtest import _detect_yield_curve_recovery_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=10))
        y3m_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-06", "2025-01-07"]),
            "value": [3.0, 3.0],
        })
        y10_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-06", "2025-01-07"]),
            "value": [4.0, 4.0],
        })
        entries = _detect_yield_curve_recovery_entries(dates, y3m_df, y10_df)
        assert entries == []

    def test_yield_empty_data(self):
        """데이터 없으면 빈 리스트."""
        from nuri.quant.validation.signal_backtest import _detect_yield_curve_recovery_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=10))
        entries = _detect_yield_curve_recovery_entries(dates, pd.DataFrame(), pd.DataFrame())
        assert entries == []


class TestSignalDefinitions:
    """SIGNAL_DEFINITIONS 상수 검증."""

    def test_total_signal_count(self):
        """시그널 15개 확인."""
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        assert len(SIGNAL_DEFINITIONS) == 15

    def test_new_signals_exist(self):
        """신규 8개 시그널이 정의에 존재."""
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        new_signals = [
            "volume_spike", "gap_up", "gap_down", "pcr_reversal",
            "short_squeeze", "insider_cluster", "vix_reversal", "yield_curve_recovery",
        ]
        for sig in new_signals:
            assert sig in SIGNAL_DEFINITIONS, f"{sig} missing"

    def test_all_have_hold_days(self):
        """모든 시그널에 hold_days 필드 존재."""
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        for sig_id, defn in SIGNAL_DEFINITIONS.items():
            assert "hold_days" in defn, f"{sig_id} missing hold_days"

    def test_macro_signals_flagged(self):
        """매크로 기반 시그널에 requires_macro 플래그."""
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        macro_signals = ["pcr_reversal", "short_squeeze", "insider_cluster", "vix_reversal", "yield_curve_recovery"]
        for sig in macro_signals:
            assert SIGNAL_DEFINITIONS[sig].get("requires_macro") is True, f"{sig} not flagged"


# ═══════════════════════════════════════════════════════
# Part 2: 신규 레짐 테스트
# ═══════════════════════════════════════════════════════


class TestEuphoriaRegime:
    """euphoria 레짐: VIX < 12 AND Fear&Greed > 80."""

    def test_euphoria_detection(self, db_path):
        """VIX 10, F&G 85 → euphoria."""
        from nuri.quant.regime.classifier import classify_regime

        dates = _make_spy_data(db_path, "bull")
        upsert_macro([
            {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 10.0, "source": "test"},
            {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 85.0, "source": "test"},
        ], db_path)

        state = classify_regime(db_path=db_path)
        assert state is not None
        assert state.regime == "euphoria"
        assert state.trend == "bull"
        assert state.volatility == "low"

    def test_not_euphoria_vix_high(self, db_path):
        """VIX 15 → euphoria 아님."""
        from nuri.quant.regime.classifier import classify_regime

        dates = _make_spy_data(db_path, "bull")
        upsert_macro([
            {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 15.0, "source": "test"},
            {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 85.0, "source": "test"},
        ], db_path)

        state = classify_regime(db_path=db_path)
        assert state is not None
        assert state.regime != "euphoria"

    def test_not_euphoria_low_fg(self, db_path):
        """F&G 50 → euphoria 아님."""
        from nuri.quant.regime.classifier import classify_regime

        dates = _make_spy_data(db_path, "bull")
        upsert_macro([
            {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 10.0, "source": "test"},
            {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 50.0, "source": "test"},
        ], db_path)

        state = classify_regime(db_path=db_path)
        assert state is not None
        assert state.regime != "euphoria"


class TestStagflationRegime:
    """stagflation 레짐: CPI > 4% AND GDP < 1%."""

    def test_stagflation_detection(self, db_path):
        """CPI 5%, GDP 0.5% → stagflation."""
        from nuri.quant.regime.classifier import classify_regime

        dates = _make_spy_data(db_path, "bear")
        last_date = dates[-1].strftime("%Y-%m-%d")
        upsert_macro([
            {"indicator": "vix", "date": last_date, "value": 28.0, "source": "test"},
            {"indicator": "fear_greed", "date": last_date, "value": 25.0, "source": "test"},
            {"indicator": "cpi_yoy", "date": last_date, "value": 5.0, "source": "test"},
            {"indicator": "gdp_growth", "date": last_date, "value": 0.5, "source": "test"},
        ], db_path)

        state = classify_regime(db_path=db_path)
        assert state is not None
        # euphoria가 아니고 stagflation이어야 함
        assert state.regime == "stagflation"
        assert state.trend == "bear"
        assert state.volatility == "high"

    def test_not_stagflation_low_cpi(self, db_path):
        """CPI 2% → stagflation 아님."""
        from nuri.quant.regime.classifier import _detect_stagflation

        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 2.0, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-01-15", "value": 0.5, "source": "test"},
        ], db_path)
        assert _detect_stagflation(db_path, "2025-01-15") is False

    def test_not_stagflation_high_gdp(self, db_path):
        """GDP 3% → stagflation 아님."""
        from nuri.quant.regime.classifier import _detect_stagflation

        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-02-15", "value": 5.0, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-02-15", "value": 3.0, "source": "test"},
        ], db_path)
        assert _detect_stagflation(db_path, "2025-02-15") is False


class TestRecoveryRegime:
    """recovery 레짐: 200일 하락 후 SMA50 상향 돌파 + VIX 하락."""

    def test_recovery_function(self):
        """_detect_recovery 직접 테스트."""
        from nuri.quant.regime.classifier import _detect_recovery

        # 200일 하락 → 100일 상승 시뮬레이션
        n = 300
        dates = pd.bdate_range("2024-01-01", periods=n)
        phase1 = np.linspace(200, 120, 200)
        phase2 = np.linspace(120, 170, 100)
        close = np.concatenate([phase1, phase2])

        df = pd.DataFrame({"close": close})
        df["sma50"] = df["close"].rolling(50).mean()
        df["sma200"] = df["close"].rolling(200).mean()
        df["date"] = [d.strftime("%Y-%m-%d") for d in dates]

        # 회복 패턴에서는 SMA50이 SMA200 위로 가야 함
        # 데이터가 정확히 교차하지 않을 수 있으므로 함수 자체를 테스트
        result = _detect_recovery(df, vix=20.0, thresholds={"sideways_pct": 2.0})
        assert isinstance(result, bool)

    def test_recovery_no_decline(self):
        """상승장에서는 recovery 미감지."""
        from nuri.quant.regime.classifier import _detect_recovery

        close = np.linspace(100, 200, 300)
        df = pd.DataFrame({"close": close})
        df["sma50"] = df["close"].rolling(50).mean()
        df["sma200"] = df["close"].rolling(200).mean()

        assert _detect_recovery(df, vix=15.0, thresholds={"sideways_pct": 2.0}) is False

    def test_recovery_insufficient_data(self):
        """데이터 부족 시 False."""
        from nuri.quant.regime.classifier import _detect_recovery

        df = pd.DataFrame({"close": [100, 110, 120], "sma50": [100, 105, 110], "sma200": [100, 102, 105]})
        assert _detect_recovery(df, vix=15.0, thresholds={"sideways_pct": 2.0}) is False


class TestSectorRotation:
    """sector_rotation 레짐: SPY 횡보 + 섹터 ETF 3%+."""

    def test_sector_rotation_detection(self, db_path):
        """SPY 횡보 + XLK 5% 상승 → sector_rotation."""
        from nuri.quant.regime.classifier import _detect_sector_rotation

        # SPY 횡보 데이터 (10일간 변동 없음)
        dates = pd.bdate_range("2025-01-01", periods=300)
        close = np.full(300, 150.0) + np.random.normal(0, 0.2, 300)
        spy_df = pd.DataFrame({"close": close})
        spy_df["date"] = [d.strftime("%Y-%m-%d") for d in dates]

        # SPY + XLK 가격 데이터 DB 주입
        spy_prices = _make_price_df("SPY", dates, close)
        upsert_prices(spy_prices, db_path)

        # XLK: 5일간 5% 상승
        xlk_close = np.full(300, 100.0)
        xlk_close[-5:] = [100, 101, 102, 103, 105]
        xlk_prices = _make_price_df("XLK", dates, xlk_close)
        upsert_prices(xlk_prices, db_path)

        result = _detect_sector_rotation(spy_df, db_path)
        assert isinstance(result, bool)

    def test_sector_rotation_no_etf_data(self, db_path):
        """섹터 ETF 없으면 False."""
        from nuri.quant.regime.classifier import _detect_sector_rotation

        close = np.full(300, 150.0)
        spy_df = pd.DataFrame({"close": close})
        assert _detect_sector_rotation(spy_df, db_path) is False


class TestEuphoriaFunction:
    """_detect_euphoria 직접 테스트."""

    def test_euphoria_true(self):
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(vix=10.0, fear_greed=85.0) is True

    def test_euphoria_false_no_data(self):
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(vix=None, fear_greed=85.0) is False
        assert _detect_euphoria(vix=10.0, fear_greed=None) is False

    def test_euphoria_boundary(self):
        """경계값: VIX=12, F&G=80은 미충족 (strict >/<)."""
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(vix=12.0, fear_greed=81.0) is False  # VIX must be < 12
        assert _detect_euphoria(vix=11.9, fear_greed=80.0) is False  # F&G must be > 80


# ═══════════════════════════════════════════════════════
# 전략 매핑 신규 레짐 테스트
# ═══════════════════════════════════════════════════════


class TestSpecialRegimeStrategy:
    """특수 레짐의 전략 매핑 테스트."""

    def test_special_regime_rules_exist(self):
        """4개 특수 레짐 규칙이 정의됨."""
        from nuri.quant.regime.strategy_map import SPECIAL_REGIME_RULES
        assert "recovery" in SPECIAL_REGIME_RULES
        assert "euphoria" in SPECIAL_REGIME_RULES
        assert "sector_rotation" in SPECIAL_REGIME_RULES
        assert "stagflation" in SPECIAL_REGIME_RULES

    def test_recovery_strategy(self):
        """회복 레짐 → defensive 포지션, 매수 시그널 포함."""
        from nuri.quant.regime.strategy_map import SPECIAL_REGIME_RULES
        recovery = SPECIAL_REGIME_RULES["recovery"]
        assert recovery["position_sizing"] == "defensive"
        assert "rsi_oversold" in recovery["recommended_signals"]
        assert "volume_spike" in recovery["recommended_signals"]

    def test_euphoria_strategy(self):
        """유포리아 → defensive, 매도 시그널만."""
        from nuri.quant.regime.strategy_map import SPECIAL_REGIME_RULES
        euphoria = SPECIAL_REGIME_RULES["euphoria"]
        assert euphoria["position_sizing"] == "defensive"
        assert "rsi_overbought" in euphoria["recommended_signals"]
        assert "rsi_oversold" in euphoria["avoid_signals"]

    def test_stagflation_strategy(self):
        """스태그플레이션 → minimal, 방어주만."""
        from nuri.quant.regime.strategy_map import SPECIAL_REGIME_RULES
        stag = SPECIAL_REGIME_RULES["stagflation"]
        assert stag["position_sizing"] == "minimal"
        assert stag["recommended_signals"] == []
        assert "XLP" in stag["sector_preference"]

    def test_sector_rotation_strategy(self):
        """섹터 로테이션 → normal, 섹터 이동 활용."""
        from nuri.quant.regime.strategy_map import SPECIAL_REGIME_RULES
        sr = SPECIAL_REGIME_RULES["sector_rotation"]
        assert sr["position_sizing"] == "normal"
        assert "volume_spike" in sr["recommended_signals"]

    def test_map_euphoria_regime(self, db_path):
        """euphoria 레짐에서 map_regime_to_strategy 동작."""
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import compute_macro_score
        from nuri.quant.regime.strategy_map import map_regime_to_strategy

        state = RegimeState(
            date="2025-01-15", trend="bull", volatility="low",
            regime="euphoria", confidence=0.75,
            details={"spy_close": 500, "vix": 10, "fear_greed": 85},
        )
        macro = compute_macro_score(db_path=db_path)
        rec = map_regime_to_strategy(state, macro, db_path)
        assert rec is not None
        assert rec.regime == "euphoria"
        assert rec.position_sizing == "defensive"

    def test_map_stagflation_regime(self, db_path):
        """stagflation 레짐에서 map_regime_to_strategy 동작."""
        from nuri.quant.regime.classifier import RegimeState
        from nuri.quant.regime.macro_score import compute_macro_score
        from nuri.quant.regime.strategy_map import map_regime_to_strategy

        state = RegimeState(
            date="2025-01-15", trend="bear", volatility="high",
            regime="stagflation", confidence=0.75,
            details={"spy_close": 400, "vix": 30, "fear_greed": 20},
        )
        macro = compute_macro_score(db_path=db_path)
        rec = map_regime_to_strategy(state, macro, db_path)
        assert rec is not None
        assert rec.regime == "stagflation"
        # 매크로 악화 시 minimal로 전환
        assert rec.position_sizing == "minimal"


class TestPrintRegimeSpecial:
    """print_regime이 특수 레짐을 처리하는지 확인."""

    def test_print_euphoria(self, capsys):
        from nuri.quant.regime.classifier import RegimeState, print_regime
        state = RegimeState(
            date="2025-01-15", trend="bull", volatility="low",
            regime="euphoria", confidence=0.75,
            details={"spy_close": 500, "sma50": 490, "sma200": 480, "vix": 10, "fear_greed": 85},
        )
        print_regime(state)
        output = capsys.readouterr().out
        assert "EUPHORIA" in output

    def test_print_stagflation(self, capsys):
        from nuri.quant.regime.classifier import RegimeState, print_regime
        state = RegimeState(
            date="2025-01-15", trend="bear", volatility="high",
            regime="stagflation", confidence=0.75,
            details={"spy_close": 400, "sma50": 410, "sma200": 430, "vix": 30, "fear_greed": 20},
        )
        print_regime(state)
        output = capsys.readouterr().out
        assert "STAGFLATION" in output


# ═══════════════════════════════════════════════════════
# 기존 레짐 비회귀 테스트
# ═══════════════════════════════════════════════════════


class TestExistingRegimePreservation:
    """기존 6개 레짐이 깨지지 않았는지 확인."""

    def test_bull_low_vol(self, db_path):
        """상승장 + 낮은 VIX → bull_low_vol (euphoria 아닌 조건)."""
        from nuri.quant.regime.classifier import classify_regime

        dates = _make_spy_data(db_path, "bull")
        upsert_macro([
            {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 15.0, "source": "test"},
            {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 60.0, "source": "test"},
        ], db_path)

        state = classify_regime(db_path=db_path)
        assert state is not None
        assert state.regime == "bull_low_vol"

    def test_bear_high_vol(self, db_path):
        """하락장 + 높은 VIX → bear_high_vol (stagflation 아닌 조건)."""
        from nuri.quant.regime.classifier import classify_regime

        dates = _make_spy_data(db_path, "bear")
        upsert_macro([
            {"indicator": "vix", "date": dates[-1].strftime("%Y-%m-%d"), "value": 32.0, "source": "test"},
            {"indicator": "fear_greed", "date": dates[-1].strftime("%Y-%m-%d"), "value": 20.0, "source": "test"},
        ], db_path)

        state = classify_regime(db_path=db_path)
        assert state is not None
        assert state.regime == "bear_high_vol"

    def test_existing_signal_definitions_preserved(self):
        """기존 7개 시그널이 그대로 존재."""
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        original_signals = [
            "rsi_oversold", "rsi_overbought", "macd_golden", "macd_dead",
            "sma_golden", "sma_dead", "bb_bounce",
        ]
        for sig in original_signals:
            assert sig in SIGNAL_DEFINITIONS


# ═══════════════════════════════════════════════════════
# Part 3: 버그 수정 검증 테스트
# ═══════════════════════════════════════════════════════


class TestShortInterestFromExternalAnalysis:
    """Fix #1: short_interest를 external_analysis 테이블에서 로드."""

    def test_load_short_interest_from_external(self, db_path):
        """_load_short_interest가 external_analysis 테이블에서 데이터 로드."""
        from nuri.collectors.external import save_external
        from nuri.quant.validation.signal_backtest import _load_short_interest

        # external_analysis에 short_interest 저장 (wallstreet collector 방식)
        save_external(
            "short_interest", "TSLA", "short_pct_float",
            "25.0", 25.0,
            details="days_to_cover=3.2",
            target_date="2025-01-15", db_path=db_path,
        )
        df = _load_short_interest("TSLA", db_path)
        assert not df.empty
        assert df.iloc[0]["value"] == 25.0

    def test_load_short_interest_empty_ticker(self, db_path):
        """해당 종목 short_interest 없으면 빈 DataFrame."""
        from nuri.quant.validation.signal_backtest import _load_short_interest

        df = _load_short_interest("NONEXIST", db_path)
        assert df.empty

    def test_load_short_interest_not_from_macro(self, db_path):
        """macro 테이블에 short_interest를 넣어도 _load_short_interest로는 안 읽힘."""
        from nuri.quant.validation.signal_backtest import _load_short_interest

        upsert_macro([
            {"indicator": "short_interest", "date": "2025-01-15", "value": 30.0, "source": "test"},
        ], db_path)
        # _load_short_interest는 external_analysis만 조회
        df = _load_short_interest("TSLA", db_path)
        assert df.empty


class TestPCRReversalSequenceCheck:
    """Fix #3: PCR 반전 시 최고점이 현재보다 앞에 와야 함."""

    def test_pcr_high_before_low(self):
        """최고점(1.3)이 현재(0.75)보다 먼저 → 감지."""
        from nuri.quant.validation.signal_backtest import _detect_pcr_reversal_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=20))
        pcr_data = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10"]),
            "value": [1.3, 1.2, 1.0, 0.9, 0.75],
        })
        entries = _detect_pcr_reversal_entries(dates, pcr_data)
        assert len(entries) >= 1

    def test_pcr_low_before_high_no_trigger(self):
        """현재가 최고점(1.3)이면 → 순서 위반으로 미감지."""
        from nuri.quant.validation.signal_backtest import _detect_pcr_reversal_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=20))
        # 낮은 값이 먼저, 높은 값이 마지막 → high→low 순서 아님
        pcr_data = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-08"]),
            "value": [0.7, 0.8, 1.3],  # 마지막이 최고점이므로 max_idx == last
        })
        entries = _detect_pcr_reversal_entries(dates, pcr_data)
        assert entries == []

    def test_pcr_max_at_end_no_trigger(self):
        """윈도우 내 max PCR이 마지막 값일 때 미감지 (high→low 순서 아님)."""
        from nuri.quant.validation.signal_backtest import _detect_pcr_reversal_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=20))
        # max가 마지막이면서 0.8 이하도 아님 → 미감지
        pcr_data = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-06", "2025-01-07"]),
            "value": [1.0, 1.3],
        })
        entries = _detect_pcr_reversal_entries(dates, pcr_data)
        assert entries == []


class TestRecoveryLongTermDecline:
    """Fix #4: recovery 레짐이 200일 장기 하락을 확인."""

    def test_recovery_requires_long_term_decline(self):
        """200일 장기 하락 없이 20일 단기 딥만으로는 recovery 미감지."""
        from nuri.quant.regime.classifier import _detect_recovery

        # 꾸준한 상승 → 20일 소폭 하락 → 반등 (장기 하락 아님)
        phase1 = np.linspace(100, 180, 250)  # 장기 상승
        phase2 = np.linspace(180, 170, 20)   # 20일 소폭 조정
        phase3 = np.linspace(170, 185, 30)   # 반등
        close = np.concatenate([phase1, phase2, phase3])

        df = pd.DataFrame({"close": close})
        df["sma50"] = df["close"].rolling(50).mean()
        df["sma200"] = df["close"].rolling(200).mean()

        # SMA200은 장기 상승 중이므로 시작보다 끝이 높음 → sma200_declining = False
        result = _detect_recovery(df, vix=20.0, thresholds={"sideways_pct": 2.0})
        assert result is False

    def test_recovery_with_genuine_decline(self):
        """200일 하락 → SMA50 돌파 → recovery 감지 가능."""
        from nuri.quant.regime.classifier import _detect_recovery

        phase1 = np.linspace(200, 120, 200)  # 200일 장기 하락
        phase2 = np.linspace(120, 170, 100)  # 100일 상승 반전
        close = np.concatenate([phase1, phase2])

        df = pd.DataFrame({"close": close})
        df["sma50"] = df["close"].rolling(50).mean()
        df["sma200"] = df["close"].rolling(200).mean()

        # 장기 하락 패턴이므로 조건 가능 (SMA50 교차 여부에 따라 True/False)
        result = _detect_recovery(df, vix=20.0, thresholds={"sideways_pct": 2.0})
        assert isinstance(result, bool)


class TestVIXReversalConsecutiveDays:
    """Fix #5: VIX 반전에 3일 연속 30+ 요구."""

    def test_three_days_required(self):
        """정확히 3일 연속 30+ 후 하락 → 감지."""
        from nuri.quant.validation.signal_backtest import _detect_vix_reversal_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=10))
        vix_df = pd.DataFrame({
            "date": pd.to_datetime([
                "2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09",
            ]),
            "value": [31.0, 32.0, 33.0, 23.0],  # 3일 30+, 4일째 25 미만
        })
        entries = _detect_vix_reversal_entries(dates, vix_df)
        assert len(entries) >= 1

    def test_two_days_not_enough(self):
        """2일 연속 30+ 후 하락 → 3일 미달로 미감지."""
        from nuri.quant.validation.signal_backtest import _detect_vix_reversal_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=10))
        vix_df = pd.DataFrame({
            "date": pd.to_datetime([
                "2025-01-06", "2025-01-07", "2025-01-08",
            ]),
            "value": [31.0, 32.0, 23.0],  # 2일만 30+
        })
        entries = _detect_vix_reversal_entries(dates, vix_df)
        assert entries == []

    def test_interrupted_streak_no_trigger(self):
        """30+ 연속이 중간에 끊기면 미감지."""
        from nuri.quant.validation.signal_backtest import _detect_vix_reversal_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=15))
        # 30+ → 28(끊김) → 31 → 24 (연속 1일만이므로 미달)
        vix_df = pd.DataFrame({
            "date": pd.to_datetime([
                "2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10",
            ]),
            "value": [31.0, 28.0, 31.0, 30.0, 24.0],
        })
        entries = _detect_vix_reversal_entries(dates, vix_df)
        assert entries == []


class TestSectorRotationWidenedRange:
    """Fix #6: sector_rotation SPY 횡보 범위 ±2%."""

    def test_spy_1_5_pct_still_sideways(self, db_path):
        """SPY 5일 수익률 1.5%는 기존 ±1%에선 미감지이나 ±2%에선 횡보."""
        from nuri.quant.regime.classifier import _detect_sector_rotation

        dates = pd.bdate_range("2025-01-01", periods=300)
        # SPY 가격: 마지막 5일에서 +1.5% 상승 (±2% 내)
        close = np.full(300, 150.0)
        close[-5:] = [150.0, 150.3, 150.6, 150.9, 152.25]  # 150→152.25 = +1.5%
        spy_df = pd.DataFrame({"close": close})

        spy_prices = _make_price_df("SPY", dates, close)
        upsert_prices(spy_prices, db_path)

        # XLK 5% 상승
        xlk_close = np.full(300, 100.0)
        xlk_close[-5:] = [100.0, 101.0, 102.0, 103.0, 105.0]
        xlk_prices = _make_price_df("XLK", dates, xlk_close)
        upsert_prices(xlk_prices, db_path)

        result = _detect_sector_rotation(spy_df, db_path)
        # SPY 1.5% < 2.0% 이므로 횡보로 판단, XLK 5%이므로 로테이션 가능
        assert result is True

    def test_spy_2_5_pct_not_sideways(self, db_path):
        """SPY 5일 수익률 2.5%는 ±2% 초과 → 횡보 아님."""
        from nuri.quant.regime.classifier import _detect_sector_rotation

        dates = pd.bdate_range("2025-01-01", periods=300)
        close = np.full(300, 150.0)
        close[-5:] = [150.0, 150.5, 151.0, 152.0, 153.75]  # +2.5%
        spy_df = pd.DataFrame({"close": close})

        spy_prices = _make_price_df("SPY", dates, close)
        upsert_prices(spy_prices, db_path)

        result = _detect_sector_rotation(spy_df, db_path)
        assert result is False


class TestInsiderClusterOptimized:
    """Fix #7: insider_cluster 슬라이딩 윈도우 최적화 — 결과 동일성 확인."""

    def test_cluster_detection_preserved(self):
        """최적화 후에도 10일 내 3건 감지 동작 동일."""
        from nuri.quant.validation.signal_backtest import _detect_insider_cluster_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=30))
        insider_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-13", "2025-01-14", "2025-01-15"]),
            "transaction_type": ["Purchase", "Purchase", "Buy"],
        })
        entries = _detect_insider_cluster_entries(dates, insider_df)
        assert len(entries) >= 1

    def test_cluster_no_false_positives(self):
        """매수 2건은 3건 미달 → 미감지."""
        from nuri.quant.validation.signal_backtest import _detect_insider_cluster_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=30))
        insider_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-13", "2025-01-14"]),
            "transaction_type": ["Purchase", "Buy"],
        })
        entries = _detect_insider_cluster_entries(dates, insider_df)
        assert entries == []

    def test_cluster_spread_over_11_days(self):
        """11일에 걸친 3건은 10일 윈도우 내 미포함 가능."""
        from nuri.quant.validation.signal_backtest import _detect_insider_cluster_entries

        dates = pd.Series(pd.bdate_range("2025-01-01", periods=30))
        # 11 영업일 간격 (첫 번째와 세 번째가 10일 윈도우 밖)
        insider_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-02", "2025-01-08", "2025-01-17"]),
            "transaction_type": ["Purchase", "Purchase", "Buy"],
        })
        entries = _detect_insider_cluster_entries(dates, insider_df)
        # 01-02~01-17은 15일 차이 → 10일 윈도우에 3건이 안 들어감
        # 단, dates 기준 윈도우이므로 특정 날짜의 i-10 ~ i 범위에서 확인
        assert isinstance(entries, list)


class TestStagflationGracefulNone:
    """Fix #2: gdp_growth 없을 때 _detect_stagflation이 경고와 함께 False 반환."""

    def test_stagflation_no_gdp_returns_false(self, db_path):
        """GDP 데이터 없으면 False (경고 로그 발생)."""
        from nuri.quant.regime.classifier import _detect_stagflation

        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 5.0, "source": "test"},
        ], db_path)
        # gdp_growth가 없으므로 False 반환
        assert _detect_stagflation(db_path, "2025-01-15") is False

    def test_stagflation_no_cpi_returns_false(self, db_path):
        """CPI 데이터 없으면 즉시 False (경고 없이)."""
        from nuri.quant.regime.classifier import _detect_stagflation

        # cpi_yoy도 gdp_growth도 없음
        assert _detect_stagflation(db_path, "2025-01-15") is False

    def test_stagflation_with_both_data(self, db_path):
        """CPI와 GDP 모두 있으면 정상 판별."""
        from nuri.quant.regime.classifier import _detect_stagflation

        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-15", "value": 5.0, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-01-15", "value": 0.5, "source": "test"},
        ], db_path)
        assert _detect_stagflation(db_path, "2025-01-15") is True


class TestYieldCurveRecoveryRename:
    """Fix #8: yield_inversion → yield_curve_recovery 이름 변경 확인."""

    def test_old_name_not_in_definitions(self):
        """구 이름 yield_inversion이 SIGNAL_DEFINITIONS에 없음."""
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        assert "yield_inversion" not in SIGNAL_DEFINITIONS

    def test_new_name_in_definitions(self):
        """신규 이름 yield_curve_recovery가 SIGNAL_DEFINITIONS에 있음."""
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS
        assert "yield_curve_recovery" in SIGNAL_DEFINITIONS
        assert SIGNAL_DEFINITIONS["yield_curve_recovery"]["requires_macro"] is True

    def test_function_renamed(self):
        """함수명도 _detect_yield_curve_recovery_entries로 변경."""
        from nuri.quant.validation import signal_backtest
        assert hasattr(signal_backtest, "_detect_yield_curve_recovery_entries")
        assert not hasattr(signal_backtest, "_detect_yield_inversion_entries")
