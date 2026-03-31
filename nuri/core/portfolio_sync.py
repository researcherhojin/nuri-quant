"""DB → portfolio.yaml 역동기화.

portfolio 테이블의 현재 상태를 config/portfolio.yaml에 반영한다.
YAML에만 존재하는 메타데이터(name, broker, total_invested, cash_*, auto_invest 등)는 보존.
holdings dict는 flow style로 출력하여 원본 포맷과 일치시킨다.
metadata JSON 컬럼의 추가 필드(flag 등)도 YAML에 복원.
"""
import json
import logging
from pathlib import Path

import yaml

from nuri.core.db import query

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "portfolio.yaml"

# 원본 YAML 상단 주석
_YAML_HEADER = """\
# ═══════════════════════════════════════════════════════
# Nuri-Quant Portfolio Configuration
# Auto-synced from DB — manual edits may be overwritten
# ═══════════════════════════════════════════════════════

"""


class _HoldingFlowDumper(yaml.Dumper):
    """holdings 항목(ticker 키가 있는 dict)만 flow style로 출력."""
    pass


def _represent_dict(dumper: yaml.Dumper, data: dict):
    """ticker 키가 있는 dict → flow style, 나머지 → block style."""
    flow = "ticker" in data
    return dumper.represent_mapping("tag:yaml.org,2002:map", data.items(), flow_style=flow)


_HoldingFlowDumper.add_representer(dict, _represent_dict)


def _load_yaml(config_path: Path | None = None) -> dict:
    """기존 YAML 로드. 없으면 빈 구조 반환."""
    if config_path is None:
        config_path = CONFIG_PATH
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _build_holdings_from_db(db_path=None) -> dict[str, list[dict]]:
    """DB portfolio 테이블에서 계좌별 보유 종목 조회. metadata JSON → 추가 필드 복원."""
    rows = query(
        "SELECT account, ticker, quantity, avg_price, currency, sector, metadata "
        "FROM portfolio ORDER BY account, ticker",
        db_path=db_path,
    )
    by_account: dict[str, list[dict]] = {}
    for r in rows:
        account = r["account"]
        holding: dict = {
            "ticker": r["ticker"],
            "qty": r["quantity"],
            "avg": r["avg_price"],
        }
        if r["sector"]:
            holding["sector"] = r["sector"]
        # metadata JSON → YAML 추가 필드 복원 (flag 등)
        if r["metadata"]:
            try:
                extra = json.loads(r["metadata"])
                holding.update(extra)
            except (json.JSONDecodeError, TypeError):
                pass
        by_account.setdefault(account, []).append(holding)
    return by_account


def sync_portfolio_to_yaml(config_path: Path | None = None, db_path=None) -> int:
    """DB → YAML 역동기화. 메타데이터 보존, holdings만 교체.

    Returns:
        동기화된 총 종목 수.
    """
    if config_path is None:
        config_path = CONFIG_PATH
    existing = _load_yaml(config_path)
    accounts = existing.get("accounts", {})
    db_holdings = _build_holdings_from_db(db_path)

    # DB에 있는 계좌별 holdings 교체
    for account_id, holdings in db_holdings.items():
        if account_id not in accounts:
            accounts[account_id] = {}
        # currency는 첫 종목 기준 (같은 계좌는 동일 통화)
        rows = query(
            "SELECT DISTINCT currency FROM portfolio WHERE account=?",
            (account_id,),
            db_path=db_path,
        )
        if rows:
            accounts[account_id]["currency"] = rows[0]["currency"]
        accounts[account_id]["holdings"] = holdings

    # DB에서 삭제된 계좌의 holdings 제거 (메타데이터는 보존)
    for account_id in accounts:
        if account_id not in db_holdings:
            if "holdings" in accounts[account_id]:
                db_count = query(
                    "SELECT COUNT(*) as cnt FROM portfolio WHERE account=?",
                    (account_id,),
                    db_path=db_path,
                )
                if db_count and db_count[0]["cnt"] == 0:
                    del accounts[account_id]["holdings"]

    existing["accounts"] = accounts

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(_YAML_HEADER)
        yaml.dump(existing, f, Dumper=_HoldingFlowDumper,
                  allow_unicode=True, default_flow_style=False, sort_keys=False)

    total = sum(len(h) for h in db_holdings.values())
    logger.info("portfolio.yaml 동기화 완료: %d 종목", total)
    return total
