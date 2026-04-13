# TheHub Hummingbot Connector Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED: Use $subagent-driven-development (if subagents available) or $executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Hummingbot spot CLOB connector for TheHub Exchange, scoped to `HMND-USDC` on Humanode chain `5234`.

**Architecture:** Add a new spot exchange connector under `hummingbot/connector/exchange/thehub` using Hyperliquid only as a Hummingbot lifecycle/layout reference. TheHub protocol behavior comes from TheHub `client.ts`, `typedData.ts`, `types.ts`, and `orderbook-server.mjs`: 1inch v4 EIP-712 limit orders, backend EIP-712 cancel/private-session intents, REST order lifecycle, SSE public stream, and private-state polling. Do not touch `hummingbot/connector/derivative` or any perps connector.

**Tech Stack:** Python 3.10+ in the Hummingbot conda environment, `eth_account`, `web3`, Hummingbot connector framework, pytest/unittest, TheHub TypeScript signing fixtures from the TheHub repo.

---

## Current Context

- Worktree: `/home/user/.config/superpowers/worktrees/hummingbot-thehub/thehub-connector-phase2`
- Branch: `feature/thehub-connector-phase2`
- Upstream base: Hummingbot `development` commit `4bf022a`
- Fork remote: `https://github.com/techdigger/hummingbot.git`
- Local environment blocker: `conda`, `mamba`, and `micromamba` are not installed; system Python is `3.13.12` and has no `pytest`.
- Baseline tests cannot run yet. Install the Hummingbot conda environment before implementing production code.

## Phase 2 Boundaries

- Implement only `hummingbot/connector/exchange/thehub`.
- Add matching tests only under `test/hummingbot/connector/exchange/thehub`.
- First trading pair is `HMND-USDC` only.
- Fee schema is maker/taker `Decimal("0.0003")`.
- Public data source v1 uses TheHub REST snapshot and SSE stream.
- Private data source v1 uses `POST /api/orderbook/private-session` plus `/api/orderbook/private-state` polling.
- Do not submit ERC-20 approvals automatically; check balance/allowance and fail fast.
- Do not implement derivatives, perps, cross-exchange hedging, or multi-market support in this phase.

## Files

- Create: `hummingbot/connector/exchange/thehub/__init__.py`
- Create: `hummingbot/connector/exchange/thehub/thehub_constants.py`
- Create: `hummingbot/connector/exchange/thehub/thehub_utils.py`
- Create: `hummingbot/connector/exchange/thehub/thehub_web_utils.py`
- Create: `hummingbot/connector/exchange/thehub/thehub_auth.py`
- Create: `hummingbot/connector/exchange/thehub/thehub_order_book.py`
- Create: `hummingbot/connector/exchange/thehub/thehub_api_order_book_data_source.py`
- Create: `hummingbot/connector/exchange/thehub/thehub_api_user_stream_data_source.py`
- Create: `hummingbot/connector/exchange/thehub/thehub_exchange.py`
- Create: `test/hummingbot/connector/exchange/thehub/__init__.py`
- Create: `test/hummingbot/connector/exchange/thehub/test_thehub_utils.py`
- Create: `test/hummingbot/connector/exchange/thehub/test_thehub_web_utils.py`
- Create: `test/hummingbot/connector/exchange/thehub/test_thehub_auth.py`
- Create: `test/hummingbot/connector/exchange/thehub/test_thehub_order_book.py`
- Create: `test/hummingbot/connector/exchange/thehub/test_thehub_api_order_book_data_source.py`
- Create: `test/hummingbot/connector/exchange/thehub/test_thehub_api_user_stream_data_source.py`
- Create: `test/hummingbot/connector/exchange/thehub/test_thehub_exchange.py`
- Create: `test/hummingbot/connector/exchange/thehub/fixtures/thehub_typed_data_fixtures.json`

## Environment Setup

### Task 0: Install And Verify Hummingbot Test Environment

**Files:** none

- [ ] **Step 1: Install conda/mamba outside the repo**

Install Miniforge or Mambaforge so `conda` or `mamba` is available in `PATH`.

- [ ] **Step 2: Create/update the Hummingbot environment**

Run:

```bash
make install
```

Expected: environment `hummingbot` exists and `python setup.py build_ext --inplace` completes.

- [ ] **Step 3: Verify a known upstream connector test**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/hyperliquid/test_hyperliquid_utils.py -q
```

Expected: PASS. If this fails, fix environment before touching connector code.

- [ ] **Step 4: Commit nothing**

Environment changes are local and should not be committed.

## Chunk 1: Connector Metadata, URLs, And Registration

### Task 1: Add TheHub Config Map And Fee Schema

**Files:**
- Create: `hummingbot/connector/exchange/thehub/__init__.py`
- Create: `hummingbot/connector/exchange/thehub/thehub_utils.py`
- Test: `test/hummingbot/connector/exchange/thehub/test_thehub_utils.py`

- [ ] **Step 1: Write the failing tests**

Create tests for default fees, connector name, example pair, Ethereum wallet usage, and address normalization.

```python
from decimal import Decimal
from unittest import TestCase

from hummingbot.connector.exchange.thehub.thehub_utils import (
    DEFAULT_FEES,
    EXAMPLE_PAIR,
    KEYS,
    validate_evm_address,
)


class TheHubUtilsTests(TestCase):
    def test_default_metadata(self):
        self.assertEqual("HMND-USDC", EXAMPLE_PAIR)
        self.assertEqual("thehub", KEYS.connector)

    def test_fee_schema_is_three_bps(self):
        self.assertEqual(Decimal("0.0003"), DEFAULT_FEES.maker_percent_fee_decimal)
        self.assertEqual(Decimal("0.0003"), DEFAULT_FEES.taker_percent_fee_decimal)

    def test_validate_evm_address_accepts_mixed_case_address(self):
        address = "0x000000000000000000000000000000000000dEaD"
        self.assertEqual(address, validate_evm_address(address))

    def test_validate_evm_address_rejects_invalid_address(self):
        with self.assertRaises(ValueError):
            validate_evm_address("not-an-address")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub/test_thehub_utils.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'hummingbot.connector.exchange.thehub'`.

- [ ] **Step 3: Implement minimal config map**

Implement `DEFAULT_FEES`, `CENTRALIZED = False`, `USE_ETHEREUM_WALLET = True`, `EXAMPLE_PAIR = "HMND-USDC"`, and `TheHubConfigMap` fields:

- `connector: str = "thehub"`
- `thehub_api_url`
- `thehub_chain_id` default `5234`
- `thehub_wallet_address`
- `thehub_private_key`
- `thehub_lop_address`
- optional `thehub_rpc_url`

Use `pydantic.SecretStr` for private key and sensitive values. Use `eth_utils.is_address` or `web3.Web3.is_address` for EVM address validation.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub/test_thehub_utils.py -q
```

Expected: PASS.

- [ ] **Step 5: Verify Hummingbot discovers the connector**

Run:

```bash
conda run -n hummingbot python - <<'PY'
from hummingbot.client.settings import AllConnectorSettings
AllConnectorSettings.all_connector_settings = {}
settings = AllConnectorSettings.get_connector_settings()
assert "thehub" in settings
assert settings["thehub"].example_pair == "HMND-USDC"
print("thehub discovered")
PY
```

Expected: prints `thehub discovered`.

- [ ] **Step 6: Commit**

```bash
git add hummingbot/connector/exchange/thehub/__init__.py hummingbot/connector/exchange/thehub/thehub_utils.py test/hummingbot/connector/exchange/thehub/__init__.py test/hummingbot/connector/exchange/thehub/test_thehub_utils.py
git commit -m "feat: add thehub connector config"
```

### Task 2: Add Constants And REST URL Helpers

**Files:**
- Create: `hummingbot/connector/exchange/thehub/thehub_constants.py`
- Create: `hummingbot/connector/exchange/thehub/thehub_web_utils.py`
- Test: `test/hummingbot/connector/exchange/thehub/test_thehub_web_utils.py`

- [ ] **Step 1: Write the failing tests**

Test base URL cleanup, chain-prefixed REST paths, health path, SSE stream path, and private header name.

```python
from unittest import TestCase

from hummingbot.connector.exchange.thehub import thehub_constants as CONSTANTS
from hummingbot.connector.exchange.thehub import thehub_web_utils as web_utils


class TheHubWebUtilsTests(TestCase):
    def test_public_rest_url_trims_base_url(self):
        self.assertEqual(
            "https://api.example.com/api/orderbook/health",
            web_utils.public_rest_url("/api/orderbook/health", "https://api.example.com/"),
        )

    def test_chain_rest_path(self):
        self.assertEqual(
            "/api/orderbook/5234/orderbook",
            web_utils.chain_path(CONSTANTS.ORDERBOOK_SNAPSHOT_PATH),
        )

    def test_private_session_header(self):
        self.assertEqual("x-orderbook-private-token", CONSTANTS.PRIVATE_SESSION_HEADER)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub/test_thehub_web_utils.py -q
```

Expected: FAIL because constants/web utilities do not exist.

- [ ] **Step 3: Implement minimal constants and helpers**

Constants:

- `EXCHANGE_NAME = "thehub"`
- `DEFAULT_CHAIN_ID = 5234`
- `DEFAULT_BASE_URL = "http://127.0.0.1:7303"` for local development; production deployments should override this with `thehub_api_url`.
- `HEALTH_PATH = "/api/orderbook/health"`
- `PRIVATE_SESSION_PATH = "/api/orderbook/private-session"`
- `PRIVATE_STATE_PATH = "/api/orderbook/private-state"`
- `PUBLIC_STREAM_PATH = "/api/orderbook/stream"`
- `ORDERBOOK_SNAPSHOT_PATH = "/orderbook"`
- `SUBMIT_ORDER_PATH = "/"`
- `ORDER_BY_HASH_PATH = "/order/{order_hash}"`
- `ADDRESS_ORDERS_PATH = "/address/{address}"`
- `CANCEL_PATH = "/api/orderbook/cancel"`
- `RECENT_TRADES_PATH = "/api/orderbook/trades"`
- `PRIVATE_SESSION_HEADER = "x-orderbook-private-token"`
- `ORDER_STATE` mapping for TheHub `open`, `partial`, `filled`, `cancelled`, `expired`, `rejected`.

Helpers:

- `rest_url(path_url: str, base_url: str) -> str`
- `public_rest_url(path_url: str, base_url: str) -> str`
- `private_rest_url(path_url: str, base_url: str) -> str`
- `chain_path(path_url: str, chain_id: int = 5234) -> str`
- `build_api_factory(...)`
- `create_throttler()`

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub/test_thehub_web_utils.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hummingbot/connector/exchange/thehub/thehub_constants.py hummingbot/connector/exchange/thehub/thehub_web_utils.py test/hummingbot/connector/exchange/thehub/test_thehub_web_utils.py
git commit -m "feat: add thehub web utilities"
```

## Chunk 2: EIP-712 Signing

### Task 3: Generate TheHub Typed Data Fixtures

**Files:**
- Create: `test/hummingbot/connector/exchange/thehub/fixtures/thehub_typed_data_fixtures.json`

- [ ] **Step 1: Generate fixtures from TheHub**

From a local TheHub checkout, write a temporary fixture generator that imports or mirrors:

- `ONE_INCH_ORDER_TYPES`
- `buildOneInchOrderDomain`
- `hashLimitOrder`
- `CANCEL_INTENT_TYPES`
- `PRIVATE_SESSION_TYPES`
- `hashCancelIntent`
- `hashPrivateSessionIntent`

Fixture values should include:

- test private key
- recovered wallet address
- chain id `5234`
- 1inch LOP verifying contract
- one sell order
- one buy order
- one cancel intent
- one private session intent
- expected order hashes and EIP-712 signatures

- [ ] **Step 2: Save only deterministic fixture data**

Use fixed salt, maker traits, deadline, cancel nonce, issuedAt, expiry, and nonce. Do not use `Date.now()` or randomness in fixture values.

- [ ] **Step 3: Commit fixtures**

```bash
git add test/hummingbot/connector/exchange/thehub/fixtures/thehub_typed_data_fixtures.json
git commit -m "test: add thehub signing fixtures"
```

### Task 4: Implement 1inch Order And Backend Intent Signing

**Files:**
- Create: `hummingbot/connector/exchange/thehub/thehub_auth.py`
- Test: `test/hummingbot/connector/exchange/thehub/test_thehub_auth.py`

- [ ] **Step 1: Write the failing tests**

Test:

- `hash_limit_order` matches fixture hash.
- `sign_limit_order` signature recovers maker address.
- `sign_cancel_intent` signature recovers owner address.
- `sign_private_session_intent` signature recovers owner address.
- `rest_authenticate` is pass-through for non-signing requests.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub/test_thehub_auth.py -q
```

Expected: FAIL because `thehub_auth.py` does not exist.

- [ ] **Step 3: Implement signing**

Implement `TheHubAuth(AuthBase)` with:

- `Account.from_key(private_key)`
- `build_one_inch_order_domain(verifying_contract, chain_id=5234)`
- `hash_limit_order(order)`
- `sign_limit_order(order)`
- `hash_cancel_intent(cancel)`
- `sign_cancel_intent(cancel)`
- `hash_private_session_intent(intent)`
- `sign_private_session_intent(intent)`
- `create_private_session_request(ttl_seconds=3600)`
- `create_cancel_request(market, order_hash, deadline)`

Use `eth_account.messages.encode_typed_data(full_message=...)` and match TheHub `typedData.ts` domain/type definitions exactly.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub/test_thehub_auth.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hummingbot/connector/exchange/thehub/thehub_auth.py test/hummingbot/connector/exchange/thehub/test_thehub_auth.py
git commit -m "feat: add thehub eip712 signing"
```

## Chunk 3: Order Book And API Parsing

### Task 5: Parse TheHub Order Book Messages

**Files:**
- Create: `hummingbot/connector/exchange/thehub/thehub_order_book.py`
- Test: `test/hummingbot/connector/exchange/thehub/test_thehub_order_book.py`

- [ ] **Step 1: Write failing tests for snapshot and trade conversion**

Use TheHub snapshot shape:

```python
SNAPSHOT = {
    "market": "HMND/USDC",
    "sequence": 7,
    "updatedAt": 1710000000000,
    "bids": [{"priceE6": "1000000", "baseAmount": "2000000000000000000", "quoteAmount": "2000000", "totalBaseAmount": "2000000000000000000", "orderCount": 1}],
    "asks": [{"priceE6": "1100000", "baseAmount": "3000000000000000000", "quoteAmount": "3300000", "totalBaseAmount": "3000000000000000000", "orderCount": 1}],
    "bestBidE6": "1000000",
    "bestAskE6": "1100000",
    "lastTradePriceE6": "1050000",
    "recentTrades": [],
    "ownerOrders": [],
}
```

Assert price conversion `priceE6 / 1e6` and HMND amount conversion `baseAmount / 1e18`.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub/test_thehub_order_book.py -q
```

Expected: FAIL because `thehub_order_book.py` does not exist.

- [ ] **Step 3: Implement parsing**

Implement:

- `TheHubOrderBook.snapshot_message_from_exchange`
- `TheHubOrderBook.diff_message_from_exchange` if SSE sends full snapshots, alias to snapshot semantics.
- `TheHubOrderBook.trade_message_from_exchange`

Use integer/string decimal conversion to avoid float precision where Hummingbot accepts `Decimal`.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub/test_thehub_order_book.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hummingbot/connector/exchange/thehub/thehub_order_book.py test/hummingbot/connector/exchange/thehub/test_thehub_order_book.py
git commit -m "feat: parse thehub order book messages"
```

### Task 6: Implement Public REST/SSE Data Source

**Files:**
- Create: `hummingbot/connector/exchange/thehub/thehub_api_order_book_data_source.py`
- Test: `test/hummingbot/connector/exchange/thehub/test_thehub_api_order_book_data_source.py`

- [ ] **Step 1: Write failing tests**

Test:

- `_request_order_book_snapshot("HMND-USDC")` calls `GET /api/orderbook/5234/orderbook?market=HMND/USDC`.
- `_order_book_snapshot` returns an `OrderBookMessage`.
- SSE `snapshot` event is routed to the diff/snapshot queue.
- reconnect path can recover by requesting REST snapshot again.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub/test_thehub_api_order_book_data_source.py -q
```

Expected: FAIL because data source does not exist.

- [ ] **Step 3: Implement minimal data source**

Subclass `OrderBookTrackerDataSource`. Implement REST snapshot first. If Hummingbot has no built-in SSE assistant, implement a small async SSE reader with `aiohttp` inside this module and keep it private to avoid a broad framework change.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub/test_thehub_api_order_book_data_source.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hummingbot/connector/exchange/thehub/thehub_api_order_book_data_source.py test/hummingbot/connector/exchange/thehub/test_thehub_api_order_book_data_source.py
git commit -m "feat: add thehub public data source"
```

## Chunk 4: Private State And Exchange Lifecycle

### Task 7: Implement Private Session Polling Data Source

**Files:**
- Create: `hummingbot/connector/exchange/thehub/thehub_api_user_stream_data_source.py`
- Test: `test/hummingbot/connector/exchange/thehub/test_thehub_api_user_stream_data_source.py`

- [ ] **Step 1: Write failing tests**

Test:

- private session request is signed with `TheHubAuth`
- token is stored
- polling sends `x-orderbook-private-token`
- `ownerOrders` with `open`, `partial`, `filled`, `cancelled`, `expired`, `rejected` produce user stream events
- `ownerSettlements` with failed/rollback status produces a high-severity event payload

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub/test_thehub_api_user_stream_data_source.py -q
```

Expected: FAIL because user stream data source does not exist.

- [ ] **Step 3: Implement minimal private polling**

Implement private session creation and a polling loop equivalent to TheHub frontend `subscribePrivateOrderbookStream`, defaulting to 4 seconds. Keep the event shape close to Hummingbot order updates so `thehub_exchange.py` can consume it without custom global plumbing.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub/test_thehub_api_user_stream_data_source.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hummingbot/connector/exchange/thehub/thehub_api_user_stream_data_source.py test/hummingbot/connector/exchange/thehub/test_thehub_api_user_stream_data_source.py
git commit -m "feat: add thehub private state polling"
```

### Task 8: Implement TheHub Exchange Class

**Files:**
- Create: `hummingbot/connector/exchange/thehub/thehub_exchange.py`
- Test: `test/hummingbot/connector/exchange/thehub/test_thehub_exchange.py`

- [ ] **Step 1: Write failing tests for lifecycle methods**

Test:

- `supported_order_types` only includes limit orders for v1.
- `trading_pair_symbol_map` maps `HMND-USDC` to `HMND/USDC`.
- `_place_order` builds a 1inch order payload and calls TheHub submit endpoint.
- `_place_cancel` builds cancel intent and calls cancel endpoint.
- `_update_order_status` maps TheHub statuses to Hummingbot order states.
- `_update_balances` reads Humanode RPC or TheHub account endpoint if present.
- insufficient allowance raises a clear connector error and does not submit an order.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub/test_thehub_exchange.py -q
```

Expected: FAIL because exchange class does not exist.

- [ ] **Step 3: Implement minimal exchange**

Subclass `ExchangePyBase` or the current spot connector base used by Hyperliquid on this Hummingbot version. Implement only the v1 methods required by tests and defer multi-market metadata until TheHub exposes `/api/orderbook/5234/markets`.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub/test_thehub_exchange.py -q
```

Expected: PASS.

- [ ] **Step 5: Run all TheHub connector tests**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add hummingbot/connector/exchange/thehub test/hummingbot/connector/exchange/thehub
git commit -m "feat: add thehub exchange connector"
```

## Chunk 5: Integration Smoke Test And PR Prep

### Task 9: Add Dry Run Smoke Script Notes

**Files:**
- Create: `docs/superpowers/plans/2026-04-13-thehub-hummingbot-connector-phase2-smoke.md`

- [ ] **Step 1: Document local smoke flow**

Include:

- how to set `thehub_api_url`
- how to set Humanode RPC URL
- how to load wallet/private key into Hummingbot connector config
- how to run paper trading/dry run without submitting live orders
- how to SSH tunnel to `159.198.79.167` if needed

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-04-13-thehub-hummingbot-connector-phase2-smoke.md
git commit -m "docs: add thehub connector smoke test notes"
```

### Task 10: Final Verification

**Files:** all changed files

- [ ] **Step 1: Run focused connector tests**

Run:

```bash
conda run -n hummingbot pytest test/hummingbot/connector/exchange/thehub -q
```

Expected: PASS.

- [ ] **Step 2: Run registration smoke**

Run:

```bash
conda run -n hummingbot python - <<'PY'
from hummingbot.client.settings import AllConnectorSettings
AllConnectorSettings.all_connector_settings = {}
settings = AllConnectorSettings.get_connector_settings()
assert "thehub" in settings
print(settings["thehub"])
PY
```

Expected: prints connector settings for `thehub`.

- [ ] **Step 3: Confirm no perps/derivatives files changed**

Run:

```bash
git diff --name-only origin/development...HEAD | grep -E '^(hummingbot/connector/derivative/|test/hummingbot/connector/derivative/|hummingbot/connector/exchange/.+perpetual|test/hummingbot/connector/exchange/.+perpetual)' && exit 1 || true
```

Expected: no output and exit code 0.

- [ ] **Step 4: Push branch**

Run:

```bash
git push -u origin feature/thehub-connector-phase2
```

- [ ] **Step 5: Open PR into `development`**

Open a PR from `techdigger:feature/thehub-connector-phase2` to `techdigger:development`. Do not open against `master` and do not push directly to `master`.
