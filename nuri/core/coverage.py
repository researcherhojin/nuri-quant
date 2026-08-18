"""Universe + agent data coverage 측정 — 순수 함수.

#272 Phase 2c 구현. 원 SPEC 은 PR #280/#284/#286 closed (TODO.md Tier 1 row 5).

이 모듈은 side effect 없이 결과만 계산. CLI/CI/UX 어디서나 재사용 가능.

데이터 흐름:
- universe.yaml → 기준 ticker set
- DB tables (prices/fundamentals/...) → 실제 채워진 ticker set
- compute_coverage() → CoverageCheck dataclass list

사용:
    from nuri.core.coverage import compute_all_coverage
    results = compute_all_coverage()
    for r in results:
        print(r.name, r.status, r.actual_pct)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from nuri.core.db import query

UNIVERSE_PATH = Path("config/universe.yaml")

# Coverage 임계값 (근거: TODO.md Tier 1 row 5, PR #284/#286/#288/#296/#343/#345 lineage — CLAUDE.md gotcha "Universe coverage 5-check gate")
DATA_THRESHOLDS: dict[str, float] = {
    "prices": 0.95,
    "fundamentals": 0.80,
    "analyst_ratings": 0.70,
    "insider_trades": 0.50,
    "superinvestors": 0.80,
}

# Spec §2.1 — universe self-coverage (always 1.0 for now)
UNIVERSE_THRESHOLD = 0.95

# 데이터 소스가 KR 종목을 지원하지 않는 테이블.
# - analyst_ratings: yfinance .KS는 애널리스트 데이터 미제공
# - insider_trades: SEC Form 4 — US 상장사 한정
# - superinvestors: SEC 13F — US 자산운용사 한정
# - estimates: yfinance .KS는 컨센서스 미제공 (estimates.py 자동 스킵)
# - earnings_surprises: yfinance .KS earnings 미제공
US_ONLY_TABLES: frozenset[str] = frozenset(
    {
        "analyst_ratings",
        "insider_trades",
        "superinvestors",
        "estimates",
        "earnings_surprises",
    }
)


@dataclass
class CoverageCheck:
    """단일 coverage check 결과."""

    name: str
    actual_pct: float
    threshold: float
    status: str  # 'PASS' | 'FAIL'
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def _load_universe(path: Optional[Path] = None) -> dict[str, set[str]]:
    """universe.yaml → {market: ticker_set}.

    Returns:
        {'us': {...}, 'kr': {...}}
    """
    p = path or UNIVERSE_PATH
    if not p.exists():
        return {"us": set(), "kr": set()}

    with p.open() as f:
        u = yaml.safe_load(f) or {}

    us = set((u.get("us_core") or {}).get("tickers") or [])
    us |= set((u.get("us_sp500_extended") or {}).get("tickers") or [])
    kr = set((u.get("kr_kospi200") or {}).get("tickers") or [])
    return {"us": us, "kr": kr}


#: 테이블별 추가 필터. 커버리지는 **우리가 판단에 쓰는 행**만 세야 한다.
#: `superinvestors` 에는 은행 13F(`dealer`)가 섞이는데(#1098), 은행은 사실상 유니버스
#: 전체를 들고 있어 이걸 포함하면 커버리지가 0.80 임계를 자동 통과한다 — 확신 13F 수집이
#: 죽어도 초록인 계기판이 된다.
_COVERAGE_FILTERS: dict[str, str] = {"superinvestors": "investor_class = 'conviction'"}


def _table_tickers(table: str, db_path: Optional[Path] = None) -> set[str]:
    """DB에서 해당 table의 unique ticker set 조회."""
    where = _COVERAGE_FILTERS.get(table)
    sql = f"SELECT DISTINCT ticker FROM {table}" + (f" WHERE {where}" if where else "")
    rows = query(sql, db_path=db_path)
    return {r["ticker"] for r in rows if r["ticker"]}


def compute_data_coverage(
    table: str,
    threshold: float,
    universe: dict[str, set[str]],
    db_path: Optional[Path] = None,
) -> CoverageCheck:
    """단일 데이터 테이블의 universe coverage 측정.

    US 기준만 평가 (대부분 데이터가 yfinance 의존, KR은 별도 검사).

    Args:
        table: DB table name (prices/fundamentals/analyst_ratings/...)
        threshold: 통과 기준 (0.0~1.0)
        universe: _load_universe() 결과
        db_path: 테스트용

    Returns:
        CoverageCheck — actual_pct, status (PASS/FAIL)
    """
    us_uni = universe["us"]
    if not us_uni:
        return CoverageCheck(
            name=f"data.{table}",
            actual_pct=0.0,
            threshold=threshold,
            status="FAIL",
            detail="universe.yaml에 us_core/us_sp500_extended 없음",
        )

    try:
        db_tickers = _table_tickers(table, db_path=db_path)
    except Exception as e:
        return CoverageCheck(
            name=f"data.{table}",
            actual_pct=0.0,
            threshold=threshold,
            status="FAIL",
            detail=f"table 조회 실패: {str(e)[:80]}",
        )

    matched = db_tickers & us_uni
    pct = len(matched) / len(us_uni)
    status = "PASS" if pct >= threshold else "FAIL"
    detail = f"{len(matched)}/{len(us_uni)} US tickers"
    if table in US_ONLY_TABLES:
        detail += " (KR n/a — 소스 미지원)"
    return CoverageCheck(
        name=f"data.{table}",
        actual_pct=pct,
        threshold=threshold,
        status=status,
        detail=detail,
    )


def compute_universe_match(
    label: str,
    upstream_tickers: set[str],
    universe: dict[str, set[str]],
    market: str = "us",
    threshold: float = UNIVERSE_THRESHOLD,
) -> CoverageCheck:
    """universe.yaml ↔ upstream (Wikipedia / KRX) 일치율.

    Args:
        label: 'us_sp500' | 'kr_kospi200'
        upstream_tickers: 외부 source에서 fetch한 ticker set (예: Wikipedia 503)
        universe: _load_universe() 결과
        market: 'us' | 'kr'
    """
    cur = universe[market]
    if not upstream_tickers:
        return CoverageCheck(
            name=f"universe.{label}",
            actual_pct=0.0,
            threshold=threshold,
            status="FAIL",
            detail="upstream fetch 실패 또는 빈 결과",
        )

    matched = cur & upstream_tickers
    pct = len(matched) / len(upstream_tickers)
    status = "PASS" if pct >= threshold else "FAIL"
    detail = f"{len(matched)}/{len(upstream_tickers)} matched"
    return CoverageCheck(
        name=f"universe.{label}",
        actual_pct=pct,
        threshold=threshold,
        status=status,
        detail=detail,
    )


def compute_all_data_coverage(
    universe: Optional[dict[str, set[str]]] = None,
    db_path: Optional[Path] = None,
) -> list[CoverageCheck]:
    """모든 데이터 테이블의 coverage check.

    DATA_THRESHOLDS 기준으로 5개 check 반환 (prices, fundamentals,
    analyst_ratings, insider_trades, superinvestors).
    """
    uni = universe if universe is not None else _load_universe()
    return [
        compute_data_coverage(table, threshold, uni, db_path=db_path) for table, threshold in DATA_THRESHOLDS.items()
    ]


def summary(checks: list[CoverageCheck]) -> dict:
    """결과 요약 dict — JSON 직렬화 가능.

    Returns:
        {'pass': N, 'fail': M, 'exit_code': 0 or 1, 'checks': [...]}
    """
    passed = sum(1 for c in checks if c.passed)
    failed = sum(1 for c in checks if not c.passed)
    return {
        "pass": passed,
        "fail": failed,
        "exit_code": 0 if failed == 0 else 1,
        "checks": [
            {
                "name": c.name,
                "actual": round(c.actual_pct, 4),
                "threshold": c.threshold,
                "status": c.status,
                "detail": c.detail,
            }
            for c in checks
        ],
    }
