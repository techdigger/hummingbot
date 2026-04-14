from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.in_flight_order import OrderState

EXCHANGE_NAME = "thehub"
DOMAIN = EXCHANGE_NAME

DEFAULT_CHAIN_ID = 5234
DEFAULT_BASE_URL = "http://127.0.0.1:7303"

HEALTH_PATH = "/api/orderbook/health"
PRIVATE_SESSION_PATH = "/api/orderbook/private-session"
PRIVATE_STATE_PATH = "/api/orderbook/private-state"
PUBLIC_STREAM_PATH = "/api/orderbook/stream"
RECENT_TRADES_PATH = "/api/orderbook/trades"
CANCEL_PATH = "/api/orderbook/cancel"

ORDERBOOK_SNAPSHOT_PATH = "/orderbook"
SUBMIT_ORDER_PATH = "/"
ORDER_BY_HASH_PATH = "/order/{order_hash}"
ADDRESS_ORDERS_PATH = "/address/{address}"

PRIVATE_SESSION_HEADER = "x-orderbook-private-token"

ORDER_STATE = {
    "open": OrderState.OPEN,
    "partial": OrderState.PARTIALLY_FILLED,
    "filled": OrderState.FILLED,
    "cancelled": OrderState.CANCELED,
    "expired": OrderState.FAILED,
    "rejected": OrderState.FAILED,
}

HEARTBEAT_TIME_INTERVAL = 30.0
MAX_REQUEST = 1_200
ALL_ENDPOINTS_LIMIT = "All"

RATE_LIMITS = [
    RateLimit(ALL_ENDPOINTS_LIMIT, limit=MAX_REQUEST, time_interval=60),
    RateLimit(
        limit_id=HEALTH_PATH,
        limit=MAX_REQUEST,
        time_interval=60,
        linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)],
    ),
    RateLimit(
        limit_id=PRIVATE_SESSION_PATH,
        limit=MAX_REQUEST,
        time_interval=60,
        linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)],
    ),
    RateLimit(
        limit_id=ORDERBOOK_SNAPSHOT_PATH,
        limit=MAX_REQUEST,
        time_interval=60,
        linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)],
    ),
    RateLimit(
        limit_id=SUBMIT_ORDER_PATH,
        limit=MAX_REQUEST,
        time_interval=60,
        linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)],
    ),
    RateLimit(
        limit_id=CANCEL_PATH,
        limit=MAX_REQUEST,
        time_interval=60,
        linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)],
    ),
    RateLimit(
        limit_id=RECENT_TRADES_PATH,
        limit=MAX_REQUEST,
        time_interval=60,
        linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)],
    ),
    RateLimit(
        limit_id=PRIVATE_STATE_PATH,
        limit=MAX_REQUEST,
        time_interval=60,
        linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)],
    ),
    RateLimit(
        limit_id=ORDER_BY_HASH_PATH,
        limit=MAX_REQUEST,
        time_interval=60,
        linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)],
    ),
    RateLimit(
        limit_id=ADDRESS_ORDERS_PATH,
        limit=MAX_REQUEST,
        time_interval=60,
        linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)],
    ),
    # PUBLIC_STREAM_PATH is SSE via raw aiohttp — not routed through the throttler
]
