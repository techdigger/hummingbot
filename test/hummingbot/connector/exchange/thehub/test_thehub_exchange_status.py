"""
Unit tests for TheHubExchange order status parsing, status mapping, and partial fills.

These tests exercise the pure parsing/mapping logic without making real network calls.
"""

import asyncio
import unittest
from decimal import Decimal

from hummingbot.connector.exchange.thehub import thehub_constants as CONSTANTS
from hummingbot.connector.exchange.thehub.thehub_exchange import TheHubExchange
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState
from hummingbot.core.data_type.common import OrderType, TradeType

TRADING_PAIR = "HMND-USDC"
WALLET = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
ORDER_HASH = "0x" + "aa" * 32


def _make_exchange() -> TheHubExchange:
    # Ensure an event loop exists — needed by OrderBookTracker.__init__ in Python 3.10+
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return TheHubExchange(
        thehub_wallet_address=WALLET,
        thehub_private_key="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
        thehub_lop_address="0x1111111254EEB25477B68fb85Ed929f73A960582",
        thehub_api_url="http://127.0.0.1:7303",
        trading_pairs=[TRADING_PAIR],
        trading_required=True,
    )


def _make_tracked_order(
    client_order_id: str = "HBOT-buy-001",
    exchange_order_id: str = ORDER_HASH,
    state: OrderState = OrderState.OPEN,
) -> InFlightOrder:
    return InFlightOrder(
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        trading_pair=TRADING_PAIR,
        order_type=OrderType.LIMIT,
        trade_type=TradeType.BUY,
        amount=Decimal("10"),
        price=Decimal("1.25"),
        creation_timestamp=1_700_000_000.0,
        initial_state=state,
    )


class TestOrderStateMappings(unittest.TestCase):
    def test_all_statuses_mapped(self):
        expected_statuses = {"open", "partial", "filled", "cancelled", "expired", "rejected"}
        self.assertEqual(set(CONSTANTS.ORDER_STATE.keys()), expected_statuses)

    def test_open_maps_to_open(self):
        self.assertEqual(CONSTANTS.ORDER_STATE["open"], OrderState.OPEN)

    def test_partial_maps_to_partially_filled(self):
        self.assertEqual(CONSTANTS.ORDER_STATE["partial"], OrderState.PARTIALLY_FILLED)

    def test_filled_maps_to_filled(self):
        self.assertEqual(CONSTANTS.ORDER_STATE["filled"], OrderState.FILLED)

    def test_cancelled_maps_to_canceled(self):
        self.assertEqual(CONSTANTS.ORDER_STATE["cancelled"], OrderState.CANCELED)

    def test_expired_maps_to_failed(self):
        self.assertEqual(CONSTANTS.ORDER_STATE["expired"], OrderState.FAILED)

    def test_rejected_maps_to_failed(self):
        self.assertEqual(CONSTANTS.ORDER_STATE["rejected"], OrderState.FAILED)


class TestParseOrderUpdate(unittest.TestCase):
    def setUp(self):
        self.exchange = _make_exchange()
        self.tracked = _make_tracked_order()

    def _resting_order(self, status: str, updated_at_ms: int = 1_700_000_001_000) -> dict:
        return {
            "id": "order-001",
            "orderHash": ORDER_HASH,
            "market": "HMND/USDC",
            "owner": WALLET,
            "side": "buy",
            "orderType": "limit",
            "signature": "0xsig",
            "status": status,
            "statusCode": 1,
            "priceE6": "1250000",
            "baseAmount": str(10 * 10 ** 18),
            "quoteAmount": "12500000",
            "makingAmount": "12537500",
            "takingAmount": str(10 * 10 ** 18),
            "filledBaseAmount": "0",
            "remainingBaseAmount": str(10 * 10 ** 18),
            "expiry": None,
            "nonce": "0",
            "feeBps": 3,
            "protocol": "1inch-v4",
            "protocolOrder": {},
            "createdAt": 1_700_000_000_000,
            "updatedAt": updated_at_ms,
        }

    def test_open_order_parsed_correctly(self):
        update = self.exchange._parse_order_update(
            self._resting_order("open"), self.tracked
        )
        self.assertEqual(update.new_state, OrderState.OPEN)
        self.assertEqual(update.exchange_order_id, ORDER_HASH)
        self.assertEqual(update.client_order_id, self.tracked.client_order_id)
        self.assertEqual(update.trading_pair, TRADING_PAIR)

    def test_partial_fill_parsed_correctly(self):
        update = self.exchange._parse_order_update(
            self._resting_order("partial"), self.tracked
        )
        self.assertEqual(update.new_state, OrderState.PARTIALLY_FILLED)

    def test_filled_order_parsed_correctly(self):
        update = self.exchange._parse_order_update(
            self._resting_order("filled"), self.tracked
        )
        self.assertEqual(update.new_state, OrderState.FILLED)

    def test_cancelled_order_parsed_correctly(self):
        update = self.exchange._parse_order_update(
            self._resting_order("cancelled"), self.tracked
        )
        self.assertEqual(update.new_state, OrderState.CANCELED)

    def test_update_timestamp_converted_from_ms(self):
        update = self.exchange._parse_order_update(
            self._resting_order("open", updated_at_ms=1_700_000_002_000), self.tracked
        )
        self.assertAlmostEqual(update.update_timestamp, 1_700_000_002.0, places=0)

    def test_unknown_status_defaults_to_open(self):
        resting = self._resting_order("unknown_future_status")
        update = self.exchange._parse_order_update(resting, self.tracked)
        self.assertEqual(update.new_state, OrderState.OPEN)


class TestRestingOrderParsing(unittest.TestCase):
    """Verify that PrivateOrderbookState.ownerOrders fields are accessible."""

    def test_resting_order_required_fields_present(self):
        resting = {
            "id": "order-002",
            "orderHash": ORDER_HASH,
            "market": "HMND/USDC",
            "owner": WALLET,
            "side": "sell",
            "orderType": "limit",
            "signature": "0xsig2",
            "status": "partial",
            "statusCode": 1,
            "priceE6": "1260000",
            "baseAmount": str(5 * 10 ** 18),
            "quoteAmount": "6300000",
            "makingAmount": str(5 * 10 ** 18),
            "takingAmount": "6281100",
            "filledBaseAmount": str(2 * 10 ** 18),
            "remainingBaseAmount": str(3 * 10 ** 18),
            "expiry": None,
            "nonce": "0",
            "feeBps": 3,
            "protocol": "1inch-v4",
            "protocolOrder": {},
            "createdAt": 1_700_000_000_000,
            "updatedAt": 1_700_000_005_000,
        }
        # Verify we can access all fields the connector reads
        self.assertEqual(resting["orderHash"], ORDER_HASH)
        self.assertEqual(resting["status"], "partial")
        self.assertEqual(resting["feeBps"], CONSTANTS.FEE_BPS)
        filled_hmnd = Decimal(resting["filledBaseAmount"]) / Decimal("1e18")
        self.assertAlmostEqual(float(filled_hmnd), 2.0)


if __name__ == "__main__":
    unittest.main()
