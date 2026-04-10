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
        portfolio_yaml.write_text(yaml.dump({
            "accounts": {
                "test_acct": {"strategy": "swing", "tickers": {}},
            }
        }))

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
        portfolio_yaml.write_text(yaml.dump({
            "accounts": {
                "test_acct": {"tickers": {}},
            }
        }))

        with patch("builtins.open", side_effect=lambda p, **kw: open(portfolio_yaml, **kw)):
            result = get_account_strategy("test_acct")
            assert result["stop_loss"] == -7  # core default


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
