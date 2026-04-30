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
-- surprise_pct 단위: FRACTION (decimal). 0.05 = 5% beat. OpenBB 원 포맷 그대로.
-- 변환 금지. Frontend/agent 는 × 100 해서 렌더/threshold 비교.
CREATE TABLE IF NOT EXISTS earnings_surprises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    quarter TEXT NOT NULL,
    eps_actual REAL,
    eps_estimate REAL,
    surprise_pct REAL,  -- FRACTION unit (0.05 = 5%). 변환 없이 raw 저장.
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
    UNIQUE(date, ticker)
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
    (
        1,
        "create audit_log table",
        """
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
    """,
    ),
    (
        2,
        "create external_analysis table",
        """
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
    """,
    ),
    (
        3,
        "add hit_quality to recommendations",
        """
        ALTER TABLE recommendations ADD COLUMN hit_quality REAL;
    """,
    ),
    (
        4,
        "create trades table for execution tracking",
        """
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
    """,
    ),
    (
        5,
        "add agent_verdicts to recommendations",
        """
        ALTER TABLE recommendations ADD COLUMN agent_verdicts TEXT;
    """,
    ),
    (
        6,
        "add scoring_detail to recommendations",
        """
        ALTER TABLE recommendations ADD COLUMN scoring_detail TEXT;
    """,
    ),
    (
        7,
        "create pipeline_events table",
        """
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
    """,
    ),
    (
        8,
        "add target prices to positions",
        """
        ALTER TABLE positions ADD COLUMN target_1_price REAL;
    """,
    ),
    (
        9,
        "add target_2_price to positions",
        """
        ALTER TABLE positions ADD COLUMN target_2_price REAL;
    """,
    ),
    (
        10,
        "add high_water_mark to positions",
        """
        ALTER TABLE positions ADD COLUMN high_water_mark REAL;
    """,
    ),
    (
        11,
        "add metadata to portfolio",
        """
        ALTER TABLE portfolio ADD COLUMN metadata TEXT;
    """,
    ),
    (
        12,
        "create macro_events table for news-driven regime intelligence",
        """
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
    """,
    ),
    (
        13,
        "create external_llm_calls audit log table for #152 LLM egress policy",
        """
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
    """,
    ),
    (
        14,
        "create decisions table for #178 Decision Intelligence",
        """
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            action TEXT NOT NULL,
            confidence REAL,
            regime TEXT,
            macro_score REAL,
            event_score REAL,
            vix REAL,
            fear_greed REAL,
            agent_verdicts TEXT,
            agreement_rate REAL,
            dissent TEXT,
            reasoning TEXT,
            scoring_detail TEXT,
            entry_price REAL,
            stop_loss REAL,
            target_1 REAL,
            target_2 REAL,
            pnl_7d REAL,
            pnl_30d REAL,
            pnl_60d REAL,
            pnl_90d REAL,
            outcome TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(date, ticker)
        );
        CREATE INDEX IF NOT EXISTS idx_decisions_ticker ON decisions(ticker);
        CREATE INDEX IF NOT EXISTS idx_decisions_date ON decisions(date);
        CREATE INDEX IF NOT EXISTS idx_decisions_outcome ON decisions(outcome);
    """,
    ),
    (
        15,
        "create decision_evidence table for #178 lineage",
        """
        CREATE TABLE IF NOT EXISTS decision_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id INTEGER NOT NULL,
            source_type TEXT NOT NULL,
            source_key TEXT NOT NULL,
            action TEXT,
            confidence REAL,
            detail TEXT,
            FOREIGN KEY (decision_id) REFERENCES decisions(id),
            UNIQUE(decision_id, source_type, source_key)
        );
        CREATE INDEX IF NOT EXISTS idx_decision_evidence_decision ON decision_evidence(decision_id);
    """,
    ),
    (
        16,
        "add classification_method to macro_events for #137 data quality",
        """
        ALTER TABLE macro_events ADD COLUMN classification_method TEXT;
    """,
    ),
    (
        17,
        "add first_buy_date to portfolio for #218 days-held tracking",
        """
        ALTER TABLE portfolio ADD COLUMN first_buy_date TEXT;
    """,
    ),
    (
        18,
        "add dividend columns to fundamentals for #227",
        """
        ALTER TABLE fundamentals ADD COLUMN annual_dividend_usd REAL;
    """,
    ),
    (
        19,
        "add dividend_yield_pct to fundamentals for #227",
        """
        ALTER TABLE fundamentals ADD COLUMN dividend_yield_pct REAL;
    """,
    ),
    (
        20,
        "recommendations UNIQUE(date, ticker) — drop 'action' from key (B1 fix)",
        # NEXT_SESSION B1 — UNIQUE(date, ticker, action) 이 docstring 의도 (INSERT OR REPLACE
        # on (date, ticker))와 어긋나 duplicate row 가 누적됐음. action 제외 후 MAX(id) 기준
        # dedup. 기존 trades.recommendation_id FK 는 보존 (MAX id 는 남김).
        """
        CREATE TABLE recommendations_new (
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
            hit_quality REAL,
            agent_verdicts TEXT,
            scoring_detail TEXT,
            UNIQUE(date, ticker)
        );
        INSERT INTO recommendations_new (
            id, date, ticker, action, confidence, regime, signals, entry_price,
            outcome_30d, outcome_60d, outcome_90d, hit, tracked_at, hit_quality,
            agent_verdicts, scoring_detail
        )
        SELECT id, date, ticker, action, confidence, regime, signals, entry_price,
               outcome_30d, outcome_60d, outcome_90d, hit, tracked_at, hit_quality,
               agent_verdicts, scoring_detail
        FROM recommendations
        WHERE id IN (SELECT MAX(id) FROM recommendations GROUP BY date, ticker);
        DROP TABLE recommendations;
        ALTER TABLE recommendations_new RENAME TO recommendations;
    """,
    ),
    (
        21,
        "create certifications table (E4-0a SIEGE instrumentation)",
        # E4-0a — SIEGE 가 자체 실행 기록을 보관해야 엔진 predictivity 측정이 가능.
        # 이전에는 certify() 가 return only 였음 (persist 0건). 이제 매 실행을 row 로 기록.
        # 각 certify() 호출 = 새 row (dedup 없음; 동일 portfolio_hash 라도 시점이 다르면 별개).
        """
        CREATE TABLE IF NOT EXISTS certifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            certified INTEGER NOT NULL,
            score REAL NOT NULL,
            total_conditions INTEGER NOT NULL,
            passed INTEGER NOT NULL,
            failed INTEGER NOT NULL,
            warnings INTEGER NOT NULL,
            regime TEXT,
            portfolio_hash TEXT,
            conditions_json TEXT NOT NULL,
            caller TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_cert_timestamp ON certifications(timestamp);
        CREATE INDEX IF NOT EXISTS idx_cert_certified ON certifications(certified);
        CREATE INDEX IF NOT EXISTS idx_cert_regime ON certifications(regime);
    """,
    ),
    (
        22,
        "separate alpha_action from portfolio_action on recommendations",
        # PR A (codex bubble-bear #1, 2026-04-21) — SIEGE REJECT (portfolio rule) 가
        # SELL (alpha signal) 로 surface 되는 경로 구조 분리. legacy `action` 은
        # 유지 (BUY/SELL/HOLD 로 derive) — tracker.py / candidates.py / UI 가 계속
        # 읽음. 새 axis 는 downstream consumer 에서 점진적으로 사용.
        # Forward-only NULL: legacy row 는 NULL 유지 (lossy retrofit 금지).
        """
        ALTER TABLE recommendations ADD COLUMN alpha_action TEXT;
        ALTER TABLE recommendations ADD COLUMN portfolio_action TEXT;
    """,
    ),
    (
        23,
        "short-horizon outcomes (7d/14d/21d) on recommendations",
        # #468 (codex Plan consult Round 1, 2026-04-28) — provisional learning memory.
        # 30d 만으로는 scheduler 시작 (2026-04-08) 이후 첫 outcome 이 5/8 부터 채워짐.
        # 21d provisional weights + 7d/14d readiness/monitoring 를 위해 컬럼 추가.
        # Forward-only NULL: 기존 row 는 next track_outcomes() 에서 elapsed gate 통과 시 채워짐.
        # outcome immutability: tracker 가 non-null 절대 overwrite 안 함 (recompute=True 명시 시만).
        """
        ALTER TABLE recommendations ADD COLUMN outcome_7d REAL;
        ALTER TABLE recommendations ADD COLUMN outcome_14d REAL;
        ALTER TABLE recommendations ADD COLUMN outcome_21d REAL;
    """,
    ),
    (
        24,
        "add event_subtype to pipeline_events for cooldown SELL-type split (#517)",
        # #517 Phase 2b — Forward-only event taxonomy. holdings_monitor.payload.action_type
        # 가 신규 emit 부터 채움 ('hard_sell' / 'trim_action' / 'position_reduce' /
        # 'divergence_alert'). 레거시 row 는 NULL 유지 (B2 STOP — backfill heuristic 위험).
        # buy_candidate_emitter._get_cooldown_tickers_by_type 가 NULL 일 때
        # legacy event_type fallback (holdings_monitor_alert / take_profit_trigger /
        # trim_recommendation) 으로 5d cooldown 적용.
        """
        ALTER TABLE pipeline_events ADD COLUMN event_subtype TEXT;
    """,
    ),
    (
        25,
        "agent_audit_ledger — append-only decision audit for 15-actor service-grade infra (#529)",
        # #529 Phase 1 — Service-grade 15-actor architecture (Round 5 codex consult,
        # data/llm_consults/2026-04-30_round5-service-grade-agents.md).
        # Append-only audit ledger: 모든 actor 의 input → judgment → output 영구 기록.
        # 사고 후 원인 재구성 가능하도록 input_hash + sample_n + duration_ms 포함.
        # Knight Capital 2012-08-01 (45분/4M+ 오류주문) 류 사고에서 사후 분석 가능 보장.
        # Layer A (enforcement) 결정만 audit 필수. Layer C (interpretation) narrative 는
        # 별도 컬럼 (선택). LLM down 이어도 actor 결정은 기록됨.
        """
        CREATE TABLE IF NOT EXISTS agent_audit_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id TEXT NOT NULL,
            actor_name TEXT NOT NULL,
            actor_version TEXT NOT NULL,
            layer TEXT NOT NULL CHECK(layer IN ('A','B','C')),
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            input_hash TEXT NOT NULL,
            input_summary TEXT,
            output TEXT NOT NULL,
            sample_n INTEGER,
            duration_ms INTEGER,
            outcome TEXT CHECK(outcome IN ('pass','block','warn','error')),
            llm_narrative TEXT,
            run_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audit_decision ON agent_audit_ledger(decision_id);
        CREATE INDEX IF NOT EXISTS idx_audit_actor ON agent_audit_ledger(actor_name, timestamp);
        CREATE INDEX IF NOT EXISTS idx_audit_run ON agent_audit_ledger(run_id);
        CREATE INDEX IF NOT EXISTS idx_audit_outcome ON agent_audit_ledger(outcome, timestamp);
    """,
    ),
    (
        26,
        "feature_flags — rollback + canary control for hypothesis lifecycle (#529)",
        # #529 Phase 1 — Release-Rollback-Manager 기반. 모든 hypothesis / actor / signal
        # 은 feature flag 로 enable/disable. `make rollback flag=<name>` 즉시 disable.
        # canary scope: 1차 (paper-trade only), 2차 (10% size cap), 3차 (full).
        # owner 는 incident response 시 누구에게 ping 할지 (현재는 사용자 본인).
        # disabled_at 채워지면 즉시 OFF (Codex Round 5 mandatory: enforcement는 100% rule).
        """
        CREATE TABLE IF NOT EXISTS feature_flags (
            flag_name TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0,
            canary_scope TEXT CHECK(canary_scope IN ('paper','partial','full')),
            owner TEXT NOT NULL DEFAULT 'system',
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            disabled_at TEXT,
            disabled_reason TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_flags_enabled ON feature_flags(enabled, canary_scope);
    """,
    ),
    (
        27,
        "agent_run_ledger — run lifecycle (started/finished/failed) for 15-actor system (#529)",
        # #529 Phase 1 — SRE-Incident-Agent + Drift-Sentinel 기반. 각 actor invocation 의
        # lifecycle 추적: started_at + finished_at + status + error. heartbeat 식 활용.
        # actor crash 시 finished_at NULL 로 남아 SRE alert trigger.
        # run_id 는 agent_audit_ledger.run_id 와 join 가능 (cross-actor causation chain).
        # parent_run_id 로 trigger chain 추적 (Decision-Compiler → Firewall → emit).
        """
        CREATE TABLE IF NOT EXISTS agent_run_ledger (
            run_id TEXT PRIMARY KEY,
            actor_name TEXT NOT NULL,
            parent_run_id TEXT,
            status TEXT NOT NULL CHECK(status IN ('started','finished','failed','timeout','cancelled')),
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            finished_at TEXT,
            duration_ms INTEGER,
            error_message TEXT,
            machine TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_run_actor_status ON agent_run_ledger(actor_name, status, started_at);
        CREATE INDEX IF NOT EXISTS idx_run_parent ON agent_run_ledger(parent_run_id);
    """,
    ),
]


def init_db(db_path: Optional[Path] = None) -> None:
    """전체 테이블 스키마 생성 + 증분 마이그레이션 적용."""
    with get_db(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.executescript(_SCHEMA_VERSION_TABLE)
        _apply_migrations(conn)


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """미적용 마이그레이션을 순서대로 실행."""
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_version").fetchall()}
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
        "SELECT MAX(version) as v FROM schema_version",
        db_path=db_path,
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
            raise ValueError(f"record account mismatch: expected {account!r}, got {r.get('account')!r}")
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
            (provider, model, endpoint, prompt_tokens, completion_tokens, latency_ms, 1 if success else 0, error_type),
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
            cursor = conn.execute(f"INSERT INTO trades ({cols}) VALUES ({placeholders})", data)
            # cursor.lastrowid is Optional[int] per DB-API spec; coerce to int
            # because the function signature is `-> int` and SQLite always
            # populates lastrowid after an INSERT.
            return cursor.lastrowid or 0


def get_trades(ticker: Optional[str] = None, db_path: Optional[Path] = None) -> list[dict]:
    """매매 실행 기록 조회. ticker 필터 선택적."""
    if ticker:
        return query(
            "SELECT * FROM trades WHERE ticker = ? ORDER BY executed_at DESC",
            (ticker,),
            db_path,
        )
    return query("SELECT * FROM trades ORDER BY executed_at DESC", db_path=db_path)


# ═══════════════════════════════════════════════════════
# Decision Intelligence (#178)
# ═══════════════════════════════════════════════════════


def upsert_decision(data: dict, db_path: Optional[Path] = None) -> int:
    """의사결정 기록 멱등 삽입/갱신. UNIQUE(date, ticker) 기준.

    같은 날 같은 종목에 대해 재실행하면 최신 데이터로 UPDATE.
    Returns: decision id (신규 삽입 시 lastrowid, 기존 갱신 시 기존 id).
    """
    with get_db(db_path) as conn:
        cols = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data.keys())
        # updated_at을 갱신하기 위해 ON CONFLICT 사용
        update_cols = [k for k in data.keys() if k not in ("date", "ticker")]
        on_conflict = ", ".join(f"{k} = :{k}" for k in update_cols)
        sql = f"""INSERT INTO decisions ({cols}) VALUES ({placeholders})
                  ON CONFLICT(date, ticker) DO UPDATE SET {on_conflict},
                  updated_at = datetime('now')"""
        cursor = conn.execute(sql, data)
        if cursor.lastrowid:
            return cursor.lastrowid
        # ON CONFLICT UPDATE → lastrowid가 0일 수 있음, 기존 id 조회
        row = conn.execute("SELECT id FROM decisions WHERE date = :date AND ticker = :ticker", data).fetchone()
        return row[0] if row else 0


def upsert_decision_evidence(decision_id: int, records: list[dict], db_path: Optional[Path] = None) -> int:
    """의사결정 증거 기록 멱등 삽입. UNIQUE(decision_id, source_type, source_key) 기준."""
    if not records:
        return 0
    with get_db(db_path) as conn:
        for rec in records:
            rec["decision_id"] = decision_id
            conn.execute(
                """INSERT INTO decision_evidence
                   (decision_id, source_type, source_key, action, confidence, detail)
                   VALUES (:decision_id, :source_type, :source_key, :action, :confidence, :detail)
                   ON CONFLICT(decision_id, source_type, source_key)
                   DO UPDATE SET action = :action, confidence = :confidence, detail = :detail""",
                rec,
            )
        return len(records)


def insert_certification(data: dict, db_path: Optional[Path] = None) -> int:
    """SIEGE Certificate 실행 기록 삽입 (E4-0a instrumentation).

    각 certify() 호출 = 새 row. UNIQUE 제약 없음 — 동일 portfolio_hash 라도 시점이
    다르면 별개로 기록되어야 엔진 predictivity 측정이 가능 (§3.7 E4 hypothesis).

    Required keys: timestamp, certified, score, total_conditions, passed, failed,
    warnings, conditions_json. Optional: regime, portfolio_hash, caller.

    Returns: inserted row id (lastrowid).
    """
    required = {
        "timestamp",
        "certified",
        "score",
        "total_conditions",
        "passed",
        "failed",
        "warnings",
        "conditions_json",
    }
    missing = required - data.keys()
    if missing:
        raise ValueError(f"insert_certification: missing required keys {missing}")

    with get_db(db_path) as conn:
        cols = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data.keys())
        sql = f"INSERT INTO certifications ({cols}) VALUES ({placeholders})"
        cursor = conn.execute(sql, data)
        return cursor.lastrowid or 0


def get_decisions(
    ticker: Optional[str] = None, outcome: Optional[str] = None, limit: int = 100, db_path: Optional[Path] = None
) -> list[dict]:
    """의사결정 목록 조회. 필터: ticker, outcome(pending/success/failure)."""
    conditions = []
    params: list = []
    if ticker:
        conditions.append("ticker = ?")
        params.append(ticker)
    if outcome:
        conditions.append("outcome = ?")
        params.append(outcome)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return query(
        f"SELECT * FROM decisions {where} ORDER BY date DESC LIMIT ?",
        (*params, limit),
        db_path,
    )


def get_decision_with_evidence(decision_id: int, db_path: Optional[Path] = None) -> Optional[dict]:
    """의사결정 + 증거 체인 조회 (lineage용)."""
    rows = query("SELECT * FROM decisions WHERE id = ?", (decision_id,), db_path)
    if not rows:
        return None
    decision = dict(rows[0])
    evidence = query(
        "SELECT * FROM decision_evidence WHERE decision_id = ? ORDER BY source_type, source_key",
        (decision_id,),
        db_path,
    )
    decision["evidence"] = [dict(e) for e in evidence]
    return decision


# ═══════════════════════════════════════════════════════
# Service-grade 15-actor agent infra (#529 Phase 1)
# Round 5 codex consult — Layer A enforcement / B compute / C interpret 분리.
# ═══════════════════════════════════════════════════════


def log_agent_audit(
    decision_id: str,
    actor_name: str,
    actor_version: str,
    layer: str,
    input_hash: str,
    output: str,
    input_summary: Optional[str] = None,
    sample_n: Optional[int] = None,
    duration_ms: Optional[int] = None,
    outcome: Optional[str] = None,
    llm_narrative: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Append-only agent decision audit (#529).

    layer: 'A' enforcement / 'B' computation / 'C' interpretation.
    outcome: 'pass' / 'block' / 'warn' / 'error'. Layer A 결정 시 필수.
    """
    if layer not in ("A", "B", "C"):
        raise ValueError(f"layer must be A/B/C, got {layer!r}")
    if outcome is not None and outcome not in ("pass", "block", "warn", "error"):
        raise ValueError(f"outcome must be pass/block/warn/error, got {outcome!r}")
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO agent_audit_ledger
               (decision_id, actor_name, actor_version, layer, input_hash, input_summary,
                output, sample_n, duration_ms, outcome, llm_narrative, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision_id,
                actor_name,
                actor_version,
                layer,
                input_hash,
                input_summary,
                output,
                sample_n,
                duration_ms,
                outcome,
                llm_narrative,
                run_id,
            ),
        )
        return cursor.lastrowid or 0


def is_feature_enabled(
    flag_name: str,
    default: bool = False,
    db_path: Optional[Path] = None,
) -> bool:
    """Feature flag 조회 (#529 Release-Rollback-Manager).

    flag 미존재 시 default 반환. disabled_at 채워진 row 는 무조건 False.
    """
    rows = query(
        "SELECT enabled, disabled_at FROM feature_flags WHERE flag_name = ?",
        (flag_name,),
        db_path,
    )
    if not rows:
        return default
    row = rows[0]
    if row["disabled_at"]:
        return False
    return bool(row["enabled"])


def set_feature_flag(
    flag_name: str,
    enabled: bool,
    canary_scope: Optional[str] = None,
    owner: str = "system",
    description: Optional[str] = None,
    disabled_reason: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Feature flag set/update (#529).

    canary_scope: 'paper' / 'partial' / 'full'.
    enabled=False 로 호출 시 disabled_at + disabled_reason 자동 채움.
    """
    if canary_scope is not None and canary_scope not in ("paper", "partial", "full"):
        raise ValueError(f"canary_scope must be paper/partial/full, got {canary_scope!r}")
    with get_db(db_path) as conn:
        if enabled:
            conn.execute(
                """INSERT INTO feature_flags
                   (flag_name, enabled, canary_scope, owner, description, updated_at,
                    disabled_at, disabled_reason)
                   VALUES (?, 1, ?, ?, ?, datetime('now'), NULL, NULL)
                   ON CONFLICT(flag_name) DO UPDATE SET
                     enabled = 1,
                     canary_scope = COALESCE(?, canary_scope),
                     owner = ?,
                     description = COALESCE(?, description),
                     updated_at = datetime('now'),
                     disabled_at = NULL,
                     disabled_reason = NULL""",
                (
                    flag_name,
                    canary_scope,
                    owner,
                    description,
                    canary_scope,
                    owner,
                    description,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO feature_flags
                   (flag_name, enabled, owner, description, updated_at,
                    disabled_at, disabled_reason)
                   VALUES (?, 0, ?, ?, datetime('now'), datetime('now'), ?)
                   ON CONFLICT(flag_name) DO UPDATE SET
                     enabled = 0,
                     updated_at = datetime('now'),
                     disabled_at = datetime('now'),
                     disabled_reason = ?""",
                (flag_name, owner, description, disabled_reason, disabled_reason),
            )


def start_agent_run(
    run_id: str,
    actor_name: str,
    parent_run_id: Optional[str] = None,
    machine: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Agent run lifecycle 시작 (#529 SRE-Incident + Drift-Sentinel)."""
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO agent_run_ledger (run_id, actor_name, parent_run_id, status, machine)
               VALUES (?, ?, ?, 'started', ?)""",
            (run_id, actor_name, parent_run_id, machine),
        )


def finish_agent_run(
    run_id: str,
    status: str = "finished",
    duration_ms: Optional[int] = None,
    error_message: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Agent run lifecycle 완료 (#529).

    status: 'finished' / 'failed' / 'timeout' / 'cancelled'.
    finished_at NULL 로 남으면 SRE-Incident-Agent alert trigger.
    """
    if status not in ("finished", "failed", "timeout", "cancelled"):
        raise ValueError(f"status must be finished/failed/timeout/cancelled, got {status!r}")
    with get_db(db_path) as conn:
        conn.execute(
            """UPDATE agent_run_ledger
               SET status = ?, finished_at = datetime('now'),
                   duration_ms = ?, error_message = ?
               WHERE run_id = ?""",
            (status, duration_ms, error_message, run_id),
        )
