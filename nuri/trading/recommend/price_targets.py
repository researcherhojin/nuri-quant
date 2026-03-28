"""
가격 목표 계산기 — 진입가/손절가/익절가 산출.

포트폴리오 보유 종목 및 개별 종목에 대해
rules.yaml 기반 손절/익절/트레일링 스톱 가격을 계산한다.

사용법:
    python -m nuri.trading.recommend.price_targets
"""
import logging
from pathlib import Path
from typing import Optional

from nuri.core.db import query, query_df
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

# ─── 성장주 판별 섹터 ────────────────────────────────────────
GROWTH_SECTORS = {
    "EV", "AI", "Semiconductor", "Quantum", "SectorC", "Fintech",
    # 한국어 섹터명도 포함
    "전기차", "반도체", "양자컴퓨터", "원자력", "핀테크", "인공지능",
}

# 성장주 판별 PE 임계값
GROWTH_PE_THRESHOLD = 30


def classify_stock_type(
    ticker: str,
    db_path: Optional[Path] = None,
) -> str:
    """종목 유형 분류 — 'growth', 'value', 'swing' 중 하나 반환.

    분류 기준:
    - PE > 30 또는 섹터가 성장 섹터에 해당하면 'growth'
    - 나머지는 'value'
    - 'swing'은 명시적으로 전달할 때만 사용
    """
    # PE ratio 조회
    pe_rows = query(
        "SELECT pe_ratio FROM fundamentals WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        (ticker,),
        db_path=db_path,
    )
    pe_ratio = pe_rows[0]["pe_ratio"] if pe_rows and pe_rows[0]["pe_ratio"] else None

    # 섹터 조회 (portfolio 테이블)
    sector_rows = query(
        "SELECT sector FROM portfolio WHERE ticker = ? LIMIT 1",
        (ticker,),
        db_path=db_path,
    )
    sector = sector_rows[0]["sector"] if sector_rows and sector_rows[0]["sector"] else ""

    # PE > 30이면 성장주
    if pe_ratio is not None and pe_ratio > GROWTH_PE_THRESHOLD:
        return "growth"

    # 섹터가 성장 섹터에 해당하면 성장주
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


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    targets = calculate_portfolio_targets()
    print_portfolio_targets(targets)
