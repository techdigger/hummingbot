import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from hummingbot.connector.exchange.thehub import thehub_constants as CONSTANTS
from hummingbot.connector.exchange.thehub import thehub_web_utils as web_utils
from hummingbot.connector.exchange.thehub.thehub_api_order_book_data_source import (
    TheHubAPIOrderBookDataSource,
)
from hummingbot.core.data_type.order_book_message import OrderBookMessageType
from test.isolated_asyncio_wrapper_test_case import IsolatedAsyncioWrapperTestCase

TRADING_PAIR = "HMND-USDC"
EX_PAIR = "HMND/USDC"
BASE_URL = "http://127.0.0.1:7303"

SNAPSHOT_REST = {
    "market": EX_PAIR,
    "sequence": 12,
    "updatedAt": 1710000000000,
    "bids": [
        {"priceE6": "1000000", "baseAmount": "2000000000000000000", "quoteAmount": "2000000", "totalBaseAmount": "2000000000000000000", "orderCount": 1},
    ],
    "asks": [
        {"priceE6": "1100000", "baseAmount": "3000000000000000000", "quoteAmount": "3300000", "totalBaseAmount": "3000000000000000000", "orderCount": 1},
    ],
    "bestBidE6": "1000000",
    "bestAskE6": "1100000",
    "lastTradePriceE6": "1050000",
    "recentTrades": [],
    "ownerOrders": [],
}


def _make_connector() -> MagicMock:
    connector = MagicMock()
    connector.thehub_api_url = BASE_URL
    connector.exchange_symbol_associated_to_pair = AsyncMock(return_value=EX_PAIR)
    connector.trading_pair_associated_to_exchange_symbol = AsyncMock(return_value=TRADING_PAIR)
    connector.get_last_traded_prices = AsyncMock(return_value={TRADING_PAIR: 1.05})
    connector._api_get = AsyncMock(return_value=dict(SNAPSHOT_REST))
    return connector


def _make_datasource(connector=None) -> TheHubAPIOrderBookDataSource:
    connector = connector or _make_connector()
    return TheHubAPIOrderBookDataSource(
        trading_pairs=[TRADING_PAIR],
        connector=connector,
        api_factory=MagicMock(),
    )


class TheHubOrderBookDataSourceRestTests(IsolatedAsyncioWrapperTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.connector = _make_connector()
        self.data_source = _make_datasource(self.connector)

    async def test_request_snapshot_calls_correct_path(self):
        await self.data_source._request_order_book_snapshot(TRADING_PAIR)
        self.connector._api_get.assert_called_once_with(
            path_url=web_utils.chain_path(CONSTANTS.ORDERBOOK_SNAPSHOT_PATH),
            params={"market": EX_PAIR},
        )

    async def test_request_snapshot_resolves_exchange_symbol(self):
        await self.data_source._request_order_book_snapshot(TRADING_PAIR)
        self.connector.exchange_symbol_associated_to_pair.assert_called_once_with(
            trading_pair=TRADING_PAIR
        )

    async def test_order_book_snapshot_returns_snapshot_message(self):
        msg = await self.data_source._order_book_snapshot(TRADING_PAIR)
        self.assertEqual(OrderBookMessageType.SNAPSHOT, msg.type)

    async def test_order_book_snapshot_trading_pair(self):
        msg = await self.data_source._order_book_snapshot(TRADING_PAIR)
        self.assertEqual(TRADING_PAIR, msg.trading_pair)

    async def test_order_book_snapshot_update_id(self):
        msg = await self.data_source._order_book_snapshot(TRADING_PAIR)
        self.assertEqual(12, msg.update_id)

    async def test_order_book_snapshot_bid_price(self):
        msg = await self.data_source._order_book_snapshot(TRADING_PAIR)
        self.assertAlmostEqual(1.0, msg.bids[0][0], places=6)

    async def test_order_book_snapshot_ask_price(self):
        msg = await self.data_source._order_book_snapshot(TRADING_PAIR)
        self.assertAlmostEqual(1.1, msg.asks[0][0], places=6)

    async def test_get_last_traded_prices_delegates_to_connector(self):
        prices = await self.data_source.get_last_traded_prices([TRADING_PAIR])
        self.assertEqual({TRADING_PAIR: 1.05}, prices)


class TheHubOrderBookDataSourceSseRoutingTests(IsolatedAsyncioWrapperTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.data_source = _make_datasource()

    async def test_snapshot_sse_event_goes_to_diff_queue(self):
        msg = {"type": "snapshot", **SNAPSHOT_REST}
        await self.data_source._route_sse_event(msg)
        queue = self.data_source._message_queue[self.data_source._diff_messages_queue_key]
        self.assertFalse(queue.empty())
        item = queue.get_nowait()
        self.assertEqual("snapshot", item["type"])

    async def test_orderbook_sse_event_goes_to_diff_queue(self):
        msg = {"type": "orderbook", **SNAPSHOT_REST}
        await self.data_source._route_sse_event(msg)
        queue = self.data_source._message_queue[self.data_source._diff_messages_queue_key]
        self.assertFalse(queue.empty())

    async def test_trade_sse_event_goes_to_trade_queue(self):
        msg = {
            "type": "trade",
            "market": EX_PAIR,
            "priceE6": "1050000",
            "baseAmount": "500000000000000000",
            "side": "buy",
            "timestamp": 1710000001000,
            "txHash": "0xdeadbeef",
        }
        await self.data_source._route_sse_event(msg)
        queue = self.data_source._message_queue[self.data_source._trade_messages_queue_key]
        self.assertFalse(queue.empty())

    async def test_unknown_sse_event_is_ignored(self):
        await self.data_source._route_sse_event({"type": "heartbeat"})
        diff_queue = self.data_source._message_queue[self.data_source._diff_messages_queue_key]
        trade_queue = self.data_source._message_queue[self.data_source._trade_messages_queue_key]
        self.assertTrue(diff_queue.empty())
        self.assertTrue(trade_queue.empty())


class TheHubOrderBookDataSourceSseStreamTests(IsolatedAsyncioWrapperTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.data_source = _make_datasource()

    def _make_sse_response(self, events: list[dict]) -> MagicMock:
        """Build a mock aiohttp response that yields SSE lines."""
        lines = []
        for event in events:
            event_type = event.pop("type", None)
            if event_type:
                lines.append(f"event: {event_type}\n".encode())
            lines.append(f"data: {json.dumps(event)}\n".encode())
            lines.append(b"\n")

        async def _aiter():
            for line in lines:
                yield line

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.content.__aiter__ = lambda _: _aiter()
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        return mock_resp

    async def test_sse_stream_routes_snapshot_event_to_diff_queue(self):
        snapshot_event = {"type": "snapshot", **SNAPSHOT_REST}
        mock_resp = self._make_sse_response([dict(snapshot_event)])

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await self.data_source._listen_to_sse_stream()

        diff_queue = self.data_source._message_queue[self.data_source._diff_messages_queue_key]
        self.assertFalse(diff_queue.empty())

    async def test_sse_stream_connects_to_correct_url(self):
        mock_resp = self._make_sse_response([])
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await self.data_source._listen_to_sse_stream()

        expected_url = web_utils.public_rest_url(CONSTANTS.PUBLIC_STREAM_PATH, BASE_URL)
        mock_session.get.assert_called_once_with(
            expected_url, headers={"Accept": "text/event-stream"}
        )


class TheHubOrderBookDataSourceReconnectTests(IsolatedAsyncioWrapperTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.data_source = _make_datasource()

    async def test_listen_for_subscriptions_retries_on_error(self):
        call_count = 0

        async def failing_sse():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("dropped")
            raise asyncio.CancelledError

        self.data_source._listen_to_sse_stream = failing_sse
        self.data_source._sleep = AsyncMock()

        with self.assertRaises(asyncio.CancelledError):
            await self.data_source.listen_for_subscriptions()

        self.assertEqual(3, call_count)

    async def test_listen_for_subscriptions_sleeps_between_retries(self):
        call_count = 0

        async def failing_sse():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("dropped")
            raise asyncio.CancelledError

        self.data_source._listen_to_sse_stream = failing_sse
        self.data_source._sleep = AsyncMock()

        with self.assertRaises(asyncio.CancelledError):
            await self.data_source.listen_for_subscriptions()

        self.data_source._sleep.assert_called_once_with(5.0)


class TheHubOrderBookDataSourceParseTests(IsolatedAsyncioWrapperTestCase):
    """Tests for the _parse_* methods — the path the base class framework actually calls."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.data_source = _make_datasource()

    async def test_parse_diff_message_puts_orderbook_message_on_queue(self):
        raw = {"type": "snapshot", "trading_pair": EX_PAIR, **SNAPSHOT_REST}
        output: asyncio.Queue = asyncio.Queue()
        await self.data_source._parse_order_book_diff_message(raw, output)
        self.assertFalse(output.empty())
        msg = output.get_nowait()
        from hummingbot.core.data_type.order_book_message import OrderBookMessageType
        self.assertEqual(OrderBookMessageType.DIFF, msg.type)

    async def test_parse_diff_message_resolves_trading_pair(self):
        raw = {"type": "snapshot", "market": EX_PAIR, **SNAPSHOT_REST}
        output: asyncio.Queue = asyncio.Queue()
        await self.data_source._parse_order_book_diff_message(raw, output)
        msg = output.get_nowait()
        self.assertEqual(TRADING_PAIR, msg.trading_pair)

    async def test_parse_diff_message_bid_price(self):
        raw = {"type": "snapshot", "market": EX_PAIR, **SNAPSHOT_REST}
        output: asyncio.Queue = asyncio.Queue()
        await self.data_source._parse_order_book_diff_message(raw, output)
        msg = output.get_nowait()
        self.assertAlmostEqual(1.0, msg.bids[0][0], places=6)

    async def test_parse_trade_message_puts_trade_on_queue(self):
        raw = {
            "type": "trade",
            "market": EX_PAIR,
            "priceE6": "1050000",
            "baseAmount": "500000000000000000",
            "side": "buy",
            "timestamp": 1710000001000,
            "txHash": "0xdeadbeef",
        }
        output: asyncio.Queue = asyncio.Queue()
        await self.data_source._parse_trade_message(raw, output)
        self.assertFalse(output.empty())
        msg = output.get_nowait()
        from hummingbot.core.data_type.order_book_message import OrderBookMessageType
        self.assertEqual(OrderBookMessageType.TRADE, msg.type)

    async def test_parse_trade_message_resolves_trading_pair(self):
        raw = {
            "type": "trade",
            "market": EX_PAIR,
            "priceE6": "1050000",
            "baseAmount": "500000000000000000",
            "side": "sell",
            "timestamp": 1710000001000,
            "txHash": "0xdeadbeef",
        }
        output: asyncio.Queue = asyncio.Queue()
        await self.data_source._parse_trade_message(raw, output)
        msg = output.get_nowait()
        self.assertEqual(TRADING_PAIR, msg.trading_pair)

    async def test_parse_trade_message_price(self):
        raw = {
            "type": "trade",
            "market": EX_PAIR,
            "priceE6": "1050000",
            "baseAmount": "500000000000000000",
            "side": "buy",
            "timestamp": 1710000001000,
            "txHash": "0xdeadbeef",
        }
        output: asyncio.Queue = asyncio.Queue()
        await self.data_source._parse_trade_message(raw, output)
        msg = output.get_nowait()
        self.assertAlmostEqual(1.05, msg.content["price"], places=6)
