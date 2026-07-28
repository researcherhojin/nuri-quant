"""nuri.core.rules 모듈 테스트 — YAML 로딩, 상수 노출, 계좌별 전략 프로파일."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from nuri.core.db import init_db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


# ═══════════════════════════════════════════════════════
# YAML 로딩 + 상수 노출 테스트
# ═══════════════════════════════════════════════════════


class TestRulesLoading:
    def test_rules_dict_loaded(self):
        from nuri.core.rules import RULES

        assert isinstance(RULES, dict)
        assert "position_limits" in RULES
        assert "stop_loss" in RULES

    def test_position_limit_constants(self):
        from nuri.core.rules import MAX_SECTOR_EXPOSURE, MAX_SINGLE_POSITION, MIN_CASH_RESERVE

        assert 0 < MAX_SINGLE_POSITION <= 1.0
        assert 0 < MAX_SECTOR_EXPOSURE <= 1.0
        assert 0 < MIN_CASH_RESERVE <= 1.0

    def test_stop_loss_constants(self):
        from nuri.core.rules import PORTFOLIO_STOP, STOCK_STOP_LOSS, STOCK_STOP_LOSS_VALUE

        assert STOCK_STOP_LOSS < 0
        assert STOCK_STOP_LOSS_VALUE < 0
        assert PORTFOLIO_STOP < 0

    def test_take_profit_constants(self):
        from nuri.core.rules import TAKE_PROFIT_GROWTH, TAKE_PROFIT_SWING, TAKE_PROFIT_VALUE

        assert TAKE_PROFIT_GROWTH["target_1"] > 0
        assert TAKE_PROFIT_VALUE["target_1"] > 0
        assert TAKE_PROFIT_SWING["target_1"] > 0

    def test_trailing_stop_constants(self):
        from nuri.core.rules import TRAILING_STOP_GROWTH, TRAILING_STOP_VALUE, TRAILING_STOP_VOLATILE

        assert TRAILING_STOP_GROWTH < 0
        assert TRAILING_STOP_VALUE < 0
        assert TRAILING_STOP_VOLATILE < 0

    def test_leverage_etfs(self):
        from nuri.core.rules import LEVERAGE_ETFS

        assert isinstance(LEVERAGE_ETFS, set)
        assert "TQQQ" in LEVERAGE_ETFS
        assert "TSLL" in LEVERAGE_ETFS


class TestAccountStrategies:
    def test_account_strategies_loaded(self):
        from nuri.core.rules import ACCOUNT_STRATEGIES

        assert "core" in ACCOUNT_STRATEGIES
        assert "active" in ACCOUNT_STRATEGIES
        assert "swing" in ACCOUNT_STRATEGIES
        assert "long_term" in ACCOUNT_STRATEGIES
        assert "pension" in ACCOUNT_STRATEGIES

    def test_core_strategy_values(self):
        from nuri.core.rules import ACCOUNT_STRATEGIES

        core = ACCOUNT_STRATEGIES["core"]
        assert core["stop_loss"] == -7
        assert core["max_single_position"] == 0.15

    def test_active_strategy_between_core_and_swing(self):
        """active 전략은 core와 swing 사이의 중간값."""
        from nuri.core.rules import ACCOUNT_STRATEGIES

        core = ACCOUNT_STRATEGIES["core"]
        active = ACCOUNT_STRATEGIES["active"]
        swing = ACCOUNT_STRATEGIES["swing"]
        # 손절은 core(-7)보다 넓고 swing(-15)보다 좁음
        assert core["stop_loss"] > active["stop_loss"] > swing["stop_loss"]
        assert active["stop_loss"] == -10
        # 비중은 core(0.15)보다 크고 swing(0.30)보다 작음
        assert core["max_single_position"] < active["max_single_position"] < swing["max_single_position"]
        assert active["max_single_position"] == 0.25
        # trailing_stop_arm 신규 필드
        assert active["trailing_stop_arm"] == 15

    def test_swing_strategy_more_permissive(self):
        from nuri.core.rules import ACCOUNT_STRATEGIES

        core = ACCOUNT_STRATEGIES["core"]
        swing = ACCOUNT_STRATEGIES["swing"]
        assert swing["stop_loss"] < core["stop_loss"]  # -15 < -7 (더 넓은 허용)
        assert swing["max_single_position"] > core["max_single_position"]

    def test_get_account_strategy_reads_portfolio(self, db_path, tmp_path):
        """portfolio.yaml의 strategy 필드로 프로파일 매핑."""
        from nuri.core.rules import get_account_strategy

        portfolio_yaml = tmp_path / "portfolio.yaml"
        portfolio_yaml.write_text(
            yaml.dump(
                {
                    "accounts": {
                        "test_acct": {"strategy": "swing", "tickers": {}},
                    }
                }
            )
        )

        real_open = open

        def mock_open(path, **kwargs):
            # portfolio.yaml 경로만 tmp_path로 리다이렉트
            if str(path).endswith("portfolio.yaml"):
                return real_open(portfolio_yaml, **kwargs)
            return real_open(path, **kwargs)

        with patch("builtins.open", side_effect=mock_open):
            result = get_account_strategy("test_acct")
            assert result["stop_loss"] == -15  # swing
            assert result["max_single_position"] == 0.30

    def test_get_account_strategy_fallback_to_core(self):
        """portfolio.yaml 없거나 계좌 없으면 core 기본값."""
        from nuri.core.rules import get_account_strategy

        with patch("builtins.open", side_effect=FileNotFoundError):
            result = get_account_strategy("nonexistent")
            assert result["stop_loss"] == -7  # core default

    def test_get_account_strategy_missing_strategy_field(self, tmp_path):
        """strategy 필드 없으면 core 기본값."""
        from nuri.core.rules import get_account_strategy

        portfolio_yaml = tmp_path / "portfolio.yaml"
        portfolio_yaml.write_text(
            yaml.dump(
                {
                    "accounts": {
                        "test_acct": {"tickers": {}},
                    }
                }
            )
        )

        with patch("builtins.open", side_effect=lambda p, **kw: open(portfolio_yaml, **kw)):
            result = get_account_strategy("test_acct")
            assert result["stop_loss"] == -7  # core default

    def test_get_account_strategy_name_reads_yaml_name(self, tmp_path):
        """이름(dict 아닌 name string) 반환 — pension 판별용."""
        from nuri.core.rules import get_account_strategy_name

        portfolio_yaml = tmp_path / "portfolio.yaml"
        portfolio_yaml.write_text(yaml.dump({"accounts": {"P_acct": {"strategy": "pension"}}}))

        real_open = open

        def mock_open(path, **kwargs):
            if str(path).endswith("portfolio.yaml"):
                return real_open(portfolio_yaml, **kwargs)
            return real_open(path, **kwargs)

        with patch("builtins.open", side_effect=mock_open):
            assert get_account_strategy_name("P_acct") == "pension"
            assert get_account_strategy_name("unknown_acct") == "core"  # 매칭 실패 → core

    def test_get_account_strategy_name_none_returns_core(self):
        from nuri.core.rules import get_account_strategy_name

        assert get_account_strategy_name(None) == "core"

    def test_get_account_strategy_name_exception_returns_core(self):
        from nuri.core.rules import get_account_strategy_name

        with patch("builtins.open", side_effect=FileNotFoundError):
            assert get_account_strategy_name("any") == "core"


# ═══════════════════════════════════════════════════════
# §3.11 측정 모드 — 사전 고정 판정 기준 lock
# ═══════════════════════════════════════════════════════


class TestMeasurementMode:
    """STRATEGY §3.11 (#824/#828) — 판정 기준은 사전 고정. 이 lock 을 깨는 변경은
    STRATEGY PR (본 테스트 + §3.11 표 동시 개정) 을 강제해 silent amend 를 차단한다."""

    def test_adjudication_params_locked(self):
        from nuri.core.rules import RULES

        mm = RULES["measurement_mode"]
        assert mm["enabled"] is True
        assert mm["declared_date"] == "2026-07-08"
        assert mm["evaluation_date"] == "2027-06-30"
        assert mm["emit_cutoff_date"] == "2027-05-15"
        assert mm["primary_window_days"] == 30
        # 키 이름이 모집단 정의 (US-only, BUY-only) 까지 잠근다 — rename = silent amend 불가
        assert mm["min_n_us_buy_decisions"] == 200
        assert mm["permutation_p_max"] == 0.05
        assert mm["permutation_scheme"] == "ticker_block_placebo"
        assert mm["permutation_n"] == 1000
        assert mm["robustness_split"] == "median_split_halves"
        assert mm["missing_outcome_max_pct"] == 15

    def test_benchmark_matches_tracker_constant(self):
        """rules.yaml benchmark 와 tracker 코드 상수의 silent 분기 방지 (SSoT lock)."""
        from nuri.agents.actors.forward_outcome_tracker import DEFAULT_BENCHMARK_TICKER
        from nuri.core.rules import RULES

        assert RULES["measurement_mode"]["benchmark"] == DEFAULT_BENCHMARK_TICKER

    def test_benchmark_by_market_us_equals_the_locked_criterion(self):
        """시장별 map 의 us 항목은 사전등록된 판정 기준과 **같은 값**이어야 한다 (#833).

        map 은 기록용 측정 인프라이고 `benchmark` 는 §3.11 판정 기준이다. 둘이
        갈라지면 US 표본이 판정 기준과 다른 벤치마크로 측정되면서 아무 게이트도
        울리지 않는다 — 사전등록의 조용한 개정.

        Gotcha-Test Pair: `benchmark_by_market.us` 를 SPY 아닌 값으로 바꾸면 FAIL.
        """
        from nuri.agents.actors.forward_outcome_tracker import DEFAULT_BENCHMARK_TICKER
        from nuri.core.rules import RULES

        mm = RULES["measurement_mode"]
        assert mm["benchmark_by_market"]["us"] == mm["benchmark"] == DEFAULT_BENCHMARK_TICKER

    def test_benchmark_by_market_covers_every_market_the_classifier_emits(self):
        """`benchmark_for` 는 모든 티커를 us/kr 둘 중 하나로 보낸다 — map 도 딱 그 둘.

        키가 빠지면 폴백이 US 벤치마크를 조용히 쓰고, 남는 키는 아무도 안 읽는
        죽은 설정이 된다.
        """
        from nuri.core.rules import RULES

        assert set(RULES["measurement_mode"]["benchmark_by_market"]) == {"us", "kr"}

    def test_every_market_benchmark_is_actually_collected(self):
        """벤치마크가 수집 배선에 없으면 alpha 가 영구 NULL 이 된다 (#860 과 같은 고장).

        `069500.KS`(KODEX 200) 는 prices 에 단 한 행도 없어 KR 벤치마크로 쓰면
        모든 KR alpha 가 NULL 이 된다. 실제 수집되는 식별자만 등재되어야 한다.

        Gotcha-Test Pair: 수집 배선에 없는 티커를 map 에 넣으면 FAIL.
        """
        from nuri.collectors.stock import _load_freshness_tickers
        from nuri.collectors.stock_kr import StockKRCollector
        from nuri.core.rules import RULES

        collected = set(_load_freshness_tickers()) | set(StockKRCollector.INDEX_TICKERS.values())
        for market, ticker in RULES["measurement_mode"]["benchmark_by_market"].items():
            assert ticker in collected, f"{market} 벤치마크 {ticker} 가 일일 수집 대상에 없음"

    def test_primary_window_supported_by_tracker(self):
        """판정 창은 tracker 가 실제 측정하는 window 여야 함."""
        from nuri.agents.actors.forward_outcome_tracker import SUPPORTED_WINDOWS
        from nuri.core.rules import RULES

        assert RULES["measurement_mode"]["primary_window_days"] in SUPPORTED_WINDOWS

    def test_sleeve_caps_cover_all_strategies(self):
        """슬리브 상한은 account_strategies 5개 프로파일과 1:1 (누락/고아 키 방지)."""
        from nuri.core.rules import ACCOUNT_STRATEGIES, RULES

        sleeve = RULES["measurement_mode"]["sleeve_max_equity_pct"]
        assert set(sleeve.keys()) == set(ACCOUNT_STRATEGIES.keys())
        for name, pct in sleeve.items():
            assert 0 <= pct <= 100, f"{name}: equity 내부 % 범위 위반"

    def test_sleeve_cap_values_locked(self):
        """확정 초기값 lock (#848, 2026-07-08) — §3.11 상향-sticky 발효.

        상향은 판정 통과 + STRATEGY PR (본 테스트 동시 개정) 로만. 하향은
        prudential 상시 허용이나, silent 변경 방지 위해 값 자체를 고정한다
        — 하향도 의도라면 이 테스트를 함께 고치는 가시적 diff 를 남길 것."""
        from nuri.core.rules import RULES

        assert RULES["measurement_mode"]["sleeve_max_equity_pct"] == {
            "core": 10,
            "active": 20,
            "swing": 100,
            "long_term": 0,
            "pension": 0,
        }


# ═══════════════════════════════════════════════════════
# 폴백 테스트
# ═══════════════════════════════════════════════════════


class TestFallback:
    def test_load_rules_fallback(self):
        """rules.yaml 없을 때 폴백 값 반환."""
        from nuri.core.rules import _RULES_PATH, _load_rules

        with patch.object(type(_RULES_PATH), "exists", return_value=False):
            fallback = _load_rules()
            assert fallback["position_limits"]["max_single_position"] == 0.15
            assert fallback["stop_loss"]["per_stock"] == -20


# ═══════════════════════════════════════════════════════
# A-3 Unified sell engine — get_stop_loss_for_account
# ═══════════════════════════════════════════════════════


class TestGetStopLossForAccount:
    """§2.2 mechanical execution — risk_agent/actions 가 certification 과 동일한
    per-account threshold 를 쓰게 하는 helper. PnL 이 계산된 행의 account 와 같은
    account 의 threshold 를 쓰는지 검증 (aggregation mismatch 방지)."""

    def _patch_portfolio_yaml(self, tmp_path, accounts_cfg: dict):
        portfolio_yaml = tmp_path / "portfolio.yaml"
        portfolio_yaml.write_text(yaml.dump({"accounts": accounts_cfg}))
        real_open = open

        def _opener(path, **kwargs):
            if str(path).endswith("portfolio.yaml"):
                return real_open(portfolio_yaml, **kwargs)
            return real_open(path, **kwargs)

        return patch("builtins.open", side_effect=_opener)

    def test_none_account_falls_back_to_global(self):
        """account 가 None 이면 global STOCK_STOP_LOSS 반환."""
        from nuri.core.rules import STOCK_STOP_LOSS, get_stop_loss_for_account

        assert get_stop_loss_for_account(None) == int(STOCK_STOP_LOSS)

    def test_empty_account_falls_back_to_global(self):
        """account 가 "" (labels 조회 실패 fallback) 이면 global STOCK_STOP_LOSS."""
        from nuri.core.rules import STOCK_STOP_LOSS, get_stop_loss_for_account

        assert get_stop_loss_for_account("") == int(STOCK_STOP_LOSS)

    def test_core_account(self, tmp_path):
        """core 전략 계좌 → -7."""
        from nuri.core.rules import get_stop_loss_for_account

        with self._patch_portfolio_yaml(tmp_path, {"Main": {"strategy": "core"}}):
            assert get_stop_loss_for_account("Main") == -7

    def test_long_term_account(self, tmp_path):
        """long_term 전략 계좌 → -20 (핵심 fix: 이전 -7 global 하드코딩)."""
        from nuri.core.rules import get_stop_loss_for_account

        with self._patch_portfolio_yaml(tmp_path, {"Toss": {"strategy": "long_term"}}):
            assert get_stop_loss_for_account("Toss") == -20

    def test_pension_account(self, tmp_path):
        """pension 전략 → -30."""
        from nuri.core.rules import get_stop_loss_for_account

        with self._patch_portfolio_yaml(tmp_path, {"IRP": {"strategy": "pension"}}):
            assert get_stop_loss_for_account("IRP") == -30

    def test_unknown_account_falls_back_to_core(self, tmp_path):
        """portfolio.yaml 에 없는 account → get_account_strategy 가 core default 반환."""
        from nuri.core.rules import get_stop_loss_for_account

        with self._patch_portfolio_yaml(tmp_path, {"Main": {"strategy": "core"}}):
            assert get_stop_loss_for_account("Unknown") == -7  # core default

    def test_return_type_is_int(self):
        """certification.py 와 비교 연산 안정성."""
        from nuri.core.rules import get_stop_loss_for_account

        result = get_stop_loss_for_account(None)
        assert isinstance(result, int)
