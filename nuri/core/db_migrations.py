"""nuri-quant DB schema + migrations data — pure data, no sqlite3 import.

Codex consult 2026-05-01 (data/llm_consults/2026-05-01_p2-db-split-round2.md):
Stage 1 of db.py split (Option C — data-only separation, behavior 0 변경).

규칙:
- 이 파일은 sqlite3 import 절대 금지 (PreToolUse hook 가 nuri/core/ 외부에서 차단)
- _SCHEMA / _SCHEMA_VERSION_TABLE / _MIGRATIONS 만 export
- 신규 migration 추가 시 _MIGRATIONS 마지막에 append (forward-only)
- Stage 2 (전체 package 분할) 전 단계 — db.py 가 이 파일을 import 해서 사용
"""

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
    (
        28,
        "agent_messages — Discord publish audit (#529 Phase 2 — DiscordBridge)",
        # #529 Phase 2 — Discord 채널 routing 영구 기록. 모든 actor → channel publish 는
        # 여기에 1 row. webhook HTTP status + retry count 포함, 발송 실패 시 SRE alert
        # trigger 가능. run_id 로 agent_run_ledger / agent_audit_ledger 와 join.
        """
        CREATE TABLE IF NOT EXISTS agent_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            channel TEXT NOT NULL CHECK(channel IN ('brief','ops','incidents','rollout')),
            actor_name TEXT,
            run_id TEXT,
            decision_id TEXT,
            content_preview TEXT,
            http_status INTEGER,
            retry_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_msg_channel_time ON agent_messages(channel, timestamp);
        CREATE INDEX IF NOT EXISTS idx_msg_run ON agent_messages(run_id);
        CREATE INDEX IF NOT EXISTS idx_msg_status ON agent_messages(http_status, timestamp);
    """,
    ),
    (
        29,
        "walkforward_runs — model evaluation audit (#529 Phase 2 — WalkForward-Validator)",
        # #529 Phase 2 actor #5 — Layer B (deterministic, ZERO LLM).
        # Rolling/expanding fold 기반 model evaluation 결과 영구 기록.
        # pit_hash = (data range + fold spec + model_id) digest →
        # 동일 입력 → 동일 hash → reproducibility 검증 가능.
        # metrics_json = {"folds": [{"fold": 0, "brier": 0.21, ...}, ...], "aggregate": {...}}
        # 향후 Regime-Posterior, Causal-Factor-Auditor, Foundation-Benchmark 가 모두 이 테이블 사용.
        """
        CREATE TABLE IF NOT EXISTS walkforward_runs (
            run_id TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            fold_spec_json TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            pit_hash TEXT NOT NULL,
            n_folds INTEGER NOT NULL,
            n_train_obs INTEGER,
            n_test_obs INTEGER,
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            finished_at TEXT,
            error_message TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_wf_model_time ON walkforward_runs(model_id, started_at);
        CREATE INDEX IF NOT EXISTS idx_wf_pit ON walkforward_runs(pit_hash);
    """,
    ),
    (
        30,
        "regime_posteriors — sticky-HMM smoothed posterior audit (#529 Phase 2 — Regime-Posterior #3)",
        # #529 Phase 2 actor #3 — Layer B (deterministic, ZERO LLM).
        # Codex consult 2026-05-01 (data/llm_consults/2026-05-01_regime-posterior-design.md):
        # 12-field audit row schema — `(as_of_date, model_version)` 가 PK 로 동일 일자 동일 모델
        # 재학습 시 idempotent upsert (ON CONFLICT DO UPDATE).
        # posterior_json = smoothed P(state_t | data_1:T). transition_params_hash +
        # emission_params_hash 로 모델 동일성 확인 (parameter drift detect).
        # data_freshness_status: PASS/WARN/FAIL — Freshness-Gatekeeper 결과 snapshot.
        # Decision-Compiler (#8) 가 향후 read-only consumer (producer/consumer 분리, consult 권고).
        """
        CREATE TABLE IF NOT EXISTS regime_posteriors (
            as_of_date TEXT NOT NULL,
            model_version TEXT NOT NULL,
            state_space_version TEXT NOT NULL,
            feature_snapshot_json TEXT NOT NULL,
            posterior_json TEXT NOT NULL,
            argmax_state INTEGER NOT NULL,
            entropy REAL NOT NULL,
            top2_margin REAL NOT NULL,
            transition_params_hash TEXT NOT NULL,
            emission_params_hash TEXT NOT NULL,
            train_window TEXT NOT NULL,
            data_freshness_status TEXT NOT NULL CHECK(data_freshness_status IN ('PASS','WARN','FAIL')),
            run_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (as_of_date, model_version)
        );
        CREATE INDEX IF NOT EXISTS idx_regime_date ON regime_posteriors(as_of_date);
        CREATE INDEX IF NOT EXISTS idx_regime_argmax ON regime_posteriors(argmax_state, as_of_date);
        CREATE INDEX IF NOT EXISTS idx_regime_run ON regime_posteriors(run_id);
    """,
    ),
    (
        31,
        "hypotheses — Hypothesis-Registry audit + lifecycle (#529 Phase 2 actor #4, Layer A)",
        # #529 Phase 2 actor #4 — Layer A enforcement (Codex Round 5 #128, #130, #347, #350).
        # Hypothesis = producer actor (RegimePosterior 등) 의 claim 1 건.
        # Lifecycle: open → validated|rejected|expired. validated 만 emit 허용.
        # Outcome attribution + deployment/rollback hub.
        #
        # 핵심 invariant:
        # - claim_hash UNIQUE: 동일 producer + claim 재등록 시 idempotent (기존 row id 반환)
        # - status CHECK: 4-state machine (Layer A enforcement)
        # - validated 는 validation_metrics_json 필수 (helper 강제)
        # - rejected 는 rejection_reason 필수 (helper 강제)
        # - expiry_date 지난 open → expire_hypotheses() 가 일괄 expired 처리
        # - feature_flag → feature_flags.flag_name 와 join: Release-Rollback 즉시 disable
        """
        CREATE TABLE IF NOT EXISTS hypotheses (
            hypothesis_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            producer_actor TEXT NOT NULL,
            producer_run_id TEXT,
            claim_text TEXT NOT NULL,
            claim_hash TEXT NOT NULL UNIQUE,
            evidence_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('open','validated','rejected','expired')),
            feature_flag TEXT,
            canary_scope TEXT CHECK(canary_scope IN ('paper','partial','full')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            expiry_date TEXT NOT NULL,
            validated_at TEXT,
            validation_metrics_json TEXT,
            rejection_reason TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_hyp_status ON hypotheses(status, expiry_date);
        CREATE INDEX IF NOT EXISTS idx_hyp_producer ON hypotheses(producer_actor, created_at);
        CREATE INDEX IF NOT EXISTS idx_hyp_flag ON hypotheses(feature_flag);
    """,
    ),
    (
        32,
        "causal_audits — Causal-Factor-Auditor 4-test verdict (#529 Phase 2 actor #6, Layer B)",
        # #529 Phase 2 actor #6 — Layer B (López de Prado 2025 *Causal Factor Investing*).
        # 4-test framework: DAG plausibility / placebo falsification / event-study / negative control.
        # composite causal_certainty (0-1) → Hypothesis-Registry (#4) 가 register/reject 결정 input.
        # factor_id + as_of_date 가 PK → 동일 factor 재audit 시 idempotent upsert.
        #
        # verdict enum:
        #   ROBUST  — all 4 tests pass, causal_certainty >= 0.7
        #   WEAK    — 일부 test 실패, certainty 0.4-0.7 (use with caution)
        #   MIRAGE  — placebo 가 origin 의 80%+ t-stat → spurious correlation 의심 (BLOCK 권고)
        #   INSUFFICIENT — sample 부족 (n<100) 또는 DAG cycle (검증 불가)
        """
        CREATE TABLE IF NOT EXISTS causal_audits (
            factor_id TEXT NOT NULL,
            as_of_date TEXT NOT NULL,
            n_obs INTEGER NOT NULL,
            verdict TEXT NOT NULL CHECK(verdict IN ('ROBUST','WEAK','MIRAGE','INSUFFICIENT')),
            causal_certainty REAL NOT NULL,
            dag_pass INTEGER NOT NULL DEFAULT 0,
            placebo_pass INTEGER NOT NULL DEFAULT 0,
            event_study_pass INTEGER NOT NULL DEFAULT 0,
            negative_control_pass INTEGER NOT NULL DEFAULT 0,
            test_results_json TEXT NOT NULL,
            run_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (factor_id, as_of_date)
        );
        CREATE INDEX IF NOT EXISTS idx_causal_factor ON causal_audits(factor_id, as_of_date);
        CREATE INDEX IF NOT EXISTS idx_causal_verdict ON causal_audits(verdict, as_of_date);
        CREATE INDEX IF NOT EXISTS idx_causal_run ON causal_audits(run_id);
    """,
    ),
    (
        33,
        "agent_decisions — Decision-Compiler audit (#529 Phase 2 capstone — actor #8, Layer B)",
        # #529 Phase 2 capstone — RegimePosterior + HypothesisRegistry + CausalFactorAuditor 의
        # 출력 통합 → 매매 추천. ZERO LLM, deterministic. 자동 매매 영구 X (#7.1) — emit 만.
        #
        # 테이블명 `agent_decisions` (legacy `decisions` from #178 과 분리) — service-grade
        # actor 의 audit-traceable form 보장. agent_audit_ledger / agent_run_ledger 와 동일한
        # `agent_*` 네이밍 컨벤션.
        #
        # decision lifecycle:
        #   pending — 계산 진행 중 (race-condition 방지)
        #   emitted — 사용자 추천 발행 완료 (Discord brief publish)
        #   blocked — 게이트 통과 X (Hypothesis BLOCK / Causal MIRAGE / 낮은 conviction)
        #   superseded — 같은 ticker 의 새 decision 등장 시 이전 decision 표시
        #
        # inputs_json: 모든 source actor run_id 영구 기록 (audit traceable form)
        #   { regime_run_id, hypothesis_id, causal_audit_id, walkforward_run_id (opt) }
        # rationale_json: 각 input 의 contribution + score breakdown (사용자/감사인 reproducible)
        """
        CREATE TABLE IF NOT EXISTS agent_decisions (
            decision_id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            as_of_date TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('BUY','SELL','HOLD')),
            conviction REAL NOT NULL,
            inputs_json TEXT NOT NULL,
            rationale_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','emitted','blocked','superseded')),
            block_reason TEXT,
            run_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_agent_decisions_ticker ON agent_decisions(ticker, as_of_date);
        CREATE INDEX IF NOT EXISTS idx_agent_decisions_status ON agent_decisions(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_agent_decisions_run ON agent_decisions(run_id);
    """,
    ),
    (
        34,
        "decision_outcomes — Forward-Outcome-Tracker closed-loop (#529 Phase 2 actor #11, Layer B)",
        # #529 Phase 2 closed-loop — DecisionCompiler #8 가 emit 한 decision 의 realized
        # outcome 추적. observation_window (7/14/30d) 후 가격 데이터로 realized_return,
        # benchmark_return (alpha), hit_threshold (target 도달) 측정 → hypothesis 자동
        # validate/reject trigger.
        #
        # 핵심 invariant:
        # - (decision_id, observation_window) PK → 동일 decision 의 7d/14d/30d 별도 row
        # - hypothesis_validation enum: pass/reject/insufficient_data
        # - tracked_as_of_date: 측정 시점의 KST date (lookahead 검증용)
        # - benchmark_return: 시장 베타 (예: SPY 또는 portfolio benchmark) 의 같은 기간 return
        #   alpha = realized_return - benchmark_return
        """
        CREATE TABLE IF NOT EXISTS decision_outcomes (
            decision_id TEXT NOT NULL,
            observation_window INTEGER NOT NULL CHECK(observation_window IN (7, 14, 30)),
            tracked_as_of_date TEXT NOT NULL,
            entry_price REAL,
            exit_price REAL,
            realized_return REAL,
            benchmark_return REAL,
            alpha REAL,
            hit_threshold INTEGER NOT NULL DEFAULT 0,
            hypothesis_validation TEXT NOT NULL CHECK(hypothesis_validation IN ('pass','reject','insufficient_data')),
            notes TEXT,
            run_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (decision_id, observation_window),
            FOREIGN KEY (decision_id) REFERENCES agent_decisions(decision_id)
        );
        CREATE INDEX IF NOT EXISTS idx_outcomes_decision ON decision_outcomes(decision_id);
        CREATE INDEX IF NOT EXISTS idx_outcomes_validation ON decision_outcomes(hypothesis_validation, tracked_as_of_date);
        CREATE INDEX IF NOT EXISTS idx_outcomes_run ON decision_outcomes(run_id);
    """,
    ),
    (
        35,
        "execution_blocks — Execution-Firewall hard constraint audit (#529 Phase 2 actor #9, Layer A)",
        # #529 Phase 2 actor #9 — Layer A enforcement (Codex Round 5).
        # DecisionCompiler emit 직후 / 사용자 매매 직전 마지막 hard constraint gate.
        # 모든 block 결정 영구 기록 — 사후 사고 분석 + 향후 룰 보정 input.
        #
        # block_type:
        #   vix_too_high             — VIX > 30 BUY 차단 (사용자 규칙 + rules.yaml)
        #   banned_leverage_etf      — TQQQ/SQQQ 등 금지 ETF (rules.yaml)
        #   position_cap             — 단일 종목 > 15%
        #   sector_concentration     — 단일 섹터 > 35%
        #   cash_reserve             — 매수 후 현금 < 20%
        #   leverage_cap             — 총 long exposure / cash > 1.5x
        #   max_daily_loss           — 일일 손실 한도 도달
        #
        # severity:
        #   hard — emit 차단 (사용자에게 Discord INCIDENTS alert)
        #   soft — emit 허용 + warn (예: VIX 25-30 caution)
        """
        CREATE TABLE IF NOT EXISTS execution_blocks (
            block_id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id TEXT NOT NULL,
            block_type TEXT NOT NULL CHECK(block_type IN (
                'vix_too_high','banned_leverage_etf','position_cap',
                'sector_concentration','cash_reserve','leverage_cap','max_daily_loss'
            )),
            severity TEXT NOT NULL CHECK(severity IN ('hard','soft')),
            block_reason TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            run_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (decision_id) REFERENCES agent_decisions(decision_id)
        );
        CREATE INDEX IF NOT EXISTS idx_blocks_decision ON execution_blocks(decision_id);
        CREATE INDEX IF NOT EXISTS idx_blocks_type ON execution_blocks(block_type, created_at);
        CREATE INDEX IF NOT EXISTS idx_blocks_severity ON execution_blocks(severity, created_at);
        CREATE INDEX IF NOT EXISTS idx_blocks_run ON execution_blocks(run_id);
    """,
    ),
    (
        36,
        "incidents — SRE-Incident-Agent infra alert ledger (#529 Phase 2 actor #14, Layer A)",
        # #529 Phase 2 actor #14 — Layer A SRE 운영 alert.
        # 6 detector (orphan_run / disk_full / db_lock / scheduler_heartbeat /
        # actor_failure_streak / data_freshness_critical) 의 영구 incident ledger.
        #
        # idempotent semantics:
        #   동일 (incident_type, target) 의 open incident 는 단 1개만 존재.
        #   재detection 시 last_detected_at + evidence_json 만 update (신규 row X).
        #   resolve 후 동일 (type,target) 재발 시 신규 row 생성 가능 (status 가 UNIQUE 의 일부).
        #
        # severity:
        #   critical — Discord INCIDENTS 채널 alert (operator urgent)
        #   warning  — Discord OPS 채널 alert
        #   info     — audit only (Discord publish X)
        #
        # status:
        #   open         — 활성 incident
        #   acknowledged — 사용자가 본 (audit-only — Discord re-publish 차단)
        #   resolved     — 종료 (resolved_at 채워짐)
        """
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_type TEXT NOT NULL CHECK(incident_type IN (
                'orphan_run','disk_full','db_lock','scheduler_heartbeat',
                'actor_failure_streak','data_freshness_critical'
            )),
            severity TEXT NOT NULL CHECK(severity IN ('critical','warning','info')),
            target TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('open','acknowledged','resolved')),
            first_detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            resolved_at TEXT,
            evidence_json TEXT NOT NULL,
            run_id TEXT,
            UNIQUE(incident_type, target, status)
        );
        CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status, severity);
        CREATE INDEX IF NOT EXISTS idx_incidents_type ON incidents(incident_type, last_detected_at);
    """,
    ),
    (
        37,
        "dr_replicas — State-Replicator-DR readiness ledger (#529 Phase 2 actor #15, Layer A)",
        # #529 Phase 2 actor #15 — Layer A enforcement (Codex Round 5).
        # MBP ↔ Mac mini DR (Disaster Recovery) state 추적. 실제 sync 는 launchd
        # autopull (5min) 이 처리, 본 actor 는 readiness 기록 + 검증 담당.
        #
        # 핵심 invariant:
        # - replica_id = 사용자 명명 (PK, e.g. 'macmini-primary', 'mbp-replica')
        # - role = primary / replica (single-writer 모델 — Round 5 mandatory #1)
        # - status = healthy / stale / unreachable / out_of_sync
        #   healthy        — sync_lag < 600s, schema 일치
        #   stale          — 600s ≤ lag < 3600s
        #   unreachable    — lag ≥ 3600s 또는 heartbeat 없음
        #   out_of_sync    — schema_version mismatch (verify action 시 산출)
        # - sync_lag_seconds = now - last_sync_at
        # - run_id 영구 기록 (audit traceable form, agent_run_ledger 와 join 가능)
        """
        CREATE TABLE IF NOT EXISTS dr_replicas (
            replica_id TEXT PRIMARY KEY,
            role TEXT NOT NULL CHECK(role IN ('primary','replica')),
            hostname TEXT NOT NULL,
            last_sync_at TEXT,
            last_sync_schema_version INTEGER,
            sync_lag_seconds INTEGER,
            status TEXT NOT NULL CHECK(status IN ('healthy','stale','unreachable','out_of_sync')),
            notes TEXT,
            run_id TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_dr_status ON dr_replicas(status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_dr_role ON dr_replicas(role);
    """,
    ),
    (
        38,
        "collector_runs — Collector-Orchestrator run audit (#529 Phase 2 actor #1, Layer B)",
        # #529 Phase 2 actor #1 — Layer B oversight (Codex Round 5).
        # 21+ collector 의 health audit form. 매 collector run (kis_prices, yfinance,
        # pykrx, fred, finviz, etc.) 을 status (started/finished/failed/timeout/
        # rate_limited) 와 함께 기록 → scan_health 가 GROUP BY 로 health 산출.
        #
        # 핵심 invariant:
        # - run_id INTEGER PK AUTOINCREMENT (collector run 마다 새 row, idempotent X)
        # - actor_run_id (TEXT) 는 agent_run_ledger.run_id 와 join 가능
        # - rows_collected vs rows_expected 비교로 PASS/WARN 구분
        # - retry_count / rate_limit_hits 로 외부 API 안정성 추적
        """
        CREATE TABLE IF NOT EXISTS collector_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            collector_name TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            finished_at TEXT,
            duration_ms INTEGER,
            status TEXT NOT NULL CHECK(status IN ('started','finished','failed','timeout','rate_limited')),
            rows_collected INTEGER DEFAULT 0,
            rows_expected INTEGER,
            error_message TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            rate_limit_hits INTEGER NOT NULL DEFAULT 0,
            actor_run_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_collector_runs_name ON collector_runs(collector_name, started_at);
        CREATE INDEX IF NOT EXISTS idx_collector_runs_status ON collector_runs(status, started_at);
    """,
    ),
    (
        39,
        "drift_alerts — Drift-Sentinel input distribution drift ledger (#529 Phase 2 actor #12, Layer B)",
        # #529 Phase 2 actor #12 — Layer B 통계 검증 (Codex Round 5).
        # 모델 input distribution drift 영구 기록. PSI / KS 2-sample test 결과 archive.
        #
        # severity (PSI 기준 산업 표준 + KS D-statistic):
        #   stable   — 분포 동일 (PSI<0.10 또는 D<0.05)
        #   minor    — 관찰 권고 (PSI 0.10-0.25 또는 D 0.05-0.10)
        #   major    — 재학습 권고 (PSI 0.25-0.50 또는 D 0.10-0.20)
        #   critical — 즉시 조치 (PSI≥0.50 또는 D≥0.20)
        #
        # test_type:
        #   psi  — Population Stability Index (binned categorical-friendly)
        #   ks   — Kolmogorov-Smirnov 2-sample D-statistic (continuous)
        #
        # 영구 기록 (idempotent X) — 매 detection 이 신규 row.
        # actor_name 은 drift 대상 actor (예: 'regime-posterior', 'decision-compiler').
        """
        CREATE TABLE IF NOT EXISTS drift_alerts (
            alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            feature_name TEXT NOT NULL,
            test_type TEXT NOT NULL CHECK(test_type IN ('psi','ks')),
            test_statistic REAL NOT NULL,
            threshold REAL NOT NULL,
            severity TEXT NOT NULL CHECK(severity IN ('stable','minor','major','critical')),
            baseline_window TEXT NOT NULL,
            current_window TEXT NOT NULL,
            n_baseline INTEGER NOT NULL,
            n_current INTEGER NOT NULL,
            distribution_summary_json TEXT NOT NULL,
            actor_name TEXT,
            run_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_drift_feature ON drift_alerts(feature_name, detected_at);
        CREATE INDEX IF NOT EXISTS idx_drift_severity ON drift_alerts(severity, detected_at);
        CREATE INDEX IF NOT EXISTS idx_drift_actor ON drift_alerts(actor_name, detected_at);
    """,
    ),
    (
        40,
        "foundation_benchmarks — Foundation-Benchmark 모델 비교 ledger (#529 Phase 2 actor #7, Layer B)",
        # #529 Phase 2 canonical actor #7 — Foundation-Benchmark.
        # TimesFM/Chronos/Moirai 같은 foundation time-series 모델을 우리 sticky-HMM
        # baseline 과 동일 protocol 로 벤치마킹 — "신모델이라 좋아 보이는" 착시 방지.
        #
        # 본 PR 은 infrastructure 만 ship — 실제 foundation 모델 통합은 별도 PR.
        # WalkForwardValidator 의 pit_hash + walkforward_run_id 와 join 가능해서
        # 동일 fold spec 기반의 cross-model 비교를 audit-traceable form 으로 보존.
        #
        # benchmark_run: 'YYYY-MM-DD-<slug>' 그루핑 키 (같은 protocol 의 비교군).
        # model_kind:
        #   baseline    — 기존 우리 모델 (sticky-HMM, simple regression 등)
        #   foundation  — TimesFM / Chronos / Moirai 등 pretrained foundation models
        #   traditional — 통계적 baseline (ARIMA, Prophet, naive seasonal 등)
        # metric_name: brier/logloss/sharpe/mse/mae/hit_rate (enum 강제).
        # higher_is_better: 0/1 — sort 방향 결정 (sharpe/hit_rate=1, brier/mse/mae=0).
        """
        CREATE TABLE IF NOT EXISTS foundation_benchmarks (
            benchmark_id INTEGER PRIMARY KEY AUTOINCREMENT,
            benchmark_run TEXT NOT NULL,
            model_id TEXT NOT NULL,
            model_kind TEXT NOT NULL CHECK(model_kind IN ('baseline','foundation','traditional')),
            metric_name TEXT NOT NULL CHECK(metric_name IN ('brier','logloss','sharpe','mse','mae','hit_rate')),
            metric_value REAL NOT NULL,
            higher_is_better INTEGER NOT NULL,
            sample_n INTEGER NOT NULL,
            pit_hash TEXT,
            walkforward_run_id TEXT,
            notes TEXT,
            actor_run_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_fbench_run ON foundation_benchmarks(benchmark_run, model_id);
        CREATE INDEX IF NOT EXISTS idx_fbench_model ON foundation_benchmarks(model_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_fbench_metric ON foundation_benchmarks(metric_name, created_at);
    """,
    ),
    (
        41,
        "discord_outbox — single-writer outbox for Discord channel digests (Codex Round 6, 2026-05-02)",
        # 사용자 통증 (2026-05-02): #brief 채널에 NVDA BUY/BUY/SELL 같은 conviction 으로
        # 따로 따로 emit 되어 노이즈 폭발. Codex 권고: per-event publish → outbox stage →
        # cron/quiet-period dispatcher 가 종합 1 embed 발송 (single-writer 패턴).
        #
        # status lifecycle:
        #   pending  → claim_pending() → claimed (claim_token + claimed_at) → mark_sent → sent
        #                                                                  → mark_failed → failed (재시도 또는 dropped)
        # lease semantics: dispatcher crash 시 claimed_at 이 stale (>5min) 이면 다른 dispatcher 가
        # 다시 claim 가능 → at-least-once 발송 (멱등성은 dedupe_key 로 caller 책임).
        #
        # priority: high → scheduled_for=now (즉시), normal → cron 주기, low → 다음 digest 까지 대기
        # dedupe_key: 같은 key 의 pending 이 있으면 stage() 가 skip 또는 update (caller 선택)
        # scheduled_for: now() default, future timestamp 면 그 시점 이후 dispatcher 픽업
        """
        CREATE TABLE IF NOT EXISTS discord_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL CHECK(channel IN ('brief','ops','incidents','rollout')),
            payload_json TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('high','normal','low')),
            dedupe_key TEXT,
            scheduled_for TEXT NOT NULL DEFAULT (datetime('now')),
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','claimed','sent','failed','dropped')),
            attempt_count INTEGER NOT NULL DEFAULT 0,
            claim_token TEXT,
            claimed_at TEXT,
            sent_at TEXT,
            last_error TEXT,
            actor_name TEXT,
            run_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_outbox_pending ON discord_outbox(channel, status, scheduled_for);
        CREATE INDEX IF NOT EXISTS idx_outbox_claim ON discord_outbox(status, claimed_at);
        CREATE INDEX IF NOT EXISTS idx_outbox_dedupe ON discord_outbox(channel, dedupe_key, status);
        CREATE INDEX IF NOT EXISTS idx_outbox_run ON discord_outbox(run_id);
    """,
    ),
    (
        42,
        "discord channel enum 확장 — agent_control + agent_dev_log (E1 #582)",
        # SQLite 는 ALTER TABLE … ALTER CONSTRAINT 미지원 → 신 테이블 생성 + INSERT
        # SELECT + DROP + RENAME 패턴 사용. 기존 row 100% 보존.
        # 두 테이블 (agent_messages, discord_outbox) 의 channel CHECK 를 동시에 확장.
        """
        -- agent_messages: rebuild with extended CHECK
        CREATE TABLE agent_messages_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            channel TEXT NOT NULL CHECK(channel IN ('brief','ops','incidents','rollout','agent_control','agent_dev_log')),
            actor_name TEXT,
            run_id TEXT,
            decision_id TEXT,
            content_preview TEXT,
            http_status INTEGER,
            retry_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT
        );
        INSERT INTO agent_messages_new
            (id, timestamp, channel, actor_name, run_id, decision_id,
             content_preview, http_status, retry_count, error_message)
            SELECT id, timestamp, channel, actor_name, run_id, decision_id,
                   content_preview, http_status, retry_count, error_message
              FROM agent_messages;
        DROP TABLE agent_messages;
        ALTER TABLE agent_messages_new RENAME TO agent_messages;
        CREATE INDEX IF NOT EXISTS idx_msg_channel_time ON agent_messages(channel, timestamp);
        CREATE INDEX IF NOT EXISTS idx_msg_run ON agent_messages(run_id);
        CREATE INDEX IF NOT EXISTS idx_msg_status ON agent_messages(http_status, timestamp);

        -- discord_outbox: rebuild with extended CHECK
        CREATE TABLE discord_outbox_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL CHECK(channel IN ('brief','ops','incidents','rollout','agent_control','agent_dev_log')),
            payload_json TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('high','normal','low')),
            dedupe_key TEXT,
            scheduled_for TEXT NOT NULL DEFAULT (datetime('now')),
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','claimed','sent','failed','dropped')),
            attempt_count INTEGER NOT NULL DEFAULT 0,
            claim_token TEXT,
            claimed_at TEXT,
            sent_at TEXT,
            last_error TEXT,
            actor_name TEXT,
            run_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO discord_outbox_new
            (id, channel, payload_json, priority, dedupe_key, scheduled_for,
             status, attempt_count, claim_token, claimed_at, sent_at, last_error,
             actor_name, run_id, created_at)
            SELECT id, channel, payload_json, priority, dedupe_key, scheduled_for,
                   status, attempt_count, claim_token, claimed_at, sent_at, last_error,
                   actor_name, run_id, created_at
              FROM discord_outbox;
        DROP TABLE discord_outbox;
        ALTER TABLE discord_outbox_new RENAME TO discord_outbox;
        CREATE INDEX IF NOT EXISTS idx_outbox_pending ON discord_outbox(channel, status, scheduled_for);
        CREATE INDEX IF NOT EXISTS idx_outbox_claim ON discord_outbox(status, claimed_at);
        CREATE INDEX IF NOT EXISTS idx_outbox_dedupe ON discord_outbox(channel, dedupe_key, status);
        CREATE INDEX IF NOT EXISTS idx_outbox_run ON discord_outbox(run_id);
    """,
    ),
    (
        43,
        "held_add_shadow — Phase 2a held add-mode shadow emit (#518)",
        """
        CREATE TABLE IF NOT EXISTS held_add_shadow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            ticker TEXT NOT NULL,
            account TEXT NOT NULL,
            mode TEXT NOT NULL CHECK(mode IN ('tp1_residual_add','ride_winner','average_down')),
            score REAL,
            current_pct REAL,
            cap_max_pct REAL,
            headroom_pct REAL,
            payload_json TEXT NOT NULL,
            run_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_held_add_shadow_ticker ON held_add_shadow(ticker, timestamp);
        CREATE INDEX IF NOT EXISTS idx_held_add_shadow_acct ON held_add_shadow(account, timestamp);
        CREATE INDEX IF NOT EXISTS idx_held_add_shadow_mode ON held_add_shadow(mode, timestamp);
    """,
    ),
    (
        44,
        "market_postmortem — daily post-market snapshot + similarity feature vector (#596 Phase 2)",
        """
        CREATE TABLE IF NOT EXISTS market_postmortem (
            date TEXT NOT NULL,
            session TEXT NOT NULL CHECK(session IN ('kr','us')),
            regime TEXT,
            vix REAL,
            fear_greed REAL,
            -- aggregated daily signals (indexed for similarity prefilter)
            vix_5d_delta REAL,
            fg_5d_delta REAL,
            spy_5d_delta REAL,
            top_sector_delta_pct REAL,
            holdings_total_pnl_pct REAL,
            -- denormalized JSON blobs (read alongside, not indexed)
            macro_summary TEXT,
            holdings_pnl TEXT,
            sector_movers TEXT,
            catalysts TEXT,
            retro_lessons TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (date, session)
        );
        CREATE INDEX IF NOT EXISTS idx_postmortem_regime ON market_postmortem(regime, session);
        CREATE INDEX IF NOT EXISTS idx_postmortem_vix ON market_postmortem(vix, session);
    """,
    ),
    (
        45,
        "incidents incident_type enum 확장 — signal_evaluation_stale (#825)",
        # signals 테이블은 발화 행만 저장 → 평가 heartbeat (pipeline_events
        # 'signal_evaluation_run') 공백이 N영업일 이상이면 SRE incident 로 surface.
        # SQLite 는 CHECK 제약 변경 미지원 → 신 테이블 + INSERT SELECT + DROP +
        # RENAME 패턴 (migration 42 와 동일). 기존 row 100% 보존.
        """
        CREATE TABLE incidents_new (
            incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_type TEXT NOT NULL CHECK(incident_type IN (
                'orphan_run','disk_full','db_lock','scheduler_heartbeat',
                'actor_failure_streak','data_freshness_critical','signal_evaluation_stale'
            )),
            severity TEXT NOT NULL CHECK(severity IN ('critical','warning','info')),
            target TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('open','acknowledged','resolved')),
            first_detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            resolved_at TEXT,
            evidence_json TEXT NOT NULL,
            run_id TEXT,
            UNIQUE(incident_type, target, status)
        );
        INSERT INTO incidents_new
            (incident_id, incident_type, severity, target, status,
             first_detected_at, last_detected_at, resolved_at, evidence_json, run_id)
            SELECT incident_id, incident_type, severity, target, status,
                   first_detected_at, last_detected_at, resolved_at, evidence_json, run_id
              FROM incidents;
        DROP TABLE incidents;
        ALTER TABLE incidents_new RENAME TO incidents;
        CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status, severity);
        CREATE INDEX IF NOT EXISTS idx_incidents_type ON incidents(incident_type, last_detected_at);
    """,
    ),
    (
        46,
        "incidents incident_type enum 확장 — alpha_report_stale (#894)",
        # §3.11 월간 alpha 진행 리포트(#856)는 "안 나가는 상태"와 "이번 달 이미 나간
        # 상태"가 관측상 동일했다 — NURI_ROLE 누락이면 판정일까지 영영 안 나가는데
        # 아무 신호가 없다. pipeline_events 'alpha_report_run' heartbeat 를 근거로
        # SRE detector 가 stale 을 잡는다. migration 45 와 동일한 재생성 패턴.
        """
        CREATE TABLE incidents_new (
            incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_type TEXT NOT NULL CHECK(incident_type IN (
                'orphan_run','disk_full','db_lock','scheduler_heartbeat',
                'actor_failure_streak','data_freshness_critical','signal_evaluation_stale',
                'alpha_report_stale'
            )),
            severity TEXT NOT NULL CHECK(severity IN ('critical','warning','info')),
            target TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('open','acknowledged','resolved')),
            first_detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            resolved_at TEXT,
            evidence_json TEXT NOT NULL,
            run_id TEXT,
            UNIQUE(incident_type, target, status)
        );
        INSERT INTO incidents_new
            (incident_id, incident_type, severity, target, status,
             first_detected_at, last_detected_at, resolved_at, evidence_json, run_id)
            SELECT incident_id, incident_type, severity, target, status,
                   first_detected_at, last_detected_at, resolved_at, evidence_json, run_id
              FROM incidents;
        DROP TABLE incidents;
        ALTER TABLE incidents_new RENAME TO incidents;
        CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status, severity);
        CREATE INDEX IF NOT EXISTS idx_incidents_type ON incidents(incident_type, last_detected_at);
    """,
    ),
    (
        47,
        "execution_blocks block_type enum 확장 — sleeve_cap (#834)",
        # §3.11 실험 슬리브 상한(rules.yaml measurement_mode.sleeve_max_equity_pct)이
        # ExecutionFirewall 의 hard block 으로 승격된다. block_type CHECK 에 없으면
        # log_execution_block 이 IntegrityError 로 죽어 firewall 자체가 무너지므로
        # 게이트 코드보다 이 migration 이 먼저다. migration 45/46 과 동일 재생성 패턴.
        """
        CREATE TABLE execution_blocks_new (
            block_id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id TEXT NOT NULL,
            block_type TEXT NOT NULL CHECK(block_type IN (
                'vix_too_high','banned_leverage_etf','position_cap',
                'sector_concentration','cash_reserve','leverage_cap','max_daily_loss',
                'sleeve_cap'
            )),
            severity TEXT NOT NULL CHECK(severity IN ('hard','soft')),
            block_reason TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            run_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (decision_id) REFERENCES agent_decisions(decision_id)
        );
        INSERT INTO execution_blocks_new
            (block_id, decision_id, block_type, severity, block_reason,
             evidence_json, run_id, created_at)
            SELECT block_id, decision_id, block_type, severity, block_reason,
                   evidence_json, run_id, created_at
              FROM execution_blocks;
        DROP TABLE execution_blocks;
        ALTER TABLE execution_blocks_new RENAME TO execution_blocks;
        CREATE INDEX IF NOT EXISTS idx_blocks_decision ON execution_blocks(decision_id);
        CREATE INDEX IF NOT EXISTS idx_blocks_type ON execution_blocks(block_type, created_at);
        CREATE INDEX IF NOT EXISTS idx_blocks_severity ON execution_blocks(severity, created_at);
        CREATE INDEX IF NOT EXISTS idx_blocks_run ON execution_blocks(run_id);
    """,
    ),
    (
        48,
        "decision_outcomes.benchmark_ticker — 행이 어느 벤치마크로 잰 alpha 인지 자기기술 (#833)",
        # KR 결정이 SPY 대비로 측정되던 것을 시장별 벤치마크로 바꾸면, 같은 테이블에
        # 서로 다른 기준으로 잰 alpha 가 섞인다. 어느 행이 어느 기준인지 모르면 §3.11
        # 판정 표본을 나눌 수 없다 — 컬럼 하나로 모든 행을 자기기술하게 만든다.
        #
        # 기존 행 backfill 은 추정이 아니라 사실이다: DEFAULT_BENCHMARK_TICKER 는
        # 도입(e9495aa) 이래 "SPY" 뿐이었고 다른 경로가 없었다. 단 benchmark_return
        # 이 NULL 인 행은 벤치마크가 아예 적용되지 않은 행(insufficient_data)이므로
        # NULL 로 남긴다 — "SPY 로 쟀다" 가 거짓이 되기 때문.
        """
        ALTER TABLE decision_outcomes ADD COLUMN benchmark_ticker TEXT;
        CREATE INDEX IF NOT EXISTS idx_outcomes_benchmark ON decision_outcomes(benchmark_ticker);
        UPDATE decision_outcomes SET benchmark_ticker = 'SPY' WHERE benchmark_return IS NOT NULL;
    """,
    ),
    (
        49,
        "incidents incident_type enum 확장 — health_check.sh 흡수 3종 (#939)",
        # `scripts/ops/health_check.sh` 의 고유 검사 3종(schema version / 필수 테이블 /
        # 단일 writer role)을 SRE detector 로 이식한다. 그 스크립트는 echo 만 하고
        # 알림 경로가 없어 시간마다 로그만 쌓였고, plist 주석이 "SRE-Incident-Agent 가
        # 이 로그를 watch 한다" 고 적어뒀으나 그런 코드는 없었다 — 광고된 배선이 허구.
        # SQLite 는 CHECK 제약 변경 미지원 → migration 45/46 과 동일한 재생성 패턴.
        """
        CREATE TABLE incidents_new (
            incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_type TEXT NOT NULL CHECK(incident_type IN (
                'orphan_run','disk_full','db_lock','scheduler_heartbeat',
                'actor_failure_streak','data_freshness_critical','signal_evaluation_stale',
                'alpha_report_stale','schema_version_drift','required_table_missing',
                'writer_role'
            )),
            severity TEXT NOT NULL CHECK(severity IN ('critical','warning','info')),
            target TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('open','acknowledged','resolved')),
            first_detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            resolved_at TEXT,
            evidence_json TEXT NOT NULL,
            run_id TEXT,
            UNIQUE(incident_type, target, status)
        );
        INSERT INTO incidents_new
            (incident_id, incident_type, severity, target, status,
             first_detected_at, last_detected_at, resolved_at, evidence_json, run_id)
            SELECT incident_id, incident_type, severity, target, status,
                   first_detected_at, last_detected_at, resolved_at, evidence_json, run_id
              FROM incidents;
        DROP TABLE incidents;
        ALTER TABLE incidents_new RENAME TO incidents;
        CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status, severity);
        CREATE INDEX IF NOT EXISTS idx_incidents_type ON incidents(incident_type, last_detected_at);
    """,
    ),
    (
        50,
        "recommendations.source — emit 경로 구분",
        """
        ALTER TABLE recommendations ADD COLUMN source TEXT;
        CREATE INDEX IF NOT EXISTS idx_recommendations_source ON recommendations(source, date);
    """,
    ),
    (
        51,
        "theses / thesis_evidence — 상승·하락 논지 원장 (#1083)",
        # `decisions` 에 컬럼을 붙이지 않는 이유 셋: (1) `decisions.action` 은 합의 엔진이
        # 주인이라 "시스템은 BUY, 나는 안 삼" 을 표현할 수 없다, (2) `UNIQUE(date, ticker)`
        # 는 논지의 결이 아니다 — 결정은 매일 재작성되지만 논지는 몇 달 간다, (3)
        # `decision_evidence.decision_id` 를 nullable 로 바꾸려면 3,330행 체인을 테이블
        # 재생성해야 한다.
        #
        # `effective_date` 는 `created_at` 의 중복이 **아니다**. `datetime('now')` 는 UTC 라
        # KST 오전에 쓴 논지의 created_at 이 `'2026-08-18 03:00:00'` 이 되고, 그러면
        # `created_at <= '2026-08-18'` 비교가 날짜 문자열과 섞여 어긋난다. PIT 조인은
        # KST 날짜인 `effective_date` 로만 한다.
        """
        CREATE TABLE IF NOT EXISTS theses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            supersedes_id INTEGER REFERENCES theses(id),
            author TEXT NOT NULL,
            stance TEXT NOT NULL CHECK (stance IN ('bullish', 'bearish', 'neutral')),
            bull_case TEXT NOT NULL,
            bear_case TEXT NOT NULL,
            effective_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'active', 'superseded', 'retired')),
            verdict TEXT CHECK (verdict IN ('broken', 'held', 'abandoned', 'unevaluable')),
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(ticker, version)
        );
        CREATE INDEX IF NOT EXISTS idx_theses_pit ON theses(ticker, status, effective_date);

        CREATE TABLE IF NOT EXISTS thesis_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thesis_id INTEGER NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
            side TEXT NOT NULL CHECK (side IN ('bull', 'bear')),
            claim TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_key TEXT,
            source_url TEXT,
            as_of TEXT,
            quote TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_thesis_evidence_thesis ON thesis_evidence(thesis_id, side);
    """,
    ),
    (
        52,
        "thesis_criteria / thesis_criteria_checks — 사전등록 반증 기준 (#1092)",
        # 논지 텍스트만 있으면 사후에 "대체로 맞았다" 로 읽힌다. **무엇이 사실이면 내가
        # 틀린 것인가**를 미리 박아야 채점이 성립한다.
        #
        # `kind='machine'` 이면 metric/op/threshold 가 전부 있어야 한다 — CHECK 로 강제한다.
        # 없는 채로 machine 을 허용하면 "자동 점검 대상" 인데 해소할 식이 없는 행이 생기고,
        # 그건 조용히 영원히 unevaluable 이 된다.
        #
        # checks 는 append-only 다. 같은 기준의 판정 이력이 곧 채점 재료이므로 덮어쓰지
        # 않는다. `UNIQUE(criterion_id, check_date)` 로 하루 1건만 둔다(재실행 멱등).
        #
        # `result` 에 `unevaluable` 이 **1급 값**인 것이 이 마이그레이션의 핵심이다.
        # 측정하지 못한 것을 `holding` 으로 적으면 게이트가 있는데 안 잡는 상태가 되고,
        # 그게 `_check_volatility_for_class` 가 넉 달간 초록이던 이유였다.
        """
        CREATE TABLE IF NOT EXISTS thesis_criteria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thesis_id INTEGER NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('machine', 'human')),
            statement TEXT NOT NULL,
            metric TEXT,
            op TEXT CHECK (op IS NULL OR op IN ('<', '<=', '>', '>=')),
            threshold REAL,
            deadline_date TEXT,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'retired')),
            created_at TEXT DEFAULT (datetime('now')),
            CHECK (
                kind <> 'machine'
                OR (metric IS NOT NULL AND op IS NOT NULL AND threshold IS NOT NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS idx_thesis_criteria_thesis
            ON thesis_criteria(thesis_id, status);

        CREATE TABLE IF NOT EXISTS thesis_criteria_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            criterion_id INTEGER NOT NULL REFERENCES thesis_criteria(id) ON DELETE CASCADE,
            check_date TEXT NOT NULL,
            result TEXT NOT NULL CHECK (result IN ('holding', 'breached', 'unevaluable')),
            observed REAL,
            detail TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(criterion_id, check_date)
        );
        CREATE INDEX IF NOT EXISTS idx_thesis_criteria_checks_date
            ON thesis_criteria_checks(check_date, result);
    """,
    ),
]
