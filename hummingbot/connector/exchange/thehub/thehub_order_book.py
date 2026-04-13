from decimal import Decimal
from typing import Dict, Optional

from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType

_PRICE_DIVISOR = Decimal("1000000")       # priceE6 → decimal price
_AMOUNT_DIVISOR = Decimal("10") ** 18     # wei → HMND


def _price(price_e6: str) -> float:
    return float(Decimal(price_e6) / _PRICE_DIVISOR)


def _amount(amount_wei: str) -> float:
    return float(Decimal(amount_wei) / _AMOUNT_DIVISOR)


class TheHubOrderBook(OrderBook):

    @classmethod
    def snapshot_message_from_exchange(
        cls,
        msg: Dict,
        timestamp: float,
        metadata: Optional[Dict] = None,
    ) -> OrderBookMessage:
        if metadata:
            msg.update(metadata)
        return OrderBookMessage(
            OrderBookMessageType.SNAPSHOT,
            {
                "trading_pair": msg["trading_pair"],
                "update_id": int(msg["sequence"]),
                "bids": [[_price(b["priceE6"]), _amount(b["baseAmount"])] for b in msg["bids"]],
                "asks": [[_price(a["priceE6"]), _amount(a["baseAmount"])] for a in msg["asks"]],
            },
            timestamp=timestamp,
        )

    @classmethod
    def diff_message_from_exchange(
        cls,
        msg: Dict,
        timestamp: Optional[float] = None,
        metadata: Optional[Dict] = None,
    ) -> OrderBookMessage:
        # TheHub SSE sends full snapshots; treat diff as a snapshot-shaped update.
        if metadata:
            msg.update(metadata)
        return OrderBookMessage(
            OrderBookMessageType.DIFF,
            {
                "trading_pair": msg["trading_pair"],
                "update_id": int(msg["sequence"]),
                "bids": [[_price(b["priceE6"]), _amount(b["baseAmount"])] for b in msg["bids"]],
                "asks": [[_price(a["priceE6"]), _amount(a["baseAmount"])] for a in msg["asks"]],
            },
            timestamp=timestamp,
        )

    @classmethod
    def trade_message_from_exchange(
        cls,
        msg: Dict,
        metadata: Optional[Dict] = None,
    ) -> OrderBookMessage:
        if metadata:
            msg.update(metadata)
        return OrderBookMessage(
            OrderBookMessageType.TRADE,
            {
                "trading_pair": msg["trading_pair"],
                "trade_type": float(TradeType.BUY.value) if msg["side"] == "buy" else float(TradeType.SELL.value),
                "trade_id": msg.get("txHash", msg.get("trade_id", "")),
                "price": _price(msg["priceE6"]),
                "amount": _amount(msg["baseAmount"]),
            },
            timestamp=msg["timestamp"] * 1e-3,
        )
