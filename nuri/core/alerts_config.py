"""알림 설정 로더 — config/alerts.yaml에서 알림 임계값을 로드.

사용법:
    from nuri.core.alerts_config import ALERTS_CONFIG
    fg_low = ALERTS_CONFIG["alerts"]["fear_greed_low"]   # 20
"""

from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "alerts.yaml"


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


ALERTS_CONFIG: dict = _load_config()
