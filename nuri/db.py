# Backward-compatible re-export — 실제 코드는 nuri/core/db.py
from nuri.core.db import *  # noqa: F401,F403
from nuri.core.db import init_db, get_db, get_connection, query, query_df, \
    upsert_prices, upsert_macro, upsert_portfolio, get_tickers, _SCHEMA
