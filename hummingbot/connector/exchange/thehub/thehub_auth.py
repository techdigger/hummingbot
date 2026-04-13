"""
TheHub EIP-712 signing for:
  - 1inch v4 Limit Order Protocol orders (on-chain, verified by LOP contract)
  - TheHub backend CancelIntent and PrivateSessionIntent (off-chain, verified by orderbook server)

TODO: verify the following against typedData.ts once available:
  - ONE_INCH_DOMAIN_NAME        (buildOneInchOrderDomain)
  - CANCEL_INTENT_TYPES         (CANCEL_INTENT_TYPES)
  - PRIVATE_SESSION_INTENT_TYPES (PRIVATE_SESSION_TYPES)
"""

import time
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data

from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest

# ---------------------------------------------------------------------------
# EIP-712 domain — TODO: verify name against typedData.ts buildOneInchOrderDomain
# ---------------------------------------------------------------------------
ONE_INCH_DOMAIN_NAME = "1inch Limit Order Protocol"
ONE_INCH_DOMAIN_VERSION = "4"

# ---------------------------------------------------------------------------
# 1inch v4 LOP Order type (standard, on-chain)
# ref: https://github.com/1inch/limit-order-protocol
# ---------------------------------------------------------------------------
ONE_INCH_ORDER_TYPES = {
    "Order": [
        {"name": "salt", "type": "uint256"},
        {"name": "maker", "type": "address"},
        {"name": "receiver", "type": "address"},
        {"name": "makerAsset", "type": "address"},
        {"name": "takerAsset", "type": "address"},
        {"name": "makingAmount", "type": "uint256"},
        {"name": "takingAmount", "type": "uint256"},
        {"name": "makerTraits", "type": "uint256"},
    ]
}

# ---------------------------------------------------------------------------
# TheHub backend intent types (off-chain)
# TODO: verify field names/types against typedData.ts
# ---------------------------------------------------------------------------
CANCEL_INTENT_TYPES = {
    "CancelIntent": [
        {"name": "maker", "type": "address"},
        {"name": "orderHash", "type": "bytes32"},
        {"name": "deadline", "type": "uint256"},
    ]
}

PRIVATE_SESSION_INTENT_TYPES = {
    "PrivateSessionIntent": [
        {"name": "owner", "type": "address"},
        {"name": "issuedAt", "type": "uint256"},
        {"name": "expiry", "type": "uint256"},
    ]
}


class TheHubAuth(AuthBase):
    def __init__(
        self,
        private_key: str,
        verifying_contract: str,
        chain_id: int = 5234,
        domain_name: str = ONE_INCH_DOMAIN_NAME,
        domain_version: str = ONE_INCH_DOMAIN_VERSION,
    ) -> None:
        self._account = Account.from_key(private_key)
        self._verifying_contract = verifying_contract
        self._chain_id = chain_id
        self._domain_name = domain_name
        self._domain_version = domain_version

    @property
    def address(self) -> str:
        return self._account.address

    def _domain(self) -> dict:
        return {
            "name": self._domain_name,
            "version": self._domain_version,
            "chainId": self._chain_id,
            "verifyingContract": self._verifying_contract,
        }

    def _sign_eip712(
        self,
        types: dict[str, list[dict[str, str]]],
        primary_type: str,
        message: dict[str, Any],
    ) -> dict[str, str]:
        signable = encode_typed_data(full_message={
            "types": types,
            "domain": self._domain(),
            "primaryType": primary_type,
            "message": message,
        })
        signed = self._account.sign_message(signable)
        return {
            "hash": "0x" + signed.message_hash.hex(),
            "signature": "0x" + signed.signature.hex(),
        }

    # ------------------------------------------------------------------
    # 1inch v4 LOP order signing
    # ------------------------------------------------------------------

    def sign_limit_order(self, order: dict[str, Any]) -> dict[str, str]:
        """Sign a 1inch v4 LOP order. Returns {"orderHash", "signature"}."""
        result = self._sign_eip712(ONE_INCH_ORDER_TYPES, "Order", order)
        return {"orderHash": result["hash"], "signature": result["signature"]}

    def hash_limit_order(self, order: dict[str, Any]) -> str:
        """EIP-712 hash of a limit order without signing."""
        return self.sign_limit_order(order)["orderHash"]

    # ------------------------------------------------------------------
    # TheHub backend cancel intent
    # ------------------------------------------------------------------

    def sign_cancel_intent(self, cancel: dict[str, Any]) -> dict[str, str]:
        """Sign a cancel intent. orderHash may be hex string or bytes."""
        cancel = dict(cancel)
        if isinstance(cancel.get("orderHash"), str):
            cancel["orderHash"] = bytes.fromhex(cancel["orderHash"].removeprefix("0x"))
        return self._sign_eip712(CANCEL_INTENT_TYPES, "CancelIntent", cancel)

    def create_cancel_request(
        self, market: str, order_hash: str, deadline: int
    ) -> dict[str, Any]:
        """Build and sign cancel payload for POST /api/orderbook/cancel."""
        signed = self.sign_cancel_intent({
            "maker": self.address,
            "orderHash": order_hash,
            "deadline": deadline,
        })
        return {
            "market": market,
            "orderHash": order_hash,
            "deadline": deadline,
            "signature": signed["signature"],
        }

    # ------------------------------------------------------------------
    # TheHub backend private session intent
    # ------------------------------------------------------------------

    def sign_private_session_intent(self, intent: dict[str, Any]) -> dict[str, str]:
        """Sign a private session intent. Returns {"hash", "signature"}."""
        return self._sign_eip712(PRIVATE_SESSION_INTENT_TYPES, "PrivateSessionIntent", intent)

    def create_private_session_request(self, ttl_seconds: int = 3600) -> dict[str, Any]:
        """Build and sign payload for POST /api/orderbook/private-session."""
        now = int(time.time())
        intent: dict[str, Any] = {
            "owner": self.address,
            "issuedAt": now,
            "expiry": now + ttl_seconds,
        }
        signed = self.sign_private_session_intent(intent)
        return {
            "owner": self.address,
            "issuedAt": intent["issuedAt"],
            "expiry": intent["expiry"],
            "signature": signed["signature"],
        }

    # ------------------------------------------------------------------
    # Hummingbot AuthBase protocol
    # ------------------------------------------------------------------

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        """Pass-through: private session token is added by the data source."""
        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        return request
