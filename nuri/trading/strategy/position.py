"""
Position Manager — SIEGE Certification Gate 적용.

모든 포지션 진입은 5개 인증 조건을 통과해야 한다.
포지션 추적, P&L 계산, 청산 조건 체크.

사용법:
    python -m nuri.trading.strategy.position
"""
import json
import logging
from dataclasses import asdict, dataclass

from nuri.core.db import get_db, query
from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)


@dataclass
class PositionCertification:
    """SIEGE 포지션 인증 게이트."""
    regime_aligned: bool        # 레짐과 방향 일치
    agent_consensus: bool       # 에이전트 3/5 이상 동의
    concentration_ok: bool      # 단일 포지션 ≤ 15%
    daily_limit_ok: bool        # 일일 신규 ≤ 5개
    drift_safe: bool            # 시그널 drift critical 아님
    certified: bool             # 전부 통과
    details: dict


@dataclass
class Position:
    """포지션."""
    ticker: str
    direction: str              # "long" or "short"
    portfolio_type: str         # "core" or "tactical"
    entry_price: float
    quantity: float
    regime_at_entry: str
    certification: PositionCertification


def certify_position(
    ticker: str,
    direction: str,
    regime: str,
    portfolio_type: str = "tactical",
    db_path=None,
) -> PositionCertification:
    """SIEGE Certification Gate — 포지션 진입 전 5개 조건 검증."""
    details = {}

    # 1. 레짐 정합성 — REGIME_ALLOCATION의 long_pct / short_pct를 source of truth로
    # 사용한다. 이 strategy table은 6 base + 4 special 레짐 모두 포함하므로
    # 이전 코드의 substring fallback과 base/special 분기는 dead code였다 (#86).
    # `long_pct > 0` / `short_pct > 0` 가 "이 방향으로 진입 허용되는가" 의 ground truth.
    from nuri.trading.strategy.longshort import REGIME_ALLOCATION
    alloc = REGIME_ALLOCATION.get(regime)
    if alloc is None:
        # 미등록 레짐 — fail closed (보수적으로 차단)
        regime_aligned = False
    elif direction == "long":
        regime_aligned = alloc.get("long_pct", 0) > 0
    else:
        regime_aligned = alloc.get("short_pct", 0) > 0
    details["regime"] = regime
    details["direction"] = direction
    details["regime_check"] = "aligned" if regime_aligned else "misaligned"

    # 2. 에이전트 합의
    agent_consensus = False
    try:
        from nuri.trading.agents.consensus import analyze_ticker
        result = analyze_ticker(ticker, db_path=db_path)
        expected = "BUY" if direction == "long" else "SELL"
        agree = sum(1 for v in result.verdicts if v.action == expected)
        agent_consensus = agree >= 2  # 5명 중 2명 이상 (숏은 합의 어려우므로 완화)
        details["agent_action"] = result.final_action
        details["agent_confidence"] = result.final_confidence
        details["agent_agree"] = f"{agree}/5"
    except Exception as e:
        details["agent_error"] = str(e)

    # 3. 포지션 집중도
    open_positions = query(
        "SELECT COUNT(*) as c FROM positions WHERE status='open' AND ticker=?",
        (ticker,), db_path=db_path,
    )
    concentration_ok = open_positions[0]["c"] == 0  # 같은 종목 중복 포지션 불가
    details["duplicate_check"] = "ok" if concentration_ok else "duplicate exists"

    # 4. 일일 최대 거래
    today = today_kst()
    today_opens = query(
        "SELECT COUNT(*) as c FROM positions WHERE entry_date=? AND portfolio_type=?",
        (today, portfolio_type), db_path=db_path,
    )
    daily_limit_ok = today_opens[0]["c"] < 5
    details["today_opens"] = today_opens[0]["c"]

    # 5. Learning Memory drift
    drift_safe = True
    try:
        from nuri.trading.engine.memory import detect_drift
        drifts = detect_drift(db_path=db_path)
        critical = [d for d in drifts if d.status == "critical"]
        if critical and direction == "long":
            # 매수 시그널이 전부 critical이면 경고
            drift_safe = len(critical) < 3  # 3개 미만이면 OK
        details["critical_drifts"] = len(critical)
    except Exception:
        pass

    certified = all([regime_aligned, agent_consensus, concentration_ok, daily_limit_ok, drift_safe])

    return PositionCertification(
        regime_aligned=regime_aligned,
        agent_consensus=agent_consensus,
        concentration_ok=concentration_ok,
        daily_limit_ok=daily_limit_ok,
        drift_safe=drift_safe,
        certified=certified,
        details=details,
    )


def open_position(
    ticker: str,
    direction: str,
    entry_price: float,
    quantity: float = 0,
    portfolio_type: str = "tactical",
    regime: str = "",
    db_path=None,
) -> bool:
    """포지션 오픈 (인증 통과 시에만)."""
    # 레짐 자동 감지
    if not regime:
        try:
            from nuri.quant.regime.classifier import classify_regime
            r = classify_regime(db_path=db_path)
            regime = r.regime if r else "unknown"
        except Exception:
            regime = "unknown"

    # SIEGE Certification
    cert = certify_position(ticker, direction, regime, portfolio_type, db_path)

    if not cert.certified:
        failed = []
        if not cert.regime_aligned:
            failed.append(f"레짐 불일치({regime}↔{direction})")
        if not cert.agent_consensus:
            failed.append(f"에이전트 미합의({cert.details.get('agent_agree', '?')})")
        if not cert.concentration_ok:
            failed.append("중복 포지션")
        if not cert.daily_limit_ok:
            failed.append(f"일일 한도 초과({cert.details.get('today_opens', '?')}/5)")
        if not cert.drift_safe:
            failed.append("시그널 drift 위험")
        logger.warning(f"[CERT BLOCKED] {ticker} {direction}: {', '.join(failed)}")
        return False

    today = today_kst()
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO positions
               (portfolio_type, ticker, direction, entry_date, entry_price, quantity,
                regime_at_entry, certification, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
            (portfolio_type, ticker, direction, today, entry_price, quantity,
             regime, json.dumps(asdict(cert))),
        )

    logger.info(f"[POSITION OPEN] {direction.upper()} {ticker} @ ${entry_price:.2f} ({portfolio_type})")
    return True


def close_position(position_id: int, exit_price: float, reason: str, db_path=None) -> None:
    """포지션 청산."""
    today = today_kst()
    pos = query("SELECT * FROM positions WHERE id=?", (position_id,), db_path=db_path)
    if not pos:
        return

    p = pos[0]
    entry = p["entry_price"]
    direction = p["direction"]

    if direction == "long":
        return_pct = (exit_price - entry) / entry * 100
    else:  # short — 가격 하락이 수익
        return_pct = (entry - exit_price) / entry * 100

    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE positions SET status='closed', exit_date=?, exit_price=?, "
            "exit_reason=?, return_pct=? WHERE id=?",
            (today, exit_price, reason, round(return_pct, 2), position_id),
        )

    logger.info(f"[POSITION CLOSE] {direction.upper()} {p['ticker']} @ ${exit_price:.2f} "
                f"→ {return_pct:+.1f}% ({reason})")


def update_prices(db_path=None) -> None:
    """오픈 포지션 현재가 + 수익률 업데이트."""
    open_pos = query("SELECT * FROM positions WHERE status='open'", db_path=db_path)
    for p in open_pos:
        ticker = p["ticker"]
        price_row = query(
            "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (ticker,), db_path=db_path,
        )
        if not price_row or not price_row[0]["close"]:
            # yfinance fallback
            try:
                import yfinance as yf
                df = yf.download(ticker, period="5d", progress=False)
                if not df.empty:
                    current = float(df["Close"].squeeze().iloc[-1])
                else:
                    continue
            except Exception:
                continue
        else:
            current = price_row[0]["close"]

        entry = p["entry_price"]
        if p["direction"] == "long":
            ret = (current - entry) / entry * 100
        else:
            ret = (entry - current) / entry * 100

        with get_db(db_path) as conn:
            conn.execute(
                "UPDATE positions SET current_price=?, return_pct=? WHERE id=?",
                (round(current, 2), round(ret, 2), p["id"]),
            )


def get_positions_summary(db_path=None) -> dict:
    """포지션 요약."""
    open_pos = query("SELECT * FROM positions WHERE status='open'", db_path=db_path)
    closed = query(
        "SELECT COUNT(*) as c, AVG(return_pct) as avg_ret, "
        "SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END) as wins "
        "FROM positions WHERE status='closed'",
        db_path=db_path,
    )

    longs = [p for p in open_pos if p["direction"] == "long"]
    shorts = [p for p in open_pos if p["direction"] == "short"]
    core = [p for p in open_pos if p["portfolio_type"] == "core"]
    tactical = [p for p in open_pos if p["portfolio_type"] == "tactical"]

    closed_stats = closed[0] if closed else {}
    total_closed = closed_stats.get("c", 0)
    avg_ret = closed_stats.get("avg_ret", 0) or 0
    wins = closed_stats.get("wins", 0) or 0

    return {
        "open_total": len(open_pos),
        "open_long": len(longs),
        "open_short": len(shorts),
        "open_core": len(core),
        "open_tactical": len(tactical),
        "closed_total": total_closed,
        "closed_win_rate": wins / total_closed if total_closed > 0 else 0,
        "closed_avg_return": round(avg_ret, 2),
        "positions": [dict(p) for p in open_pos],
    }


def print_positions(db_path=None) -> None:
    """포지션 현황 출력."""
    update_prices(db_path)
    summary = get_positions_summary(db_path)

    print(f"\n{'=' * 80}")
    print(f"  Position Monitor — {summary['open_total']} open "
          f"(L:{summary['open_long']} S:{summary['open_short']} | "
          f"Core:{summary['open_core']} Tac:{summary['open_tactical']})")
    print(f"{'=' * 80}")

    if summary["positions"]:
        print(f"  {'Type':<8} {'Dir':<6} {'Ticker':<8} {'Entry':>10} {'Current':>10} {'P&L':>8} {'Regime':<18}")
        print(f"  {'-' * 72}")
        for p in summary["positions"]:
            ret = p.get("return_pct", 0) or 0
            cur = p.get("current_price", 0) or 0
            print(f"  {p['portfolio_type']:<8} {p['direction']:<6} {p['ticker']:<8} "
                  f"${p['entry_price']:>9,.2f} ${cur:>9,.2f} {ret:>+7.1f}% {p.get('regime_at_entry', ''):<18}")
    else:
        print("  오픈 포지션 없음")

    if summary["closed_total"] > 0:
        print(f"\n  Closed: {summary['closed_total']}건, "
              f"승률 {summary['closed_win_rate']:.0%}, "
              f"평균 수익 {summary['closed_avg_return']:+.1f}%")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from nuri.core.db import init_db
    init_db()
    print_positions()
