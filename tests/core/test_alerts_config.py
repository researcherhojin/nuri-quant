"""nuri.core.alerts_config 모듈 테스트 — YAML 로딩 + 알림 설정."""

from unittest.mock import patch

import pytest
import yaml


class TestLoadConfig:
    """_load_config() 함수 동작 검증."""

    def test_loads_valid_yaml(self, tmp_path):
        """유효한 alerts YAML을 딕셔너리로 로드."""
        cfg_file = tmp_path / "alerts.yaml"
        cfg_file.write_text(
            yaml.dump({"alerts": {"price_swing_pct": 5.0}}), encoding="utf-8"
        )

        import nuri.core.alerts_config as mod

        with patch.object(mod, "_CONFIG_PATH", cfg_file):
            result = mod._load_config()

        assert result == {"alerts": {"price_swing_pct": 5.0}}

    def test_missing_file_returns_empty_dict(self, tmp_path):
        """설정 파일이 없으면 빈 딕셔너리 반환."""
        import nuri.core.alerts_config as mod

        missing = tmp_path / "nonexistent.yaml"
        with patch.object(mod, "_CONFIG_PATH", missing):
            result = mod._load_config()

        assert result == {}

    def test_empty_yaml_returns_empty_dict(self, tmp_path):
        """빈 YAML 파일 → 빈 딕셔너리."""
        cfg_file = tmp_path / "alerts.yaml"
        cfg_file.write_text("", encoding="utf-8")

        import nuri.core.alerts_config as mod

        with patch.object(mod, "_CONFIG_PATH", cfg_file):
            result = mod._load_config()

        assert result == {}

    def test_yaml_with_only_null_returns_empty_dict(self, tmp_path):
        """YAML 내용이 null만 있을 때 빈 딕셔너리 반환."""
        cfg_file = tmp_path / "alerts.yaml"
        cfg_file.write_text("null\n", encoding="utf-8")

        import nuri.core.alerts_config as mod

        with patch.object(mod, "_CONFIG_PATH", cfg_file):
            result = mod._load_config()

        assert result == {}


class TestAlertsConfig:
    """모듈 레벨 ALERTS_CONFIG 상수 검증."""

    def test_alerts_config_is_dict(self):
        """ALERTS_CONFIG가 dict 타입."""
        from nuri.core.alerts_config import ALERTS_CONFIG

        assert isinstance(ALERTS_CONFIG, dict)

    def test_alerts_section_structure(self):
        """실제 config/alerts.yaml에서 로드된 alerts 섹션 구조."""
        from nuri.core.alerts_config import ALERTS_CONFIG

        if ALERTS_CONFIG:
            alerts = ALERTS_CONFIG.get("alerts", {})
            assert "price_swing_pct" in alerts
            assert "fear_greed_low" in alerts
            assert "fear_greed_high" in alerts
            assert isinstance(alerts["price_swing_pct"], (int, float))

    def test_channels_section(self):
        """channels 섹션 존재 확인."""
        from nuri.core.alerts_config import ALERTS_CONFIG

        if ALERTS_CONFIG:
            channels = ALERTS_CONFIG.get("channels", {})
            assert isinstance(channels, dict)

    def test_notifications_section(self):
        """notifications 섹션 존재 및 boolean 값 확인."""
        from nuri.core.alerts_config import ALERTS_CONFIG

        if ALERTS_CONFIG:
            notifications = ALERTS_CONFIG.get("notifications", {})
            for key, val in notifications.items():
                assert isinstance(val, bool), (
                    f"notifications.{key} should be bool, got {type(val)}"
                )

    def test_reload_with_custom_yaml(self, tmp_path):
        """커스텀 YAML로 다시 로드."""
        import nuri.core.alerts_config as mod

        cfg_file = tmp_path / "alerts.yaml"
        cfg_file.write_text(
            yaml.dump({
                "alerts": {"price_swing_pct": 10.0, "fear_greed_low": 15},
                "channels": {"discord": False},
            }),
            encoding="utf-8",
        )
        with patch.object(mod, "_CONFIG_PATH", cfg_file):
            result = mod._load_config()

        assert result["alerts"]["price_swing_pct"] == 10.0
        assert result["alerts"]["fear_greed_low"] == 15
        assert result["channels"]["discord"] is False

    def test_fear_greed_thresholds_ordering(self):
        """fear_greed_low < fear_greed_high 검증."""
        from nuri.core.alerts_config import ALERTS_CONFIG

        if ALERTS_CONFIG:
            alerts = ALERTS_CONFIG.get("alerts", {})
            low = alerts.get("fear_greed_low")
            high = alerts.get("fear_greed_high")
            if low is not None and high is not None:
                assert low < high, f"fear_greed_low ({low}) >= fear_greed_high ({high})"
