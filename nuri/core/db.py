"""
Nuri-Quant 데이터베이스 모듈 — 모든 DB 접근의 단일 진입점.

다른 모듈에서 sqlite3를 직접 import하지 않는다.
모든 DB 작업은 이 모듈의 함수를 통해서만 수행한다.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import pandas as pd

from nuri.core.db_migrations import _MIGRATIONS, _SCHEMA, _SCHEMA_VERSION_TABLE

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


# ═══════════════════════════════════════════════════════
# State-Replicator-DR helpers (#529 Phase 2 actor #15, Layer A)
# ═══════════════════════════════════════════════════════

_DR_VALID_ROLES: tuple[str, ...] = ("primary", "replica")
_DR_VALID_STATUSES: tuple[str, ...] = ("healthy", "stale", "unreachable", "out_of_sync")


def upsert_dr_replica(
    replica_id: str,
    role: str,
    hostname: str,
    last_sync_at: Optional[str],
    last_sync_schema_version: Optional[int],
    sync_lag_seconds: Optional[int],
    status: str,
    notes: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """DR replica state upsert (#529 State-Replicator-DR).

    role: 'primary' / 'replica' — single-writer 모델 (Codex Round 5 mandatory #1).
    status: 'healthy' / 'stale' / 'unreachable' / 'out_of_sync'.
    enum 위반 시 ValueError — Layer A actor 호출 전 validation 강제.
    """
    if role not in _DR_VALID_ROLES:
        raise ValueError(f"role must be primary/replica, got {role!r}")
    if status not in _DR_VALID_STATUSES:
        raise ValueError(f"status must be healthy/stale/unreachable/out_of_sync, got {status!r}")
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO dr_replicas
               (replica_id, role, hostname, last_sync_at, last_sync_schema_version,
                sync_lag_seconds, status, notes, run_id, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(replica_id) DO UPDATE SET
                 role = excluded.role,
                 hostname = excluded.hostname,
                 last_sync_at = excluded.last_sync_at,
                 last_sync_schema_version = excluded.last_sync_schema_version,
                 sync_lag_seconds = excluded.sync_lag_seconds,
                 status = excluded.status,
                 notes = COALESCE(excluded.notes, notes),
                 run_id = COALESCE(excluded.run_id, run_id),
                 updated_at = datetime('now')""",
            (
                replica_id,
                role,
                hostname,
                last_sync_at,
                last_sync_schema_version,
                sync_lag_seconds,
                status,
                notes,
                run_id,
            ),
        )


# ═══════════════════════════════════════════════════════
# Collector-Orchestrator helpers (#529 Phase 2 actor #1, Layer B)
# ═══════════════════════════════════════════════════════

_COLLECTOR_VALID_STATUSES: tuple[str, ...] = (
    "started",
    "finished",
    "failed",
    "timeout",
    "rate_limited",
)


def log_collector_run(
    collector_name: str,
    status: str,
    rows_collected: int = 0,
    rows_expected: Optional[int] = None,
    duration_ms: Optional[int] = None,
    error_message: Optional[str] = None,
    retry_count: int = 0,
    rate_limit_hits: int = 0,
    actor_run_id: Optional[str] = None,
    finished_at: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Single INSERT — 매 collector run 의 결과 영구 기록. lastrowid 반환.

    enum 검증: status ∈ ('started','finished','failed','timeout','rate_limited').
    Layer B Collector-Orchestrator 가 21+ collector 의 health 추적용으로 호출.

    actor_run_id: agent_run_ledger.run_id 와 join 가능 (오케스트레이션 chain 추적).
    finished_at None 이면 in-progress 상태 (started 직후 호출 시).
    """
    if status not in _COLLECTOR_VALID_STATUSES:
        raise ValueError(f"status must be one of {_COLLECTOR_VALID_STATUSES}, got {status!r}")
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO collector_runs
               (collector_name, status, rows_collected, rows_expected,
                duration_ms, error_message, retry_count, rate_limit_hits,
                actor_run_id, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                collector_name,
                status,
                rows_collected,
                rows_expected,
                duration_ms,
                error_message,
                retry_count,
                rate_limit_hits,
                actor_run_id,
                finished_at,
            ),
        )
        return int(cursor.lastrowid or 0)


def log_walkforward_run(
    run_id: str,
    model_id: str,
    fold_spec: dict,
    metrics: dict,
    pit_hash: str,
    n_folds: int,
    n_train_obs: Optional[int] = None,
    n_test_obs: Optional[int] = None,
    finished_at: Optional[str] = None,
    error_message: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Walk-forward evaluation result audit (#529 Phase 2 — WalkForward-Validator).

    fold_spec: {"kind": "rolling"|"expanding", "train_size": N, "test_size": M, "step": K}
    metrics: {"aggregate": {"brier": .., "logloss": ..}, "folds": [{"fold": 0, ..}, ...]}
    pit_hash: data digest + fold spec + model_id → reproducibility key.
    finished_at None → run still in progress (started_at default).
    """
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO walkforward_runs
               (run_id, model_id, fold_spec_json, metrics_json, pit_hash,
                n_folds, n_train_obs, n_test_obs, finished_at, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id) DO UPDATE SET
                 metrics_json = excluded.metrics_json,
                 finished_at = COALESCE(excluded.finished_at, finished_at),
                 error_message = excluded.error_message""",
            (
                run_id,
                model_id,
                json.dumps(fold_spec, sort_keys=True),
                json.dumps(metrics, default=str),
                pit_hash,
                n_folds,
                n_train_obs,
                n_test_obs,
                finished_at,
                error_message,
            ),
        )


def log_agent_message(
    channel: str,
    content_preview: str,
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    http_status: Optional[int] = None,
    retry_count: int = 0,
    error_message: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Discord publish audit (#529 Phase 2 — DiscordBridge).

    channel: 'brief' / 'ops' / 'incidents' / 'rollout'.
    content_preview: 첫 200자 (긴 embed 도 grep 가능하도록).
    http_status: 204 정상 발송, 4xx/5xx 실패. NULL = 네트워크 실패 전 단계.
    """
    if channel not in ("brief", "ops", "incidents", "rollout"):
        raise ValueError(f"channel must be brief/ops/incidents/rollout, got {channel!r}")
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO agent_messages
               (channel, actor_name, run_id, decision_id, content_preview,
                http_status, retry_count, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                channel,
                actor_name,
                run_id,
                decision_id,
                content_preview[:200],
                http_status,
                retry_count,
                error_message,
            ),
        )
        return cursor.lastrowid or 0


def log_regime_posterior(
    as_of_date: str,
    model_version: str,
    state_space_version: str,
    feature_snapshot: dict,
    posterior: list[float],
    argmax_state: int,
    entropy: float,
    top2_margin: float,
    transition_params_hash: str,
    emission_params_hash: str,
    train_window: str,
    data_freshness_status: str,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Sticky-HMM smoothed posterior audit (#529 Phase 2 — Regime-Posterior actor #3).

    Codex Round 5 Layer B. (as_of_date, model_version) 가 PK 로 동일 학습 재실행 시 idempotent
    upsert. posterior_json = list[float] (state 별 P(state_t | data_1:T), sum=1).
    data_freshness_status: PASS/WARN/FAIL — Freshness-Gatekeeper 의 결정 snapshot.

    Layer A 가 이 row 를 read 하여 enforce 가능 (e.g. argmax 변경 시 SIEGE re-run trigger).
    """
    if data_freshness_status not in ("PASS", "WARN", "FAIL"):
        raise ValueError(f"data_freshness_status must be PASS/WARN/FAIL, got {data_freshness_status!r}")
    if abs(sum(posterior) - 1.0) > 1e-6:
        raise ValueError(f"posterior must sum to 1 (got {sum(posterior):.6f}) — sticky-HMM smoothed P violation")
    if not (0 <= argmax_state < len(posterior)):
        raise ValueError(f"argmax_state {argmax_state} out of range [0, {len(posterior)})")
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO regime_posteriors
               (as_of_date, model_version, state_space_version, feature_snapshot_json,
                posterior_json, argmax_state, entropy, top2_margin,
                transition_params_hash, emission_params_hash, train_window,
                data_freshness_status, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(as_of_date, model_version) DO UPDATE SET
                 state_space_version = excluded.state_space_version,
                 feature_snapshot_json = excluded.feature_snapshot_json,
                 posterior_json = excluded.posterior_json,
                 argmax_state = excluded.argmax_state,
                 entropy = excluded.entropy,
                 top2_margin = excluded.top2_margin,
                 transition_params_hash = excluded.transition_params_hash,
                 emission_params_hash = excluded.emission_params_hash,
                 train_window = excluded.train_window,
                 data_freshness_status = excluded.data_freshness_status,
                 run_id = excluded.run_id""",
            (
                as_of_date,
                model_version,
                state_space_version,
                json.dumps(feature_snapshot, sort_keys=True, default=str),
                json.dumps(posterior),
                argmax_state,
                entropy,
                top2_margin,
                transition_params_hash,
                emission_params_hash,
                train_window,
                data_freshness_status,
                run_id,
            ),
        )


# ═══════════════════════════════════════════════════════
# Hypothesis-Registry helpers (#529 Phase 2 actor #4 — Layer A)
# ═══════════════════════════════════════════════════════

_HYPOTHESIS_STATUSES = ("open", "validated", "rejected", "expired")
_CANARY_SCOPES = ("paper", "partial", "full")


def register_hypothesis(
    hypothesis_id: str,
    name: str,
    version: str,
    producer_actor: str,
    claim_text: str,
    evidence: dict,
    expiry_date: str,
    producer_run_id: Optional[str] = None,
    feature_flag: Optional[str] = None,
    canary_scope: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> tuple[str, bool]:
    """Hypothesis 등록 — claim_hash idempotent (동일 producer + claim 재등록 시 기존 id 반환).

    Returns (hypothesis_id, is_new) — is_new=False 시 기존 row 그대로.
    Initial status = 'open'. 명시적 validate/reject/expire 호출로만 전이.

    Codex Round 5 Layer A: open→validated 는 validation_metrics_json 필수.
    """
    import hashlib

    if canary_scope is not None and canary_scope not in _CANARY_SCOPES:
        raise ValueError(f"canary_scope must be {_CANARY_SCOPES}, got {canary_scope!r}")
    claim_hash = hashlib.sha256(f"{producer_actor}|{claim_text}".encode()).hexdigest()[:32]

    with get_db(db_path) as conn:
        existing = conn.execute(
            "SELECT hypothesis_id FROM hypotheses WHERE claim_hash = ?",
            (claim_hash,),
        ).fetchone()
        if existing:
            return existing["hypothesis_id"], False
        conn.execute(
            """INSERT INTO hypotheses
               (hypothesis_id, name, version, producer_actor, producer_run_id,
                claim_text, claim_hash, evidence_json, status,
                feature_flag, canary_scope, expiry_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)""",
            (
                hypothesis_id,
                name,
                version,
                producer_actor,
                producer_run_id,
                claim_text,
                claim_hash,
                json.dumps(evidence, sort_keys=True, default=str),
                feature_flag,
                canary_scope,
                expiry_date,
            ),
        )
        return hypothesis_id, True


def validate_hypothesis(
    hypothesis_id: str,
    validation_metrics: dict,
    db_path: Optional[Path] = None,
) -> None:
    """open → validated 전이. validation_metrics 필수 (Layer A enforcement).

    Codex Round 5 mandatory: 검증 metrics 없이 validated 로 변경 불가.
    이미 validated/rejected/expired 면 ValueError (status machine 위반).
    """
    if not validation_metrics:
        raise ValueError("validation_metrics dict required to validate (Layer A enforcement)")
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM hypotheses WHERE hypothesis_id = ?",
            (hypothesis_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"hypothesis {hypothesis_id!r} not found")
        if row["status"] != "open":
            raise ValueError(
                f"cannot validate hypothesis {hypothesis_id!r}: status={row['status']!r} "
                "(only open → validated allowed)"
            )
        conn.execute(
            """UPDATE hypotheses SET status='validated',
               validated_at=datetime('now'),
               validation_metrics_json=?
               WHERE hypothesis_id=?""",
            (json.dumps(validation_metrics, sort_keys=True, default=str), hypothesis_id),
        )


def reject_hypothesis(
    hypothesis_id: str,
    rejection_reason: str,
    db_path: Optional[Path] = None,
) -> None:
    """open → rejected. rejection_reason 필수."""
    if not rejection_reason or not rejection_reason.strip():
        raise ValueError("rejection_reason required to reject (Layer A enforcement)")
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM hypotheses WHERE hypothesis_id = ?",
            (hypothesis_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"hypothesis {hypothesis_id!r} not found")
        if row["status"] != "open":
            raise ValueError(
                f"cannot reject hypothesis {hypothesis_id!r}: status={row['status']!r} (only open → rejected allowed)"
            )
        conn.execute(
            "UPDATE hypotheses SET status='rejected', rejection_reason=? WHERE hypothesis_id=?",
            (rejection_reason, hypothesis_id),
        )


def expire_hypotheses(db_path: Optional[Path] = None) -> int:
    """open + expiry_date < today → expired. 반환: 만료 처리된 row 수.

    SRE-Incident-Agent / scheduler 가 cron 으로 주기 호출. idempotent.
    """
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """UPDATE hypotheses SET status='expired'
               WHERE status='open' AND date(expiry_date) < date('now')"""
        )
        return cursor.rowcount


# ═══════════════════════════════════════════════════════
# Causal-Factor-Auditor helper (#529 Phase 2 actor #6 — Layer B)
# ═══════════════════════════════════════════════════════

_CAUSAL_VERDICTS = ("ROBUST", "WEAK", "MIRAGE", "INSUFFICIENT")


def log_causal_audit(
    factor_id: str,
    as_of_date: str,
    n_obs: int,
    verdict: str,
    causal_certainty: float,
    dag_pass: bool,
    placebo_pass: bool,
    event_study_pass: bool,
    negative_control_pass: bool,
    test_results: dict,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Causal-Factor-Auditor 4-test verdict audit (#529 Phase 2 actor #6).

    López de Prado 2025: 4 tests = DAG plausibility / placebo / event-study / negative control.
    causal_certainty ∈ [0,1] composite = 4 test pass-rate weighted by t-stat strength.
    (factor_id, as_of_date) PK → 동일 factor 재audit 시 idempotent upsert.

    Layer B contract: ZERO LLM, deterministic. 결과는 Hypothesis-Registry (#4) consumer.
    """
    if verdict not in _CAUSAL_VERDICTS:
        raise ValueError(f"verdict must be {_CAUSAL_VERDICTS}, got {verdict!r}")
    if not (0.0 <= causal_certainty <= 1.0):
        raise ValueError(f"causal_certainty must be in [0,1], got {causal_certainty}")
    if n_obs < 0:
        raise ValueError(f"n_obs must be >= 0, got {n_obs}")
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO causal_audits
               (factor_id, as_of_date, n_obs, verdict, causal_certainty,
                dag_pass, placebo_pass, event_study_pass, negative_control_pass,
                test_results_json, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(factor_id, as_of_date) DO UPDATE SET
                 n_obs = excluded.n_obs,
                 verdict = excluded.verdict,
                 causal_certainty = excluded.causal_certainty,
                 dag_pass = excluded.dag_pass,
                 placebo_pass = excluded.placebo_pass,
                 event_study_pass = excluded.event_study_pass,
                 negative_control_pass = excluded.negative_control_pass,
                 test_results_json = excluded.test_results_json,
                 run_id = excluded.run_id""",
            (
                factor_id,
                as_of_date,
                n_obs,
                verdict,
                causal_certainty,
                int(dag_pass),
                int(placebo_pass),
                int(event_study_pass),
                int(negative_control_pass),
                json.dumps(test_results, sort_keys=True, default=str),
                run_id,
            ),
        )


# ═══════════════════════════════════════════════════════
# Decision-Compiler helper (#529 Phase 2 capstone — actor #8, Layer B)
# ═══════════════════════════════════════════════════════

_DECISION_ACTIONS = ("BUY", "SELL", "HOLD")
_DECISION_STATUSES = ("pending", "emitted", "blocked", "superseded")
_REQUIRED_INPUT_KEYS = ("regime_run_id", "hypothesis_id", "causal_audit_id")


def log_decision(
    decision_id: str,
    ticker: str,
    as_of_date: str,
    action: str,
    conviction: float,
    inputs: dict,
    rationale: dict,
    status: str,
    block_reason: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Decision-Compiler 출력 영구 기록 (#529 Phase 2 capstone).

    audit traceable form 강제: inputs 에 source actor run_id 누락 시 panic.
    Layer B contract: ZERO LLM, deterministic. 모든 emit / block 결정 기록.

    inputs 필수 키:
        regime_run_id — RegimePosterior 의 run_id
        hypothesis_id — HypothesisRegistry 의 hypothesis_id (check_emit 통과한 것)
        causal_audit_id — CausalFactorAuditor 의 (factor_id, as_of_date) 식별자
        walkforward_run_id (optional) — WalkForwardValidator 결과
    """
    if action not in _DECISION_ACTIONS:
        raise ValueError(f"action must be {_DECISION_ACTIONS}, got {action!r}")
    if status not in _DECISION_STATUSES:
        raise ValueError(f"status must be {_DECISION_STATUSES}, got {status!r}")
    if not (0.0 <= conviction <= 1.0):
        raise ValueError(f"conviction must be in [0,1], got {conviction}")
    missing = [k for k in _REQUIRED_INPUT_KEYS if k not in inputs]
    if missing:
        raise ValueError(f"inputs missing required audit keys: {missing} (audit traceability enforcement)")
    if status == "blocked" and not block_reason:
        raise ValueError("blocked decision must include block_reason")

    with get_db(db_path) as conn:
        # 동일 ticker 의 이전 emitted/pending decision 은 superseded 처리 (idempotent)
        if status in ("emitted", "blocked"):
            conn.execute(
                """UPDATE agent_decisions SET status='superseded'
                   WHERE ticker=? AND as_of_date=? AND decision_id != ?
                   AND status IN ('pending','emitted')""",
                (ticker, as_of_date, decision_id),
            )
        conn.execute(
            """INSERT INTO agent_decisions
               (decision_id, ticker, as_of_date, action, conviction,
                inputs_json, rationale_json, status, block_reason, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(decision_id) DO UPDATE SET
                 action = excluded.action,
                 conviction = excluded.conviction,
                 inputs_json = excluded.inputs_json,
                 rationale_json = excluded.rationale_json,
                 status = excluded.status,
                 block_reason = excluded.block_reason""",
            (
                decision_id,
                ticker,
                as_of_date,
                action,
                conviction,
                json.dumps(inputs, sort_keys=True, default=str),
                json.dumps(rationale, sort_keys=True, default=str),
                status,
                block_reason,
                run_id,
            ),
        )


# ═══════════════════════════════════════════════════════
# Forward-Outcome-Tracker helper (#529 Phase 2 actor #11 — Layer B)
# ═══════════════════════════════════════════════════════

_OUTCOME_VALIDATIONS = ("pass", "reject", "insufficient_data")
_OUTCOME_WINDOWS = (7, 14, 30)


def log_decision_outcome(
    decision_id: str,
    observation_window: int,
    tracked_as_of_date: str,
    hypothesis_validation: str,
    entry_price: Optional[float] = None,
    exit_price: Optional[float] = None,
    realized_return: Optional[float] = None,
    benchmark_return: Optional[float] = None,
    alpha: Optional[float] = None,
    hit_threshold: bool = False,
    notes: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Decision outcome audit (#529 Phase 2 closed-loop — Forward-Outcome-Tracker).

    (decision_id, observation_window) PK 로 동일 decision 의 7d/14d/30d 별도 row.
    동일 (decision_id, window) 재계산 시 idempotent upsert.

    hypothesis_validation: pass/reject/insufficient_data — Hypothesis-Registry 의 validate/reject
    호출 trigger. insufficient_data 는 false validation 차단 (가격 데이터 부족).
    """
    if observation_window not in _OUTCOME_WINDOWS:
        raise ValueError(f"observation_window must be {_OUTCOME_WINDOWS}, got {observation_window}")
    if hypothesis_validation not in _OUTCOME_VALIDATIONS:
        raise ValueError(f"hypothesis_validation must be {_OUTCOME_VALIDATIONS}, got {hypothesis_validation!r}")
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO decision_outcomes
               (decision_id, observation_window, tracked_as_of_date,
                entry_price, exit_price, realized_return, benchmark_return, alpha,
                hit_threshold, hypothesis_validation, notes, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(decision_id, observation_window) DO UPDATE SET
                 tracked_as_of_date = excluded.tracked_as_of_date,
                 entry_price = excluded.entry_price,
                 exit_price = excluded.exit_price,
                 realized_return = excluded.realized_return,
                 benchmark_return = excluded.benchmark_return,
                 alpha = excluded.alpha,
                 hit_threshold = excluded.hit_threshold,
                 hypothesis_validation = excluded.hypothesis_validation,
                 notes = excluded.notes,
                 run_id = excluded.run_id""",
            (
                decision_id,
                observation_window,
                tracked_as_of_date,
                entry_price,
                exit_price,
                realized_return,
                benchmark_return,
                alpha,
                int(hit_threshold),
                hypothesis_validation,
                notes,
                run_id,
            ),
        )


# ═══════════════════════════════════════════════════════
# Execution-Firewall helper (#529 Phase 2 actor #9 — Layer A)
# ═══════════════════════════════════════════════════════

_BLOCK_TYPES = (
    "vix_too_high",
    "banned_leverage_etf",
    "position_cap",
    "sector_concentration",
    "cash_reserve",
    "leverage_cap",
    "max_daily_loss",
)
_BLOCK_SEVERITIES = ("hard", "soft")


def log_execution_block(
    decision_id: str,
    block_type: str,
    severity: str,
    block_reason: str,
    evidence: dict,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Execution-Firewall block 결정 영구 기록 (#529 Phase 2 actor #9).

    block_type / severity enum 검증. evidence_json 에 위반 detail (현재 값 vs 임계값) 기록.
    Layer A enforcement: hard severity 위반 = emit 차단, soft = warn only.

    Returns: 신규 block_id (lastrowid).
    """
    if block_type not in _BLOCK_TYPES:
        raise ValueError(f"block_type must be {_BLOCK_TYPES}, got {block_type!r}")
    if severity not in _BLOCK_SEVERITIES:
        raise ValueError(f"severity must be {_BLOCK_SEVERITIES}, got {severity!r}")
    if not block_reason or not block_reason.strip():
        raise ValueError("block_reason required (Layer A enforcement audit)")
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO execution_blocks
               (decision_id, block_type, severity, block_reason, evidence_json, run_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                decision_id,
                block_type,
                severity,
                block_reason,
                json.dumps(evidence, sort_keys=True, default=str),
                run_id,
            ),
        )
        return cursor.lastrowid or 0


# ═══════════════════════════════════════════════════════
# SRE-Incident-Agent helpers (#529 Phase 2 actor #14 — Layer A)
# ═══════════════════════════════════════════════════════

_INCIDENT_TYPES = (
    "orphan_run",
    "disk_full",
    "db_lock",
    "scheduler_heartbeat",
    "actor_failure_streak",
    "data_freshness_critical",
)
_INCIDENT_SEVERITIES = ("critical", "warning", "info")
_INCIDENT_STATUSES = ("open", "acknowledged", "resolved")


def log_incident(
    incident_type: str,
    severity: str,
    target: str,
    evidence: dict,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """SRE-Incident 영구 기록 (#529 Phase 2 actor #14, Layer A).

    Idempotent semantics:
        동일 (incident_type, target, status='open') incident 가 존재하면
        last_detected_at + evidence_json 만 update (신규 row X — 동일 incident_id 반환).
        존재하지 않으면 신규 INSERT (status='open', first_detected_at=now).

    Returns: incident_id (기존 or 신규).

    enum 검증: incident_type, severity 모두 _INCIDENT_TYPES / _INCIDENT_SEVERITIES 에서.
    """
    if incident_type not in _INCIDENT_TYPES:
        raise ValueError(f"incident_type must be {_INCIDENT_TYPES}, got {incident_type!r}")
    if severity not in _INCIDENT_SEVERITIES:
        raise ValueError(f"severity must be {_INCIDENT_SEVERITIES}, got {severity!r}")
    if not target or not str(target).strip():
        raise ValueError("target required (actor_name / table / ticker / 'system')")

    evidence_json = json.dumps(evidence, sort_keys=True, default=str)
    with get_db(db_path) as conn:
        # open 인 동일 (type, target) 가 있으면 update + 기존 incident_id 반환.
        existing = conn.execute(
            """SELECT incident_id FROM incidents
               WHERE incident_type = ? AND target = ? AND status = 'open'""",
            (incident_type, target),
        ).fetchone()
        if existing is not None:
            existing_id = existing[0]
            conn.execute(
                """UPDATE incidents
                   SET last_detected_at = datetime('now'),
                       evidence_json = ?,
                       severity = ?,
                       run_id = COALESCE(?, run_id)
                   WHERE incident_id = ?""",
                (evidence_json, severity, run_id, existing_id),
            )
            return int(existing_id)
        # 신규 incident.
        cursor = conn.execute(
            """INSERT INTO incidents
               (incident_type, severity, target, status, evidence_json, run_id)
               VALUES (?, ?, ?, 'open', ?, ?)""",
            (incident_type, severity, target, evidence_json, run_id),
        )
        return cursor.lastrowid or 0


def acknowledge_incident(
    incident_id: int,
    db_path: Optional[Path] = None,
) -> bool:
    """Incident 를 사용자가 봤음 표시 (audit-only — Discord re-publish 차단용).

    Returns: True if updated, False if no open incident with that id.
    """
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """UPDATE incidents
               SET status = 'acknowledged'
               WHERE incident_id = ? AND status = 'open'""",
            (incident_id,),
        )
        return (cursor.rowcount or 0) > 0


def resolve_incident(
    incident_id: int,
    db_path: Optional[Path] = None,
) -> bool:
    """Incident 종료 — status='resolved' + resolved_at=now.

    Returns: True if updated, False if no open/acknowledged incident with that id.
    Resolve 후 동일 (type, target) 재발 시 신규 row 가능 (status 가 UNIQUE 의 일부).
    """
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """UPDATE incidents
               SET status = 'resolved',
                   resolved_at = datetime('now')
               WHERE incident_id = ? AND status IN ('open','acknowledged')""",
            (incident_id,),
        )
        return (cursor.rowcount or 0) > 0


# ═══════════════════════════════════════════════════════
# Drift-Sentinel helper (#529 Phase 2 actor #12 — Layer B)
# ═══════════════════════════════════════════════════════

_DRIFT_TEST_TYPES = ("psi", "ks")
_DRIFT_SEVERITIES = ("stable", "minor", "major", "critical")


def log_drift_alert(
    feature_name: str,
    test_type: str,
    test_statistic: float,
    threshold: float,
    severity: str,
    baseline_window: str,
    current_window: str,
    n_baseline: int,
    n_current: int,
    distribution_summary: dict,
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Drift-Sentinel 분포 drift 결과 영구 기록 (#529 Phase 2 actor #12, Layer B).

    PSI / KS 2-sample test 결과 archive. 매 detection 이 신규 row (idempotent X) —
    historical drift trend 분석용.

    enum 검증:
        test_type ∈ ('psi','ks')
        severity ∈ ('stable','minor','major','critical')
    값 검증:
        test_statistic / threshold ≥ 0.0 (PSI / KS D-stat 양수)
        n_baseline / n_current ≥ 0

    Returns: alert_id (lastrowid).

    Layer B contract: ZERO LLM, deterministic. SREIncidentAgent 가 critical drift
    surfaced 시 incident 로 escalate 가능 (별도 trigger).
    """
    if test_type not in _DRIFT_TEST_TYPES:
        raise ValueError(f"test_type must be {_DRIFT_TEST_TYPES}, got {test_type!r}")
    if severity not in _DRIFT_SEVERITIES:
        raise ValueError(f"severity must be {_DRIFT_SEVERITIES}, got {severity!r}")
    if test_statistic < 0.0:
        raise ValueError(f"test_statistic must be >= 0.0, got {test_statistic}")
    if threshold < 0.0:
        raise ValueError(f"threshold must be >= 0.0, got {threshold}")
    if n_baseline < 0 or n_current < 0:
        raise ValueError(f"n_baseline / n_current must be >= 0, got {n_baseline} / {n_current}")
    if not feature_name or not str(feature_name).strip():
        raise ValueError("feature_name required")

    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO drift_alerts
               (feature_name, test_type, test_statistic, threshold, severity,
                baseline_window, current_window, n_baseline, n_current,
                distribution_summary_json, actor_name, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                feature_name,
                test_type,
                float(test_statistic),
                float(threshold),
                severity,
                baseline_window,
                current_window,
                int(n_baseline),
                int(n_current),
                json.dumps(distribution_summary, sort_keys=True, default=str),
                actor_name,
                run_id,
            ),
        )
        return cursor.lastrowid or 0


# ═══════════════════════════════════════════════════════
# Foundation-Benchmark helper (#529 Phase 2 actor #7 — Layer B)
# ═══════════════════════════════════════════════════════

_FBENCH_VALID_KINDS: tuple[str, ...] = ("baseline", "foundation", "traditional")
_FBENCH_VALID_METRICS: tuple[str, ...] = ("brier", "logloss", "sharpe", "mse", "mae", "hit_rate")


def log_foundation_benchmark(
    benchmark_run: str,
    model_id: str,
    model_kind: str,
    metric_name: str,
    metric_value: float,
    higher_is_better: bool,
    sample_n: int,
    pit_hash: Optional[str] = None,
    walkforward_run_id: Optional[str] = None,
    notes: Optional[str] = None,
    actor_run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Foundation-Benchmark 단일 metric 기록 (#529 Phase 2 actor #7).

    benchmark_run: 'YYYY-MM-DD-<slug>' 그루핑 키 (같은 protocol 의 비교군).
    model_kind ∈ ('baseline','foundation','traditional') 검증.
    metric_name ∈ ('brier','logloss','sharpe','mse','mae','hit_rate') 검증.
    sample_n >= 0 검증 (음수 panic).
    pit_hash / walkforward_run_id: WalkForwardValidator audit join 용.

    Returns: lastrowid (benchmark_id).
    """
    if model_kind not in _FBENCH_VALID_KINDS:
        raise ValueError(f"model_kind must be one of {_FBENCH_VALID_KINDS}, got {model_kind!r}")
    if metric_name not in _FBENCH_VALID_METRICS:
        raise ValueError(f"metric_name must be one of {_FBENCH_VALID_METRICS}, got {metric_name!r}")
    if sample_n < 0:
        raise ValueError(f"sample_n must be >= 0, got {sample_n}")
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO foundation_benchmarks
               (benchmark_run, model_id, model_kind, metric_name, metric_value,
                higher_is_better, sample_n, pit_hash, walkforward_run_id,
                notes, actor_run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                benchmark_run,
                model_id,
                model_kind,
                metric_name,
                float(metric_value),
                1 if higher_is_better else 0,
                int(sample_n),
                pit_hash,
                walkforward_run_id,
                notes,
                actor_run_id,
            ),
        )
        return cursor.lastrowid or 0
