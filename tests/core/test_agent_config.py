"""nuri.core.agent_config 모듈 테스트 — YAML 로딩 + 설정 접근."""

import importlib
from unittest.mock import patch

import pytest
import yaml


class TestLoadConfig:
    """_load_config() 함수 동작 검증."""

    def test_loads_valid_yaml(self, tmp_path):
        """유효한 YAML을 딕셔너리로 로드."""
        cfg_file = tmp_path / "agents.yaml"
        cfg_file.write_text(
            yaml.dump({"technical": {"rsi_oversold": 30}}), encoding="utf-8"
        )

        import nuri.core.agent_config as mod

        with patch.object(mod, "_CONFIG_PATH", cfg_file):
            result = mod._load_config()

        assert result == {"technical": {"rsi_oversold": 30}}

    def test_missing_file_returns_empty_dict(self, tmp_path):
        """설정 파일이 없으면 빈 딕셔너리 반환."""
        import nuri.core.agent_config as mod

        missing = tmp_path / "nonexistent.yaml"
        with patch.object(mod, "_CONFIG_PATH", missing):
            result = mod._load_config()

        assert result == {}

    def test_empty_yaml_returns_empty_dict(self, tmp_path):
        """빈 YAML 파일 → 빈 딕셔너리."""
        cfg_file = tmp_path / "agents.yaml"
        cfg_file.write_text("", encoding="utf-8")

        import nuri.core.agent_config as mod

        with patch.object(mod, "_CONFIG_PATH", cfg_file):
            result = mod._load_config()

        assert result == {}

    def test_yaml_with_only_null_returns_empty_dict(self, tmp_path):
        """YAML 내용이 null만 있을 때 빈 딕셔너리 반환."""
        cfg_file = tmp_path / "agents.yaml"
        cfg_file.write_text("null\n", encoding="utf-8")

        import nuri.core.agent_config as mod

        with patch.object(mod, "_CONFIG_PATH", cfg_file):
            result = mod._load_config()

        assert result == {}


class TestAgentConfig:
    """모듈 레벨 AGENT_CONFIG 상수 검증."""

    def test_agent_config_is_dict(self):
        """AGENT_CONFIG가 dict 타입."""
        from nuri.core.agent_config import AGENT_CONFIG

        assert isinstance(AGENT_CONFIG, dict)

    def test_agent_config_has_expected_keys(self):
        """실제 config/agents.yaml에서 로드된 주요 키 확인."""
        from nuri.core.agent_config import AGENT_CONFIG

        # 실제 파일이 있으면 이 키들이 존재해야 함
        if AGENT_CONFIG:
            expected_agents = {
                "technical", "fundamental", "macro", "risk",
                "smart_money", "wallstreet", "korean_market",
                "options", "crypto", "retail",
            }
            for agent in expected_agents:
                assert agent in AGENT_CONFIG, f"Missing agent config: {agent}"

    def test_confidence_normalization_section(self):
        """confidence_normalization 섹션이 존재하고 올바른 구조."""
        from nuri.core.agent_config import AGENT_CONFIG

        if AGENT_CONFIG:
            cn = AGENT_CONFIG.get("confidence_normalization", {})
            assert "enabled" in cn
            assert "scales" in cn
            for agent_name, scale in cn["scales"].items():
                assert "raw_min" in scale, f"{agent_name} missing raw_min"
                assert "raw_max" in scale, f"{agent_name} missing raw_max"
                assert scale["raw_min"] < scale["raw_max"], (
                    f"{agent_name}: raw_min >= raw_max"
                )

    def test_reload_with_custom_yaml(self, tmp_path):
        """커스텀 YAML로 _load_config를 다시 호출하면 새 값 반환."""
        import nuri.core.agent_config as mod

        cfg_file = tmp_path / "agents.yaml"
        cfg_file.write_text(
            yaml.dump({
                "consensus": {"risk_veto_threshold": 99},
                "technical": {"rsi_oversold": 25},
            }),
            encoding="utf-8",
        )
        with patch.object(mod, "_CONFIG_PATH", cfg_file):
            result = mod._load_config()

        assert result["consensus"]["risk_veto_threshold"] == 99
        assert result["technical"]["rsi_oversold"] == 25

    def test_nested_confidence_block_structure(self, tmp_path):
        """에이전트별 confidence 블록의 cap 필드 검증."""
        import nuri.core.agent_config as mod

        cfg_file = tmp_path / "agents.yaml"
        cfg_file.write_text(
            yaml.dump({
                "technical": {"confidence": {"cap": 90, "hold": 40}},
            }),
            encoding="utf-8",
        )
        with patch.object(mod, "_CONFIG_PATH", cfg_file):
            result = mod._load_config()

        assert result["technical"]["confidence"]["cap"] == 90
        assert result["technical"]["confidence"]["hold"] == 40
