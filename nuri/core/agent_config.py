"""에이전트 설정 로더 — config/agents.yaml에서 에이전트별 임계값을 로드.

사용법:
    from nuri.core.agent_config import AGENT_CONFIG
    cfg = AGENT_CONFIG["technical"]
    rsi_oversold = cfg["rsi_oversold"]   # 30
    conf_cap = cfg["confidence"]["cap"]  # 90
"""
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "agents.yaml"


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


AGENT_CONFIG: dict = _load_config()
