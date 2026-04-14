from unittest import TestCase

from hummingbot.connector.exchange.thehub.thehub_order_book import TheHubOrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessageType

SNAPSHOT = {
    "market": "HMND/USDC",
    "sequence": 7,
    "updatedAt": 1710000000000,
    "bids": [
        {"priceE6": "1000000", "baseAmount": "2000000000000000000", "quoteAmount": "2000000", "totalBaseAmount": "2000000000000000000", "orderCount": 1},
        {"priceE6": "990000",  "baseAmount": "5000000000000000000", "quoteAmount": "4950000", "totalBaseAmount": "5000000000000000000", "orderCount": 2},
    ],
    "asks": [
        {"priceE6": "1100000", "baseAmount": "3000000000000000000", "quoteAmount": "3300000", "totalBaseAmount": "3000000000000000000", "orderCount": 1},
        {"priceE6": "1200000", "baseAmount": "1000000000000000000", "quoteAmount": "1200000", "totalBaseAmount": "1000000000000000000", "orderCount": 1},
    ],
    "bestBidE6": "1000000",
    "bestAskE6": "1100000",
    "lastTradePriceE6": "1050000",
    "recentTrades": [],
    "ownerOrders": [],
}

TRADE = {
    "priceE6": "1050000",
    "baseAmount": "500000000000000000",
    "side": "buy",
    "timestamp": 1710000001000,
    "txHash": "0xdeadbeef",
    "trading_pair": "HMND-USDC",
}


class TheHubOrderBookSnapshotTests(TestCase):
    def setUp(self):
        self.msg = TheHubOrderBook.snapshot_message_from_exchange(
            msg=dict(SNAPSHOT),
            timestamp=1710000000.0,
            metadata={"trading_pair": "HMND-USDC"},
        )

    def test_message_type_is_snapshot(self):
        self.assertEqual(OrderBookMessageType.SNAPSHOT, self.msg.type)

    def test_trading_pair(self):
        self.assertEqual("HMND-USDC", self.msg.trading_pair)

    def test_update_id_equals_sequence(self):
        self.assertEqual(7, self.msg.update_id)

    def test_timestamp(self):
        self.assertAlmostEqual(1710000000.0, self.msg.timestamp)

    def test_bid_price_converted_from_e6(self):
        best_bid_price = self.msg.bids[0][0]
        self.assertAlmostEqual(1.0, best_bid_price, places=6)

    def test_bid_size_converted_from_wei(self):
        best_bid_size = self.msg.bids[0][1]
        self.assertAlmostEqual(2.0, best_bid_size, places=9)

    def test_ask_price_converted_from_e6(self):
        best_ask_price = self.msg.asks[0][0]
        self.assertAlmostEqual(1.1, best_ask_price, places=6)

    def test_ask_size_converted_from_wei(self):
        best_ask_size = self.msg.asks[0][1]
        self.assertAlmostEqual(3.0, best_ask_size, places=9)

    def test_bid_count(self):
        self.assertEqual(2, len(self.msg.bids))

    def test_ask_count(self):
        self.assertEqual(2, len(self.msg.asks))

    def test_second_bid_price(self):
        self.assertAlmostEqual(0.99, self.msg.bids[1][0], places=6)

    def test_second_ask_price(self):
        self.assertAlmostEqual(1.2, self.msg.asks[1][0], places=6)


class TheHubOrderBookDiffTests(TestCase):
    def test_diff_message_has_diff_type(self):
        msg = TheHubOrderBook.diff_message_from_exchange(
            msg=dict(SNAPSHOT),
            timestamp=1710000000.0,
            metadata={"trading_pair": "HMND-USDC"},
        )
        self.assertEqual(OrderBookMessageType.DIFF, msg.type)

    def test_diff_bids_match_snapshot_bids(self):
        snap = TheHubOrderBook.snapshot_message_from_exchange(
            msg=dict(SNAPSHOT), timestamp=1710000000.0, metadata={"trading_pair": "HMND-USDC"},
        )
        diff = TheHubOrderBook.diff_message_from_exchange(
            msg=dict(SNAPSHOT), timestamp=1710000000.0, metadata={"trading_pair": "HMND-USDC"},
        )
        self.assertEqual(snap.bids, diff.bids)
        self.assertEqual(snap.asks, diff.asks)


class TheHubOrderBookTradeTests(TestCase):
    def setUp(self):
        self.msg = TheHubOrderBook.trade_message_from_exchange(msg=dict(TRADE))

    def test_message_type_is_trade(self):
        self.assertEqual(OrderBookMessageType.TRADE, self.msg.type)

    def test_trading_pair(self):
        self.assertEqual("HMND-USDC", self.msg.trading_pair)

    def test_price_converted_from_e6(self):
        self.assertAlmostEqual(1.05, self.msg.content["price"], places=6)

    def test_amount_converted_from_wei(self):
        self.assertAlmostEqual(0.5, self.msg.content["amount"], places=9)

    def test_timestamp_converted_from_ms(self):
        self.assertAlmostEqual(1710000001.0, self.msg.timestamp, places=0)

    def test_trade_id_is_tx_hash(self):
        self.assertEqual("0xdeadbeef", self.msg.content["trade_id"])
