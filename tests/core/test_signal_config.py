"""nuri.core.signal_config 모듈 테스트 — 시그널 YAML 로딩 + 헬퍼 함수."""

from unittest.mock import patch

import pytest
import yaml


class TestLoadConfig:
    """_load_config() 함수 동작 검증."""

    def test_loads_valid_yaml(self, tmp_path):
        """유효한 signals YAML을 딕셔너리로 로드."""
        cfg_file = tmp_path / "signals.yaml"
        cfg_file.write_text(
            yaml.dump({"signals": {"rsi_oversold": {"type": "BUY"}}}),
            encoding="utf-8",
        )

        import nuri.core.signal_config as mod

        with patch.object(mod, "_CONFIG_PATH", cfg_file):
            result = mod._load_config()

        assert result == {"signals": {"rsi_oversold": {"type": "BUY"}}}

    def test_missing_file_returns_empty_dict(self, tmp_path):
        """설정 파일이 없으면 빈 딕셔너리 반환."""
        import nuri.core.signal_config as mod

        missing = tmp_path / "nonexistent.yaml"
        with patch.object(mod, "_CONFIG_PATH", missing):
            result = mod._load_config()

        assert result == {}

    def test_empty_yaml_returns_empty_dict(self, tmp_path):
        """빈 YAML 파일 → 빈 딕셔너리."""
        cfg_file = tmp_path / "signals.yaml"
        cfg_file.write_text("", encoding="utf-8")

        import nuri.core.signal_config as mod

        with patch.object(mod, "_CONFIG_PATH", cfg_file):
            result = mod._load_config()

        assert result == {}

    def test_yaml_with_only_null_returns_empty_dict(self, tmp_path):
        """YAML 내용이 null만 있을 때 빈 딕셔너리 반환."""
        cfg_file = tmp_path / "signals.yaml"
        cfg_file.write_text("null\n", encoding="utf-8")

        import nuri.core.signal_config as mod

        with patch.object(mod, "_CONFIG_PATH", cfg_file):
            result = mod._load_config()

        assert result == {}


class TestSignalConfig:
    """모듈 레벨 SIGNAL_CONFIG 상수 검증."""

    def test_signal_config_is_dict(self):
        from nuri.core.signal_config import SIGNAL_CONFIG

        assert isinstance(SIGNAL_CONFIG, dict)

    def test_has_signals_section(self):
        """실제 config/signals.yaml에서 signals 섹션 존재."""
        from nuri.core.signal_config import SIGNAL_CONFIG

        if SIGNAL_CONFIG:
            assert "signals" in SIGNAL_CONFIG
            assert len(SIGNAL_CONFIG["signals"]) > 0


class TestGetSignalMeta:
    """get_signal_meta() — 시그널 메타데이터 반환."""

    def test_existing_signal(self):
        from nuri.core.signal_config import SIGNAL_CONFIG, get_signal_meta

        if SIGNAL_CONFIG:
            meta = get_signal_meta("rsi_oversold")
            assert "type" in meta
            assert meta["type"] == "BUY"
            assert "description" in meta

    def test_nonexistent_signal_returns_empty_dict(self):
        from nuri.core.signal_config import get_signal_meta

        result = get_signal_meta("totally_fake_signal_xyz")
        assert result == {}

    def test_returns_dict_type(self):
        from nuri.core.signal_config import get_signal_meta

        result = get_signal_meta("rsi_oversold")
        assert isinstance(result, dict)

    def test_with_custom_config(self, tmp_path):
        """커스텀 SIGNAL_CONFIG로 메타데이터 조회."""
        import nuri.core.signal_config as mod

        custom = {
            "signals": {
                "test_signal": {
                    "description": "Test",
                    "type": "SELL",
                    "hold_days": 10,
                    "enabled": True,
                    "params": {"threshold": 42},
                },
            },
        }
        with patch.object(mod, "SIGNAL_CONFIG", custom):
            meta = mod.get_signal_meta("test_signal")

        assert meta["type"] == "SELL"
        assert meta["hold_days"] == 10


class TestGetSignalParams:
    """get_signal_params() — 시그널 파라미터 반환."""

    def test_existing_signal_with_params(self):
        from nuri.core.signal_config import SIGNAL_CONFIG, get_signal_params

        if SIGNAL_CONFIG:
            params = get_signal_params("rsi_oversold")
            assert isinstance(params, dict)
            assert "threshold" in params
            assert params["threshold"] == 30

    def test_signal_without_params_returns_empty_dict(self):
        """params가 없는 시그널 → 빈 dict."""
        import nuri.core.signal_config as mod

        custom = {"signals": {"no_params": {"type": "BUY"}}}
        with patch.object(mod, "SIGNAL_CONFIG", custom):
            result = mod.get_signal_params("no_params")

        assert result == {}

    def test_signal_with_null_params_returns_empty_dict(self):
        """params: null → 빈 dict."""
        import nuri.core.signal_config as mod

        custom = {"signals": {"null_params": {"type": "BUY", "params": None}}}
        with patch.object(mod, "SIGNAL_CONFIG", custom):
            result = mod.get_signal_params("null_params")

        assert result == {}

    def test_nonexistent_signal_returns_empty_dict(self):
        from nuri.core.signal_config import get_signal_params

        result = get_signal_params("nonexistent_signal_xyz")
        assert result == {}


class TestIsEnabled:
    """is_enabled() — 시그널 활성화 여부."""

    def test_enabled_signal(self):
        """enabled: true → True."""
        import nuri.core.signal_config as mod

        custom = {"signals": {"sig": {"enabled": True}}}
        with patch.object(mod, "SIGNAL_CONFIG", custom):
            assert mod.is_enabled("sig") is True

    def test_disabled_signal(self):
        """enabled: false → False."""
        import nuri.core.signal_config as mod

        custom = {"signals": {"sig": {"enabled": False}}}
        with patch.object(mod, "SIGNAL_CONFIG", custom):
            assert mod.is_enabled("sig") is False

    def test_missing_enabled_defaults_true(self):
        """enabled 키 미정의 → True (안전한 기본값)."""
        import nuri.core.signal_config as mod

        custom = {"signals": {"sig": {"type": "BUY"}}}
        with patch.object(mod, "SIGNAL_CONFIG", custom):
            assert mod.is_enabled("sig") is True

    def test_nonexistent_signal_defaults_true(self):
        """존재하지 않는 시그널 → True."""
        from nuri.core.signal_config import is_enabled

        assert is_enabled("nonexistent_signal_xyz") is True


class TestListBuySignals:
    """list_buy_signals() — BUY 타입 시그널 목록."""

    def test_returns_set(self):
        from nuri.core.signal_config import list_buy_signals

        result = list_buy_signals()
        assert isinstance(result, set)

    def test_contains_known_buy_signals(self):
        from nuri.core.signal_config import SIGNAL_CONFIG, list_buy_signals

        if SIGNAL_CONFIG:
            buy_signals = list_buy_signals()
            assert "rsi_oversold" in buy_signals
            assert "macd_golden" in buy_signals
            assert "bb_bounce" in buy_signals

    def test_excludes_sell_signals(self):
        from nuri.core.signal_config import SIGNAL_CONFIG, list_buy_signals

        if SIGNAL_CONFIG:
            buy_signals = list_buy_signals()
            assert "rsi_overbought" not in buy_signals
            assert "macd_dead" not in buy_signals

    def test_excludes_disabled_signals(self):
        """enabled: false인 BUY 시그널은 제외."""
        import nuri.core.signal_config as mod

        custom = {
            "signals": {
                "active_buy": {"type": "BUY", "enabled": True},
                "disabled_buy": {"type": "BUY", "enabled": False},
                "sell_sig": {"type": "SELL", "enabled": True},
            },
        }
        with patch.object(mod, "SIGNAL_CONFIG", custom):
            result = mod.list_buy_signals()

        assert result == {"active_buy"}

    def test_empty_config_returns_empty_set(self):
        """빈 설정 → 빈 set."""
        import nuri.core.signal_config as mod

        with patch.object(mod, "SIGNAL_CONFIG", {}):
            result = mod.list_buy_signals()

        assert result == set()


class TestListSellSignals:
    """list_sell_signals() — SELL 타입 시그널 목록."""

    def test_returns_set(self):
        from nuri.core.signal_config import list_sell_signals

        result = list_sell_signals()
        assert isinstance(result, set)

    def test_contains_known_sell_signals(self):
        from nuri.core.signal_config import SIGNAL_CONFIG, list_sell_signals

        if SIGNAL_CONFIG:
            sell_signals = list_sell_signals()
            assert "rsi_overbought" in sell_signals
            assert "macd_dead" in sell_signals
            assert "sma_dead" in sell_signals

    def test_excludes_buy_signals(self):
        from nuri.core.signal_config import SIGNAL_CONFIG, list_sell_signals

        if SIGNAL_CONFIG:
            sell_signals = list_sell_signals()
            assert "rsi_oversold" not in sell_signals
            assert "bb_bounce" not in sell_signals

    def test_excludes_disabled_signals(self):
        """enabled: false인 SELL 시그널은 제외."""
        import nuri.core.signal_config as mod

        custom = {
            "signals": {
                "active_sell": {"type": "SELL", "enabled": True},
                "disabled_sell": {"type": "SELL", "enabled": False},
                "buy_sig": {"type": "BUY", "enabled": True},
            },
        }
        with patch.object(mod, "SIGNAL_CONFIG", custom):
            result = mod.list_sell_signals()

        assert result == {"active_sell"}

    def test_empty_config_returns_empty_set(self):
        """빈 설정 → 빈 set."""
        import nuri.core.signal_config as mod

        with patch.object(mod, "SIGNAL_CONFIG", {}):
            result = mod.list_sell_signals()

        assert result == set()
