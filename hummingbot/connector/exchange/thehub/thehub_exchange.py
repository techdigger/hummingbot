"""
TheHub spot CLOB connector for Hummingbot.

Architecture:
  - Signing:     EIP-712 via TheHubAuth (1inch v4 LOP + backend intents)
  - Order book:  SSE stream (/api/orderbook/stream) — full snapshots
  - Private data: Polling (/api/orderbook/private-state) — signed session token
  - Balances:    Humanode JSON-RPC eth_call (balanceOf) — no trusted API endpoint yet
  - Trading pair: HMND-USDC only (hardcoded for v1)

Phase 1 items deferred (TheHub team not yet implemented):
  - clientOrderId round-trip
  - Fills endpoint
  - Structured error codes
  - Markets / account balance API endpoints
"""

import asyncio
import time
from decimal import Decimal
from typing import Any, AsyncIterable, Dict, List, Optional, Tuple

import aiohttp
from bidict import bidict

from hummingbot.connector.constants import s_decimal_NaN
from hummingbot.connector.exchange.thehub import (
    thehub_constants as CONSTANTS,
    thehub_web_utils as web_utils,
)
from hummingbot.connector.exchange.thehub.thehub_api_order_book_data_source import (
    TheHubAPIOrderBookDataSource,
)
from hummingbot.connector.exchange.thehub.thehub_api_user_stream_data_source import (
    TheHubAPIUserStreamDataSource,
)
from hummingbot.connector.exchange.thehub.thehub_auth import TheHubAuth
from hummingbot.connector.exchange.thehub.thehub_order_book import TheHubOrderBook
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.connector.utils import combine_to_hb_trading_pair, get_new_client_order_id
from hummingbot.core.api_throttler.data_types import RateLimit
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import AddedToCostTradeFee, TokenAmount, TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

# ERC-20 balanceOf(address) function selector
_BALANCE_OF_SELECTOR = "70a08231"


class TheHubExchange(ExchangePyBase):
    """
    Hummingbot spot connector for TheHub orderbook exchange on Humanode.
    """

    UPDATE_ORDER_STATUS_MIN_INTERVAL = 10.0
    SHORT_POLL_INTERVAL = 5.0
    LONG_POLL_INTERVAL = 120.0

    web_utils = web_utils

    def __init__(
        self,
        thehub_wallet_address: str = "",
        thehub_private_key: str = "",
        thehub_lop_address: str = "",
        thehub_api_url: str = CONSTANTS.DEFAULT_BASE_URL,
        thehub_chain_id: int = CONSTANTS.DEFAULT_CHAIN_ID,
        thehub_rpc_url: str = CONSTANTS.HUMANODE_RPC_URL,
        trading_pairs: Optional[List[str]] = None,
        trading_required: bool = True,
        domain: str = CONSTANTS.DOMAIN,
        balance_asset_limit: Optional[Dict[str, Dict[str, Decimal]]] = None,
        rate_limits_share_pct: Decimal = Decimal("100"),
    ):
        self._wallet_address = thehub_wallet_address
        self._private_key = thehub_private_key
        self._lop_address = thehub_lop_address
        self._api_base_url = thehub_api_url.rstrip("/")
        self._chain_id = thehub_chain_id
        self._rpc_url = thehub_rpc_url
        self._trading_pairs = trading_pairs or [CONSTANTS.TRADING_PAIR]
        self._trading_required = trading_required
        self._domain = domain
        super().__init__(balance_asset_limit, rate_limits_share_pct)

    # ------------------------------------------------------------------
    # ExchangePyBase required properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._domain

    @property
    def authenticator(self) -> Optional[TheHubAuth]:
        if self._trading_required:
            return TheHubAuth(
                private_key=self._private_key,
                verifying_contract=self._lop_address,
                chain_id=self._chain_id,
            )
        return None

    @property
    def thehub_api_url(self) -> str:
        return self._api_base_url

    @property
    def rate_limits_rules(self) -> List[RateLimit]:
        return CONSTANTS.RATE_LIMITS

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def client_order_id_max_length(self) -> Optional[int]:
        return CONSTANTS.MAX_ORDER_ID_LEN

    @property
    def client_order_id_prefix(self) -> str:
        return CONSTANTS.BROKER_ID

    @property
    def trading_rules_request_path(self) -> str:
        # We override _update_trading_rules; this value is required by abstract base
        return CONSTANTS.HEALTH_PATH

    @property
    def trading_pairs_request_path(self) -> str:
        return CONSTANTS.HEALTH_PATH

    @property
    def check_network_request_path(self) -> str:
        return CONSTANTS.HEALTH_PATH

    @property
    def trading_pairs(self) -> List[str]:
        return self._trading_pairs

    @property
    def is_cancel_request_in_exchange_synchronous(self) -> bool:
        return True

    @property
    def is_trading_required(self) -> bool:
        return self._trading_required

    @property
    def api_base_url(self) -> str:
        return self._api_base_url

    # ------------------------------------------------------------------
    # Network check — GET /api/orderbook/health
    # ------------------------------------------------------------------

    async def _make_network_check_request(self) -> None:
        await self._api_get(path_url=self.check_network_request_path)

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception) -> bool:
        return False

    # ------------------------------------------------------------------
    # Web assistants factory
    # ------------------------------------------------------------------

    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        return web_utils.build_api_factory(
            throttler=self._throttler,
            auth=self._auth,
        )

    # ------------------------------------------------------------------
    # Trading pair mapping (hardcoded for v1)
    # ------------------------------------------------------------------

    async def _initialize_trading_pair_symbol_map(self) -> None:
        mapping = bidict()
        mapping[CONSTANTS.EXCHANGE_MARKET] = combine_to_hb_trading_pair(
            CONSTANTS.BASE_ASSET, CONSTANTS.QUOTE_ASSET
        )
        self._set_trading_pair_symbol_map(mapping)

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Any) -> None:
        # Trading pair is hardcoded for v1; ignore any API response
        mapping = bidict()
        mapping[CONSTANTS.EXCHANGE_MARKET] = combine_to_hb_trading_pair(
            CONSTANTS.BASE_ASSET, CONSTANTS.QUOTE_ASSET
        )
        self._set_trading_pair_symbol_map(mapping)

    # ------------------------------------------------------------------
    # Trading rules (hardcoded for v1 — Phase 1 will expose a markets endpoint)
    # ------------------------------------------------------------------

    async def _update_trading_rules(self) -> None:
        self._trading_rules.clear()
        self._trading_rules[CONSTANTS.TRADING_PAIR] = TradingRule(
            trading_pair=CONSTANTS.TRADING_PAIR,
            min_order_size=Decimal("0.0001"),
            min_base_amount_increment=Decimal("0.0001"),
            min_price_increment=Decimal("0.000001"),  # 1 / 10^6
            max_order_size=CONSTANTS.MAX_BASE_AMOUNT_HMND,
        )

    async def _format_trading_rules(self, exchange_info: Any) -> List[TradingRule]:
        # Not used; we override _update_trading_rules directly
        return []

    async def _make_trading_rules_request(self) -> Any:
        return {}

    async def _make_trading_pairs_request(self) -> Any:
        return {}

    # ------------------------------------------------------------------
    # Supported order types
    # ------------------------------------------------------------------

    def supported_order_types(self) -> List[OrderType]:
        return [OrderType.LIMIT]

    # ------------------------------------------------------------------
    # Fee
    # ------------------------------------------------------------------

    def _get_fee(
        self,
        base_currency: str,
        quote_currency: str,
        order_type: OrderType,
        order_side: TradeType,
        amount: Decimal,
        price: Decimal = s_decimal_NaN,
        is_maker: Optional[bool] = None,
    ) -> TradeFeeBase:
        return AddedToCostTradeFee(percent=Decimal(str(CONSTANTS.FEE_BPS / CONSTANTS.BPS_DENOMINATOR)))

    async def _update_trading_fees(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Data sources
    # ------------------------------------------------------------------

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        return TheHubAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            connector=self,
            api_factory=self._web_assistants_factory,
            domain=self.domain,
        )

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:
        return TheHubAPIUserStreamDataSource(
            auth=self._auth,
            trading_pairs=self._trading_pairs,
            connector=self,
            api_factory=self._web_assistants_factory,
            domain=self.domain,
        )

    # ------------------------------------------------------------------
    # Balances — Humanode JSON-RPC (no API endpoint yet in Phase 1)
    # ------------------------------------------------------------------

    async def _update_balances(self) -> None:
        local_asset_names = set(self._account_balances.keys())
        remote_asset_names = set()

        tokens = [
            (CONSTANTS.BASE_ASSET, CONSTANTS.WEHMND_ADDRESS, CONSTANTS.WEHMND_DECIMALS),
            (CONSTANTS.QUOTE_ASSET, CONSTANTS.USDC_ADDRESS, CONSTANTS.USDC_DECIMALS),
        ]

        for asset_name, token_address, decimals in tokens:
            try:
                raw = await self._fetch_erc20_balance(
                    token_address=token_address,
                    holder_address=self._wallet_address,
                )
                balance = Decimal(raw) / Decimal(10 ** decimals)
                self._account_balances[asset_name] = balance
                self._account_available_balances[asset_name] = balance
                remote_asset_names.add(asset_name)
            except Exception as e:
                self.logger().warning(
                    f"Failed to fetch {asset_name} balance from Humanode RPC: {e}"
                )

        for asset_name in local_asset_names - remote_asset_names:
            del self._account_available_balances[asset_name]
            del self._account_balances[asset_name]

    async def _fetch_erc20_balance(self, token_address: str, holder_address: str) -> int:
        """
        Call balanceOf(address) on an ERC-20 contract via Humanode JSON-RPC.

        Returns the raw integer balance (not scaled by decimals).
        """
        clean_addr = holder_address.lower().removeprefix("0x")
        padded = "000000000000000000000000" + clean_addr  # 32 bytes
        call_data = "0x" + _BALANCE_OF_SELECTOR + padded

        payload = {
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{"to": token_address, "data": call_data}, "latest"],
            "id": 1,
        }

        rpc_url = self._rpc_url or CONSTANTS.HUMANODE_RPC_URL
        async with aiohttp.ClientSession() as session:
            async with session.post(
                rpc_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                result = await resp.json()

        if "error" in result:
            raise ValueError(f"RPC error: {result['error']}")

        hex_balance = result.get("result", "0x0")
        return int(hex_balance, 16)

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    def buy(
        self,
        trading_pair: str,
        amount: Decimal,
        order_type: OrderType = OrderType.LIMIT,
        price: Decimal = s_decimal_NaN,
        **kwargs,
    ) -> str:
        order_id = get_new_client_order_id(
            is_buy=True,
            trading_pair=trading_pair,
            hbot_order_id_prefix=self.client_order_id_prefix,
            max_id_len=self.client_order_id_max_length,
        )
        from hummingbot.core.utils.async_utils import safe_ensure_future
        safe_ensure_future(
            self._create_order(
                trade_type=TradeType.BUY,
                order_id=order_id,
                trading_pair=trading_pair,
                amount=amount,
                order_type=order_type,
                price=price,
                **kwargs,
            )
        )
        return order_id

    def sell(
        self,
        trading_pair: str,
        amount: Decimal,
        order_type: OrderType = OrderType.LIMIT,
        price: Decimal = s_decimal_NaN,
        **kwargs,
    ) -> str:
        order_id = get_new_client_order_id(
            is_buy=False,
            trading_pair=trading_pair,
            hbot_order_id_prefix=self.client_order_id_prefix,
            max_id_len=self.client_order_id_max_length,
        )
        from hummingbot.core.utils.async_utils import safe_ensure_future
        safe_ensure_future(
            self._create_order(
                trade_type=TradeType.SELL,
                order_id=order_id,
                trading_pair=trading_pair,
                amount=amount,
                order_type=order_type,
                price=price,
                **kwargs,
            )
        )
        return order_id

    async def _place_order(
        self,
        order_id: str,
        trading_pair: str,
        amount: Decimal,
        trade_type: TradeType,
        order_type: OrderType,
        price: Decimal,
        **kwargs,
    ) -> Tuple[str, float]:
        """
        Build, sign, and submit a 1inch v4 limit order to TheHub.

        :returns: (order_hash, timestamp)
        """
        side = "buy" if trade_type is TradeType.BUY else "sell"
        price_e6 = int(price * Decimal("1e6"))
        base_amount = int(amount * Decimal("1e18"))

        # No expiry for limit orders in v1 (mirrors ORDERBOOK_LIMIT_ORDER_NO_EXPIRY = 0)
        expires_at = 0

        order_data = self._auth.build_limit_order_data(
            side=side,
            price_e6=price_e6,
            base_amount=base_amount,
            expires_at=expires_at,
        )

        signed = self._auth.sign_limit_order(order_data)
        order_hash = signed["orderHash"]
        signature = signed["signature"]

        request_body = {
            "orderHash": order_hash,
            "signature": signature,
            "data": order_data,
            "orderType": "limit",
            "displayPriceE6": str(price_e6),
            "cancelUnfilled": False,
        }

        result = await self._api_post(
            path_url=web_utils.chain_path(CONSTANTS.SUBMIT_ORDER_PATH),
            data=request_body,
            limit_id=CONSTANTS.SUBMIT_ORDER_PATH,
        )

        if not result.get("accepted", False):
            msg = result.get("message", "Order rejected by TheHub.")
            raise IOError(f"TheHub rejected order {order_id}: {msg}")

        resting_order = result.get("order")
        exchange_order_id = (resting_order or {}).get("orderHash") or order_hash

        return exchange_order_id, self.current_timestamp

    # ------------------------------------------------------------------
    # Order cancellation
    # ------------------------------------------------------------------

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder) -> bool:
        """
        Sign and submit a CancelIntent for the tracked order's orderHash.
        """
        order_hash = tracked_order.exchange_order_id
        if not order_hash:
            self.logger().warning(
                f"Cannot cancel {order_id}: exchange_order_id (orderHash) not yet known."
            )
            return False

        cancel_request = self._auth.create_cancel_request(
            market=CONSTANTS.EXCHANGE_MARKET,
            order_hash=order_hash,
        )

        result = await self._api_post(
            path_url=CONSTANTS.CANCEL_PATH,
            data=cancel_request,
        )

        if result.get("cancelled", False):
            return True

        msg = result.get("message", "").lower()
        if "not found" in msg or "already cancelled" in msg or "already canceled" in msg:
            await self._order_tracker.process_order_not_found(order_id)

        return False

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception) -> bool:
        return "not found" in str(status_update_exception).lower()

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception) -> bool:
        return "not found" in str(cancelation_exception).lower()

    # ------------------------------------------------------------------
    # Order status (polling fallback)
    # ------------------------------------------------------------------

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        """Fetch a single order by its orderHash and return an OrderUpdate."""
        order_hash = tracked_order.exchange_order_id
        if not order_hash:
            raise asyncio.TimeoutError("No exchange_order_id yet.")

        result = await self._api_get(
            path_url=web_utils.chain_path(
                CONSTANTS.ORDER_BY_HASH_PATH.format(order_hash=order_hash)
            ),
            limit_id=CONSTANTS.ORDER_BY_HASH_PATH,
        )

        return self._parse_order_update(result, tracked_order)

    def _parse_order_update(
        self, resting_order: Dict[str, Any], tracked_order: InFlightOrder
    ) -> OrderUpdate:
        status_str = resting_order.get("status", "open")
        new_state = CONSTANTS.ORDER_STATE.get(status_str, OrderState.OPEN)

        return OrderUpdate(
            trading_pair=tracked_order.trading_pair,
            update_timestamp=resting_order.get("updatedAt", 0) * 1e-3,
            new_state=new_state,
            client_order_id=tracked_order.client_order_id,
            exchange_order_id=resting_order.get("orderHash", tracked_order.exchange_order_id),
        )

    # ------------------------------------------------------------------
    # Trade fills (Phase 1 fills endpoint not yet available → return empty)
    # ------------------------------------------------------------------

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        # TODO: implement when TheHub adds GET /api/orderbook/{chainId}/fills
        return []

    # ------------------------------------------------------------------
    # Status polling loop
    # ------------------------------------------------------------------

    async def _status_polling_loop_fetch_updates(self) -> None:
        from hummingbot.core.utils.async_utils import safe_gather
        await safe_gather(
            self._update_order_status(),
            self._update_balances(),
        )

    async def _update_order_status(self) -> None:
        await self._update_orders()

    async def _update_lost_orders_status(self) -> None:
        await self._update_lost_orders()

    # ------------------------------------------------------------------
    # User stream event processing
    # ------------------------------------------------------------------

    async def _iter_user_event_queue(self) -> AsyncIterable[Dict[str, Any]]:
        while True:
            try:
                yield await self._user_stream_tracker.user_stream.get()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().network(
                    "Unknown error. Retrying after 1 second.",
                    exc_info=True,
                    app_warning_msg=(
                        "Could not fetch user events from TheHub. "
                        "Check API URL and network connection."
                    ),
                )
                await self._sleep(1.0)

    async def _user_stream_event_listener(self) -> None:
        """
        Process events from the private-state polling queue.

        Each event is a dict: {"channel": "private_state", "data": PrivateOrderbookState}
        """
        async for event in self._iter_user_event_queue():
            try:
                channel = event.get("channel")
                if channel != "private_state":
                    continue

                private_state: Dict[str, Any] = event["data"]
                for resting_order in private_state.get("ownerOrders", []):
                    self._process_private_order(resting_order)

            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception("Error processing TheHub private state event.")
                await self._sleep(5.0)

    def _process_private_order(self, resting_order: Dict[str, Any]) -> None:
        """
        Convert a RestingOrder from the private state into an OrderUpdate and process it.
        """
        order_hash = resting_order.get("orderHash")
        if not order_hash:
            return

        # Match against tracked orders by exchange_order_id
        tracked = self._order_tracker.all_orders_by_exchange_order_id.get(order_hash)
        if tracked is None:
            return

        status_str = resting_order.get("status", "open")
        new_state = CONSTANTS.ORDER_STATE.get(status_str, OrderState.OPEN)

        order_update = OrderUpdate(
            trading_pair=tracked.trading_pair,
            update_timestamp=resting_order.get("updatedAt", 0) * 1e-3,
            new_state=new_state,
            client_order_id=tracked.client_order_id,
            exchange_order_id=order_hash,
        )
        self._order_tracker.process_order_update(order_update=order_update)

    # ------------------------------------------------------------------
    # Last traded prices (needed by OrderBookTrackerDataSource)
    # ------------------------------------------------------------------

    async def get_last_traded_prices(
        self, trading_pairs: List[str], domain: Optional[str] = None
    ) -> Dict[str, float]:
        result = {}
        try:
            snapshot = await self._api_get(
                path_url=web_utils.chain_path(CONSTANTS.ORDERBOOK_SNAPSHOT_PATH),
                params={"market": CONSTANTS.EXCHANGE_MARKET},
                limit_id=CONSTANTS.ORDERBOOK_SNAPSHOT_PATH,
            )
            last_price_e6 = snapshot.get("lastTradePriceE6")
            if last_price_e6 and CONSTANTS.TRADING_PAIR in trading_pairs:
                result[CONSTANTS.TRADING_PAIR] = float(Decimal(last_price_e6) / Decimal("1e6"))
        except Exception:
            pass
        return result

    # ------------------------------------------------------------------
    # REST URL helper used by ExchangePyBase._api_get / _api_post
    # ------------------------------------------------------------------

    def _rest_url(self, path_url: str) -> str:
        return self._api_base_url + path_url
