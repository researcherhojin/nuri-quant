"""
Nuri-Quant 데이터베이스 모듈 — 모든 DB 접근의 단일 진입점.

다른 모듈에서 sqlite3를 직접 import하지 않는다.
모든 DB 작업은 이 모듈의 함수를 통해서만 수행한다.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import pandas as pd

DB_PATH = Path(__file__).parent.parent.parent / "data" / "portfolio.db"

# ═══════════════════════════════════════════════════════
# 연결 관리
# ═══════════════════════════════════════════════════════


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """DB 연결 반환. WAL 모드, foreign keys 활성화."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def get_db(db_path: Optional[Path] = None):
    """DB 컨텍스트 매니저. 성공 시 자동 commit, 실패 시 rollback."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════
# 스키마 초기화
# ═══════════════════════════════════════════════════════

_SCHEMA = """
-- 주가 데이터 (OHLCV)
CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    adj_close REAL,
    UNIQUE(ticker, date)
);

-- 포트폴리오 보유 종목
CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    ticker TEXT NOT NULL,
    quantity REAL,
    avg_price REAL,
    currency TEXT DEFAULT 'USD',
    sector TEXT,
    updated_at TEXT,
    UNIQUE(account, ticker)
);

-- 매크로 지표 (금리, 유가, 환율, Fear&Greed 등)
CREATE TABLE IF NOT EXISTS macro (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator TEXT NOT NULL,
    date TEXT NOT NULL,
    value REAL,
    source TEXT,
    UNIQUE(indicator, date)
);

-- ARK Invest 매매 내역
CREATE TABLE IF NOT EXISTS ark (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT,
    shares REAL,
    weight REAL,
    fund TEXT,
    UNIQUE(date, ticker, fund)
);

-- 기술적 지표 (RSI, MACD, BB, MA)
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    rsi_14 REAL,
    macd REAL,
    macd_signal REAL,
    macd_hist REAL,
    bb_upper REAL,
    bb_middle REAL,
    bb_lower REAL,
    sma_20 REAL,
    sma_50 REAL,
    sma_200 REAL,
    ema_12 REAL,
    ema_26 REAL,
    UNIQUE(ticker, date)
);

-- 이벤트 캘린더 (실적발표, FOMC, 배당)
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    event_type TEXT,
    ticker TEXT,
    description TEXT,
    importance INTEGER DEFAULT 1
);

-- 뉴스
CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    title TEXT,
    url TEXT UNIQUE,
    source TEXT,
    sentiment REAL
);

-- 기관/외인 수급
CREATE TABLE IF NOT EXISTS institutional_flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    institution_net REAL,
    foreign_net REAL,
    individual_net REAL,
    source TEXT,
    UNIQUE(ticker, date, market)
);

-- 애널리스트 컨센서스 (목표가, 투자의견)
CREATE TABLE IF NOT EXISTS estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    recommendation TEXT,
    target_high REAL,
    target_low REAL,
    target_mean REAL,
    target_median REAL,
    num_analysts INTEGER,
    current_price REAL,
    UNIQUE(ticker, date)
);

-- 슈퍼투자자 포트폴리오 (SEC 13F)
CREATE TABLE IF NOT EXISTS superinvestors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    investor TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    shares REAL,
    market_value REAL,
    portfolio_pct REAL,
    issuer_name TEXT,
    UNIQUE(investor, filing_date, ticker)
);

-- 펀더멘탈 지표 (PER, ROE, 마진, 성장률 등)
CREATE TABLE IF NOT EXISTS fundamentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    market_cap REAL,
    pe_ratio REAL,
    forward_pe REAL,
    price_to_book REAL,
    peg_ratio REAL,
    roe REAL,
    roa REAL,
    gross_margin REAL,
    operating_margin REAL,
    profit_margin REAL,
    revenue_growth REAL,
    earnings_growth REAL,
    debt_to_equity REAL,
    current_ratio REAL,
    dividend_yield REAL,
    beta REAL,
    UNIQUE(ticker, date)
);

-- 스윙 트레이드 추적
CREATE TABLE IF NOT EXISTS swing_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_signal TEXT,
    agent_action TEXT,
    agent_confidence REAL,
    agent_agreement REAL,
    exit_date TEXT,
    exit_price REAL,
    exit_reason TEXT,
    return_pct REAL,
    status TEXT DEFAULT 'open',    -- open, closed, stopped
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, entry_date)
);

-- 전략 학습 메모리 (append-only)
CREATE TABLE IF NOT EXISTS strategy_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    regime TEXT,
    period TEXT NOT NULL,          -- "all_time", "recent_90d", "recent_30d"
    trades INTEGER,
    win_rate REAL,
    profit_factor REAL,
    avg_return REAL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(snapshot_date, signal_id, regime, period)
);

-- Long/Short 포지션 관리
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_type TEXT NOT NULL,  -- 'core' or 'tactical'
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,       -- 'long' or 'short'
    entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    quantity REAL,
    current_price REAL,
    return_pct REAL,
    regime_at_entry TEXT,
    certification TEXT,            -- JSON
    exit_date TEXT,
    exit_price REAL,
    exit_reason TEXT,
    status TEXT DEFAULT 'open',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, entry_date, direction)
);

-- 레짐 전환 이력
CREATE TABLE IF NOT EXISTS regime_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    from_regime TEXT,
    to_regime TEXT,
    action_taken TEXT,             -- JSON: what positions were opened/closed
    created_at TEXT DEFAULT (datetime('now'))
);

-- Wall Street 데이터: 애널리스트 등급 변경
CREATE TABLE IF NOT EXISTS analyst_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    firm TEXT,
    to_grade TEXT,
    from_grade TEXT,
    action TEXT,
    target_price REAL,
    UNIQUE(ticker, date, firm)
);

-- Wall Street 데이터: 실적 서프라이즈
CREATE TABLE IF NOT EXISTS earnings_surprises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    quarter TEXT NOT NULL,
    eps_actual REAL,
    eps_estimate REAL,
    surprise_pct REAL,
    UNIQUE(ticker, quarter)
);

-- Wall Street 데이터: 내부자 매매
CREATE TABLE IF NOT EXISTS insider_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    insider_name TEXT,
    position TEXT,
    transaction_type TEXT,
    shares REAL,
    value REAL,
    UNIQUE(ticker, date, insider_name, transaction_type)
);

-- [Phase 3] 멀티팩터 스코어
CREATE TABLE IF NOT EXISTS factors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    momentum_score REAL,
    value_score REAL,
    quality_score REAL,
    sentiment_score REAL,
    composite_score REAL,
    UNIQUE(ticker, date)
);

-- 추천 추적 (E-3)
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence REAL,
    regime TEXT,
    signals TEXT,
    entry_price REAL,
    outcome_30d REAL,
    outcome_60d REAL,
    outcome_90d REAL,
    hit BOOLEAN,
    tracked_at TEXT,
    UNIQUE(date, ticker, action)
);

-- ETF 자금흐름 추적 (섹터 ETF AUM/거래량)
CREATE TABLE IF NOT EXISTS etf_flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    name TEXT,
    total_assets REAL,
    volume_avg REAL,
    nav_price REAL,
    UNIQUE(ticker, date)
);

-- [Phase 3] 백테스트 결과
CREATE TABLE IF NOT EXISTS backtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT,
    start_date TEXT,
    end_date TEXT,
    total_return REAL,
    sharpe REAL,
    max_drawdown REAL,
    win_rate REAL,
    params TEXT,
    created_at TEXT
);
"""


_SCHEMA_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# 증분 마이그레이션 목록: (version, description, sql)
# 새 마이그레이션 추가 시 여기에 튜플을 append한다.
_MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "create audit_log table", """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            user_id TEXT NOT NULL DEFAULT 'system',
            action TEXT NOT NULL,
            table_name TEXT NOT NULL,
            ticker TEXT,
            details TEXT,
            ip_address TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
    """),
    (2, "create external_analysis table", """
        CREATE TABLE IF NOT EXISTS external_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            source TEXT NOT NULL,
            ticker TEXT,
            data_type TEXT NOT NULL,
            value TEXT,
            numeric_value REAL,
            details TEXT,
            collected_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(date, source, ticker, data_type)
        );
        CREATE INDEX IF NOT EXISTS idx_external_source ON external_analysis(source, ticker);
        CREATE INDEX IF NOT EXISTS idx_external_date ON external_analysis(date);
    """),
    (3, "add hit_quality to recommendations", """
        ALTER TABLE recommendations ADD COLUMN hit_quality REAL;
    """),
    (4, "create trades table for execution tracking", """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recommendation_id INTEGER REFERENCES recommendations(id),
            ticker TEXT NOT NULL,
            action TEXT NOT NULL,
            executed_at TEXT NOT NULL,
            entry_price REAL,
            exit_price REAL,
            exit_date TEXT,
            exit_reason TEXT,
            shares REAL,
            notes TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
        CREATE INDEX IF NOT EXISTS idx_trades_rec ON trades(recommendation_id);
    """),
    (5, "add agent_verdicts to recommendations", """
        ALTER TABLE recommendations ADD COLUMN agent_verdicts TEXT;
    """),
    (6, "add scoring_detail to recommendations", """
        ALTER TABLE recommendations ADD COLUMN scoring_detail TEXT;
    """),
    (7, "create pipeline_events table", """
        CREATE TABLE IF NOT EXISTS pipeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            event_type TEXT NOT NULL,
            step TEXT,
            payload TEXT,
            duration_ms INTEGER,
            record_count INTEGER,
            causation_id INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_pipeline_events_step ON pipeline_events(step, timestamp);
        CREATE INDEX IF NOT EXISTS idx_pipeline_events_type ON pipeline_events(event_type, timestamp);
    """),
    (8, "add target prices to positions", """
        ALTER TABLE positions ADD COLUMN target_1_price REAL;
    """),
    (9, "add target_2_price to positions", """
        ALTER TABLE positions ADD COLUMN target_2_price REAL;
    """),
    (10, "add high_water_mark to positions", """
        ALTER TABLE positions ADD COLUMN high_water_mark REAL;
    """),
    (11, "add metadata to portfolio", """
        ALTER TABLE portfolio ADD COLUMN metadata TEXT;
    """),
    (12, "create macro_events table for news-driven regime intelligence", """
        CREATE TABLE IF NOT EXISTS macro_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
            published_at TEXT NOT NULL,
            source TEXT NOT NULL,
            query_keyword TEXT,
            headline TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            category TEXT,
            sentiment REAL,
            confidence REAL,
            regime_hint TEXT,
            raw_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_macro_events_published ON macro_events(published_at);
        CREATE INDEX IF NOT EXISTS idx_macro_events_category ON macro_events(category);
    """),
    (13, "create external_llm_calls audit log table for #152 LLM egress policy", """
        CREATE TABLE IF NOT EXISTS external_llm_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            latency_ms INTEGER,
            success INTEGER NOT NULL,
            error_type TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_external_llm_calls_timestamp ON external_llm_calls(timestamp);
        CREATE INDEX IF NOT EXISTS idx_external_llm_calls_model ON external_llm_calls(model);
    """),
]


def init_db(db_path: Optional[Path] = None) -> None:
    """전체 테이블 스키마 생성 + 증분 마이그레이션 적용."""
    with get_db(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.executescript(_SCHEMA_VERSION_TABLE)
        _apply_migrations(conn)


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """미적용 마이그레이션을 순서대로 실행."""
    applied = {
        row[0]
        for row in conn.execute("SELECT version FROM schema_version").fetchall()
    }
    for version, desc, sql in _MIGRATIONS:
        if version not in applied:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                (version, desc),
            )
            conn.commit()


def get_schema_version(db_path: Optional[Path] = None) -> int:
    """현재 적용된 최신 스키마 버전 반환. 마이그레이션 없으면 0."""
    rows = query(
        "SELECT MAX(version) as v FROM schema_version", db_path=db_path,
    )
    return rows[0]["v"] or 0 if rows and rows[0]["v"] is not None else 0


# ═══════════════════════════════════════════════════════
# Upsert 함수
# ═══════════════════════════════════════════════════════


def upsert_prices(df: pd.DataFrame, db_path: Optional[Path] = None) -> int:
    """주가 DataFrame을 prices 테이블에 upsert.

    DataFrame 컬럼: ticker, date, open, high, low, close, volume, adj_close
    """
    if df.empty:
        return 0
    with get_db(db_path) as conn:
        rows = df.to_dict("records")
        conn.executemany(
            """INSERT OR REPLACE INTO prices
               (ticker, date, open, high, low, close, volume, adj_close)
               VALUES (:ticker, :date, :open, :high, :low, :close, :volume, :adj_close)""",
            rows,
        )
        return len(rows)


def upsert_portfolio(records: list[dict], db_path: Optional[Path] = None) -> int:
    """포트폴리오 보유 종목 upsert."""
    if not records:
        return 0
    # metadata 필드 없는 레코드에 기본값 추가
    for r in records:
        r.setdefault("metadata", None)
    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO portfolio
               (account, ticker, quantity, avg_price, currency, sector, metadata, updated_at)
               VALUES (:account, :ticker, :quantity, :avg_price, :currency, :sector,
                       :metadata, datetime('now'))""",
            records,
        )
        return len(records)


def replace_portfolio_account(
    account: str,
    records: list[dict],
    db_path: Optional[Path] = None,
) -> tuple[int, int]:
    """특정 계좌의 보유 종목을 records로 완전 교체 (sync 시맨틱).

    yaml → DB 동기화 시 stale 행을 제거하기 위한 함수.
    DELETE + INSERT를 단일 트랜잭션으로 수행 → 다른 계좌는 건드리지 않음.
    records가 빈 리스트면 해당 계좌의 모든 행을 삭제 (전량 청산 표현).

    Args:
        account: 대상 계좌 ID
        records: 새 보유 종목 레코드. 모든 record["account"]가 account와 일치해야 함.

    Returns:
        (deleted_count, inserted_count)

    Raises:
        ValueError: records 중 account가 일치하지 않는 항목이 있을 때
    """
    for r in records:
        if r.get("account") != account:
            raise ValueError(
                f"record account mismatch: expected {account!r}, got {r.get('account')!r}"
            )
        r.setdefault("metadata", None)

    with get_db(db_path) as conn:
        cur = conn.execute("DELETE FROM portfolio WHERE account = ?", (account,))
        deleted = cur.rowcount
        if records:
            conn.executemany(
                """INSERT INTO portfolio
                   (account, ticker, quantity, avg_price, currency, sector, metadata, updated_at)
                   VALUES (:account, :ticker, :quantity, :avg_price, :currency, :sector,
                           :metadata, datetime('now'))""",
                records,
            )
        return (deleted, len(records))


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
    if df.empty:
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
    if not records:
        return 0
    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT INTO events (date, event_type, ticker, description, importance)
               VALUES (:date, :event_type, :ticker, :description, :importance)""",
            records,
        )
        return len(records)


def upsert_news(records: list[dict], db_path: Optional[Path] = None) -> int:
    """뉴스 upsert (URL 기준 중복 제거)."""
    if not records:
        return 0
    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO news (ticker, date, title, url, source, sentiment)
               VALUES (:ticker, :date, :title, :url, :source, :sentiment)""",
            records,
        )
        return len(records)


def upsert_macro_events(records: list[dict], db_path: Optional[Path] = None) -> int:
    """매크로 이벤트 upsert (URL 기준 중복 제거).

    레코드 키: published_at, source, query_keyword, headline, url,
              category, sentiment, confidence, regime_hint, raw_json
    URL이 이미 존재하면 INSERT OR IGNORE로 스킵.
    """
    if not records:
        return 0
    with get_db(db_path) as conn:
        cursor = conn.executemany(
            """INSERT OR IGNORE INTO macro_events
               (published_at, source, query_keyword, headline, url,
                category, sentiment, confidence, regime_hint, raw_json)
               VALUES (:published_at, :source, :query_keyword, :headline, :url,
                       :category, :sentiment, :confidence, :regime_hint, :raw_json)""",
            records,
        )
        return cursor.rowcount if cursor.rowcount >= 0 else len(records)


def log_external_llm_call(
    *,
    provider: str,
    model: str,
    endpoint: str,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    latency_ms: Optional[int] = None,
    success: bool = True,
    error_type: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """STRATEGY.md §4.4.3 audit log — 외부 LLM 호출 1건 기록.

    **content는 절대 저장하지 않는다.** prompt나 response 텍스트는
    이 함수의 인자로 받지도, DB에 넣지도 않는다. token 카운트와
    metadata만 audit한다.

    Returns: 새로 insert된 row id
    """
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO external_llm_calls
               (provider, model, endpoint, prompt_tokens, completion_tokens,
                latency_ms, success, error_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (provider, model, endpoint, prompt_tokens, completion_tokens,
             latency_ms, 1 if success else 0, error_type),
        )
        return cursor.lastrowid or 0


# ═══════════════════════════════════════════════════════
# Trading-as-Git: 매매 이력 해시 (OpenAlice 패턴 적용)
# ═══════════════════════════════════════════════════════




# ═══════════════════════════════════════════════════════
# 감사 로깅
# ═══════════════════════════════════════════════════════


def audit_log(
    action: str,
    table_name: str,
    ticker: str = "",
    details: str = "",
    user_id: str = "system",
    ip_address: str = "",
    db_path: Optional[Path] = None,
) -> None:
    """감사 로그 기록 (append-only)."""
    try:
        with get_db(db_path) as conn:
            conn.execute(
                """INSERT INTO audit_log (user_id, action, table_name, ticker, details, ip_address)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, action, table_name, ticker, details, ip_address),
            )
    except Exception:
        pass  # 감사 로깅 실패가 메인 로직을 방해하면 안 됨


# ═══════════════════════════════════════════════════════
# 조회 함수
# ═══════════════════════════════════════════════════════


def query(sql: str, params: tuple = (), db_path: Optional[Path] = None) -> list[dict]:
    """범용 읽기 쿼리 → list[dict]."""
    with get_db(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


def query_df(sql: str, params: tuple = (), db_path: Optional[Path] = None) -> pd.DataFrame:
    """범용 읽기 쿼리 → DataFrame."""
    conn = get_connection(db_path)
    try:
        df = pd.read_sql_query(sql, conn, params=params)
        return df
    finally:
        conn.close()


def get_tickers(account: Optional[str] = None, db_path: Optional[Path] = None) -> list[str]:
    """보유 종목 티커 목록 조회. account 필터 선택적."""
    if account:
        rows = query(
            "SELECT DISTINCT ticker FROM portfolio WHERE account = ?",
            (account,),
            db_path,
        )
    else:
        rows = query("SELECT DISTINCT ticker FROM portfolio", db_path=db_path)
    return [row["ticker"] for row in rows]


def get_latest_price(ticker: str, db_path: Optional[Path] = None) -> Optional[dict]:
    """특정 종목의 최신 가격 조회."""
    rows = query(
        "SELECT * FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        (ticker,),
        db_path,
    )
    return rows[0] if rows else None


# ═══════════════════════════════════════════════════════
# 매매 실행 추적 (trades)
# ═══════════════════════════════════════════════════════


def upsert_trade(data: dict, db_path: Optional[Path] = None) -> int:
    """매매 실행 기록 삽입 또는 업데이트.

    data 필수 키: ticker, action, executed_at
    선택 키: recommendation_id, entry_price, exit_price, exit_date, exit_reason, shares, notes
    기존 id가 있으면 업데이트, 없으면 삽입.
    """
    with get_db(db_path) as conn:
        if "id" in data and data["id"] is not None:
            # 기존 레코드 업데이트
            trade_id = data.pop("id")
            if not data:
                return 0
            set_clause = ", ".join(f"{k} = :{k}" for k in data)
            data["_id"] = trade_id
            conn.execute(f"UPDATE trades SET {set_clause} WHERE id = :_id", data)
            return trade_id
        else:
            # 신규 삽입
            data.pop("id", None)
            cols = ", ".join(data.keys())
            placeholders = ", ".join(f":{k}" for k in data.keys())
            cursor = conn.execute(
                f"INSERT INTO trades ({cols}) VALUES ({placeholders})", data
            )
            return cursor.lastrowid


def get_trades(ticker: Optional[str] = None, db_path: Optional[Path] = None) -> list[dict]:
    """매매 실행 기록 조회. ticker 필터 선택적."""
    if ticker:
        return query(
            "SELECT * FROM trades WHERE ticker = ? ORDER BY executed_at DESC",
            (ticker,), db_path,
        )
    return query("SELECT * FROM trades ORDER BY executed_at DESC", db_path=db_path)
