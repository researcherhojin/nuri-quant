# Backward-compatible re-export — 실제 코드는 nuri/core/rules.py
from nuri.core.rules import *  # noqa: F401,F403
from nuri.core.rules import RULES, MAX_SINGLE_POSITION, MAX_SECTOR_EXPOSURE, \
    STOCK_STOP_LOSS, PORTFOLIO_STOP, LEVERAGE_ETFS
