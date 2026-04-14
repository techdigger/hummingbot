# TheHub Hummingbot Market Making Plan

## Decision

Build a Hummingbot spot CLOB connector for TheHub Exchange, but do not copy Hyperliquid protocol behavior directly. Hyperliquid remains the best structural Hummingbot reference because it is an off-chain orderbook DEX with signed orders, but TheHub's real protocol reference is its own code:

- `src/pages/app/orderbook/client.ts`
- `src/pages/app/orderbook/typedData.ts`
- `src/pages/app/orderbook/types.ts`
- `scripts/orderbook-server.mjs`
- `docs/orderbook-exchange.md`

The connector should target TheHub's current 1inch-compatible orderbook architecture on public `main` and the live server's `.mjs` runtime, not the older `orderbook-exchange` branch or custom settlement-contract path. The first market is `HMND/USDC` on Humanode chain `5234`.

## Phase 1: TheHub API Readiness

Ask TheHub team for bot-safe exchange semantics before connector implementation:

- Add `clientOrderId` to order submit responses and all order-status/private-state responses.
- Make order submit idempotent per `owner + market + clientOrderId`.
- Make cancel idempotent and allow cancel by either `orderHash` or `clientOrderId`.
- Return structured errors like `{ "code": "INSUFFICIENT_ALLOWANCE", "message": "...", "details": {} }` for invalid signature, unsupported market, duplicate client order id, insufficient balance, insufficient allowance, expired order, filled order, cancelled order, and rate limit.
- Add `GET /api/orderbook/5234/markets` with base/quote symbols, token addresses, decimals, tick size, minimum order size, fee bps, chain id, and 1inch LOP verifying contract.
- Add `GET /api/orderbook/5234/account/:address` with balances, reserved amounts, available amounts, and 1inch LOP allowances. If this is not available, the Hummingbot connector will read Humanode RPC directly.
- Add `GET /api/orderbook/5234/fills?address=...&cursor=...` for reconnect/backfill after bot downtime.
- Add clear fill finality fields: backend matched, on-chain tx submitted, on-chain settled, failed, rolled back.
- Add `GET /api/orderbook/ready` that reports process readiness, persistence health, Humanode RPC reachability, LOP configured, resolver enabled, and current market sequence.
- Confirm `/api/orderbook/admin/*` remains blocked from public access or always requires `x-orderbook-admin-token`.

Ask TheHub to implement WebSocket for v1 production if they can deliver it
without delaying the API contract. REST snapshot plus SSE/private polling is an
acceptable fallback for first smoke testing, but it is worse for market making.

- Public channel: orderbook snapshots or diffs, trades, heartbeat.
- Private channel: order updates, fills, settlement updates.
- All events should include `market`, `sequence`, `updatedAt`, `orderHash`, and `clientOrderId` where applicable.
- Reconnect model: client can fetch REST snapshot, then consume stream updates after a known sequence.

If WebSocket is not ready, v1 smoke testing can use REST snapshots, TheHub's SSE public stream, and private-state polling. Private polling must authenticate by calling `POST /api/orderbook/private-session`, then sending the returned token in the `x-orderbook-private-token` header when reading private owner state. REST order lookup, fills backfill, private-state snapshot, and market metadata are still required even when WebSocket exists because the connector needs reconciliation and reconnect recovery.

## Phase 2: Connector Scope And Architecture

Fork `hummingbot/hummingbot` and create `hummingbot/connector/exchange/thehub`.

Implement v1 as a narrow spot connector:

- Trading pair: `HMND-USDC` only.
- Fees: `0.03%` per matched side via `TradeFeeSchema` using `Decimal("0.0003")`.
- REST adapter for health/readiness, market metadata, orderbook snapshot, order submit, order lookup, owner orders, cancel, fills, and recent trades.
- Public data source using WebSocket if TheHub ships it; otherwise use SSE plus periodic REST snapshot recovery.
- User data source using WebSocket if TheHub ships it; otherwise use signed private session plus polling `/api/orderbook/private-state`.
- Auth module using `eth_account` for 1inch v4 EIP-712 order signing and TheHub backend EIP-712 cancel/private-session signing.
- Balance module using Humanode RPC for HMND/USDC wallet balances and 1inch LOP allowances unless TheHub exposes a trusted balance/allowance endpoint.
- Approval policy: v1 does not submit ERC-20 approvals automatically. It performs a preflight allowance check and fails fast with a clear error when allowance is insufficient.

Use Hyperliquid only for Hummingbot class layout and lifecycle patterns. Use TheHub frontend/backend code for signing, request payloads, status mapping, and fee semantics.

## Phase 3: Order Lifecycle And Risk Semantics

Map TheHub `RestingOrder.status` to Hummingbot order states:

- `open`: open
- `partial`: partially filled
- `filled`: filled
- `cancelled`: cancelled
- `expired`: failed/expired
- `rejected`: failed

Track settlement separately from strategy fill state. TheHub's resolver model is inventory-backed and not atomic across both sides:

- Strategy state uses TheHub backend order status and filled amounts as the Hummingbot fill signal.
- Accounting/finality should track resolver submission and on-chain settlement status separately.
- Failed settlement rollback must be surfaced as a high-severity connector event and should pause or kill the bot, because it can invalidate a previously observed backend match.

The v1 bot should start conservatively:

- one trading pair
- fixed spread PMM first
- small order sizes
- strict inventory caps
- order refresh interval
- kill switch on API errors, stale stream, settlement rollback, or balance mismatch

## Phase 4: Testing And Simulation

Before live trading:

- Unit test 1inch v4 hash/sign payloads against TheHub `typedData.ts` fixtures.
- Generate TypeScript signing fixtures from TheHub and verify Python `eth_account` output matches for order hash, signature recovery address, cancel intent hash, and private session intent hash.
- Unit test cancel/private-session EIP-712 signing.
- Unit test REST parsing for `OrderBookSnapshot`, `RestingOrder`, `OrdersPage`, and `PrivateOrderbookState`.
- Unit test status mapping and partial fill handling.
- Mock SSE/WebSocket stream reconnect behavior.
- Add integration tests against a local TheHub orderbook server or SSH-tunneled VPS endpoint.
- Run a dry-run/paper mode that computes quotes and would-be orders without submitting signed orders.

Only after those pass, run with tiny live sizes on `HMND/USDC`.

## Phase 5: Deployment And VPS Constraints

Do not assume the current VPS is ready for full Hummingbot production.

Current server findings:

- Debian 12, 2 vCPU, about 2 GB RAM.
- Docker and Caddy are running.
- TheHub appears under `/opt/thehub`, but that directory is not a Git repo.
- Running processes include `node scripts/orderbook-server.mjs`, `node scripts/settle-orderbook-match.js`, and Caddy.
- Memory is tight; Node orderbook and settlement processes were using significant RAM, and swap was already in use.
- `techdigger` can SSH but does not have passwordless sudo and cannot inspect Docker.

Deployment approach:

- For development, use local machine or a separate bot VPS and reach TheHub through direct API or SSH tunnel.
- Do not run full Hummingbot on `server1` until memory is measured under load; use local/separate VPS for connector development first.
- Get Docker/sudo visibility before relying on this VPS for production deployment, logs, or rollback.

## Phase 6: Hummingbot Strategy Enablement

After the connector is stable:

- Start with PMM Simple V2 or a minimal custom V2 script.
- Then test Avellaneda-Stoikov if inventory signals are reliable.
- Add cross-exchange hedging only after TheHub fill finality and balance accounting are proven.
- Add more markets only after TheHub exposes market metadata and the connector no longer hardcodes `HMND/USDC`.

The long-term payoff remains access to Hummingbot's built-in strategy library, order tracking, balance management, dashboard/history tooling, Telegram integration, paper-trading workflow, and future cross-exchange market making.
