"""
브로커 추상 인터페이스 + Alpaca 페이퍼 트레이딩 구현.

환경변수:
    ALPACA_API_KEY — Alpaca API key (paper)
    ALPACA_SECRET_KEY — Alpaca secret key
    ALPACA_BASE_URL — 기본값: https://paper-api.alpaca.markets (페이퍼)

사용법:
    python -m nuri.trading.execution.broker --dry-run
"""
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """주문 결과."""
    broker: str
    ticker: str
    side: str           # "buy" / "sell"
    quantity: float
    order_type: str     # "market" / "limit"
    status: str         # "submitted" / "filled" / "rejected" / "dry_run"
    filled_price: Optional[float] = None
    order_id: Optional[str] = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class Position:
    """보유 포지션."""
    ticker: str
    quantity: float
    avg_price: float
    current_price: float
    pnl_pct: float


class BaseBroker(ABC):
    """브로커 인터페이스."""

    @abstractmethod
    def submit_order(self, ticker: str, side: str, quantity: float,
                     order_type: str = "market") -> Order:
        ...

    @abstractmethod
    def get_positions(self) -> list[Position]:
        ...

    @abstractmethod
    def get_account_value(self) -> float:
        ...

    @abstractmethod
    def cancel_all(self) -> int:
        ...


class DryRunBroker(BaseBroker):
    """드라이런 브로커 — 실제 주문 없이 로깅만."""

    def __init__(self):
        self._positions: list[Position] = []
        self._orders: list[Order] = []
        self._cash = 100_000.0

    def submit_order(self, ticker: str, side: str, quantity: float,
                     order_type: str = "market") -> Order:
        order = Order(
            broker="dry_run", ticker=ticker, side=side,
            quantity=quantity, order_type=order_type,
            status="dry_run", order_id=f"DRY-{len(self._orders)+1}",
        )
        self._orders.append(order)
        logger.info(f"[DRY RUN] {side.upper()} {quantity} {ticker} ({order_type})")
        return order

    def get_positions(self) -> list[Position]:
        return self._positions

    def get_account_value(self) -> float:
        return self._cash

    def cancel_all(self) -> int:
        return 0


class AlpacaBroker(BaseBroker):
    """Alpaca 페이퍼 트레이딩 브로커.

    ALPACA_API_KEY와 ALPACA_SECRET_KEY 환경변수 필요.
    기본값은 페이퍼 트레이딩 URL.
    """

    def __init__(self):
        self.api_key = os.getenv("ALPACA_API_KEY", "")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        self.base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

        if not self.api_key or not self.secret_key:
            raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY required")

        self._headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        }

    def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        import httpx
        url = f"{self.base_url}/v2{path}"
        r = httpx.request(method, url, headers=self._headers, json=json, timeout=10)
        r.raise_for_status()
        return r.json()

    def submit_order(self, ticker: str, side: str, quantity: float,
                     order_type: str = "market") -> Order:
        data = {
            "symbol": ticker,
            "qty": str(quantity),
            "side": side,
            "type": order_type,
            "time_in_force": "day",
        }
        try:
            result = self._request("POST", "/orders", json=data)
            return Order(
                broker="alpaca", ticker=ticker, side=side,
                quantity=quantity, order_type=order_type,
                status=result.get("status", "submitted"),
                filled_price=float(result["filled_avg_price"]) if result.get("filled_avg_price") else None,
                order_id=result.get("id"),
            )
        except Exception as e:
            logger.error(f"Alpaca order failed: {e}")
            return Order(
                broker="alpaca", ticker=ticker, side=side,
                quantity=quantity, order_type=order_type,
                status="rejected",
            )

    def get_positions(self) -> list[Position]:
        try:
            data = self._request("GET", "/positions")
            return [
                Position(
                    ticker=p["symbol"],
                    quantity=float(p["qty"]),
                    avg_price=float(p["avg_entry_price"]),
                    current_price=float(p["current_price"]),
                    pnl_pct=float(p["unrealized_plpc"]) * 100,
                )
                for p in data
            ]
        except Exception as e:
            logger.error(f"Alpaca positions failed: {e}")
            return []

    def get_account_value(self) -> float:
        try:
            data = self._request("GET", "/account")
            return float(data["portfolio_value"])
        except Exception:
            return 0.0

    def cancel_all(self) -> int:
        try:
            data = self._request("DELETE", "/orders")
            return len(data) if isinstance(data, list) else 0
        except Exception:
            return 0


def get_broker(dry_run: bool = True) -> BaseBroker:
    """브로커 팩토리. dry_run=False이면 Alpaca 연결 시도."""
    if dry_run:
        return DryRunBroker()

    try:
        return AlpacaBroker()
    except ValueError as e:
        logger.warning(f"Alpaca unavailable ({e}), falling back to dry run")
        return DryRunBroker()


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    broker = get_broker(dry_run=not args.live)
    print(f"Broker: {type(broker).__name__}")
    print(f"Account value: ${broker.get_account_value():,.2f}")
    print(f"Positions: {len(broker.get_positions())}")

    # 테스트 주문
    order = broker.submit_order("AAPL", "buy", 1)
    print(f"Order: {order.status} ({order.order_id})")
