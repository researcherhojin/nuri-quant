"""Tests for nuri.trading.execution.broker.

Extracted from tests/test_trading_engine_all.py (refactor #157).
Source: test_new_features.py, test_coverage_round10.py, test_coverage_round12.py,
test_coverage_round13.py, test_coverage_round16.py, test_coverage_round26.py,
test_coverage_boost.py, test_coverage_extra.py.
"""
from unittest.mock import MagicMock, patch

import pytest


class TestBroker:
    """From test_new_features.py."""

    def test_dry_run(self):
        from nuri.trading.execution.broker import get_broker
        broker = get_broker(dry_run=True)
        assert broker.get_account_value() == 100_000.0

        order = broker.submit_order("AAPL", "buy", 1)
        assert order.status == "dry_run"

    def test_factory_fallback(self):
        from nuri.trading.execution.broker import get_broker
        broker = get_broker(dry_run=False)
        assert broker.get_account_value() >= 0


class TestBroker_R10:
    """From test_coverage_round10.py."""

    def test_dryrun_submit_order(self, rich_db):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        result = broker.submit_order("AAPL", "buy", 10)
        assert result is not None

    def test_dryrun_sell_order(self, rich_db):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        result = broker.submit_order("AAPL", "sell", 5)
        assert result is not None

    def test_dryrun_get_positions(self, rich_db):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        positions = broker.get_positions()
        assert isinstance(positions, list)

    def test_get_broker_dryrun(self):
        from nuri.trading.execution.broker import get_broker
        broker = get_broker(dry_run=True)
        assert broker is not None


class TestBroker_R26:
    """From test_coverage_round26.py."""

    def test_dry_run_broker(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "dry_run"
        assert order.broker == "dry_run"
        assert broker.get_account_value() == 100_000.0
        assert broker.get_positions() == []
        assert broker.cancel_all() == 0

    def test_order_post_init_filled(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="filled")
        assert order.filled_qty == 10
        assert order.unfilled_qty == 0.0

    def test_order_post_init_unfilled(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="submitted")
        assert order.filled_qty == 0.0
        assert order.unfilled_qty == 10

    def test_order_is_partial(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="partially_filled",
                      filled_qty=5, unfilled_qty=5)
        assert order.is_partial is True

    def test_alpaca_no_keys(self, monkeypatch):
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
        from nuri.trading.execution.broker import AlpacaBroker
        with pytest.raises(ValueError):
            AlpacaBroker()

    def test_alpaca_submit_error(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
        from nuri.trading.execution.broker import AlpacaBroker
        broker = AlpacaBroker()
        monkeypatch.setattr(broker, "_request", MagicMock(side_effect=Exception("fail")))
        order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "rejected"

    def test_alpaca_submit_partial_fill(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
        from nuri.trading.execution.broker import AlpacaBroker
        broker = AlpacaBroker()
        monkeypatch.setattr(broker, "_request", MagicMock(return_value={
            "status": "filled", "filled_qty": "5", "filled_avg_price": "150.0", "id": "abc123",
        }))
        order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "partially_filled"
        assert order.is_partial

    def test_alpaca_get_positions_error(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
        from nuri.trading.execution.broker import AlpacaBroker
        broker = AlpacaBroker()
        monkeypatch.setattr(broker, "_request", MagicMock(side_effect=Exception("fail")))
        assert broker.get_positions() == []

    def test_alpaca_get_account_error(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
        from nuri.trading.execution.broker import AlpacaBroker
        broker = AlpacaBroker()
        monkeypatch.setattr(broker, "_request", MagicMock(side_effect=Exception("fail")))
        assert broker.get_account_value() == 0.0

    def test_alpaca_cancel_all_error(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
        from nuri.trading.execution.broker import AlpacaBroker
        broker = AlpacaBroker()
        monkeypatch.setattr(broker, "_request", MagicMock(side_effect=Exception("fail")))
        assert broker.cancel_all() == 0

    def test_get_broker_dry_run(self):
        from nuri.trading.execution.broker import DryRunBroker, get_broker
        b = get_broker(dry_run=True)
        assert isinstance(b, DryRunBroker)

    def test_get_broker_live_no_keys(self, monkeypatch):
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
        from nuri.trading.execution.broker import DryRunBroker, get_broker
        b = get_broker(dry_run=False)
        assert isinstance(b, DryRunBroker)


class TestBrokerOrder:
    """From test_coverage_round16.py."""

    def test_filled_order_auto_qty(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="filled")
        assert order.filled_qty == 10
        assert order.unfilled_qty == 0.0

    def test_pending_order_auto_qty(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="submitted")
        assert order.filled_qty == 0.0
        assert order.unfilled_qty == 10

    def test_partial_fill_detection(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="partially_filled",
                      filled_qty=5, unfilled_qty=5)
        assert order.is_partial is True

    def test_not_partial_when_fully_filled(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="filled")
        assert order.is_partial is False

    def test_explicit_timestamp(self):
        from nuri.trading.execution.broker import Order
        order = Order(broker="test", ticker="AAPL", side="buy", quantity=10,
                      order_type="market", status="dry_run", timestamp="2025-01-01T00:00:00")
        assert order.timestamp == "2025-01-01T00:00:00"


class TestDryRunBroker:
    """From test_coverage_round16.py."""

    def test_submit_order(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        order = broker.submit_order("AAPL", "buy", 5, "market")
        assert order.status == "dry_run"
        assert order.broker == "dry_run"
        assert order.order_id is not None and order.order_id.startswith("DRY-")

    def test_multiple_orders_increment_id(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        o1 = broker.submit_order("AAPL", "buy", 5)
        o2 = broker.submit_order("NVDA", "sell", 3)
        assert o1.order_id == "DRY-1"
        assert o2.order_id == "DRY-2"

    def test_get_positions(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        assert broker.get_positions() == []

    def test_get_account_value(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        assert broker.get_account_value() == 100_000.0

    def test_cancel_all(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        assert broker.cancel_all() == 0


class TestAlpacaBroker:
    """From test_coverage_round16.py."""

    def test_init_without_keys(self):
        from nuri.trading.execution.broker import AlpacaBroker
        with pytest.raises(ValueError, match="ALPACA_API_KEY"):
            AlpacaBroker()

    def test_init_with_keys(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "test-key")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
        broker = AlpacaBroker()
        assert broker.api_key == "test-key"
        assert broker.secret_key == "test-secret"

    def test_submit_order_success(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        mock_response = {
            "id": "order-123", "status": "filled",
            "filled_qty": "10", "filled_avg_price": "175.50",
        }
        with patch.object(broker, "_request", return_value=mock_response):
            order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "filled"
        assert order.filled_price == 175.50
        assert order.filled_qty == 10.0

    def test_submit_order_partial_fill(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        mock_response = {
            "id": "order-456", "status": "filled",
            "filled_qty": "5", "filled_avg_price": "175.50",
        }
        with patch.object(broker, "_request", return_value=mock_response):
            order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "partially_filled"
        assert order.filled_qty == 5.0
        assert order.unfilled_qty == 5.0
        assert order.is_partial is True

    def test_submit_order_failure(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", side_effect=Exception("network error")):
            order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "rejected"

    def test_get_positions_success(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        mock_data = [
            {"symbol": "AAPL", "qty": "10", "avg_entry_price": "170",
             "current_price": "180", "unrealized_plpc": "0.0588"},
        ]
        with patch.object(broker, "_request", return_value=mock_data):
            positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0].ticker == "AAPL"
        assert positions[0].pnl_pct == pytest.approx(5.88)

    def test_get_positions_failure(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", side_effect=Exception("fail")):
            positions = broker.get_positions()
        assert positions == []

    def test_get_account_value_success(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", return_value={"portfolio_value": "250000.50"}):
            value = broker.get_account_value()
        assert value == 250000.50

    def test_get_account_value_failure(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", side_effect=Exception("fail")):
            value = broker.get_account_value()
        assert value == 0.0

    def test_cancel_all_success(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", return_value=[{"id": "1"}, {"id": "2"}]):
            count = broker.cancel_all()
        assert count == 2

    def test_cancel_all_failure(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = AlpacaBroker()
        with patch.object(broker, "_request", side_effect=Exception("fail")):
            count = broker.cancel_all()
        assert count == 0


class TestGetBroker:
    """From test_coverage_round16.py."""

    def test_dry_run(self):
        from nuri.trading.execution.broker import DryRunBroker, get_broker
        broker = get_broker(dry_run=True)
        assert isinstance(broker, DryRunBroker)

    def test_no_alpaca_keys_fallback(self, monkeypatch):
        from nuri.trading.execution.broker import DryRunBroker, get_broker
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
        broker = get_broker(dry_run=False)
        assert isinstance(broker, DryRunBroker)

    def test_with_alpaca_keys(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker, get_broker
        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
        broker = get_broker(dry_run=False)
        assert isinstance(broker, AlpacaBroker)


class TestAlpacaBrokerMock:
    """From test_coverage_round13.py."""

    def test_alpaca_init_no_keys(self):
        from nuri.trading.execution.broker import AlpacaBroker
        with pytest.raises(ValueError):
            AlpacaBroker()

    def test_alpaca_submit_order(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "test-key")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
        broker = AlpacaBroker()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "order123", "status": "accepted"}
        with patch("requests.post", return_value=mock_resp):
            result = broker.submit_order("AAPL", "buy", 10)
        assert result is not None

    def test_alpaca_get_positions(self, monkeypatch):
        from nuri.trading.execution.broker import AlpacaBroker
        monkeypatch.setenv("ALPACA_API_KEY", "test-key")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
        broker = AlpacaBroker()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        with patch("requests.get", return_value=mock_resp):
            positions = broker.get_positions()
        assert isinstance(positions, list)


class TestAlpacaBroker_R12:
    """From test_coverage_round12.py."""

    def test_alpaca_broker_init_no_keys(self):
        from nuri.trading.execution.broker import get_broker
        broker = get_broker(dry_run=True)
        assert broker is not None

    def test_dryrun_submit_multiple(self, rich_db):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        r1 = broker.submit_order("AAPL", "buy", 10)
        r2 = broker.submit_order("AAPL", "sell", 5)
        r3 = broker.submit_order("NVDA", "buy", 3)
        assert r1 is not None
        assert r2 is not None
        assert r3 is not None


class TestBrokerPosition:
    """From test_coverage_extra.py."""

    def test_position_dataclass(self):
        from nuri.trading.execution.broker import Position
        p = Position("AAPL", 10, 150.0, 155.0, 3.3)
        assert p.ticker == "AAPL"
        assert p.pnl_pct == 3.3


class TestOrder:
    """From test_coverage_boost.py."""

    def test_create_filled(self):
        from nuri.trading.execution.broker import Order
        o = Order("test", "AAPL", "buy", 10, "market", "filled", 155.0)
        assert o.filled_qty == 10
        assert o.unfilled_qty == 0.0
        assert o.is_partial is False

    def test_create_submitted(self):
        from nuri.trading.execution.broker import Order
        o = Order("test", "AAPL", "buy", 10, "market", "submitted")
        assert o.filled_qty == 0.0
        assert o.unfilled_qty == 10

    def test_partial_fill(self):
        from nuri.trading.execution.broker import Order
        o = Order("test", "AAPL", "buy", 10, "market", "partially_filled", 155.0, 5, 5)
        assert o.is_partial is True

    def test_timestamp_auto(self):
        from nuri.trading.execution.broker import Order
        o = Order("test", "AAPL", "buy", 10, "market", "filled")
        assert o.timestamp != ""


class TestDryRunBroker_Boost:
    """From test_coverage_boost.py."""

    def test_submit_order(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        order = broker.submit_order("AAPL", "buy", 10)
        assert order.status == "dry_run"
        assert order.ticker == "AAPL"
        assert order.quantity == 10

    def test_sell_order(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        order = broker.submit_order("TSLA", "sell", 5, "limit")
        assert order.side == "sell"
        assert order.status == "dry_run"

    def test_get_positions(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        positions = broker.get_positions()
        assert isinstance(positions, list)

    def test_get_account_value(self):
        from nuri.trading.execution.broker import DryRunBroker
        broker = DryRunBroker()
        value = broker.get_account_value()
        assert isinstance(value, (int, float))


class TestGetBroker_Boost:
    """From test_coverage_boost.py."""

    def test_returns_dryrun_by_default(self, monkeypatch):
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        from nuri.trading.execution.broker import get_broker
        broker = get_broker()
        assert broker.__class__.__name__ == "DryRunBroker"
