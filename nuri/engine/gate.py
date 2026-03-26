"""
Gated Execution — SIEGE 패턴 적용.

파이프라인 각 단계 실행 전, 데이터/설정 준비 상태를 검증하는 게이트.
조건 미충족 시 실행을 차단하고, 무엇이 부족한지 명시적으로 보여준다.

사용법:
    python -m nuri.engine.gate
    python -m nuri.engine.gate --phase regime
"""
import argparse
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

from nuri.core.db import query

logger = logging.getLogger(__name__)


@dataclass
class GateCondition:
    """게이트 개별 조건."""
    id: str
    phase: str              # "collect", "validate", "regime", "recommend"
    description: str
    passed: bool
    detail: str             # 통과 시 수치, 실패 시 해결 방법


@dataclass
class GateResult:
    """게이트 전체 결과."""
    phase: str
    total: int
    passed: int
    score: float            # 0.0 ~ 1.0
    ready: bool             # 모든 필수 조건 통과
    conditions: list[GateCondition]


# ═══════════════════════════════════════════════════════
# 조건 정의
# ═══════════════════════════════════════════════════════

def _check_prices(db_path=None) -> GateCondition:
    rows = query("SELECT COUNT(*) as c, COUNT(DISTINCT ticker) as t FROM prices", db_path=db_path)
    count, tickers = rows[0]["c"], rows[0]["t"]
    ok = count >= 1000 and tickers >= 5
    return GateCondition(
        "prices_data", "collect",
        "가격 데이터 충분 (1000건+, 5종목+)",
        ok,
        f"{count:,}건, {tickers}종목" if ok else f"부족: {count}건, {tickers}종목. make collect 실행 필요",
    )


def _check_spy(db_path=None) -> GateCondition:
    rows = query("SELECT COUNT(*) as c FROM prices WHERE ticker = 'SPY'", db_path=db_path)
    count = rows[0]["c"]
    ok = count >= 200
    return GateCondition(
        "spy_data", "regime",
        "SPY 가격 200일+ (레짐 분류용)",
        ok,
        f"SPY {count}일" if ok else f"SPY {count}일 (200일 미만). SPY 수집 필요",
    )


def _check_vix(db_path=None) -> GateCondition:
    rows = query("SELECT COUNT(*) as c FROM macro WHERE indicator = 'vix'", db_path=db_path)
    count = rows[0]["c"]
    ok = count >= 20
    return GateCondition(
        "vix_data", "regime",
        "VIX 데이터 20일+ (변동성 판별용)",
        ok,
        f"VIX {count}일" if ok else f"VIX {count}일. ^VIX yfinance 수집 또는 FRED 필요",
    )


def _check_macro(db_path=None) -> GateCondition:
    rows = query("SELECT COUNT(DISTINCT indicator) as c FROM macro", db_path=db_path)
    count = rows[0]["c"]
    ok = count >= 3
    return GateCondition(
        "macro_indicators", "regime",
        "매크로 지표 3종+",
        ok,
        f"{count}종 보유" if ok else f"{count}종만 보유. FRED_API_KEY 설정 후 make collect",
    )


def _check_portfolio(db_path=None) -> GateCondition:
    rows = query("SELECT COUNT(DISTINCT ticker) as c FROM portfolio", db_path=db_path)
    count = rows[0]["c"]
    ok = count >= 1
    return GateCondition(
        "portfolio_exists", "collect",
        "포트폴리오 등록 (1종목+)",
        ok,
        f"{count}종목" if ok else "portfolio 비어있음. make setup 또는 import_portfolio.py",
    )


def _check_signal_scorecard(db_path=None) -> GateCondition:
    from pathlib import Path
    report_dir = Path(__file__).parent.parent.parent / "data" / "reports"
    found = False
    if report_dir.exists():
        for d in sorted(report_dir.iterdir(), reverse=True):
            if (d / "signal_scorecard.csv").exists():
                found = True
                break
    return GateCondition(
        "signal_scorecard", "validate",
        "시그널 스코어카드 CSV 존재",
        found,
        "존재" if found else "없음. make validate 먼저 실행",
    )


def _check_superinvestor_quarters(db_path=None) -> GateCondition:
    rows = query("SELECT COUNT(DISTINCT filing_date) as c FROM superinvestors", db_path=db_path)
    count = rows[0]["c"]
    ok = count >= 2
    return GateCondition(
        "superinvestor_history", "validate",
        "슈퍼투자자 13F 2분기+ (추종 백테스트용)",
        ok,
        f"{count}분기" if ok else f"{count}분기. python -m nuri.collectors.superinvestors 실행",
    )


def _check_estimates_accumulation(db_path=None) -> GateCondition:
    rows = query("SELECT MIN(date) as oldest, COUNT(DISTINCT date) as days FROM estimates", db_path=db_path)
    oldest = rows[0]["oldest"]
    days = rows[0]["days"]
    if oldest:
        elapsed = (datetime.now() - datetime.strptime(oldest, "%Y-%m-%d")).days
        ok = elapsed >= 90
        detail = f"{days}일 누적, {elapsed}일 경과" if ok else f"{days}일 누적, {elapsed}일 경과 (90일 필요, {90-elapsed}일 남음)"
    else:
        ok = False
        detail = "estimates 없음. python -m nuri.collectors.estimates 실행"
    return GateCondition(
        "estimates_90d", "validate",
        "애널리스트 estimates 90일+ 누적",
        ok, detail,
    )


def _check_fear_greed(db_path=None) -> GateCondition:
    rows = query("SELECT COUNT(*) as c FROM macro WHERE indicator = 'fear_greed'", db_path=db_path)
    count = rows[0]["c"]
    ok = count >= 1
    return GateCondition(
        "fear_greed", "collect",
        "Fear & Greed 지수 수집",
        ok,
        f"{count}건" if ok else "없음. make collect 실행",
    )


def _check_etf_flows(db_path=None) -> GateCondition:
    rows = query("SELECT COUNT(DISTINCT date) as c FROM etf_flows", db_path=db_path)
    count = rows[0]["c"]
    ok = count >= 2
    return GateCondition(
        "etf_flows_history", "collect",
        "ETF 자금흐름 2일+ (섹터 로테이션 분석용)",
        ok,
        f"{count}일" if ok else f"{count}일. python -m nuri.collectors.etf_flows 실행 (주 1회 자동)",
    )


# 전체 조건 목록
ALL_CHECKS = [
    _check_portfolio,
    _check_prices,
    _check_fear_greed,
    _check_spy,
    _check_vix,
    _check_macro,
    _check_signal_scorecard,
    _check_superinvestor_quarters,
    _check_estimates_accumulation,
    _check_etf_flows,
]

# 단계별 필수 조건
REQUIRED_BY_PHASE = {
    "collect": {"portfolio_exists"},
    "validate": {"prices_data", "signal_scorecard"},
    "regime": {"spy_data", "prices_data"},
    "recommend": {"prices_data", "spy_data", "signal_scorecard"},
}


# ═══════════════════════════════════════════════════════
# 게이트 실행
# ═══════════════════════════════════════════════════════


def check_gate(phase: str | None = None, db_path=None) -> GateResult:
    """파이프라인 게이트 검증.

    Args:
        phase: 특정 단계만 (None=전체)
    """
    conditions = []
    for check_fn in ALL_CHECKS:
        cond = check_fn(db_path=db_path)
        if phase and cond.phase != phase:
            continue
        conditions.append(cond)

    total = len(conditions)
    passed = sum(1 for c in conditions if c.passed)
    score = passed / total if total > 0 else 0

    # 필수 조건 확인
    required = REQUIRED_BY_PHASE.get(phase, set()) if phase else set()
    required_all_pass = all(
        c.passed for c in conditions if c.id in required
    ) if required else score >= 0.5

    return GateResult(
        phase=phase or "all",
        total=total,
        passed=passed,
        score=round(score, 2),
        ready=required_all_pass,
        conditions=conditions,
    )


def check_all_gates(db_path=None) -> dict[str, GateResult]:
    """모든 단계의 게이트를 개별적으로 검증."""
    return {
        phase: check_gate(phase, db_path)
        for phase in ["collect", "validate", "regime", "recommend"]
    }


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


def print_gate(result: GateResult) -> None:
    status = "READY" if result.ready else "BLOCKED"
    color_label = status
    print(f"\n{'=' * 60}")
    print(f"  Gate [{result.phase}]: {color_label} ({result.passed}/{result.total}, score {result.score:.0%})")
    print(f"{'=' * 60}")

    for c in result.conditions:
        icon = "[PASS]" if c.passed else "[FAIL]"
        print(f"  {icon} {c.description}")
        print(f"        {c.detail}")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant Pipeline Gate")
    parser.add_argument("--phase", choices=["collect", "validate", "regime", "recommend"],
                        help="특정 단계만 확인")
    args = parser.parse_args()

    if args.phase:
        result = check_gate(args.phase)
        print_gate(result)
    else:
        gates = check_all_gates()
        for phase, result in gates.items():
            print_gate(result)
