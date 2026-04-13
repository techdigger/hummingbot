import asyncio
import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import aiohttp

from hummingbot.connector.exchange.thehub import thehub_constants as CONSTANTS
from hummingbot.connector.exchange.thehub import thehub_web_utils as web_utils
from hummingbot.connector.exchange.thehub.thehub_order_book import TheHubOrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.logger import HummingbotLogger

if TYPE_CHECKING:
    from hummingbot.connector.exchange.thehub.thehub_exchange import TheHubExchange


class TheHubAPIOrderBookDataSource(OrderBookTrackerDataSource):
    HEARTBEAT_TIME_INTERVAL = CONSTANTS.HEARTBEAT_TIME_INTERVAL

    _logger: Optional[HummingbotLogger] = None

    def __init__(
        self,
        trading_pairs: List[str],
        connector: "TheHubExchange",
        api_factory: WebAssistantsFactory,
        domain: str = CONSTANTS.DOMAIN,
    ) -> None:
        super().__init__(trading_pairs)
        self._connector = connector
        self._domain = domain
        self._api_factory = api_factory

    # ------------------------------------------------------------------
    # REST snapshot
    # ------------------------------------------------------------------

    async def get_last_traded_prices(
        self, trading_pairs: List[str], domain: Optional[str] = None
    ) -> Dict[str, float]:
        return await self._connector.get_last_traded_prices(trading_pairs=trading_pairs)

    async def _request_order_book_snapshot(self, trading_pair: str) -> Dict[str, Any]:
        """GET /api/orderbook/{chain_id}/orderbook?market=HMND/USDC"""
        ex_pair = await self._connector.exchange_symbol_associated_to_pair(
            trading_pair=trading_pair
        )
        return await self._connector._api_get(
            path_url=web_utils.chain_path(CONSTANTS.ORDERBOOK_SNAPSHOT_PATH),
            params={"market": ex_pair},
        )

    async def _order_book_snapshot(self, trading_pair: str) -> OrderBookMessage:
        snapshot = await self._request_order_book_snapshot(trading_pair)
        timestamp = snapshot["updatedAt"] * 1e-3
        return TheHubOrderBook.snapshot_message_from_exchange(
            snapshot,
            timestamp,
            metadata={"trading_pair": trading_pair},
        )

    # ------------------------------------------------------------------
    # SSE public stream
    # TheHub SSE sends full orderbook snapshots; route them to the diff
    # queue so Hummingbot applies them as full replacements.
    # ------------------------------------------------------------------

    async def listen_for_subscriptions(self) -> None:
        while True:
            try:
                await self._listen_to_sse_stream()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception(
                    "SSE stream disconnected. Retrying in 5 seconds..."
                )
                await self._sleep(5.0)

    async def _listen_to_sse_stream(self) -> None:
        base_url = self._connector.thehub_api_url
        url = web_utils.public_rest_url(CONSTANTS.PUBLIC_STREAM_PATH, base_url)
        # sock_read timeout ensures we detect stale TCP connections that stop
        # sending data without closing (e.g. idle load balancers).
        timeout = aiohttp.ClientTimeout(
            total=None, sock_read=self.HEARTBEAT_TIME_INTERVAL * 2
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"Accept": "text/event-stream"}) as resp:
                resp.raise_for_status()
                # Per SSE spec: accumulate data lines; dispatch on blank line.
                event_name: Optional[str] = None
                data_buf: list[str] = []
                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8").rstrip("\r\n")
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_buf.append(line[5:].strip())
                    elif line == "":
                        # Blank line = dispatch accumulated event
                        if data_buf:
                            data_str = "\n".join(data_buf)
                            try:
                                msg = json.loads(data_str)
                            except json.JSONDecodeError:
                                pass
                            else:
                                if event_name:
                                    msg.setdefault("type", event_name)
                                await self._route_sse_event(msg)
                        event_name = None
                        data_buf = []

    async def _route_sse_event(self, msg: Dict[str, Any]) -> None:
        event_type = msg.get("type", "")
        if event_type in ("snapshot", "orderbook"):
            self._message_queue[self._diff_messages_queue_key].put_nowait(msg)
        elif event_type == "trade":
            self._message_queue[self._trade_messages_queue_key].put_nowait(msg)

    # ------------------------------------------------------------------
    # Message parsers (called by base-class listen_for_* loops)
    # ------------------------------------------------------------------

    async def _parse_order_book_diff_message(
        self, raw_message: Dict[str, Any], message_queue: asyncio.Queue
    ) -> None:
        trading_pair = await self._connector.trading_pair_associated_to_exchange_symbol(
            raw_message.get("market", "")
        )
        timestamp = raw_message.get("updatedAt", 0) * 1e-3
        msg = TheHubOrderBook.diff_message_from_exchange(
            raw_message,
            timestamp,
            metadata={"trading_pair": trading_pair},
        )
        message_queue.put_nowait(msg)

    async def _parse_order_book_snapshot_message(
        self, raw_message: Dict[str, Any], message_queue: asyncio.Queue
    ) -> None:
        await self._parse_order_book_diff_message(raw_message, message_queue)

    async def _parse_trade_message(
        self, raw_message: Dict[str, Any], message_queue: asyncio.Queue
    ) -> None:
        trading_pair = await self._connector.trading_pair_associated_to_exchange_symbol(
            raw_message.get("market", "")
        )
        msg = TheHubOrderBook.trade_message_from_exchange(
            raw_message,
            metadata={"trading_pair": trading_pair},
        )
        message_queue.put_nowait(msg)

    def _channel_originating_message(self, event_message: Dict[str, Any]) -> str:
        # Not used — SSE routing is handled by _route_sse_event directly
        return ""

    # ------------------------------------------------------------------
    # WebSocket stubs (not used — TheHub uses SSE)
    # ------------------------------------------------------------------

    async def subscribe_to_trading_pair(self, trading_pair: str) -> bool:
        # SSE stream is not per-pair; no incremental subscription needed
        return True

    async def unsubscribe_from_trading_pair(self, trading_pair: str) -> bool:
        return True

    async def _connected_websocket_assistant(self):  # type: ignore[override]
        raise NotImplementedError("TheHub uses SSE, not WebSocket")

    async def _subscribe_channels(self, ws) -> None:  # type: ignore[override]
        raise NotImplementedError("TheHub uses SSE, not WebSocket")
