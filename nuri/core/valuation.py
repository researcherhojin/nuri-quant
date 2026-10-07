"""보유 평가액을 USD 기준으로 환산하는 공통 순수 함수."""

import math

from nuri.core.fx import is_krw_holding


def holding_value_usd(ticker, currency, quantity, price, rate: float | None) -> float | None:
    """가격/수량/환율 부재는 미상이다. 원가 대체 여부는 호출자가 명시한다."""
    if quantity is None or price is None:
        return None
    try:
        quantity, price = float(quantity), float(price)
        if not math.isfinite(quantity) or quantity < 0:
            return None
        if quantity == 0:
            return 0.0
        if not math.isfinite(price) or price <= 0:
            return None
        value = quantity * price
        rate = float(rate) if rate is not None else None
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    if is_krw_holding(ticker, currency):
        if rate is None or not math.isfinite(rate) or rate <= 0:
            return None
        return value / rate
    if str(currency or "USD").upper() != "USD":
        return None
    return value
