"""투자 규칙 로더 — config/rules.yaml에서 규칙을 로드.

사용법:
    from nuri.rules import RULES
    max_pos = RULES["position_limits"]["max_single_position"]
"""
from pathlib import Path

import yaml

_RULES_PATH = Path(__file__).parent.parent.parent / "config" / "rules.yaml"

def _load_rules() -> dict:
    if _RULES_PATH.exists():
        with open(_RULES_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)
    # 폴백 (파일 없을 때)
    return {
        "position_limits": {"max_single_position": 0.15, "max_sector_exposure": 0.35},
        "stop_loss": {"per_stock": -20, "portfolio": -10},
        "leverage": {"banned_etfs": ["TSLL", "TQQQ", "SQQQ", "UPRO", "SPXU"]},
    }

RULES = _load_rules()

# 편의 상수 (기존 코드 호환)
MAX_SINGLE_POSITION = RULES["position_limits"]["max_single_position"]
MAX_SECTOR_EXPOSURE = RULES["position_limits"]["max_sector_exposure"]
STOCK_STOP_LOSS = RULES["stop_loss"]["per_stock"]
PORTFOLIO_STOP = RULES["stop_loss"]["portfolio"]
LEVERAGE_ETFS = set(RULES["leverage"]["banned_etfs"])
