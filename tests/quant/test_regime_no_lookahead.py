"""E3-1 Stage 0 — Classifier no-lookahead audit (STRATEGY §3.6).

regime classifier 의 historical 호출이 미래 데이터를 사용하지 않음을 검증.
검증 대상 (codex Plan consult 결과):
- compute_dynamic_thresholds(date): VIX/SMA 임계값 — past-only quantile
- _load_spy_series(date): SPY 시계열 — past-only rows
- _get_vix(date) / _get_fear_greed(date): 단일 latest past 값
- _detect_stagflation(date) / _detect_sector_rotation(date): macro / 섹터 ETF past-only
- _detect_euphoria(vix, fear_greed) / _detect_recovery(spy_df): pure functions, 호출자 책임
- classify_regime_history(start, end): monthly sampling = 월별 마지막 가용일 (intra-month flip 은닉은
  sampling design 의 known trade-off, lookahead 가 아님 — sampling 기능을 lock)
"""
import numpy as np
import pandas as pd

from nuri.core.db import upsert_macro, upsert_prices


def _seed_spy_with_split(db_path, past_days=300, future_days=60, past_price=200.0, future_price=400.0):
    """과거 + 미래 SPY price 동시 삽입.

    cutoff_date 기준 과거 days = past_days (가격 수렴 past_price 부근),
    미래 days = future_days (가격 future_price 부근, 과거와 명확히 다름).
    Returns: cutoff_date (str YYYY-MM-DD).
    """
    rng = np.random.default_rng(42)
    total = past_days + future_days
    end = pd.Timestamp("2025-12-31")
    dates = pd.bdate_range(end=end, periods=total)
    cutoff_idx = past_days - 1
    cutoff_date = dates[cutoff_idx].strftime("%Y-%m-%d")

    past_close = past_price + rng.normal(0, 1, past_days)
    future_close = future_price + rng.normal(0, 1, future_days)
    close = np.concatenate([past_close, future_close])

    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.999,
        "high": close * 1.001,
        "low": close * 0.999,
        "close": close,
        "volume": [50_000_000] * total,
        "adj_close": close,
    })
    upsert_prices(df, db_path)
    return cutoff_date


def _seed_macro_with_split(db_path, indicator, past_dates, past_value, future_dates, future_value):
    """단일 indicator 에 대해 과거/미래 가격 분리 삽입."""
    records = (
        [{"indicator": indicator, "date": d, "value": past_value, "source": "test"} for d in past_dates]
        + [{"indicator": indicator, "date": d, "value": future_value, "source": "test"} for d in future_dates]
    )
    upsert_macro(records, db_path=db_path)


class TestNoLookaheadThresholds:
    """compute_dynamic_thresholds(date) 가 past-only 분위수를 반환."""

    def test_vix_threshold_uses_only_past_values(self, db_path):
        """과거 VIX = 15 (low), 미래 VIX = 35 (high). cutoff 기준 median 은 ~15 이어야."""
        from nuri.quant.regime.classifier import compute_dynamic_thresholds

        # 과거 60일 VIX = 15, 미래 60일 VIX = 35
        end = pd.Timestamp("2025-06-30")
        all_dates = pd.bdate_range(end=end + pd.Timedelta(days=120), periods=120)
        cutoff_date = all_dates[59].strftime("%Y-%m-%d")
        past_dates = [d.strftime("%Y-%m-%d") for d in all_dates[:60]]
        future_dates = [d.strftime("%Y-%m-%d") for d in all_dates[60:]]
        _seed_macro_with_split(db_path, "vix", past_dates, 15.0, future_dates, 35.0)
        # SPY 도 충분히 (compute 가 SMA gap 계산하므로)
        _seed_spy_with_split(db_path, past_days=300, future_days=60)

        thresholds = compute_dynamic_thresholds(db_path=db_path, date=cutoff_date)
        # past 60일 VIX median = 15 → vix_threshold 가 ~15 (절대 future 35 의 영향 받지 않아야)
        assert thresholds["vix_threshold"] < 20, f"future VIX leak: {thresholds['vix_threshold']}"

    def test_sma_threshold_uses_only_past_prices(self, db_path):
        """과거 가격 200 부근 (low SMA gap), 미래 400 (huge gap). cutoff 기준 sideways_pct 는 small."""
        from nuri.quant.regime.classifier import compute_dynamic_thresholds

        cutoff_date = _seed_spy_with_split(db_path, past_days=300, future_days=60,
                                            past_price=200.0, future_price=400.0)
        thresholds = compute_dynamic_thresholds(db_path=db_path, date=cutoff_date)
        # 과거 데이터만으로는 가격이 ~200 부근 stable → SMA gap std 작음 → sideways_pct 작음
        # 미래 leak 시 가격 점프가 SMA gap 변동성 키워서 sideways_pct 가 커짐
        assert thresholds["sideways_pct"] < 5.0, f"future price leak: {thresholds['sideways_pct']}"


class TestNoLookaheadDataLoaders:
    """_load_spy_series / _get_vix / _get_fear_greed 가 cutoff 이후 row 미반영."""

    def test_load_spy_series_excludes_future_rows(self, db_path):
        from nuri.quant.regime.classifier import _load_spy_series

        cutoff_date = _seed_spy_with_split(db_path, past_days=300, future_days=60)
        df = _load_spy_series(date=cutoff_date, db_path=db_path)
        assert df is not None
        assert df["date"].max() <= cutoff_date, f"future row leaked: max={df['date'].max()} > cutoff={cutoff_date}"
        assert len(df) == 300, f"unexpected row count: {len(df)} (should be past_days=300)"

    def test_get_vix_returns_latest_past_value(self, db_path):
        from nuri.quant.regime.classifier import _get_vix

        end = pd.Timestamp("2025-06-30")
        all_dates = pd.bdate_range(end=end + pd.Timedelta(days=120), periods=120)
        cutoff_date = all_dates[59].strftime("%Y-%m-%d")
        past_dates = [d.strftime("%Y-%m-%d") for d in all_dates[:60]]
        future_dates = [d.strftime("%Y-%m-%d") for d in all_dates[60:]]
        _seed_macro_with_split(db_path, "vix", past_dates, 15.0, future_dates, 35.0)

        vix = _get_vix(date=cutoff_date, db_path=db_path)
        assert vix == 15.0, f"future VIX leak: returned {vix} (past=15.0, future=35.0)"

    def test_get_fear_greed_returns_latest_past_value(self, db_path):
        from nuri.quant.regime.classifier import _get_fear_greed

        end = pd.Timestamp("2025-06-30")
        all_dates = pd.bdate_range(end=end + pd.Timedelta(days=120), periods=120)
        cutoff_date = all_dates[59].strftime("%Y-%m-%d")
        past_dates = [d.strftime("%Y-%m-%d") for d in all_dates[:60]]
        future_dates = [d.strftime("%Y-%m-%d") for d in all_dates[60:]]
        _seed_macro_with_split(db_path, "fear_greed", past_dates, 45.0, future_dates, 85.0)

        fg = _get_fear_greed(date=cutoff_date, db_path=db_path)
        assert fg == 45.0, f"future fear_greed leak: returned {fg} (past=45.0, future=85.0)"


class TestNoLookaheadDetectors:
    """special regime detector — DB 의존 detector 만 (pure 함수는 호출자 책임)."""

    def test_detect_stagflation_past_only(self, db_path):
        """과거 CPI=5/GDP=0.5 (stagflation 발동), 미래 CPI=2/GDP=3 (정상). cutoff 기준 True 여야."""
        from nuri.quant.regime.classifier import _detect_stagflation

        end = pd.Timestamp("2025-06-30")
        all_dates = pd.bdate_range(end=end + pd.Timedelta(days=120), periods=120)
        cutoff_date = all_dates[59].strftime("%Y-%m-%d")
        past_dates = [d.strftime("%Y-%m-%d") for d in all_dates[:60]]
        future_dates = [d.strftime("%Y-%m-%d") for d in all_dates[60:]]
        _seed_macro_with_split(db_path, "cpi_yoy", past_dates, 5.0, future_dates, 2.0)
        _seed_macro_with_split(db_path, "gdp_growth", past_dates, 0.5, future_dates, 3.0)

        result = _detect_stagflation(db_path=db_path, date=cutoff_date)
        assert result is True, "past stagflation conditions should trigger; future normal data leaked instead"

    def test_detect_sector_rotation_past_only(self, db_path):
        """과거 SPY 횡보 + XLK 5% 상승 (sector_rotation 발동), 미래 XLK 폭락. cutoff 기준 True 여야."""
        from nuri.quant.regime.classifier import _detect_sector_rotation

        # SPY 과거 50일 횡보 (200 부근), 미래 50일 폭락 (100 부근)
        end = pd.Timestamp("2025-12-31")
        total_days = 100
        all_dates = pd.bdate_range(end=end, periods=total_days)
        cutoff_idx = 49
        cutoff_date = all_dates[cutoff_idx].strftime("%Y-%m-%d")

        rng = np.random.default_rng(42)
        # SPY 과거: 200 부근 stable, 미래: 100 부근 (큰 하락)
        spy_past = 200 + rng.normal(0, 0.5, 50)
        spy_future = 100 + rng.normal(0, 0.5, 50)
        spy_close = np.concatenate([spy_past, spy_future])

        # XLK 과거: 100 → 110 (10% 상승, 21일 lookback ret > 3% 보장),
        # XLK 미래: 110 → 50 (폭락 — 만약 future leak 시 % 계산이 음수가 되어 detection False)
        xlk_past = np.linspace(100, 110, 50)
        xlk_future = np.linspace(110, 50, 50)
        xlk_close = np.concatenate([xlk_past, xlk_future])

        for ticker, close_arr in [("SPY", spy_close), ("XLK", xlk_close)]:
            df = pd.DataFrame({
                "ticker": ticker,
                "date": [d.strftime("%Y-%m-%d") for d in all_dates],
                "open": close_arr * 0.999,
                "high": close_arr * 1.001,
                "low": close_arr * 0.999,
                "close": close_arr,
                "volume": [10_000_000] * total_days,
                "adj_close": close_arr,
            })
            upsert_prices(df, db_path)

        result = _detect_sector_rotation(db_path=db_path, date=cutoff_date)
        # 과거 21일 (cutoff 포함) 만 보면 SPY 횡보 + XLK 상승 5% → True
        # 미래 leak 시 LIMIT 21 + ORDER BY DESC 가 미래 row 까지 포함해 XLK 폭락 → False
        assert result is True, "past sector rotation should trigger; future data leak suppressed it"


class TestClassifyRegimeHistorySampling:
    """classify_regime_history monthly sampling = 월별 마지막 가용 거래일.

    intra-month flip 은닉은 sampling design 의 known trade-off (resolution = 1 월).
    lookahead 가 아닌 sampling resolution 이슈 — 본 test 는 monthly 가
    실제로 last-of-month 를 picking 하는지 lock-in (refactor 시 silent break 방지).
    """

    def test_monthly_dates_pick_last_business_day_per_month(self, db_path):
        from nuri.quant.regime.classifier import classify_regime_history

        # 2024-01 ~ 2024-03, 3개월 분 SPY 거래일 (월별 last 거래일 ~ 1/31, 2/29, 3/29)
        # 충분한 lookback 위해 200+30+30+30 = 290일 backfill
        all_dates = pd.bdate_range(end="2024-03-31", periods=290)
        rng = np.random.default_rng(42)
        close = 200 + np.linspace(0, 30, 290) + rng.normal(0, 0.5, 290)
        df = pd.DataFrame({
            "ticker": "SPY",
            "date": [d.strftime("%Y-%m-%d") for d in all_dates],
            "open": close * 0.999, "high": close * 1.001, "low": close * 0.999,
            "close": close, "volume": [50_000_000] * 290, "adj_close": close,
        })
        upsert_prices(df, db_path)
        # VIX 도 채워야 _get_vix path 안전
        upsert_macro(
            [{"indicator": "vix", "date": d.strftime("%Y-%m-%d"), "value": 18.0, "source": "test"}
             for d in all_dates],
            db_path=db_path,
        )

        history = classify_regime_history(start_date="2024-01-01", end_date="2024-03-31", db_path=db_path)
        # 3개월 → 정확히 3개 sample (1월, 2월, 3월 last business day 각 1개)
        assert len(history) == 3, f"expected 3 monthly samples, got {len(history)}"
        # 정확한 last business day pinning (codex Round 1 P1: month label 만으로는 first-day bug 검출 불가)
        # 2024-01-31 = Wed, 2024-02-29 = Thu (leap year), 2024-03-29 = Fri (3/31 = Sun)
        sampled_dates = sorted(s.date for s in history)
        assert sampled_dates == ["2024-01-31", "2024-02-29", "2024-03-29"], (
            f"sampling did not pick last business day per month: {sampled_dates}"
        )


class TestEndToEndInvariance:
    """codex Round 1 강화 — before/after future insert 동일 결과 (any leak shape 검출).

    개별 단위 함수 leak 가 모두 fix 됐다고 해도, 새 leak path 가 미래에 도입되면
    end-to-end behavior 가 바뀐다. 따라서 classify_regime(date=cutoff) 를
    cutoff 미래 row 추가 전후로 비교해 invariance 를 hard-lock.
    """

    def test_classify_regime_invariant_to_future_inserts(self, db_path):
        from nuri.quant.regime.classifier import classify_regime

        # cutoff 시점까지 충분한 SPY + VIX + fear_greed
        cutoff_date = _seed_spy_with_split(db_path, past_days=300, future_days=0,
                                            past_price=200.0, future_price=400.0)
        # macro 도 cutoff 까지만 채우기
        all_dates = pd.bdate_range(end="2025-12-31", periods=300)
        past_only = [d.strftime("%Y-%m-%d") for d in all_dates]
        upsert_macro(
            [{"indicator": "vix", "date": d, "value": 18.0, "source": "test"} for d in past_only],
            db_path=db_path,
        )
        upsert_macro(
            [{"indicator": "fear_greed", "date": d, "value": 50.0, "source": "test"} for d in past_only],
            db_path=db_path,
        )

        before = classify_regime(date=cutoff_date, db_path=db_path)
        assert before is not None

        # 미래 60일 데이터 삽입 (가격 폭락 + VIX 폭등 + fear_greed 패닉) — 어떤 leak 도 결과를 흔들 것
        future_dates = pd.bdate_range(start=pd.Timestamp(cutoff_date) + pd.Timedelta(days=1), periods=60)
        future_close = np.full(60, 50.0)  # SPY 폭락
        df_future = pd.DataFrame({
            "ticker": "SPY",
            "date": [d.strftime("%Y-%m-%d") for d in future_dates],
            "open": future_close, "high": future_close, "low": future_close,
            "close": future_close, "volume": [50_000_000] * 60, "adj_close": future_close,
        })
        upsert_prices(df_future, db_path)
        upsert_macro(
            [{"indicator": "vix", "date": d.strftime("%Y-%m-%d"), "value": 50.0, "source": "test"}
             for d in future_dates],
            db_path=db_path,
        )
        upsert_macro(
            [{"indicator": "fear_greed", "date": d.strftime("%Y-%m-%d"), "value": 5.0, "source": "test"}
             for d in future_dates],
            db_path=db_path,
        )

        after = classify_regime(date=cutoff_date, db_path=db_path)
        assert after is not None
        # 같은 cutoff 호출은 어떤 future insert 도 결과를 바꾸면 안 됨
        assert after.regime == before.regime, (
            f"classify_regime not invariant: regime {before.regime} → {after.regime} after future insert"
        )
        assert after.trend == before.trend, f"trend changed: {before.trend} → {after.trend}"
        assert after.volatility == before.volatility, (
            f"volatility changed: {before.volatility} → {after.volatility}"
        )
        assert after.confidence == before.confidence, (
            f"confidence changed: {before.confidence} → {after.confidence}"
        )

    def test_classify_regime_history_invariant_to_future_inserts(self, db_path):
        """codex Round 2 P1 — classify_regime_history(start, end) 도 invariance 검증."""
        from nuri.quant.regime.classifier import classify_regime_history

        # 충분한 backfill (200d lookback + 3개월 sampling)
        all_dates = pd.bdate_range(end="2024-03-31", periods=290)
        rng = np.random.default_rng(7)
        close = 200 + np.linspace(0, 30, 290) + rng.normal(0, 0.5, 290)
        df = pd.DataFrame({
            "ticker": "SPY",
            "date": [d.strftime("%Y-%m-%d") for d in all_dates],
            "open": close * 0.999, "high": close * 1.001, "low": close * 0.999,
            "close": close, "volume": [50_000_000] * 290, "adj_close": close,
        })
        upsert_prices(df, db_path)
        upsert_macro(
            [{"indicator": "vix", "date": d.strftime("%Y-%m-%d"), "value": 18.0, "source": "test"}
             for d in all_dates],
            db_path=db_path,
        )

        before = classify_regime_history(start_date="2024-01-01", end_date="2024-03-31", db_path=db_path)
        assert len(before) == 3

        # cutoff (2024-03-31) 이후 미래 60일 적대적 데이터 (가격 폭락 + VIX 폭등)
        future_dates = pd.bdate_range(start="2024-04-01", periods=60)
        future_close = np.full(60, 50.0)
        df_future = pd.DataFrame({
            "ticker": "SPY",
            "date": [d.strftime("%Y-%m-%d") for d in future_dates],
            "open": future_close, "high": future_close, "low": future_close,
            "close": future_close, "volume": [50_000_000] * 60, "adj_close": future_close,
        })
        upsert_prices(df_future, db_path)
        upsert_macro(
            [{"indicator": "vix", "date": d.strftime("%Y-%m-%d"), "value": 50.0, "source": "test"}
             for d in future_dates],
            db_path=db_path,
        )

        after = classify_regime_history(start_date="2024-01-01", end_date="2024-03-31", db_path=db_path)
        assert len(after) == 3
        # 같은 (start, end) 윈도우에 대해 history 길이 + 각 sample 의 regime/trend/vol 모두 동일
        assert [s.date for s in after] == [s.date for s in before]
        for b, a in zip(before, after, strict=True):
            assert a.regime == b.regime, (
                f"regime drift after future insert at {b.date}: {b.regime} → {a.regime}"
            )
            assert a.trend == b.trend, f"trend drift at {b.date}: {b.trend} → {a.trend}"
            assert a.volatility == b.volatility, (
                f"volatility drift at {b.date}: {b.volatility} → {a.volatility}"
            )

    def test_detect_sector_rotation_invariant_to_future_inserts(self, db_path):
        """codex Round 1 P1 개별 강화 — sector rotation 단일 shape 가 아닌 invariance pattern."""
        from nuri.quant.regime.classifier import _detect_sector_rotation

        # 과거 50일 SPY 횡보 + XLK 10% 상승 (sector_rotation True 보장)
        end = pd.Timestamp("2025-12-31")
        all_dates = pd.bdate_range(end=end, periods=50)
        cutoff_date = all_dates[-1].strftime("%Y-%m-%d")

        rng = np.random.default_rng(42)
        spy_close = 200 + rng.normal(0, 0.5, 50)
        xlk_close = np.linspace(100, 110, 50)
        for ticker, close_arr in [("SPY", spy_close), ("XLK", xlk_close)]:
            df = pd.DataFrame({
                "ticker": ticker,
                "date": [d.strftime("%Y-%m-%d") for d in all_dates],
                "open": close_arr * 0.999, "high": close_arr * 1.001,
                "low": close_arr * 0.999, "close": close_arr,
                "volume": [10_000_000] * 50, "adj_close": close_arr,
            })
            upsert_prices(df, db_path)

        before = _detect_sector_rotation(db_path=db_path, date=cutoff_date)
        assert before is True

        # 다양한 future shape 으로 perturbation: XLK 폭등/폭락, SPY 급등 등 4 시나리오
        future_dates = pd.bdate_range(start=pd.Timestamp(cutoff_date) + pd.Timedelta(days=1), periods=30)
        for spy_future_val, xlk_future_val in [(100.0, 50.0), (300.0, 200.0), (200.0, 1000.0), (50.0, 0.1)]:
            for ticker, val in [("SPY", spy_future_val), ("XLK", xlk_future_val)]:
                arr = np.full(30, val)
                df = pd.DataFrame({
                    "ticker": ticker,
                    "date": [d.strftime("%Y-%m-%d") for d in future_dates],
                    "open": arr * 0.999, "high": arr * 1.001, "low": arr * 0.999,
                    "close": arr, "volume": [10_000_000] * 30, "adj_close": arr,
                })
                upsert_prices(df, db_path)
            after = _detect_sector_rotation(db_path=db_path, date=cutoff_date)
            assert after == before, (
                f"_detect_sector_rotation not invariant under future perturbation "
                f"SPY={spy_future_val} XLK={xlk_future_val}: {before} → {after}"
            )
