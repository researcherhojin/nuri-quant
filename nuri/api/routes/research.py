"""검증 창고 (validation warehouse) 읽기 — 백테스트 + walk-forward 실행 이력.

backtests 테이블은 그동안 writer 가 없어 비어 있었다(Phase 3 placeholder). P1a 에서
save_backtest() writer + engine persist 로 채워진다. walkforward_runs 는 Phase 2
WalkForwardValidator 가 기록한다(현재 caller 부재 → P1b 에서 model_fn 어댑터로 활성화).

이 엔드포인트들은 read-only 로, 저장된 실행 이력을 그대로 surface 한다. 승격(weight>0)
판단의 근거가 되는 walk-forward 결과를 사람이 검토하기 위한 창구다. 자체 재계산 없음.

/api/research/* 네임스페이스 — swing.py 가 /api/backtest 를 이미 소유하므로 분리.
"""

import json
import logging

from fastapi import APIRouter, Query

from nuri.core.db import query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["research"])


def _loads(raw: str | None) -> dict:
    """TEXT 컬럼의 JSON 을 안전 파싱 (불량/None → 빈 dict)."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


@router.get("/research/backtests")
def list_backtests(limit: int = Query(20, ge=1, le=200)) -> dict:
    """backtests 테이블의 최근 실행 결과 (최신순)."""
    rows = query(
        """SELECT id, strategy_id, start_date, end_date, total_return, sharpe,
                  max_drawdown, win_rate, params, created_at,
                  code_rev, execution_config_sha_v1
           FROM backtests
           ORDER BY id DESC
           LIMIT ?""",
        (limit,),
    )
    backtests = [
        {
            "id": r["id"],
            "strategy_id": r["strategy_id"],
            "start_date": r["start_date"],
            "end_date": r["end_date"],
            "total_return": r["total_return"],
            "sharpe": r["sharpe"],
            "max_drawdown": r["max_drawdown"],
            "win_rate": r["win_rate"],
            "params": _loads(r["params"]),
            # 이 행을 만든 코드 리비전. 컬럼이 canonical (#1305); #1115~#1305 사이의
            # 행은 params JSON 안에만 있어 legacy fallback 으로 읽는다. 둘 다 없으면
            # **None** — 귀속 도입 전 행이라는 뜻이고, 그 자체가 정보다: 망가진 것으로
            # 판명된 코드의 산출물일 수 있는데 행만 봐서는 알 수 없다는 뜻이다.
            "code_rev": r["code_rev"] or _loads(r["params"]).get("code_rev"),
            "execution_config_sha_v1": r["execution_config_sha_v1"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return {"backtests": backtests, "count": len(backtests)}


@router.get("/research/walkforward")
def list_walkforward(limit: int = Query(20, ge=1, le=200)) -> dict:
    """walkforward_runs 의 최근 실행 (최신순). metrics 는 aggregate 만 surface."""
    rows = query(
        """SELECT run_id, model_id, n_folds, n_train_obs, n_test_obs,
                  metrics_json, started_at, finished_at, error_message
           FROM walkforward_runs
           ORDER BY started_at DESC
           LIMIT ?""",
        (limit,),
    )
    runs = [
        {
            "run_id": r["run_id"],
            "model_id": r["model_id"],
            "n_folds": r["n_folds"],
            "n_train_obs": r["n_train_obs"],
            "n_test_obs": r["n_test_obs"],
            # 폴드별 상세는 생략, 집계 지표만 (검토용 요약)
            "aggregate": _loads(r["metrics_json"]).get("aggregate", {}),
            "started_at": r["started_at"],
            "finished_at": r["finished_at"],
            "error_message": r["error_message"],
        }
        for r in rows
    ]
    return {"runs": runs, "count": len(runs)}
