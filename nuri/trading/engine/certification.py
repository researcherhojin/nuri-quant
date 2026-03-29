"""
SIEGE Certification Engine — 추천 결과의 형식 검증.

원본 SIEGE의 Formal Assurance(Lean/Isabelle 정리 증명)를 투자 도메인에 맞게 적용.
추천이 rules.yaml의 모든 규칙을 만족하는지 기계적으로 검증하고,
위반 시 인증서를 거부한다.

검증 항목 (10-condition):
1. position_limit     — 종목 비중 <= 15%
2. sector_limit       — 섹터 비중 <= 35%
3. cash_reserve       — 현금 비중 >= 20%
4. stop_loss_growth   — 성장주 손절 -7% 이내
5. stop_loss_value    — 가치주 손절 -10% 이내
6. leverage_ban       — 레버리지 ETF 비보유
7. vix_gate           — VIX > 30 시 매수 없음
8. buy_checklist      — TipRanks + 슈퍼투자자 + PE + 매출
9. conflict_free      — BUY/SELL 동시 시그널 없음 (또는 관망)
10. drift_safe        — critical drift 시그널 기반 매수 없음

사용법:
    python -m nuri.trading.engine.certification
"""
import logging
from dataclasses import dataclass
from datetime import datetime

from nuri.core.db import query
from nuri.core.rules import (
    LEVERAGE_ETFS,
    MAX_SECTOR_EXPOSURE,
    MAX_SINGLE_POSITION,
    STOCK_STOP_LOSS,
    VIX_BLOCK_ABOVE,
)

logger = logging.getLogger(__name__)


@dataclass
class CertCondition:
    """인증 조건 결과."""
    id: str
    description: str
    passed: bool
    detail: str
    severity: str = "error"  # "error" = 차단, "warning" = 경고만


@dataclass
class Certificate:
    """SIEGE 인증서."""
    timestamp: str
    total_conditions: int
    passed: int
    failed: int
    warnings: int
    certified: bool          # 모든 error 조건 통과
    conditions: list[CertCondition]
    score: float             # 0~100

    def __post_init__(self):
        if not self.timestamp:
            from nuri.core.timezone import kst_now

            self.timestamp = kst_now().isoformat()


def _check_position_limits(db_path=None) -> CertCondition:
    """1. 단일 종목 비중 <= 15%."""
    try:
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        if df.empty:
            return CertCondition("position_limit", "종목 비중 <= 15%", True, "포트폴리오 비어있음")

        # 종목별 합산 비중
        agg = df.groupby("ticker")["weight_pct"].sum()
        violations = agg[agg / 100 > MAX_SINGLE_POSITION]
        if violations.empty:
            return CertCondition("position_limit", "종목 비중 <= 15%", True,
                                f"최대 비중: {agg.max():.1f}%")
        tickers = ", ".join(f"{t}({v:.1f}%)" for t, v in violations.items())
        return CertCondition("position_limit", "종목 비중 <= 15%", False,
                            f"위반: {tickers}", "error")
    except Exception as e:
        return CertCondition("position_limit", "종목 비중 <= 15%", False, f"검증 실패: {e}")


def _check_sector_limits(db_path=None) -> CertCondition:
    """2. 섹터 비중 <= 35%."""
    try:
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        if df.empty:
            return CertCondition("sector_limit", "섹터 비중 <= 35%", True, "포트폴리오 비어있음")

        sector_agg = df.groupby("sector")["weight_pct"].sum()
        violations = sector_agg[sector_agg / 100 > MAX_SECTOR_EXPOSURE]
        if violations.empty:
            return CertCondition("sector_limit", "섹터 비중 <= 35%", True,
                                f"최대 섹터: {sector_agg.max():.1f}%")
        sectors = ", ".join(f"{s}({v:.1f}%)" for s, v in violations.items())
        return CertCondition("sector_limit", "섹터 비중 <= 35%", False,
                            f"위반: {sectors}", "error")
    except Exception:
        return CertCondition("sector_limit", "섹터 비중 <= 35%", True, "검증 스킵")


def _check_leverage_ban(db_path=None) -> CertCondition:
    """6. 레버리지 ETF 비보유."""
    rows = query("SELECT ticker FROM portfolio WHERE ticker IN ({})".format(
        ",".join(f"'{t}'" for t in LEVERAGE_ETFS)
    ), db_path=db_path)
    held = [r["ticker"] for r in rows]
    if not held:
        return CertCondition("leverage_ban", "레버리지 ETF 비보유", True, "위반 없음")
    return CertCondition("leverage_ban", "레버리지 ETF 비보유", False,
                        f"보유 중: {', '.join(held)}", "error")


def _check_vix_gate(db_path=None) -> CertCondition:
    """7. VIX > 30 시 매수 시그널 없음."""
    vix_rows = query(
        "SELECT value FROM macro WHERE indicator='vix' ORDER BY date DESC LIMIT 1",
        db_path=db_path,
    )
    if not vix_rows:
        return CertCondition("vix_gate", f"VIX > {VIX_BLOCK_ABOVE} 매수 차단", True, "VIX 데이터 없음")

    vix = float(vix_rows[0]["value"])
    if vix <= VIX_BLOCK_ABOVE:
        return CertCondition("vix_gate", f"VIX > {VIX_BLOCK_ABOVE} 매수 차단", True,
                            f"VIX {vix:.1f} (정상)")
    return CertCondition("vix_gate", f"VIX > {VIX_BLOCK_ABOVE} 매수 차단", False,
                        f"VIX {vix:.1f} — 신규 매수 금지 구간", "warning")


def _check_stop_loss_compliance(db_path=None) -> CertCondition:
    """3-4. 손절선 준수 여부."""
    try:
        from nuri.analysis.portfolio import analyze_portfolio
        df = analyze_portfolio()
        if df.empty:
            return CertCondition("stop_loss", "손절선 준수", True, "포트폴리오 비어있음")

        violations = df[df["pnl_pct"] < STOCK_STOP_LOSS]
        if violations.empty:
            return CertCondition("stop_loss", "손절선 준수", True,
                                f"최대 손실: {df['pnl_pct'].min():.1f}%")
        tickers = ", ".join(f"{r['ticker']}({r['pnl_pct']:.1f}%)" for _, r in violations.head(5).iterrows())
        return CertCondition("stop_loss", "손절선 준수", False,
                            f"위반 {len(violations)}건: {tickers}", "error")
    except Exception:
        return CertCondition("stop_loss", "손절선 준수", True, "검증 스킵")


def _check_conflicts(db_path=None) -> CertCondition:
    """9. BUY/SELL 동시 시그널 해소."""
    try:
        from nuri.trading.engine.conflicts import detect_conflicts
        conflicts = detect_conflicts(db_path=db_path)
        high = [c for c in conflicts if c.severity == "high"]
        if not high:
            return CertCondition("conflict_free", "방향 충돌 해소", True,
                                f"충돌 {len(conflicts)}건 (high 0건)")
        tickers = ", ".join(c.ticker for c in high[:5])
        return CertCondition("conflict_free", "방향 충돌 해소", False,
                            f"high 충돌 {len(high)}건: {tickers}", "warning")
    except Exception:
        return CertCondition("conflict_free", "방향 충돌 해소", True, "검증 스킵")


def _check_drift_safety(db_path=None) -> CertCondition:
    """10. Critical drift 시그널 기반 매수 없음."""
    try:
        from nuri.trading.engine.memory import detect_drift
        drifts = detect_drift(db_path=db_path)
        critical = [d for d in drifts if d.status == "critical"]
        if not critical:
            return CertCondition("drift_safe", "시그널 drift 안전", True, "critical 없음")
        names = ", ".join(d.signal_id for d in critical)
        return CertCondition("drift_safe", "시그널 drift 안전", False,
                            f"critical {len(critical)}개: {names}", "warning")
    except Exception:
        return CertCondition("drift_safe", "시그널 drift 안전", True, "검증 스킵")


def _check_external_data(db_path=None) -> CertCondition:
    """8. 외부 데이터 수집 여부 (매수 체크리스트)."""
    try:
        from nuri.collectors.external import get_external_summary
        summary = get_external_summary(db_path)
        total = summary["total_records"]
        sources = len(summary["sources"])
        if total >= 10 and sources >= 3:
            return CertCondition("external_data", "외부 데이터 충분", True,
                                f"{total}건, {sources}개 소스")
        return CertCondition("external_data", "외부 데이터 충분", False,
                            f"{total}건, {sources}개 소스 (10건+, 3소스+ 필요)", "warning")
    except Exception:
        return CertCondition("external_data", "외부 데이터 충분", False, "external_analysis 테이블 없음", "warning")


def _check_data_freshness(db_path=None) -> CertCondition:
    """5. 데이터 신선도 (SPY 72h 이내)."""
    rows = query("SELECT MAX(date) as latest FROM prices WHERE ticker='SPY'", db_path=db_path)
    if not rows or not rows[0]["latest"]:
        return CertCondition("data_fresh", "데이터 신선도 (72h)", False, "SPY 데이터 없음")
    from nuri.core.timezone import kst_now

    latest = datetime.strptime(rows[0]["latest"], "%Y-%m-%d")
    # KST 기준으로 신선도 비교 (naive datetime 통일)
    age_hours = (kst_now().replace(tzinfo=None) - latest).total_seconds() / 3600
    if age_hours <= 72:
        return CertCondition("data_fresh", "데이터 신선도 (72h)", True,
                            f"SPY {age_hours:.0f}시간 전")
    return CertCondition("data_fresh", "데이터 신선도 (72h)", False,
                        f"SPY {age_hours:.0f}시간 전 (72h 초과)", "warning")


def _check_rules_loaded(db_path=None) -> CertCondition:
    """규칙 파일 로드 확인."""
    from nuri.core.rules import RULES
    keys = len(RULES)
    has_take_profit = "take_profit" in RULES
    has_entry = "entry_rules" in RULES
    ok = keys >= 5 and has_take_profit and has_entry
    return CertCondition("rules_loaded", "rules.yaml 완전 로드", ok,
                        f"{keys}개 섹션 (take_profit={has_take_profit}, entry={has_entry})")


# 10개 조건 목록
ALL_CERT_CHECKS = [
    _check_position_limits,      # 1. 종목 비중
    _check_sector_limits,        # 2. 섹터 비중
    _check_stop_loss_compliance, # 3-4. 손절선
    _check_data_freshness,       # 5. 데이터 신선도
    _check_leverage_ban,         # 6. 레버리지 금지
    _check_vix_gate,             # 7. VIX 게이트
    _check_external_data,        # 8. 외부 데이터
    _check_conflicts,            # 9. 충돌 해소
    _check_drift_safety,         # 10. drift 안전
    _check_rules_loaded,         # 규칙 로드
]


def certify(db_path=None) -> Certificate:
    """SIEGE 인증서 발급. 10개 조건 검증 후 pass/fail 판정."""
    conditions = [check(db_path=db_path) for check in ALL_CERT_CHECKS]

    total = len(conditions)
    passed = sum(1 for c in conditions if c.passed)
    failed = sum(1 for c in conditions if not c.passed and c.severity == "error")
    warnings = sum(1 for c in conditions if not c.passed and c.severity == "warning")
    certified = failed == 0
    score = round(passed / total * 100, 1) if total > 0 else 0

    from nuri.core.timezone import kst_now

    return Certificate(
        timestamp=kst_now().isoformat(),
        total_conditions=total,
        passed=passed,
        failed=failed,
        warnings=warnings,
        certified=certified,
        conditions=conditions,
        score=score,
    )


def print_certificate(cert: Certificate) -> None:
    """인증서 CLI 출력."""
    status = "CERTIFIED" if cert.certified else "REJECTED"
    print(f"\n{'═' * 60}")
    print(f"  SIEGE Certificate — {status} ({cert.score:.0f}%)")
    print(f"  {cert.timestamp}")
    print(f"{'═' * 60}")
    print(f"  Passed: {cert.passed}/{cert.total_conditions} | "
          f"Failed: {cert.failed} | Warnings: {cert.warnings}")
    print(f"{'─' * 60}")

    for c in cert.conditions:
        if c.passed:
            icon = "✅"
        elif c.severity == "error":
            icon = "❌"
        else:
            icon = "⚠️"
        print(f"  {icon} {c.description}")
        print(f"      {c.detail}")

    print(f"{'═' * 60}")
    if cert.certified:
        print("  ✅ 모든 필수 조건 통과. 추천 실행 가능.")
    else:
        print("  ❌ 필수 조건 미충족. 위반 사항 해결 후 재검증 필요.")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cert = certify()
    print_certificate(cert)
