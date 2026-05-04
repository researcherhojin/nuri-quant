"""Market data writes — prices, macro, signals, ARK, events, news, macro_events.

All upsert/insert helpers for external data feeds. Read paths (for analysis)
go through `query()` / `query_df()` at the facade root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from .connection import get_db


def upsert_prices(df: pd.DataFrame, db_path: Optional[Path] = None) -> int:
    """가격 데이터 DataFrame upsert."""
    if df.empty:
        return 0
    with get_db(db_path) as conn:
        rows = df.to_dict("records")
        conn.executemany(
            """INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume, adj_close)
               VALUES (:ticker, :date, :open, :high, :low, :close, :volume, :adj_close)""",
            rows,
        )
        return len(rows)


def upsert_macro(records: list[dict], db_path: Optional[Path] = None) -> int:
    """매크로 지표 upsert."""
    if not records:
        return 0
    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO macro (indicator, date, value, source)
               VALUES (:indicator, :date, :value, :source)""",
            records,
        )
        return len(records)


def upsert_signals(df: pd.DataFrame, db_path: Optional[Path] = None) -> int:
    """기술적 지표 DataFrame upsert."""
    if df.empty:  # pragma: no cover — empty DataFrame guard
        return 0
    with get_db(db_path) as conn:
        rows = df.to_dict("records")
        conn.executemany(
            """INSERT OR REPLACE INTO signals
               (ticker, date, rsi_14, macd, macd_signal, macd_hist,
                bb_upper, bb_middle, bb_lower, sma_20, sma_50, sma_200, ema_12, ema_26)
               VALUES (:ticker, :date, :rsi_14, :macd, :macd_signal, :macd_hist,
                       :bb_upper, :bb_middle, :bb_lower,
                       :sma_20, :sma_50, :sma_200, :ema_12, :ema_26)""",
            rows,
        )
        return len(rows)


def upsert_ark(records: list[dict], db_path: Optional[Path] = None) -> int:
    """ARK 매매 내역 upsert."""
    if not records:
        return 0
    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO ark (date, ticker, direction, shares, weight, fund)
               VALUES (:date, :ticker, :direction, :shares, :weight, :fund)""",
            records,
        )
        return len(records)


def insert_events(records: list[dict], db_path: Optional[Path] = None) -> int:
    """이벤트 추가 (중복 허용, additive)."""
    if not records:  # pragma: no cover — empty-records guard
        return 0
    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT INTO events (date, event_type, ticker, description, importance)
               VALUES (:date, :event_type, :ticker, :description, :importance)""",
            records,
        )
        return len(records)


def upsert_news(records: list[dict], db_path: Optional[Path] = None) -> int:
    """뉴스 upsert (URL 기준 중복 제거). 반환값은 실제 신규 삽입 건수 (dedup 후).

    이전에는 `len(records)` 를 그대로 반환하여 URL UNIQUE 로 IGNORE 된 행도 카운트에
    포함됐다 (#351). `cursor.rowcount` 는 INSERT OR IGNORE 에서 실제 inserted 수만
    반환하므로 로그 "뉴스 N 건 수집" 이 DB 상태와 일치한다 (§2.4 Observability).
    """
    if not records:
        return 0
    with get_db(db_path) as conn:
        cur = conn.executemany(
            """INSERT OR IGNORE INTO news (ticker, date, title, url, source, sentiment)
               VALUES (:ticker, :date, :title, :url, :source, :sentiment)""",
            records,
        )
        return cur.rowcount


def upsert_macro_events(records: list[dict], db_path: Optional[Path] = None) -> int:
    """매크로 이벤트 upsert (URL 기준 중복 제거).

    레코드 키: published_at, source, query_keyword, headline, url,
              category, sentiment, confidence, regime_hint, raw_json,
              classification_method (optional)
    URL이 이미 존재하면 INSERT OR IGNORE로 스킵.
    """
    if not records:
        return 0
    # classification_method가 없는 레코드 호환 처리
    for r in records:
        r.setdefault("classification_method", None)
    with get_db(db_path) as conn:
        cursor = conn.executemany(
            """INSERT OR IGNORE INTO macro_events
               (published_at, source, query_keyword, headline, url,
                category, sentiment, confidence, regime_hint, raw_json,
                classification_method)
               VALUES (:published_at, :source, :query_keyword, :headline, :url,
                       :category, :sentiment, :confidence, :regime_hint, :raw_json,
                       :classification_method)""",
            records,
        )
        return cursor.rowcount if cursor.rowcount >= 0 else len(records)
