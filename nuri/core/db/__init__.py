"""
Nuri-Quant 데이터베이스 모듈 — 모든 DB 접근의 단일 진입점.

다른 모듈에서 sqlite3를 직접 import하지 않는다 (PreToolUse hook 차단).
모든 DB 작업은 이 모듈의 함수를 통해서만 수행한다.

Package layout (P2 Stage 2 — PR #566):
    connection.py — sole sqlite3 importer + lifecycle (get_db, init_db, DB_PATH)
    __init__.py   — facade: query/query_df/get_tickers + all writer functions
                    (behavior modules to be extracted in follow-up commits)
"""

from pathlib import Path
from typing import Optional

import pandas as pd

from nuri.core.db_migrations import _MIGRATIONS, _SCHEMA, _SCHEMA_VERSION_TABLE  # noqa: F401 — back-compat re-export

from .agent_runtime import (  # noqa: F401, E402
    finish_agent_run,
    log_agent_audit,
    log_agent_message,
    log_collector_run,
    set_feature_flag,
    start_agent_run,
    upsert_dr_replica,
)
from .audit import (  # noqa: F401, E402
    audit_log,
    log_external_llm_call,
)
from .candidate_ledger_ops import (  # noqa: F401, E402
    get_candidate_run,
    mark_acted,
    record_candidate_run,
)
from .connection import (  # noqa: F401 — facade re-exports for back-compat
    DB_PATH,
    DatabaseError,
    OperationalError,
    _apply_migrations,
    get_connection,
    get_db,
    init_db,
)
from .decisions import (  # noqa: F401, E402
    insert_certification,
    upsert_decision,
    upsert_decision_evidence,
)
from .discord_outbox_ops import CLAIM_LEASE_SECONDS as CLAIM_LEASE_SECONDS  # noqa: E402
from .discord_outbox_ops import claim_pending_outbox as claim_pending_outbox  # noqa: E402
from .discord_outbox_ops import mark_outbox_failed as mark_outbox_failed  # noqa: E402
from .discord_outbox_ops import mark_outbox_sent as mark_outbox_sent  # noqa: E402
from .discord_outbox_ops import outbox_health as outbox_health  # noqa: E402
from .discord_outbox_ops import stage_outbox as stage_outbox  # noqa: E402
from .execution_ops import (  # noqa: F401, E402
    acknowledge_incident,
    log_decision,
    log_decision_outcome,
    log_drift_alert,
    log_execution_block,
    log_incident,
    resolve_incident,
)

# ═══════════════════════════════════════════════════════
# Submodule re-exports — P2 Stage 2 PR-B (writer split)
# ═══════════════════════════════════════════════════════
from .market_data import (  # noqa: F401, E402
    insert_events,
    upsert_ark,
    upsert_macro,
    upsert_macro_events,
    upsert_news,
    upsert_prices,
    upsert_signals,
)
from .portfolio import (  # noqa: F401, E402
    replace_portfolio_account,
    upsert_portfolio,
)
from .postmortem_ops import (  # noqa: F401, E402
    find_similar_days,
    upsert_postmortem,
)
from .research_ops import (  # noqa: F401, E402
    expire_hypotheses,
    log_causal_audit,
    log_foundation_benchmark,
    log_regime_posterior,
    log_walkforward_run,
    register_hypothesis,
    reject_hypothesis,
    save_backtest,
    validate_hypothesis,
)
from .thesis_ops import (  # noqa: F401, E402
    ThesisValidationError,
    add_criteria,
    get_active_thesis,
    get_criteria,
    get_thesis_history,
    upsert_thesis,
)
from .trades import upsert_trade  # noqa: F401, E402


def get_schema_version(db_path: Optional[Path] = None) -> int:
    """현재 적용된 최신 스키마 버전 반환. 마이그레이션 없으면 0."""
    rows = query(
        "SELECT MAX(version) as v FROM schema_version",
        db_path=db_path,
    )
    return rows[0]["v"] or 0 if rows and rows[0]["v"] is not None else 0


# ═══════════════════════════════════════════════════════
# 조회 함수 (root facade — codex 'do not split' list, monkeypatch-sensitive)
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


def get_trades(ticker: Optional[str] = None, db_path: Optional[Path] = None) -> list[dict]:
    """매매 실행 기록 조회. ticker 필터 선택적."""
    if ticker:
        return query(
            "SELECT * FROM trades WHERE ticker = ? ORDER BY executed_at DESC",
            (ticker,),
            db_path,
        )
    return query("SELECT * FROM trades ORDER BY executed_at DESC", db_path=db_path)


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
    # PIT 조인 — `decisions.thesis_id` 컬럼이 아니다. 컬럼이면 기존 행이 영원히 NULL 이지만,
    # 조인이면 그 티커의 첫 논지를 쓰는 순간 **기존 결정 전부**가 논지를 갖는다 (#1083).
    decision["thesis"] = get_active_thesis(decision["ticker"], as_of=decision["date"], db_path=db_path)
    return decision


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
