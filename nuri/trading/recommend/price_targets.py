"""
가격 목표 계산기 — 진입가/손절가/익절가 산출 + 익절 도달 시 SELL 시그널 생성.

포트폴리오 보유 종목 및 개별 종목에 대해
rules.yaml 기반 손절/익절/트레일링 스톱 가격을 계산한다.
현재가가 1차/2차 익절 수준에 도달하면 자동으로 SELL 시그널을 생성한다.

사용법:
    python -m nuri.trading.recommend.price_targets
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from nuri.core.db import get_db, query, query_df
from nuri.core.rules import (
    STOCK_STOP_LOSS,
    STOCK_STOP_LOSS_VALUE,
    TAKE_PROFIT_GROWTH,
    TAKE_PROFIT_SWING,
    TAKE_PROFIT_VALUE,
    TRAILING_STOP_GROWTH,
    TRAILING_STOP_VALUE,
    TRAILING_STOP_VOLATILE,
)

logger = logging.getLogger(__name__)

# ─── 성장주 판별 섹터 (자동 분류 폴백용) ──────────────────────
GROWTH_SECTORS = {
    "EV", "AI", "Semiconductor", "Quantum", "Nuclear", "Fintech",
    "전기차", "반도체", "양자컴퓨터", "원자력", "핀테크", "인공지능",
}

# 성장주 판별 PE 임계값 (자동 분류 폴백용)
GROWTH_PE_THRESHOLD = 30

# ─── stock_types.yaml 캐시 ─────────────────────────────────
_STOCK_TYPES_PATH = Path(__file__).parent.parent.parent.parent / "config" / "stock_types.yaml"
_stock_types_cache: dict[str, str] | None = None


def _load_stock_types() -> dict[str, str]:
    """config/stock_types.yaml에서 종목별 유형 로드. 결과 캐시."""
    global _stock_types_cache
    if _stock_types_cache is not None:
        return _stock_types_cache

    import yaml

    mapping: dict[str, str] = {}
    if _STOCK_TYPES_PATH.exists():
        with open(_STOCK_TYPES_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for stock_type in ("growth", "value", "swing"):
            for ticker in data.get(stock_type, []):
                mapping[str(ticker)] = stock_type
        logger.debug("stock_types.yaml 로드: %d종목", len(mapping))
    _stock_types_cache = mapping
    return mapping


def classify_stock_type(
    ticker: str,
    db_path: Optional[Path] = None,
) -> str:
    """종목 유형 분류 — 'growth', 'value', 'swing' 중 하나 반환.

    분류 우선순위:
    1. config/stock_types.yaml에 명시된 종목 → 해당 유형
    2. PE > 30 → 'growth'
    3. 섹터가 성장 섹터 → 'growth'
    4. 나머지 → 'value'
    """
    # 1순위: stock_types.yaml 수동 오버라이드
    manual = _load_stock_types()
    if ticker in manual:
        return manual[ticker]

    # 2순위: PE ratio 기반
    pe_rows = query(
        "SELECT pe_ratio FROM fundamentals WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        (ticker,),
        db_path=db_path,
    )
    pe_ratio = pe_rows[0]["pe_ratio"] if pe_rows and pe_rows[0]["pe_ratio"] else None

    if pe_ratio is not None and pe_ratio > GROWTH_PE_THRESHOLD:
        return "growth"

    # 3순위: 섹터 기반
    sector_rows = query(
        "SELECT sector FROM portfolio WHERE ticker = ? LIMIT 1",
        (ticker,),
        db_path=db_path,
    )
    sector = sector_rows[0]["sector"] if sector_rows and sector_rows[0]["sector"] else ""

    if sector and any(gs.lower() in sector.lower() for gs in GROWTH_SECTORS):
        return "growth"

    return "value"


def _get_current_price(
    ticker: str,
    db_path: Optional[Path] = None,
) -> Optional[float]:
    """DB에서 최신 종가 조회."""
    rows = query(
        "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        (ticker,),
        db_path=db_path,
    )
    if rows and rows[0]["close"]:
        return float(rows[0]["close"])
    return None


def _get_analyst_target(
    ticker: str,
    db_path: Optional[Path] = None,
) -> Optional[float]:
    """DB에서 애널리스트 목표가 조회."""
    rows = query(
        "SELECT target_mean FROM estimates WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        (ticker,),
        db_path=db_path,
    )
    if rows and rows[0]["target_mean"]:
        return float(rows[0]["target_mean"])
    return None


def calculate_targets(
    ticker: str,
    entry_price: Optional[float] = None,
    stock_type: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict:
    """종목별 진입가/손절가/익절가/트레일링 스톱 계산.

    Args:
        ticker: 종목 티커
        entry_price: 진입가 (None이면 현재가 사용)
        stock_type: 종목 유형 ('growth', 'value', 'swing'). None이면 자동 분류
        db_path: DB 경로 (테스트용)

    Returns:
        dict: 가격 목표 정보
    """
    # 현재가 조회
    current_price = _get_current_price(ticker, db_path=db_path)
    if current_price is None:
        logger.warning("가격 데이터 없음: %s", ticker)
        return {"ticker": ticker, "error": "가격 데이터 없음"}

    # 진입가 결정
    if entry_price is None:
        entry_price = current_price

    # 종목 유형 분류
    if stock_type is None:
        stock_type = classify_stock_type(ticker, db_path=db_path)

    # 유형별 규칙 적용
    if stock_type == "growth":
        stop_loss_pct = STOCK_STOP_LOSS          # -7%
        target_1_pct = TAKE_PROFIT_GROWTH["target_1"]  # +20%
        target_2_pct = TAKE_PROFIT_GROWTH["target_2"]  # +40%
        trailing_stop_pct = TRAILING_STOP_GROWTH  # -15%
    elif stock_type == "swing":
        stop_loss_pct = STOCK_STOP_LOSS          # -7%
        target_1_pct = TAKE_PROFIT_SWING["target_1"]   # +5%
        target_2_pct = TAKE_PROFIT_SWING["target_2"]   # +10%
        trailing_stop_pct = TRAILING_STOP_VOLATILE      # -20% (스윙은 변동성 높음)
    else:  # value
        stop_loss_pct = STOCK_STOP_LOSS_VALUE    # -10%
        target_1_pct = TAKE_PROFIT_VALUE["target_1"]   # +15%
        target_2_pct = TAKE_PROFIT_VALUE["target_2"]   # +30%
        trailing_stop_pct = TRAILING_STOP_VALUE   # -15%

    # 가격 계산
    stop_loss = round(entry_price * (1 + stop_loss_pct / 100), 2)
    target_1 = round(entry_price * (1 + target_1_pct / 100), 2)
    target_2 = round(entry_price * (1 + target_2_pct / 100), 2)

    # 애널리스트 목표가
    analyst_target = _get_analyst_target(ticker, db_path=db_path)
    analyst_upside_pct = None
    if analyst_target is not None and entry_price > 0:
        analyst_upside_pct = round((analyst_target / entry_price - 1) * 100, 1)

    return {
        "ticker": ticker,
        "stock_type": stock_type,
        "current_price": current_price,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "stop_loss_pct": stop_loss_pct,
        "target_1": target_1,
        "target_1_pct": target_1_pct,
        "target_1_sell_pct": 50,           # 1차 익절 시 50% 매도
        "target_2": target_2,
        "target_2_pct": target_2_pct,
        "target_2_sell_pct": 25,           # 2차 익절 시 25% 매도
        "trailing_stop_pct": trailing_stop_pct,
        "analyst_target": analyst_target,
        "analyst_upside_pct": analyst_upside_pct,
    }


def calculate_portfolio_targets(
    db_path: Optional[Path] = None,
) -> list[dict]:
    """포트폴리오 전체 보유 종목의 가격 목표 계산.

    Returns:
        list[dict]: 종목별 가격 목표 리스트
    """
    df = query_df(
        "SELECT ticker, quantity, avg_price, sector FROM portfolio",
        db_path=db_path,
    )
    if df.empty:
        logger.warning("포트폴리오에 보유 종목 없음")
        return []

    targets = []
    for _, row in df.iterrows():
        ticker = row["ticker"]
        avg_price = row["avg_price"] if row["avg_price"] else None

        result = calculate_targets(
            ticker=ticker,
            entry_price=avg_price,
            db_path=db_path,
        )
        if "error" in result:
            logger.warning("건너뜀: %s — %s", ticker, result["error"])
            continue

        # 포트폴리오 추가 정보
        result["quantity"] = row["quantity"]
        result["avg_price"] = avg_price
        targets.append(result)

    # 종목명 기준 정렬
    targets.sort(key=lambda t: t["ticker"])
    return targets


def _type_label(stock_type: str) -> str:
    """종목 유형 한국어 라벨."""
    labels = {
        "growth": "성장주",
        "value": "가치주",
        "swing": "스윙",
    }
    return labels.get(stock_type, stock_type)


def _format_price(price: float, ticker: str = "") -> str:
    """가격 포맷팅 — KRW 또는 USD."""
    if ticker.endswith(".KS"):
        return f"₩{price:,.0f}"
    return f"${price:,.2f}"


def format_target_tree(target: dict) -> str:
    """가격 목표를 트리 형태 문자열로 포맷팅.

    예시:
        종목: NVDA (성장주)
        현재가: $168.00
        ├── 매수가 (진입): $165.00
        ├── 손절가: $153.45 (-7.0%)
        ├── 1차 익절: $198.00 (+20.0%) → 50% 매도
        ├── 2차 익절: $231.00 (+40.0%) → 25% 매도
        ├── 트레일링 스톱: 고점 대비 -15.0% (나머지 25%)
        └── 애널리스트 목표가: $273.61 (+63.4%)
    """
    if "error" in target:
        return f"종목: {target['ticker']} — {target['error']}"

    ticker = target["ticker"]
    type_label = _type_label(target["stock_type"])
    fp = lambda p: _format_price(p, ticker)  # noqa: E731

    lines = [
        f"종목: {ticker} ({type_label})",
        f"현재가: {fp(target['current_price'])}",
        f"├── 매수가 (진입): {fp(target['entry_price'])}",
        f"├── 손절가: {fp(target['stop_loss'])} ({target['stop_loss_pct']:+.1f}%)",
        f"├── 1차 익절: {fp(target['target_1'])} (+{target['target_1_pct']:.1f}%) → {target['target_1_sell_pct']}% 매도",
        f"├── 2차 익절: {fp(target['target_2'])} (+{target['target_2_pct']:.1f}%) → {target['target_2_sell_pct']}% 매도",
        f"├── 트레일링 스톱: 고점 대비 {target['trailing_stop_pct']:+.1f}% (나머지 25%)",
    ]

    # 애널리스트 목표가 (있을 때만)
    if target["analyst_target"] is not None:
        lines.append(
            f"└── 애널리스트 목표가: {fp(target['analyst_target'])} ({target['analyst_upside_pct']:+.1f}%)"
        )
    else:
        # 마지막 줄 교체: ├ → └
        lines[-1] = lines[-1].replace("├──", "└──")

    return "\n".join(lines)


def print_portfolio_targets(targets: list[dict]) -> None:
    """포트폴리오 전체 가격 목표 출력."""
    if not targets:
        print("포트폴리오에 가격 목표 대상 종목 없음")
        return

    print("=" * 60)
    print("포트폴리오 가격 목표")
    print("=" * 60)

    for i, target in enumerate(targets):
        if i > 0:
            print("-" * 50)
        print(format_target_tree(target))

    print("=" * 60)
    print(f"총 {len(targets)}개 종목")


@dataclass
class TakeProfitSignal:
    """익절 도달 시 생성되는 SELL 시그널."""
    ticker: str
    position_id: int
    stock_type: str
    direction: str          # "SELL"
    level: str              # "target_1" or "target_2"
    entry_price: float
    target_price: float
    current_price: float
    sell_pct: int           # 매도 비율 (50 또는 25)
    return_pct: float       # 현재 수익률
    note: str


def check_take_profit_signals(db_path: Optional[Path] = None) -> list[TakeProfitSignal]:
    """오픈 포지션 중 익절 도달 종목에 대해 SELL 시그널 생성.

    positions 테이블의 target_1_price, target_2_price와 현재가를 비교하여
    익절 가격에 도달한 종목에 대해 매도 시그널을 반환한다.

    Args:
        db_path: DB 경로 (테스트용)

    Returns:
        TakeProfitSignal 리스트
    """
    # 오픈 포지션 중 long 방향만 (short 익절은 별도 로직)
    open_positions = query(
        "SELECT id, ticker, entry_price, direction, target_1_price, target_2_price "
        "FROM positions WHERE status = 'open' AND direction = 'long'",
        db_path=db_path,
    )

    signals: list[TakeProfitSignal] = []

    for pos in open_positions:
        ticker = pos["ticker"]
        entry_price = pos["entry_price"]
        target_1 = pos["target_1_price"]
        target_2 = pos["target_2_price"]

        # 익절가가 설정되지 않은 포지션은 건너뜀
        if target_1 is None and target_2 is None:
            continue

        current_price = _get_current_price(ticker, db_path=db_path)
        if current_price is None:
            continue

        stock_type = classify_stock_type(ticker, db_path=db_path)
        return_pct = (current_price - entry_price) / entry_price * 100 if entry_price > 0 else 0

        # 2차 익절 도달 체크 (우선)
        if target_2 is not None and current_price >= target_2:
            signals.append(TakeProfitSignal(
                ticker=ticker,
                position_id=pos["id"],
                stock_type=stock_type,
                direction="SELL",
                level="target_2",
                entry_price=entry_price,
                target_price=target_2,
                current_price=current_price,
                sell_pct=25,  # 2차 익절: 25% 매도
                return_pct=round(return_pct, 1),
                note=f"2차 익절 도달 ({_type_label(stock_type)}): {return_pct:+.1f}% → 25% 매도",
            ))
        # 1차 익절 도달 체크
        elif target_1 is not None and current_price >= target_1:
            signals.append(TakeProfitSignal(
                ticker=ticker,
                position_id=pos["id"],
                stock_type=stock_type,
                direction="SELL",
                level="target_1",
                entry_price=entry_price,
                target_price=target_1,
                current_price=current_price,
                sell_pct=50,  # 1차 익절: 50% 매도
                return_pct=round(return_pct, 1),
                note=f"1차 익절 도달 ({_type_label(stock_type)}): {return_pct:+.1f}% → 50% 매도",
            ))

    return signals


def set_position_targets(
    position_id: int,
    entry_price: float,
    stock_type: Optional[str] = None,
    ticker: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> dict:
    """포지션에 익절가 설정 (positions 테이블 업데이트).

    Args:
        position_id: 포지션 ID
        entry_price: 진입가
        stock_type: 종목 유형. None이면 ticker 기반 자동 분류
        ticker: 종목 티커 (stock_type 자동 분류용)
        db_path: DB 경로 (테스트용)

    Returns:
        dict: 설정된 익절가 정보
    """
    if stock_type is None and ticker:
        stock_type = classify_stock_type(ticker, db_path=db_path)
    elif stock_type is None:
        stock_type = "growth"  # 기본값

    # 유형별 익절 비율 적용
    if stock_type == "growth":
        target_1_pct = TAKE_PROFIT_GROWTH["target_1"]  # +20%
        target_2_pct = TAKE_PROFIT_GROWTH["target_2"]  # +40%
    elif stock_type == "swing":
        target_1_pct = TAKE_PROFIT_SWING["target_1"]   # +5%
        target_2_pct = TAKE_PROFIT_SWING["target_2"]   # +10%
    else:  # value
        target_1_pct = TAKE_PROFIT_VALUE["target_1"]   # +15%
        target_2_pct = TAKE_PROFIT_VALUE["target_2"]   # +30%

    target_1_price = round(entry_price * (1 + target_1_pct / 100), 2)
    target_2_price = round(entry_price * (1 + target_2_pct / 100), 2)

    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE positions SET target_1_price = ?, target_2_price = ? WHERE id = ?",
            (target_1_price, target_2_price, position_id),
        )

    logger.info(
        "[TARGET SET] position #%d: 1차 익절 $%.2f (+%d%%), 2차 익절 $%.2f (+%d%%)",
        position_id, target_1_price, target_1_pct, target_2_price, target_2_pct,
    )

    return {
        "position_id": position_id,
        "stock_type": stock_type,
        "entry_price": entry_price,
        "target_1_price": target_1_price,
        "target_1_pct": target_1_pct,
        "target_2_price": target_2_price,
        "target_2_pct": target_2_pct,
    }


def print_take_profit_signals(signals: list[TakeProfitSignal]) -> None:
    """익절 시그널 CLI 출력."""
    if not signals:
        print("\n익절 도달 종목 없음")
        return

    print(f"\n{'=' * 60}")
    print("  Take-Profit Signals — 익절 도달 종목")
    print(f"{'=' * 60}")

    for sig in signals:
        fp = lambda p: _format_price(p, sig.ticker)  # noqa: E731
        print(f"  [{sig.level.upper()}] SELL {sig.ticker} ({_type_label(sig.stock_type)})")
        print(f"    진입가: {fp(sig.entry_price)} → 현재가: {fp(sig.current_price)} ({sig.return_pct:+.1f}%)")
        print(f"    목표가: {fp(sig.target_price)} → {sig.sell_pct}% 매도")
        print()

    print(f"{'=' * 60}")
    print(f"총 {len(signals)}건 익절 시그널")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    targets = calculate_portfolio_targets()
    print_portfolio_targets(targets)

    # 익절 도달 체크
    tp_signals = check_take_profit_signals()
    print_take_profit_signals(tp_signals)
