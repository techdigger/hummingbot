"""
TheHub private user stream data source.

TheHub has no private WebSocket.  Private state is accessed via:
  1. POST /api/orderbook/private-session  (signed PrivateSessionIntent → token)
  2. GET  /api/orderbook/private-state    (poll with x-orderbook-private-token header)

This data source:
  - Acquires a session token using TheHubAuth.create_private_session_request().
  - Polls private-state every PRIVATE_STATE_POLL_INTERVAL seconds.
  - Refreshes the token before it expires.
  - Pushes {"channel": "private_state", "data": <PrivateOrderbookState>} into the queue.
"""

import asyncio
import time
from typing import TYPE_CHECKING, List, Optional

from hummingbot.connector.exchange.thehub import thehub_constants as CONSTANTS
from hummingbot.connector.exchange.thehub.thehub_auth import TheHubAuth
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.logger import HummingbotLogger

if TYPE_CHECKING:
    from hummingbot.connector.exchange.thehub.thehub_exchange import TheHubExchange


class TheHubAPIUserStreamDataSource(UserStreamTrackerDataSource):
    _logger: Optional[HummingbotLogger] = None

    def __init__(
        self,
        auth: TheHubAuth,
        trading_pairs: List[str],
        connector: "TheHubExchange",
        api_factory: WebAssistantsFactory,
        domain: str = CONSTANTS.DOMAIN,
    ) -> None:
        super().__init__()
        self._auth = auth
        self._trading_pairs = trading_pairs
        self._connector = connector
        self._api_factory = api_factory
        self._domain = domain

        self._private_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._last_recv_timestamp: float = 0.0

    @classmethod
    def logger(cls) -> HummingbotLogger:
        import logging
        if cls._logger is None:
            cls._logger = logging.getLogger(
                HummingbotLogger.logger_name_for_class(cls)
            )
        return cls._logger

    @property
    def last_recv_time(self) -> float:
        return self._last_recv_timestamp

    # ------------------------------------------------------------------
    # Main loop (overrides WS-based base)
    # ------------------------------------------------------------------

    async def listen_for_user_stream(self, output: asyncio.Queue) -> None:
        while True:
            try:
                await self._ensure_private_session()
                await self._poll_once(output)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception(
                    "Error polling TheHub private state. Retrying in "
                    f"{CONSTANTS.SSE_RECONNECT_DELAY}s..."
                )
                self._private_token = None
                await asyncio.sleep(CONSTANTS.SSE_RECONNECT_DELAY)
                continue

            await asyncio.sleep(CONSTANTS.PRIVATE_STATE_POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def _ensure_private_session(self) -> None:
        if self._private_token and time.time() < self._token_expires_at - 60:
            return

        self.logger().debug("Acquiring TheHub private session token...")
        request_body = self._auth.create_private_session_request(
            ttl_seconds=CONSTANTS.PRIVATE_SESSION_TTL
        )
        result = await self._connector._api_post(
            path_url=CONSTANTS.PRIVATE_SESSION_PATH,
            data=request_body,
        )
        self._private_token = result["token"]
        self._token_expires_at = float(
            result.get("expiresAt", time.time() + CONSTANTS.PRIVATE_SESSION_TTL)
        )
        self.logger().debug(f"Private session acquired, expires at {self._token_expires_at}.")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_once(self, output: asyncio.Queue) -> None:
        result = await self._connector._api_get(
            path_url=CONSTANTS.PRIVATE_STATE_PATH,
            params={"market": CONSTANTS.EXCHANGE_MARKET},
            headers={CONSTANTS.PRIVATE_SESSION_HEADER: self._private_token},
        )
        self._last_recv_timestamp = time.time()
        output.put_nowait({"channel": "private_state", "data": result})
