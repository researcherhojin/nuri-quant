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

# ─── 성장주 판별 섹터 (자동 분류 폴백용) ──────────────────────
GROWTH_SECTORS = {
    "EV", "AI", "Semiconductor", "Quantum", "SectorC", "Fintech",
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


# ═══════════════════════════════════════════════════════
# 익절 시그널 감지
# ═══════════════════════════════════════════════════════


def check_take_profit_signals(db_path: Optional[Path] = None) -> list[dict]:
    """포트폴리오 전체에서 익절 도달 종목 감지.

    각 보유 종목의 현재가를 진입가 대비 비교하여,
    1차/2차 익절 목표에 도달한 종목을 반환.

    Returns:
        list[dict]: 익절 시그널 리스트
            - ticker, stock_type, entry_price, current_price, return_pct
            - level ("target_1" or "target_2")
            - sell_pct (매도 비율: 50% or 25%)
    """
    df = query_df(
        "SELECT ticker, avg_price, quantity FROM portfolio WHERE quantity > 0",
        db_path=db_path,
    )
    if df.empty:
        return []

    signals = []
    for _, row in df.iterrows():
        ticker = row["ticker"]
        entry_price = row["avg_price"]
        if not entry_price or entry_price <= 0:
            continue

        current_price = _get_current_price(ticker, db_path=db_path)
        if current_price is None:
            logger.debug("No price data for %s, skipping take-profit check", ticker)
            continue

        stock_type = classify_stock_type(ticker, db_path=db_path)
        targets = calculate_targets(ticker, entry_price, stock_type, db_path=db_path)
        if "error" in targets:
            continue

        return_pct = (current_price / entry_price - 1) * 100

        # 2차 익절 도달 (우선)
        if current_price >= targets["target_2"]:
            sell_pct = TAKE_PROFIT_GROWTH.get("target_2_sell_pct", 25) if stock_type == "growth" else \
                       TAKE_PROFIT_SWING.get("target_2_sell_pct", 100) if stock_type == "swing" else \
                       TAKE_PROFIT_VALUE.get("target_2_sell_pct", 25)
            signals.append({
                "ticker": ticker, "stock_type": stock_type,
                "entry_price": entry_price, "current_price": current_price,
                "return_pct": round(return_pct, 1),
                "level": "target_2", "target_price": targets["target_2"],
                "sell_pct": sell_pct, "quantity": row["quantity"],
            })
        # 1차 익절 도달
        elif current_price >= targets["target_1"]:
            sell_pct = TAKE_PROFIT_GROWTH.get("target_1_sell_pct", 50) if stock_type == "growth" else \
                       TAKE_PROFIT_SWING.get("target_1_sell_pct", 50) if stock_type == "swing" else \
                       TAKE_PROFIT_VALUE.get("target_1_sell_pct", 50)
            signals.append({
                "ticker": ticker, "stock_type": stock_type,
                "entry_price": entry_price, "current_price": current_price,
                "return_pct": round(return_pct, 1),
                "level": "target_1", "target_price": targets["target_1"],
                "sell_pct": sell_pct, "quantity": row["quantity"],
            })

    return sorted(signals, key=lambda s: s["return_pct"], reverse=True)


# ═══════════════════════════════════════════════════════
# 트레일링 스톱 감지
# ═══════════════════════════════════════════════════════


def check_trailing_stop_signals(db_path: Optional[Path] = None) -> list[dict]:
    """포트폴리오 전체에서 트레일링 스톱 도달 종목 감지.

    각 보유 종목의 최고가(high water mark) 대비 현재가 하락률을 계산하여,
    임계값(-15% growth/value, -20% volatile/swing)을 초과하면 시그널 생성.

    Returns:
        list[dict]: 트레일링 스톱 시그널 리스트
    """
    df = query_df(
        "SELECT ticker, avg_price, quantity FROM portfolio WHERE quantity > 0",
        db_path=db_path,
    )
    if df.empty:
        return []

    signals = []
    for _, row in df.iterrows():
        ticker = row["ticker"]
        entry_price = row["avg_price"]
        if not entry_price or entry_price <= 0:
            continue

        current_price = _get_current_price(ticker, db_path=db_path)
        if current_price is None:
            logger.debug("No price data for %s, skipping trailing stop check", ticker)
            continue

        # 고점(HWM) 계산: prices 테이블에서 진입 이후 최고가
        hwm_rows = query(
            "SELECT MAX(high) as max_high FROM prices WHERE ticker = ?",
            (ticker,), db_path=db_path,
        )
        hwm = hwm_rows[0]["max_high"] if hwm_rows and hwm_rows[0]["max_high"] else None
        if hwm is None or hwm <= 0:
            continue

        # 진입가보다 낮으면 HWM = max(entry_price, hwm)
        hwm = max(hwm, entry_price)

        # 유형별 임계값
        stock_type = classify_stock_type(ticker, db_path=db_path)
        if stock_type == "swing":
            threshold = TRAILING_STOP_VOLATILE  # -20%
        elif stock_type == "growth":
            threshold = TRAILING_STOP_GROWTH    # -15%
        else:
            threshold = TRAILING_STOP_VALUE     # -15%

        # 하락률 계산
        drop_pct = (current_price / hwm - 1) * 100
        stop_price = round(hwm * (1 + threshold / 100), 2)

        if drop_pct <= threshold:
            signals.append({
                "ticker": ticker, "stock_type": stock_type,
                "entry_price": entry_price, "current_price": current_price,
                "high_water_mark": hwm, "stop_price": stop_price,
                "drop_pct": round(drop_pct, 1), "threshold": threshold,
                "status": "TRIGGERED", "quantity": row["quantity"],
            })

    return sorted(signals, key=lambda s: s["drop_pct"])


# ═══════════════════════════════════════════════════════
# 포트폴리오 MDD 손절
# ═══════════════════════════════════════════════════════


def check_portfolio_mdd(db_path: Optional[Path] = None) -> dict | None:
    """포트폴리오 전체 MDD가 -10% 한도를 초과하는지 확인.

    analyze_portfolio()의 환율 변환 로직을 활용하여 USD 기준 PnL 계산.

    Returns:
        dict: MDD 위반 정보. 위반 없으면 None.
    """
    from nuri.core.rules import PORTFOLIO_STOP

    # 환율 조회 (KRW → USD 변환용)
    from nuri.core.db import query as _q
    usd_krw = 1400.0  # 폴백
    try:
        fx_rows = _q("SELECT value FROM macro WHERE indicator = 'usd_krw' ORDER BY date DESC LIMIT 1", db_path=db_path)
        if fx_rows and fx_rows[0]["value"]:
            usd_krw = float(fx_rows[0]["value"])
    except Exception:
        pass

    holdings = query_df(
        "SELECT ticker, avg_price, quantity FROM portfolio WHERE quantity > 0",
        db_path=db_path,
    )
    if holdings.empty:
        return None

    total_cost = 0.0
    total_value = 0.0
    for _, row in holdings.iterrows():
        ticker = row["ticker"]
        avg_price = row["avg_price"] or 0
        qty = row["quantity"] or 0
        is_krw = ticker.endswith(".KS")

        cost = avg_price * qty
        current = _get_current_price(ticker, db_path=db_path)
        value = (current or avg_price) * qty

        # KRW 종목은 USD로 변환
        if is_krw and usd_krw > 0:
            cost /= usd_krw
            value /= usd_krw

        total_cost += cost
        total_value += value

    if total_cost <= 0:
        return None

    pnl_pct = (total_value / total_cost - 1) * 100

    if pnl_pct <= PORTFOLIO_STOP:
        return {
            "total_cost": round(total_cost, 2),
            "total_value": round(total_value, 2),
            "pnl_pct": round(pnl_pct, 1),
            "limit": PORTFOLIO_STOP,
            "severity": "critical",
            "message": f"포트폴리오 MDD {pnl_pct:.1f}% (한도 {PORTFOLIO_STOP}%)",
        }

    return None


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    targets = calculate_portfolio_targets()
    print_portfolio_targets(targets)
