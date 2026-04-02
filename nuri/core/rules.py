"""투자 규칙 로더 — config/rules.yaml에서 규칙을 로드.

사용법:
    from nuri.core.rules import RULES
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

# ─── 포지션 한도 ───
MAX_SINGLE_POSITION = RULES["position_limits"]["max_single_position"]
MAX_SECTOR_EXPOSURE = RULES["position_limits"]["max_sector_exposure"]
MIN_CASH_RESERVE = RULES.get("position_limits", {}).get("min_cash_reserve", 0.20)

# ─── 손절 ───
STOCK_STOP_LOSS = RULES["stop_loss"]["per_stock"]
STOCK_STOP_LOSS_VALUE = RULES.get("stop_loss", {}).get("per_stock_value", -10)
PORTFOLIO_STOP = RULES["stop_loss"]["portfolio"]

# ─── 익절 ───
_tp = RULES.get("take_profit", {})
TAKE_PROFIT_GROWTH = _tp.get("growth", {"target_1": 20, "target_2": 40})
TAKE_PROFIT_VALUE = _tp.get("value", {"target_1": 15, "target_2": 30})
TAKE_PROFIT_SWING = _tp.get("swing", {"target_1": 5, "target_2": 10})
SWING_STOP_LOSS = TAKE_PROFIT_SWING.get("stop_loss", -5)
SWING_MAX_HOLD_DAYS = TAKE_PROFIT_SWING.get("max_hold_days", 7)
SWING_MIN_SCAN_SCORE = TAKE_PROFIT_SWING.get("min_scan_score", 20)
SWING_MIN_AGENT_CONFIDENCE = TAKE_PROFIT_SWING.get("min_agent_confidence", 50)

# ─── 트레일링 스톱 ───
_ts = RULES.get("trailing_stop", {})
TRAILING_STOP_GROWTH = _ts.get("growth", -15)
TRAILING_STOP_VALUE = _ts.get("value", -15)
TRAILING_STOP_VOLATILE = _ts.get("volatile", -20)

# ─── 매수 진입 조건 ───
_entry = RULES.get("entry_rules", {})
VIX_BLOCK_ABOVE = _entry.get("vix_gate", {}).get("block_above", 30)
VIX_CAUTION_ABOVE = _entry.get("vix_gate", {}).get("caution_above", 25)
REGIME_CASH = _entry.get("regime_cash", {
    "extreme_fear": 0.60, "fear": 0.40, "neutral": 0.25,
    "greed": 0.20, "extreme_greed": 0.40,
})
MAX_TRANCHES = _entry.get("scaling_in", {}).get("max_tranches", 3)
TRANCHE_INTERVAL_DAYS = _entry.get("scaling_in", {}).get("tranche_interval_days", 5)

# ─── 매수 체크리스트 ───
_chk = RULES.get("buy_checklist", {})
MIN_TIPRANKS_CONSENSUS = _chk.get("min_tipranks_consensus", "moderate_buy")
MIN_SUPERINVESTORS = _chk.get("min_superinvestors", 3)
MAX_PE_RATIO = _chk.get("max_pe_ratio", 100)
MIN_REVENUE_GROWTH = _chk.get("min_revenue_growth", 0)
REQUIRE_FACTOR_TOP50 = _chk.get("require_factor_top50pct", True)

# ─── 매도 우선순위 ───
SELL_PRIORITY = RULES.get("sell_priority", [
    "leverage_etf", "stop_loss_exceeded", "no_superinvestor",
    "position_limit_exceeded", "sector_limit_exceeded",
])

# ─── 레버리지 제한 ───
LEVERAGE_ETFS = set(RULES["leverage"]["banned_etfs"])
LEVERAGE_MAX_DAYS = RULES.get("leverage", {}).get("max_holding_days", 5)
