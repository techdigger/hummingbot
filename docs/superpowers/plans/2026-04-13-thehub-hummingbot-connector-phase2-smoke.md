# TheHub Connector Smoke Notes

Status: blocked on TheHub API availability.

The connector unit suite verifies the Hummingbot-side mechanics, signing shapes, order status mapping, SSE parsing, and private-state polling code paths with mocked exchange responses. It does not prove live compatibility because there is no TheHub orderbook API endpoint available to smoke against yet.

## Current Verification

Run the focused connector suite:

```bash
micromamba run -p /home/user/.local/share/micromamba/envs/hummingbot pytest test/hummingbot/connector/exchange/thehub -q
```

Expected result at the time this note was written:

```text
117 passed, 4 warnings
```

Run the Hummingbot connector registration check:

```bash
micromamba run -p /home/user/.local/share/micromamba/envs/hummingbot python -c "from hummingbot.client.settings import AllConnectorSettings; AllConnectorSettings.all_connector_settings = {}; settings = AllConnectorSettings.get_connector_settings(); assert 'thehub' in settings; print(settings['thehub'])"
```

Expected: `ConnectorSetting(name='thehub', ...)` with `example_pair='HMND-USDC'`, non-centralized exchange type, Ethereum wallet enabled, and maker/taker fee decimal `0.0003`.

## Configuration Inputs

The connector currently needs these values before any live or tunneled smoke run:

- `thehub_api_url`: TheHub orderbook API base URL. Default is local development only: `http://127.0.0.1:7303`.
- `thehub_chain_id`: `5234`.
- `thehub_wallet_address`: bot wallet address.
- `thehub_private_key`: bot wallet private key. Use a tiny-size live wallet only.
- `thehub_lop_address`: deployed 1inch Limit Order Protocol verifying contract on Humanode. The current test fixture uses `0x1111111254EEB25477B68fb85Ed929f73A960582`; re-verify this against TheHub `typedData.ts` and deployment config before live trading.
- `thehub_rpc_url`: Humanode RPC URL for HMND/USDC balances and allowance preflight. Default: `https://explorer-rpc-http.mainnet.stages.humanode.io`.

The v1 connector must not auto-submit ERC-20 approvals. Set allowances separately and let the connector fail fast if allowance is insufficient.

## Smoke Scope Once API Exists

Before tiny live trading, run a narrow API smoke against a local TheHub server or an SSH-tunneled endpoint:

- `GET /api/orderbook/health`
- `GET /api/orderbook/5234/orderbook?market=HMND/USDC`
- `GET /api/orderbook/stream?market=HMND%2FUSDC` and confirm SSE snapshot events parse.
- `POST /api/orderbook/private-session` with signed `PrivateSessionIntent`.
- `GET /api/orderbook/private-state` with `x-orderbook-private-token`.
- Submit one tiny limit order only after signing/domain verification passes.
- Query the order by hash or owner address.
- Cancel the order and verify idempotent cancel behavior.

If any endpoint is absent, treat the live connector as blocked and do not run strategy trading.

## Dry-Run Flow

Until the API exists, dry-run is local-only:

1. Run the unit suite above.
2. Run the registration check above.
3. Verify EIP-712 fixtures against TheHub `typedData.ts`, especially backend domain, cancel intent, private session intent, and LOP verifying contract.
4. Review generated order payloads manually or in a mocked test. Do not submit signed orders.
5. Keep PMM/live strategy disabled until an API smoke run proves snapshot, private session, order submit, status lookup, and cancel against the actual server.

## SSH Tunnel Placeholder

If TheHub later exposes an orderbook server only on a VPS-local port, use an SSH tunnel to map the remote orderbook port to local `7303`, then set:

```text
thehub_api_url=http://127.0.0.1:7303
```

Do not use this path until the remote port, process owner, and access policy are confirmed. The previous VPS notes reported tight memory and limited operational visibility, so avoid running full Hummingbot on that host until load and rollback access are understood.
