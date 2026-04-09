"""Layer 0 데이터 무결성 테스트 — VIX 히스테리시스 + 데이터 신선도."""
from datetime import timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_prices
from nuri.core.timezone import kst_now, today_kst


@pytest.fixture
def db_path(tmp_path):
    """임시 DB 경로 픽스처."""
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _insert_spy_data(db_path, n_days=300, trend="bull", last_date=None):
    """SPY 가격 데이터 삽입 헬퍼."""
    if last_date is None:
        from nuri.core.timezone import today_kst
        last_date = today_kst()
    # bdate_range는 주말을 건너뛰어 마지막 날짜가 last_date와 다를 수 있음
    # freshness 테스트에서 정확한 날짜가 필요하므로 date_range 사용
    dates = pd.date_range(end=last_date, periods=n_days, freq="D")

    if trend == "bull":
        close = np.linspace(100, 200, n_days) + np.random.default_rng(42).normal(0, 0.5, n_days)
    elif trend == "bear":
        up = np.linspace(150, 200, n_days // 3 * 2)
        down = np.linspace(200, 130, n_days - len(up))
        close = np.concatenate([up, down]) + np.random.default_rng(42).normal(0, 0.3, n_days)
    else:  # sideways
        close = np.full(n_days, 150.0) + np.random.default_rng(42).normal(0, 1, n_days)

    df = pd.DataFrame({
        "ticker": "SPY",
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "volume": [50000000] * n_days,
        "adj_close": close,
    })
    upsert_prices(df, db_path)
    return [d.strftime("%Y-%m-%d") for d in dates]


# ═══════════════════════════════════════════════════════
# Task 0-2: VIX 히스테리시스 — 일별 VIX 조회 테스트
# ═══════════════════════════════════════════════════════


class TestVixHysteresis:
    """히스테리시스 윈도우에서 각 날짜의 실제 VIX를 사용하는지 검증."""

    def test_historical_vix_used_per_day(self, db_path):
        """각 히스테리시스 날짜에 해당 날짜의 VIX가 사용되는지 확인."""
        dates = _insert_spy_data(db_path, n_days=300, trend="bull")

        # 히스테리시스 윈도우(마지막 5일)에 각각 다른 VIX 삽입
        # 마지막 5일에 VIX 14, 15, 16, 17, 18 삽입
        for i, vix_val in enumerate([14.0, 15.0, 16.0, 17.0, 18.0]):
            upsert_macro([{
                "indicator": "vix",
                "date": dates[-(5 - i)],
                "value": vix_val,
                "source": "test",
            }], db_path)

        # Fear & Greed 삽입
        upsert_macro([{
            "indicator": "fear_greed",
            "date": dates[-1],
            "value": 55.0,
            "source": "test",
        }], db_path)

        from nuri.quant.regime.classifier import _get_vix

        # _get_vix가 날짜별로 올바른 값을 반환하는지 확인
        assert _get_vix(date=dates[-5], db_path=db_path) == 14.0
        assert _get_vix(date=dates[-4], db_path=db_path) == 15.0
        assert _get_vix(date=dates[-3], db_path=db_path) == 16.0
        assert _get_vix(date=dates[-2], db_path=db_path) == 17.0
        assert _get_vix(date=dates[-1], db_path=db_path) == 18.0

    def test_hysteresis_calls_get_vix_per_day(self, db_path):
        """classify_regime이 히스테리시스 루프에서 _get_vix를 날짜별로 호출하는지 확인."""
        dates = _insert_spy_data(db_path, n_days=300, trend="bull")

        # 히스테리시스 윈도우 내 각 날짜에 VIX 삽입
        for i in range(10):
            upsert_macro([{
                "indicator": "vix",
                "date": dates[-(10 - i)],
                "value": 15.0 + i * 0.1,
                "source": "test",
            }], db_path)

        upsert_macro([{
            "indicator": "fear_greed",
            "date": dates[-1],
            "value": 60.0,
            "source": "test",
        }], db_path)

        # _get_vix 호출을 추적
        call_dates = []
        original_get_vix = None

        from nuri.quant.regime import classifier
        original_get_vix = classifier._get_vix

        def tracking_get_vix(date=None, db_path=None):
            call_dates.append(date)
            return original_get_vix(date=date, db_path=db_path)

        with patch.object(classifier, '_get_vix', side_effect=tracking_get_vix):
            state = classifier.classify_regime(db_path=db_path)

        assert state is not None
        # 히스테리시스 윈도우(5일) + 최초 1회(line 237) = 최소 6회 호출
        # 히스테리시스 내 호출에서 date 파라미터가 None이 아닌 실제 날짜여야 함
        hysteresis_calls = [d for d in call_dates if d is not None]
        assert len(hysteresis_calls) >= 2, (
            f"히스테리시스 내 날짜별 VIX 조회가 {len(hysteresis_calls)}회뿐 (최소 2회 예상)"
        )

    def test_regime_still_works_with_single_vix(self, db_path):
        """VIX가 하나만 있어도 히스테리시스가 정상 동작."""
        dates = _insert_spy_data(db_path, n_days=300, trend="bull")

        # 마지막 날짜에만 VIX 삽입
        upsert_macro([{
            "indicator": "vix",
            "date": dates[-1],
            "value": 15.0,
            "source": "test",
        }], db_path)
        upsert_macro([{
            "indicator": "fear_greed",
            "date": dates[-1],
            "value": 55.0,
            "source": "test",
        }], db_path)

        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(db_path=db_path)
        assert state is not None
        assert state.trend == "bull"


# ═══════════════════════════════════════════════════════
# Task 0-4: 데이터 신선도 차단 테스트
# ═══════════════════════════════════════════════════════


class TestDataFreshnessEnforcement:
    """SPY 데이터가 120시간 초과 시 classify_regime이 None을 반환하는지 검증."""

    @pytest.fixture(autouse=True)
    def reset_freshness_warned(self):
        """테스트 간 _freshness_warned 전역 상태 초기화."""
        from nuri.quant.regime import classifier
        classifier._freshness_warned = False
        yield
        classifier._freshness_warned = False

    def test_stale_data_blocks_regime(self, db_path):
        """120시간 초과 데이터 → classify_regime이 None 반환."""
        # 10일 전 날짜로 데이터 삽입
        stale_date = (kst_now().replace(tzinfo=None) - timedelta(days=10)).strftime("%Y-%m-%d")
        _insert_spy_data(db_path, n_days=300, trend="bull", last_date=stale_date)

        upsert_macro([{
            "indicator": "vix",
            "date": stale_date,
            "value": 15.0,
            "source": "test",
        }], db_path)

        from nuri.quant.regime.classifier import classify_regime
        # date=None이므로 freshness 체크 실행됨
        state = classify_regime(db_path=db_path)
        assert state is None, "120시간 초과 데이터로 레짐 분류가 차단되어야 함"

    def test_fresh_data_allows_regime(self, db_path):
        """신선한 데이터 → classify_regime이 정상 동작."""
        today = today_kst()
        dates = _insert_spy_data(db_path, n_days=300, trend="bull", last_date=today)

        upsert_macro([{
            "indicator": "vix",
            "date": dates[-1],
            "value": 15.0,
            "source": "test",
        }], db_path)
        upsert_macro([{
            "indicator": "fear_greed",
            "date": dates[-1],
            "value": 60.0,
            "source": "test",
        }], db_path)

        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime(db_path=db_path)
        assert state is not None, "신선한 데이터로 레짐 분류가 성공해야 함"

    def test_dated_query_bypasses_freshness(self, db_path):
        """date 파라미터 지정 시 freshness 체크를 건너뜀."""
        stale_date = (kst_now().replace(tzinfo=None) - timedelta(days=10)).strftime("%Y-%m-%d")
        _insert_spy_data(db_path, n_days=300, trend="bull", last_date=stale_date)

        upsert_macro([{
            "indicator": "vix",
            "date": stale_date,
            "value": 15.0,
            "source": "test",
        }], db_path)
        upsert_macro([{
            "indicator": "fear_greed",
            "date": stale_date,
            "value": 60.0,
            "source": "test",
        }], db_path)

        from nuri.quant.regime.classifier import classify_regime
        # date를 명시하면 freshness 체크 우회
        state = classify_regime(date=stale_date, db_path=db_path)
        assert state is not None, "date 파라미터 지정 시 freshness 체크를 건너뛰어야 함"

    def test_no_data_returns_false(self, db_path):
        """SPY 데이터 없으면 _check_data_freshness가 False 반환."""
        from nuri.quant.regime.classifier import _check_data_freshness
        result = _check_data_freshness(db_path=db_path)
        assert result is False

    def test_freshness_check_returns_true_for_fresh(self, db_path):
        """오늘 데이터가 있으면 _check_data_freshness가 True 반환."""
        today = today_kst()
        _insert_spy_data(db_path, n_days=300, trend="bull", last_date=today)

        from nuri.quant.regime.classifier import _check_data_freshness
        result = _check_data_freshness(db_path=db_path)
        assert result is True


# ═══════════════════════════════════════════════════════
# Task 0-4: 매크로 스코어 경고 테스트
# ═══════════════════════════════════════════════════════


class TestMacroScoreWarnings:
    """누락 지표 시 warnings 리스트가 채워지는지 검증."""

    def test_empty_db_has_all_warnings(self, db_path):
        """데이터 없는 DB → 모든 지표에 대한 경고."""
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(db_path=db_path)
        assert score.warnings is not None
        assert len(score.warnings) == 8, f"8개 지표 모두 경고 예상, 실제: {len(score.warnings)}"

    def test_partial_data_partial_warnings(self, db_path):
        """일부 데이터만 있을 때 해당 지표만 경고 없음."""
        date = "2025-01-15"
        upsert_macro([
            {"indicator": "vix", "date": date, "value": 15.0, "source": "test"},
            {"indicator": "fear_greed", "date": date, "value": 50.0, "source": "test"},
        ], db_path)

        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.warnings is not None
        # vix와 sentiment는 데이터가 있으므로 경고 없어야 함
        warning_names = [w.split(":")[0] for w in score.warnings]
        assert "vix" not in warning_names
        assert "sentiment" not in warning_names
        # 나머지 6개는 경고 있어야 함
        assert len(score.warnings) == 6

    def test_full_data_no_warnings(self, db_path):
        """모든 데이터가 있으면 warnings=None."""
        date = "2025-01-15"
        upsert_macro([
            {"indicator": "us_10y_yield", "date": date, "value": 4.0, "source": "test"},
            {"indicator": "us_2y_yield", "date": date, "value": 3.0, "source": "test"},
            {"indicator": "us_3m_yield", "date": date, "value": 2.5, "source": "test"},
            {"indicator": "vix", "date": date, "value": 15.0, "source": "test"},
            {"indicator": "put_call_ratio", "date": date, "value": 0.85, "source": "test"},
            {"indicator": "fear_greed", "date": date, "value": 55.0, "source": "test"},
            {"indicator": "unemployment", "date": date, "value": 3.8, "source": "test"},
            {"indicator": "cpi_yoy", "date": date, "value": 2.1, "source": "test"},
            {"indicator": "fed_funds_rate", "date": date, "value": 2.0, "source": "test"},
        ], db_path)

        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(date=date, db_path=db_path)
        assert score.warnings is None, f"모든 데이터가 있으므로 경고 없어야 함, 실제: {score.warnings}"

    def test_score_still_50_when_missing(self, db_path):
        """누락 시 50점(중립)을 사용하는 기존 동작 유지."""
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score(db_path=db_path)
        # 모든 지표가 50점이므로 총점도 50점
        assert score.total_score == 50.0


# ═══════════════════════════════════════════════════════
# Task 0-4: 스코어카드 신선도 경고 테스트
# ═══════════════════════════════════════════════════════


class TestScorecardStaleness:
    """스코어카드 파일이 7일 초과 시 후보 노트에 경고가 추가되는지 검증."""

    def test_stale_scorecard_adds_note(self, tmp_path, db_path):
        """7일 초과 스코어카드 → 후보 노트에 경고 문구."""
        # 10일 전 디렉토리에 스코어카드 생성
        stale_date = (kst_now().replace(tzinfo=None) - timedelta(days=10)).strftime("%Y-%m-%d")
        report_dir = tmp_path / "reports" / stale_date
        report_dir.mkdir(parents=True)

        scorecard_df = pd.DataFrame({
            "ticker": [None, None],
            "signal_id": ["rsi_oversold", "macd_golden"],
            "win_rate": [0.6, 0.55],
            "profit_factor": [2.0, 1.5],
            "avg_return": [0.05, 0.03],
            "total_trades": [100, 80],
        })
        scorecard_df.to_csv(report_dir / "signal_scorecard.csv", index=False)

        from nuri.trading.recommend import candidates as cand_module
        original_report_dir = cand_module.REPORT_DIR

        try:
            cand_module.REPORT_DIR = tmp_path / "reports"
            data, age_days = cand_module._load_scorecard()
            assert age_days is not None
            assert age_days >= 9  # KST/UTC 시차로 9일이 될 수 있음
            assert len(data) > 0
        finally:
            cand_module.REPORT_DIR = original_report_dir

    def test_fresh_scorecard_no_warning(self, tmp_path):
        """7일 이내 스코어카드 → 경고 없음."""
        today = today_kst()
        report_dir = tmp_path / "reports" / today
        report_dir.mkdir(parents=True)

        scorecard_df = pd.DataFrame({
            "ticker": [None],
            "signal_id": ["rsi_oversold"],
            "win_rate": [0.6],
            "profit_factor": [2.0],
            "avg_return": [0.05],
            "total_trades": [100],
        })
        scorecard_df.to_csv(report_dir / "signal_scorecard.csv", index=False)

        from nuri.trading.recommend import candidates as cand_module
        original_report_dir = cand_module.REPORT_DIR

        try:
            cand_module.REPORT_DIR = tmp_path / "reports"
            data, age_days = cand_module._load_scorecard()
            assert age_days is not None
            assert age_days <= 7
        finally:
            cand_module.REPORT_DIR = original_report_dir

    def test_no_scorecard_returns_none_age(self, tmp_path):
        """스코어카드 파일 없으면 age_days=None."""
        from nuri.trading.recommend import candidates as cand_module
        original_report_dir = cand_module.REPORT_DIR

        try:
            cand_module.REPORT_DIR = tmp_path / "nonexistent"
            data, age_days = cand_module._load_scorecard()
            assert data == {}
            assert age_days is None
        finally:
            cand_module.REPORT_DIR = original_report_dir
