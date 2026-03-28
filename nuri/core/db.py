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

-- [Phase 2] LLM 벤치마크 결과
CREATE TABLE IF NOT EXISTS llm_bench (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT,
    prompt_type TEXT,
    prompt TEXT,
    response TEXT,
    score REAL,
    latency_ms INTEGER,
    timestamp TEXT
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
    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO portfolio
               (account, ticker, quantity, avg_price, currency, sector, updated_at)
               VALUES (:account, :ticker, :quantity, :avg_price, :currency, :sector,
                       datetime('now'))""",
            records,
        )
        return len(records)


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
