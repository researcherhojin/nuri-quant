"""
Long/Short Strategy Engine — 레짐 기반 방향 전환.

Bull → 롱 ETF + 개별종목
Bear → 인버스 ETF (SH, SQQQ)
Sideways → 축소 + 현금

사용법:
    python -m nuri.trading.strategy.longshort
    python -m nuri.trading.strategy.longshort --execute
"""
import argparse
import logging
from dataclasses import dataclass

from nuri.core.db import init_db, query

logger = logging.getLogger(__name__)

# 레짐 → 전략 매핑 (롱/숏/현금 비중)
# 근거: O'Neil/Minervini 방법론 + 6-사이트 외부 데이터 분석 (2026-03-28)
REGIME_ALLOCATION = {
    "bull_low_vol":     {"direction": "long",    "long_pct": 80, "short_pct": 0,  "cash_pct": 20, "note": "공격적 — 풀 포지션, 성장주 집중"},
    "bull_high_vol":    {"direction": "long",    "long_pct": 60, "short_pct": 0,  "cash_pct": 40, "note": "선택적 — 상위 시그널만, 팩터 상위 50%"},
    "sideways_low_vol": {"direction": "neutral", "long_pct": 40, "short_pct": 0,  "cash_pct": 60, "note": "중립 — 평균회귀, 스윙 위주"},
    "sideways_high_vol":{"direction": "neutral", "long_pct": 20, "short_pct": 0,  "cash_pct": 80, "note": "방어적 — 최소 포지션, 현금 극대화"},
    "bear_low_vol":     {"direction": "short",   "long_pct": 10, "short_pct": 30, "cash_pct": 60, "note": "숏 편향 — SH 헤지, 방어 섹터만 롱"},
    "bear_high_vol":    {"direction": "short",   "long_pct": 0,  "short_pct": 50, "cash_pct": 50, "note": "풀 숏 + 현금 — 관망, SH/SDS 보유"},
}

# 레짐 전환 시 행동 규칙
REGIME_TRANSITION_RULES = {
    ("bull_low_vol", "bull_high_vol"):       "롱 80%→60% 축소, VIX 모니터링",
    ("bull_high_vol", "sideways_low_vol"):   "롱 60%→40% 축소, 성장주 → 가치주 로테이션",
    ("bull_high_vol", "sideways_high_vol"):  "롱 60%→20% 축소, 현금 80%로 방어 전환",
    ("sideways_low_vol", "sideways_high_vol"): "롱 40%→20% 축소, 스윙 포지션 정리",
    ("sideways_high_vol", "bear_low_vol"):   "롱 20%→10%, 숏 30% 진입 (SH)",
    ("sideways_high_vol", "bear_high_vol"):  "롱 전량 청산, 숏 50% 진입 (SH/SDS)",
    ("bear_low_vol", "bear_high_vol"):       "롱 잔여분 청산, 숏 50%로 확대",
    ("bear_high_vol", "sideways_high_vol"):  "숏 전량 청산, 롱 20% 재진입",
    ("bear_low_vol", "sideways_low_vol"):    "숏 전량 청산, 롱 40%로 복귀",
    ("sideways_low_vol", "bull_low_vol"):    "롱 40%→80% 확대, 성장주 재진입",
    ("sideways_high_vol", "bull_low_vol"):   "롱 20%→80% 확대, 분할 매수",
}

# 롱/숏 ETF 유니버스
LONG_ETFS = ["QQQ", "SPY", "VOO"]
SHORT_ETFS = {
    "conservative": ["SH", "PSQ"],           # -1x
    "moderate": ["SDS"],                      # -2x
    "aggressive": ["SQQQ", "SPXU"],          # -3x (단기만)
}


@dataclass
class StrategyAction:
    """전략 실행 액션."""
    action: str             # "open_long", "open_short", "close", "hold", "switch"
    ticker: str
    direction: str          # "long" or "short"
    portfolio_type: str     # "tactical"
    reason: str
    regime: str
    confidence: float


def generate_strategy(db_path=None) -> list[StrategyAction]:
    """현재 레짐 기반 전략 액션 생성."""
    try:
        from nuri.quant.regime.classifier import classify_regime
        regime_state = classify_regime(db_path=db_path)
    except Exception:
        return []

    if regime_state is None:
        return []

    regime = regime_state.regime
    alloc = REGIME_ALLOCATION.get(regime, REGIME_ALLOCATION["sideways_high_vol"])
    direction = alloc["direction"]

    actions = []

    # 현재 오픈 포지션 확인
    open_longs = query(
        "SELECT * FROM positions WHERE status='open' AND direction='long' AND portfolio_type='tactical'",
        db_path=db_path,
    )
    open_shorts = query(
        "SELECT * FROM positions WHERE status='open' AND direction='short' AND portfolio_type='tactical'",
        db_path=db_path,
    )

    # ── 1. 레짐 전환 시 포지션 청산 ──
    # bear인데 tactical long이 있으면 → 청산
    if "bear" in regime:
        for pos in open_longs:
            actions.append(StrategyAction(
                "close", pos["ticker"], "long", "tactical",
                f"레짐 {regime} → tactical 롱 청산",
                regime, 90,
            ))

    # bull인데 tactical short이 있으면 → 청산
    if "bull" in regime:
        for pos in open_shorts:
            actions.append(StrategyAction(
                "close", pos["ticker"], "short", "tactical",
                f"레짐 {regime} → tactical 숏 청산",
                regime, 90,
            ))

    # ── 2. 새 포지션 오픈 ──
    if direction == "long" and not open_longs:
        # 롱 ETF 오픈
        for etf in LONG_ETFS[:2]:
            actions.append(StrategyAction(
                "open_long", etf, "long", "tactical",
                f"레짐 {regime} → 롱 ETF 진입",
                regime, regime_state.confidence * 100,
            ))

        # 스캐너 상위 종목 추가
        try:
            from nuri.trading.swing.scanner import scan_market
            scanned = scan_market(top_n=5)
            for sr in scanned[:3]:
                if sr.score >= 30:
                    actions.append(StrategyAction(
                        "open_long", sr.ticker, "long", "tactical",
                        f"스캐너 {sr.signal}(score={sr.score:.0f})",
                        regime, min(70, sr.score),
                    ))
        except Exception:
            pass

    elif direction == "short" and not open_shorts:
        # 인버스 ETF — 변동성에 따라 선택
        if "high" in regime:
            etfs = SHORT_ETFS["aggressive"][:1]  # SQQQ (단기)
        else:
            etfs = SHORT_ETFS["conservative"][:1]  # SH (보수적)

        for etf in etfs:
            actions.append(StrategyAction(
                "open_short", etf, "short", "tactical",
                f"레짐 {regime} → 인버스 ETF 진입",
                regime, regime_state.confidence * 100,
            ))

    elif direction == "neutral":
        # sideways — 기존 포지션 축소만, 신규 없음
        if alloc["short_pct"] > 0 and not open_shorts:
            # sideways_high_vol에서 소규모 헤지
            actions.append(StrategyAction(
                "open_short", "SH", "short", "tactical",
                f"레짐 {regime} → 소규모 헤지",
                regime, 40,
            ))

    # ── 3. 기존 포지션 P&L 체크 → 손절/익절 ──
    for pos in open_longs + open_shorts:
        ret = pos.get("return_pct", 0) or 0
        if ret >= 10:
            actions.append(StrategyAction(
                "close", pos["ticker"], pos["direction"], "tactical",
                f"익절 ({ret:+.1f}% ≥ +10%)",
                regime, 85,
            ))
        elif ret <= -5:
            actions.append(StrategyAction(
                "close", pos["ticker"], pos["direction"], "tactical",
                f"손절 ({ret:+.1f}% ≤ -5%)",
                regime, 95,
            ))

    return actions


def execute_strategy(actions: list[StrategyAction], db_path=None) -> int:
    """전략 액션 실행 (SIEGE Certification 적용)."""
    from nuri.trading.strategy.position import close_position, open_position, update_prices

    update_prices(db_path)
    executed = 0

    for a in actions:
        if a.action == "close":
            # 해당 포지션 찾아서 청산
            pos = query(
                "SELECT id, entry_price FROM positions WHERE ticker=? AND direction=? AND status='open' LIMIT 1",
                (a.ticker, a.direction), db_path=db_path,
            )
            if pos:
                # 현재가 조회
                price_row = query(
                    "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
                    (a.ticker,), db_path=db_path,
                )
                exit_price = price_row[0]["close"] if price_row and price_row[0]["close"] else a.confidence
                close_position(pos[0]["id"], exit_price, a.reason, db_path)
                executed += 1

        elif a.action in ("open_long", "open_short"):
            # 현재가 조회
            try:
                import yfinance as yf
                df = yf.download(a.ticker, period="5d", progress=False)
                if not df.empty:
                    price = float(df["Close"].squeeze().iloc[-1])
                else:
                    continue
            except Exception:
                continue

            # open_position 내부에서 SIEGE Certification 실행
            success = open_position(
                ticker=a.ticker,
                direction=a.direction,
                entry_price=price,
                portfolio_type=a.portfolio_type,
                regime=a.regime,
                db_path=db_path,
            )
            if success:
                executed += 1

    return executed


def print_strategy(actions: list[StrategyAction]) -> None:
    """전략 출력."""
    if not actions:
        print("전략 액션 없음 (현재 포지션 유지)")
        return

    # 현재 레짐 표시
    regime = actions[0].regime if actions else "unknown"
    alloc = REGIME_ALLOCATION.get(regime, {})

    print(f"\n{'=' * 75}")
    print(f"  Long/Short Strategy — {regime}")
    print(f"  Target: Long {alloc.get('long_pct', 0)}% / Short {alloc.get('short_pct', 0)}% / Cash {alloc.get('cash_pct', 0)}%")
    print(f"{'=' * 75}")

    closes = [a for a in actions if a.action == "close"]
    opens = [a for a in actions if a.action != "close"]

    if closes:
        print(f"\n  CLOSE ({len(closes)}건):")
        for a in closes:
            print(f"    {a.direction.upper()} {a.ticker} — {a.reason}")

    if opens:
        print(f"\n  OPEN ({len(opens)}건):")
        for a in opens:
            dir_label = "LONG" if "long" in a.action else "SHORT"
            print(f"    {dir_label} {a.ticker} — {a.reason} (conf: {a.confidence:.0f})")

    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()

    parser = argparse.ArgumentParser(description="Nuri-Quant Long/Short Strategy")
    parser.add_argument("--execute", action="store_true", help="전략 실행 (포지션 오픈/클로즈)")
    args = parser.parse_args()

    actions = generate_strategy()
    print_strategy(actions)

    if args.execute and actions:
        n = execute_strategy(actions)
        logger.info(f"전략 실행: {n}건")

        from nuri.trading.strategy.position import print_positions
        print_positions()
