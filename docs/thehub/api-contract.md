# TheHub Orderbook API Contract

Minimum API needed for the TheHub Hummingbot connector on `HMND/USDC`, Humanode
chain `5234`. This is a required contract, not a description of endpoints that
already exist.

This is a backend API contract, not a Solidity smart contract request. TheHub
should implement these HTTP/WebSocket/SSE surfaces around its existing
1inch-compatible orderbook architecture. Hummingbot still needs the deployed
1inch Limit Order Protocol verifying contract address and exact EIP-712 typed
data definitions for order, cancel, and private-session signing.

Use Unix milliseconds for event/order timestamps. Use token base-unit decimal
strings for amounts. Every private order/fill response must round-trip both
`clientOrderId` and `orderHash`.

## Required Schemas

### Order

Required fields:

```json
{
  "clientOrderId": "HBOT-1700000000000-1",
  "orderHash": "0x...",
  "market": "HMND/USDC",
  "owner": "0x...",
  "side": "buy",
  "orderType": "limit",
  "status": "open",
  "priceE6": "1000000",
  "baseAmount": "1000000000000000000",
  "quoteAmount": "1000000",
  "filledBaseAmount": "0",
  "filledQuoteAmount": "0",
  "remainingBaseAmount": "1000000000000000000",
  "remainingQuoteAmount": "1000000",
  "createdAt": 1700000000000,
  "updatedAt": 1700000000000
}
```

Allowed `status`: `open`, `partial`, `filled`, `cancelled`, `expired`,
`rejected`.

### Fill

Required fields:

```json
{
  "fillId": "fill-...",
  "matchId": "match-...",
  "clientOrderId": "HBOT-1700000000000-1",
  "orderHash": "0x...",
  "market": "HMND/USDC",
  "owner": "0x...",
  "side": "buy",
  "priceE6": "1000000",
  "baseAmount": "1000000000000000000",
  "quoteAmount": "1000000",
  "feeAmount": "300",
  "liquidity": "maker",
  "matchedAt": 1700000001000,
  "settlement": {
    "status": "matched",
    "txHash": null,
    "submittedAt": null,
    "settledAt": null,
    "failureReason": null
  }
}
```

Allowed settlement `status`: `matched`, `submitted`, `settled`, `failed`,
`rolled_back`.

Semantics:

- `matched`: backend match; bot can treat it as the fill signal.
- `submitted`: resolver submitted the on-chain settlement tx.
- `settled`: on-chain finality reached.
- `failed`: settlement tx failed but backend match may still retry.
- `rolled_back`: backend match invalidated; bot must halt and reconcile.

### Error

All non-2xx responses:

```json
{ "code": "INSUFFICIENT_ALLOWANCE", "message": "...", "details": {} }
```

Required codes: `INVALID_SIGNATURE`, `UNSUPPORTED_MARKET`,
`DUPLICATE_CLIENT_ORDER_ID`, `UNKNOWN_ORDER`, `INSUFFICIENT_BALANCE`,
`INSUFFICIENT_ALLOWANCE`, `EXPIRED_ORDER`, `ORDER_FILLED`, `ORDER_CANCELLED`,
`ORDER_REJECTED`, `RATE_LIMITED`, `PRIVATE_SESSION_REQUIRED`,
`PRIVATE_SESSION_EXPIRED`, `SETTLEMENT_FAILED`, `INTERNAL_ERROR`.

## Endpoints

### Health And Metadata

`GET /api/orderbook/ready`

Response must include `ready`, `persistence`, `humanodeRpc`, `lopConfigured`,
`resolverEnabled`, `chainId`, `sequence`, `updatedAt`.

`GET /api/orderbook/5234/markets`

Response:

```json
{
  "markets": [{
    "market": "HMND/USDC",
    "baseSymbol": "HMND",
    "quoteSymbol": "USDC",
    "baseToken": "0x0000000000000000000000000000000000000802",
    "quoteToken": "0x33E5b3e24501774598367bc0832B52787aC39Ca5",
    "baseDecimals": 18,
    "quoteDecimals": 6,
    "priceDecimals": 6,
    "tickSizeE6": "1",
    "minBaseAmount": "1",
    "feeBps": 3,
    "chainId": 5234,
    "limitOrderProtocol": "0x..."
  }]
}
```

### Public Market Data

`GET /api/orderbook/5234/orderbook?market=HMND/USDC`

Response must include `market`, `sequence`, `updatedAt`, `bids`, `asks`.
Each book level must include `priceE6`, `baseAmount`, `quoteAmount`,
`totalBaseAmount`, `orderCount`.

`GET /api/orderbook/trades?market=HMND/USDC&cursor=...`

Response must include `market`, `cursor`, `trades[]`. Each trade must include
`tradeId`, `market`, `priceE6`, `baseAmount`, `quoteAmount`, `matchedAt`.

Preferred: WebSocket public channel.

Public WebSocket events must include `type`, `market`, `sequence`, `updatedAt`,
and `data`. Supported `type`: `orderbook`, `trade`, `heartbeat`.

Reconnect flow:

- Fetch a REST orderbook snapshot.
- Consume WebSocket events with `sequence` greater than the snapshot sequence.
- If the client detects a sequence gap, fetch a fresh REST snapshot and resume.

Fallback if WebSocket is not ready for v1 smoke testing:

`GET /api/orderbook/stream?market=HMND/USDC`

SSE events must include `type`, `market`, `sequence`, `updatedAt`, `data`.
Supported `type`: `orderbook`, `trade`, `heartbeat`. Reconnect flow: fetch REST
snapshot, then consume stream events with a higher `sequence`.

### Submit Order

`POST /api/orderbook/5234`

Request:

```json
{
  "clientOrderId": "HBOT-1700000000000-1",
  "orderHash": "0x...",
  "signature": "0x...",
  "data": {},
  "orderType": "limit",
  "displayPriceE6": "1000000",
  "cancelUnfilled": false
}
```

Response must include `accepted`, `clientOrderId`, `orderHash`, `order`.
`order` must be an `Order`.

Idempotency:

- Key: `owner + market + clientOrderId`.
- Same request repeated: return existing order with the same `orderHash`.
- Same `clientOrderId` with different order content: return
  `DUPLICATE_CLIENT_ORDER_ID`.

### Order Lookup

`GET /api/orderbook/5234/order/{orderHash}`

Response: `Order`. Required: `clientOrderId` must be present.

`GET /api/orderbook/5234/address/{address}?market=HMND/USDC`

Response must include `market`, `owner`, `sequence`, `orders[]`.
Each item in `orders` must be an `Order`.

### Cancel

`POST /api/orderbook/cancel`

Request:

```json
{
  "market": "HMND/USDC",
  "owner": "0x...",
  "orderHash": "0x...",
  "clientOrderId": "HBOT-1700000000000-1",
  "cancelNonce": "1700000000000",
  "deadline": 1700000060,
  "signature": "0x..."
}
```

Response must include `cancelled`, `clientOrderId`, `orderHash`, `status`,
`updatedAt`.

Idempotency:

- Cancel by either `orderHash` or `clientOrderId`.
- Repeated cancel on cancelled order returns terminal `status: "cancelled"`.
- Filled/expired order returns terminal `status` or structured `ORDER_FILLED` /
  `EXPIRED_ORDER`.
- Unknown order returns `UNKNOWN_ORDER`.

### Private State

`POST /api/orderbook/private-session`

Request must include `owner`, `nonce`, `issuedAt`, `expiresAt`, `signature`.
Response must include `token`, `owner`, `expiresAt` in Unix seconds.

Preferred: WebSocket private channel authenticated by either the private-session
token or an equivalent EIP-712 private-session auth message.

Private WebSocket events must include order updates, fills, settlement updates,
`market`, `sequence`, `updatedAt`, and both `clientOrderId` and `orderHash`
where applicable.

REST private-state polling remains required for reconciliation and as a fallback
if WebSocket is not ready for v1 smoke testing:

`GET /api/orderbook/private-state?market=HMND/USDC`

Requires header `x-orderbook-private-token`. Response must include `market`,
`owner`, `sequence`, `updatedAt`, `orders[]`, `fills[]`, `settlements[]`.
`orders[]` items are `Order`; `fills[]` items are `Fill`; `settlements[]` items
must include `matchId`, `orderHash`, `status`, `txHash`, `baseAmount`,
`quoteAmount`, `updatedAt`.

`GET /api/orderbook/5234/fills?address=0x...&market=HMND/USDC&cursor=...`

Response must include `market`, `owner`, `cursor`, `fills[]`.
Each item in `fills` must be a `Fill`.

### Optional Account State

`GET /api/orderbook/5234/account/{address}`

Optional but useful for production operations. Response should include wallet
balances, reserved amounts, available amounts, and 1inch Limit Order Protocol
allowances for HMND and USDC. If this endpoint is not available, Hummingbot will
read balances and allowances from Humanode RPC directly.

## Admin Access

`/api/orderbook/admin/*` must remain blocked from public access or require
`x-orderbook-admin-token`. Bot endpoints must not require admin access.
